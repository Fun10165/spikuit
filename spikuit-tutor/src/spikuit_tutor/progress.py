"""compute_progress() — the learner-facing retention report.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.3, §5.2) moves
``Circuit.progress`` wholesale out of ``spikuit-core``. The report is
pure tutor domain — it reads FSRS stability/retrievability, which after
Stage 2 live in the tutor's overlay store, not the substrate.

It still needs two substrate-native signals, both reached through the
appkit contract:

- **review history** — ``substrate.get_spikes_for`` per neuron, for
  the retention rate (made public on the contract for exactly this);
- **graph topology** — ``neighbors`` / ``predecessors``, from which
  the tutor computes its own degree centrality (the substrate no
  longer hands one out).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .scheduler import TutorScheduler


async def compute_progress(
    scheduler: "TutorScheduler", *, domain: str | None = None
) -> dict:
    """Generate a learner-focused progress report.

    Returns per-domain mastery, retention rate, learning velocity, weak
    spots, and review adherence. Optionally scoped to one ``domain``.
    """
    substrate = scheduler.substrate
    now = datetime.now(timezone.utc)

    # Gather neurons (optionally filtered by domain).
    all_neurons = await substrate.list_neurons(limit=1_000_000)
    if domain:
        neurons = [n for n in all_neurons if n.domain == domain]
    else:
        neurons = all_neurons

    neuron_ids = {n.id for n in neurons}

    # Degree centrality, computed over the *whole* substrate graph — the
    # substrate no longer exposes one (§4.3), so the tutor derives it
    # from neighbour/predecessor counts: deg(n) / (N - 1).
    total_nodes = len(all_neurons)

    def _centrality(nid: str) -> float:
        if total_nodes <= 1:
            return 0.0
        deg = len(substrate.neighbors(nid)) + len(substrate.predecessors(nid))
        return deg / (total_nodes - 1)

    # -- Per-domain mastery ------------------------------------------------
    domain_stats: dict[str, dict] = defaultdict(lambda: {
        "count": 0,
        "stabilities": [],
        "retrievabilities": [],
    })
    for n in neurons:
        d = n.domain or "(none)"
        card = scheduler.get_card(n.id)
        domain_stats[d]["count"] += 1
        if card and card.stability is not None:
            domain_stats[d]["stabilities"].append(card.stability)
            # Retrievability = exp(-elapsed / stability).
            elapsed = (now - card.due).total_seconds() / 86400 + card.stability
            if card.stability > 0:
                r = math.exp(-max(0, elapsed - card.stability) / card.stability)
                domain_stats[d]["retrievabilities"].append(r)

    mastery = {}
    for d, stats in domain_stats.items():
        stabs = stats["stabilities"]
        rets = stats["retrievabilities"]
        mastery[d] = {
            "neuron_count": stats["count"],
            "avg_stability": round(sum(stabs) / len(stabs), 2) if stabs else None,
            "avg_retrievability": round(sum(rets) / len(rets), 3) if rets else None,
            "reviewed_count": len(stabs),
        }

    # -- Retention rate (from spike history) -------------------------------
    # The substrate keeps the spike table; the tutor reads it per neuron
    # through the contract's get_spikes_for (§4.3).
    total_fires = 0
    success_fires = 0
    domain_retention: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "success": 0}
    )
    for n in neurons:
        d = n.domain or "(none)"
        spikes = await substrate.get_spikes_for(n.id, limit=1_000_000)
        for spike in spikes:
            total_fires += 1
            domain_retention[d]["total"] += 1
            # Grade: 1=miss, 2=weak, 3=fire, 4=strong.
            if int(spike.grade) >= 3:  # fire or strong
                success_fires += 1
                domain_retention[d]["success"] += 1

    retention = {
        "overall": round(success_fires / total_fires, 3) if total_fires > 0 else None,
        "total_reviews": total_fires,
        "per_domain": {
            d: round(v["success"] / v["total"], 3) if v["total"] > 0 else None
            for d, v in domain_retention.items()
        },
    }

    # -- Learning velocity -------------------------------------------------
    # Neurons added per week (last 4 weeks).
    weekly_counts: list[dict] = []
    for weeks_ago in range(4):
        week_end = now - timedelta(weeks=weeks_ago)
        week_start = week_end - timedelta(weeks=1)
        count = sum(
            1 for n in neurons
            if getattr(n, "created_at", None)
            and week_start <= n.created_at <= week_end
        )
        weekly_counts.append(
            {"week_of": week_start.strftime("%Y-%m-%d"), "added": count}
        )
    weekly_counts.reverse()  # oldest first

    velocity = {
        "weekly": weekly_counts,
        "total_neurons": len(neurons),
    }

    # -- Weak spots (low stability + high centrality) ----------------------
    weak_spots = []
    for n in neurons:
        card = scheduler.get_card(n.id)
        centrality = _centrality(n.id)
        if card is None or card.stability is None:
            # Never reviewed — include if it has connections.
            if centrality > 0:
                weak_spots.append({
                    "id": n.id,
                    "domain": n.domain,
                    "stability": None,
                    "centrality": round(centrality, 4),
                    "reason": "never_reviewed",
                })
        elif card.stability < 5.0:
            if centrality > 0:
                weak_spots.append({
                    "id": n.id,
                    "domain": n.domain,
                    "stability": round(card.stability, 2),
                    "centrality": round(centrality, 4),
                    "reason": "low_stability",
                })

    # Sort by centrality desc (most important weak spots first).
    weak_spots.sort(key=lambda x: x["centrality"], reverse=True)
    weak_spots = weak_spots[:20]

    # -- Review adherence --------------------------------------------------
    # Lazy cards (§4.4) make "has a card" mean "reviewed at least once",
    # so the denominator is the full in-scope neuron count, not the
    # carded count — preserving the pre-Stage-2 ratio's meaning.
    due_ids = await scheduler.due_neurons(limit=1_000_000)
    due_in_scope = [nid for nid in due_ids if nid in neuron_ids]
    reviewed_neurons = {
        n.id for n in neurons
        if (c := scheduler.get_card(n.id)) is not None and c.stability is not None
    }
    denominator = len(neurons)

    adherence = {
        "total_neurons": len(neurons),
        "reviewed_at_least_once": len(reviewed_neurons),
        "currently_overdue": len(due_in_scope),
        "adherence_rate": round(
            len(reviewed_neurons) / denominator, 3
        ) if denominator > 0 else None,
    }

    return {
        "domain_filter": domain,
        "mastery": mastery,
        "retention": retention,
        "velocity": velocity,
        "weak_spots": weak_spots,
        "adherence": adherence,
    }
