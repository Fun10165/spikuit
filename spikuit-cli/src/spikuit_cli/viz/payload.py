"""Graph visualization data contract — substrate (+ optional tutor overlay)
→ a JSON-able dict. See ``docs/design/graph-viz.md`` §3.

Pure with respect to rendering: this module knows nothing about HTML, sigma,
or any UI concern. The app (``viz/app/``) knows nothing about the substrate.
This dict is the only interface between the two.

All string fields (``label``, ``excerpt``) are carried as plain data. Callers
that render them into a page MUST insert them as text (``textContent`` /
attribute assignment), never compose markup — this module does not escape
anything, by design, because escaping-at-the-wrong-layer is exactly the bug
the pyvis-based implementation had.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import networkx as nx

from spikuit_core import Circuit

from ..helpers import _extract_title

if TYPE_CHECKING:
    from spikuit_tutor import TutorScheduler

_TOP_GROUPS = 8
_EXCERPT_LIMIT = 200
_SIZE_BY_VALUES = frozenset({"centrality", "pressure", "stability"})


def _excerpt(content: str) -> str:
    """First paragraph after the title heading, truncated."""
    lines = content.splitlines()
    if lines and lines[0].strip().startswith("#"):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    first_para = body.split("\n\n", 1)[0] if body else ""
    if len(first_para) > _EXCERPT_LIMIT:
        return first_para[: _EXCERPT_LIMIT - 1].rstrip() + "…"
    return first_para


def _compute_groups(
    assignment: dict[str, Any], kind: str
) -> tuple[dict[Any, Any], list[dict[str, Any]]]:
    """Slot the top-8 keys by count (desc, tie-broken by key asc); fold
    everything else — including unassigned (``None``) nodes — into one
    ``"other"`` group. Returns (key -> slot, group list).
    """
    counts: Counter[Any] = Counter(v for v in assignment.values() if v is not None)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
    top = ordered[:_TOP_GROUPS]
    rest_keys = {k for k, _ in ordered[_TOP_GROUPS:]}

    slot_of: dict[Any, Any] = {}
    groups: list[dict[str, Any]] = []
    for i, (key, count) in enumerate(top, start=1):
        slot_of[key] = i
        label = f"Community {key}" if kind == "community" else str(key)
        groups.append({"key": str(key), "kind": kind, "label": label, "count": count, "slot": i})

    other_count = sum(counts[k] for k in rest_keys)
    other_count += sum(1 for v in assignment.values() if v is None)
    if other_count > 0:
        groups.append({"key": "other", "kind": kind, "label": "Other", "count": other_count, "slot": "other"})
    for key in rest_keys:
        slot_of[key] = "other"

    return slot_of, groups


def _empty_payload(*, size_by: str, overlay: str | None) -> dict[str, Any]:
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "neuron_count": 0,
            "synapse_count": 0,
            "size_by": size_by,
            "coloring": "domain",
            "overlay": overlay,
            "component_count": 0,
            "weight_domain": [0.0, 1.0],
        },
        "groups": [],
        "nodes": [],
        "edges": [],
    }


async def build_viz_payload(
    circuit: Circuit,
    *,
    overlay: str | None = None,
    size_by: str = "centrality",
    spikes_window_days: int = 90,
    scheduler: "TutorScheduler | None" = None,
) -> dict[str, Any]:
    """Build the graph-viz data contract from a connected ``Circuit``.

    Args:
        circuit: A connected ``Circuit``. Only read from — never mutated.
        overlay: ``None`` (default, substrate-only — the tutor DB is never
            touched) or ``"tutor"`` to include FSRS card state per node.
        size_by: ``"centrality"`` (default) | ``"pressure"`` | ``"stability"``.
            ``"stability"`` requires ``overlay="tutor"``.
        spikes_window_days: neurons whose most recent spike is older than
            this are treated the same as never-fired (``spike_recency`` is
            ``null``) — this caps an otherwise unbounded per-node query and
            matches the Activity mode's own "dormant" bucket (§5.2).
        scheduler: an *already-open* ``TutorScheduler`` over ``circuit``,
            required (and only used) when ``overlay="tutor"``. The signature
            takes only ``circuit`` for the substrate-only path; opening the
            tutor overlay is the caller's decision, made explicit here via
            this parameter so this function can guarantee it never opens
            the tutor DB itself.

    Returns:
        The JSON-able dict described in ``docs/design/graph-viz.md`` §3.
    """
    if size_by not in _SIZE_BY_VALUES:
        raise ValueError(f"size_by must be one of {sorted(_SIZE_BY_VALUES)}, got {size_by!r}")
    if size_by == "stability" and overlay != "tutor":
        raise ValueError("size_by='stability' requires overlay='tutor'")
    if overlay == "tutor" and scheduler is None:
        raise ValueError("overlay='tutor' requires a scheduler")

    graph = circuit.graph
    if graph.number_of_nodes() == 0:
        return _empty_payload(size_by=size_by, overlay=overlay)

    neurons = {n.id: n for n in await circuit.list_neurons(limit=100_000)}

    community_map = circuit.community_map()
    use_community = len(community_map) > 0
    if use_community:
        assignment = {nid: community_map.get(nid) for nid in graph.nodes}
        group_kind = "community"
    else:
        assignment = {nid: neurons[nid].domain if nid in neurons else None for nid in graph.nodes}
        group_kind = "domain"
    slot_of, groups = _compute_groups(assignment, group_kind)

    centrality: dict[str, float] = {}
    if size_by == "centrality" and graph.number_of_nodes() > 1:
        centrality = nx.degree_centrality(graph)

    component_of: dict[str, int] = {}
    components = sorted(nx.weakly_connected_components(graph), key=len, reverse=True)
    for cid, members in enumerate(components):
        for nid in members:
            component_of[nid] = cid

    now = datetime.now(timezone.utc)
    window_seconds = spikes_window_days * 86400

    nodes: list[dict[str, Any]] = []
    for nid in graph.nodes:
        neuron = neurons.get(nid)
        content = neuron.content if neuron else ""
        node_data = graph.nodes[nid]

        if size_by == "centrality":
            size_raw = centrality.get(nid, 0.0)
        elif size_by == "pressure":
            size_raw = circuit.get_pressure(nid)
        else:  # stability
            assert scheduler is not None  # guarded above
            card = scheduler.get_card(nid)
            size_raw = card.stability if card and card.stability else 0.0

        spike_recency: float | None = None
        spikes = await circuit.get_spikes_for(nid, limit=1)
        if spikes:
            fired_at = spikes[0].fired_at
            if fired_at.tzinfo is None:
                fired_at = fired_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - fired_at).total_seconds()
            if age_seconds <= window_seconds:
                spike_recency = age_seconds

        tutor_block: dict[str, Any] | None = None
        if overlay == "tutor":
            assert scheduler is not None  # guarded above
            card = scheduler.get_card(nid)
            if card is not None:
                due_in_days = (card.due - now).total_seconds() / 86400
                tutor_block = {
                    "stability": card.stability,
                    "difficulty": card.difficulty,
                    "state": card.state.name,
                    "due_in_days": due_in_days,
                }

        nodes.append({
            "id": nid,
            "label": _extract_title(content) if content else nid,
            "group": slot_of.get(assignment.get(nid), "other"),
            "size_raw": size_raw,
            "domain": node_data.get("domain"),
            "type": node_data.get("type"),
            "pressure": circuit.get_pressure(nid),
            "community_id": community_map.get(nid),
            "component_id": component_of.get(nid),
            "excerpt": _excerpt(content) if content else "",
            "spike_recency": spike_recency,
            "tutor": tutor_block,
        })

    edges: list[dict[str, Any]] = []
    weights: list[float] = []
    for u, v, data in graph.edges(data=True):
        weight = data.get("weight", 0.5)
        weights.append(weight)
        edges.append({
            "source": u,
            "target": v,
            "type": data.get("type", "relates_to"),
            "weight": weight,
            "co_fires": data.get("co_fires", 0),
        })
    weight_domain = [min(weights), max(weights)] if weights else [0.0, 1.0]

    return {
        "meta": {
            "generated_at": now.isoformat(),
            "neuron_count": graph.number_of_nodes(),
            "synapse_count": graph.number_of_edges(),
            "size_by": size_by,
            "coloring": group_kind,
            "overlay": overlay,
            "component_count": len(components),
            "weight_domain": weight_domain,
        },
        "groups": groups,
        "nodes": nodes,
        "edges": edges,
    }
