"""TutorScheduler — the tutor's FSRS scheduling engine.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.2, §5.2)
inverts the review orchestration. Before Stage 2, ``Circuit.fire`` was
the conductor — it recorded the spike, ran FSRS, persisted the card,
and propagated activation, all inside ``spikuit-core``. After Stage 2
``spikuit-core`` owns no learner model: FSRS scheduling is wholly the
tutor's.

``TutorScheduler`` is that owner. It bundles the three things a review
needs:

- the **substrate** — a ``spikuit-core`` ``Circuit``, reached only
  through the appkit contract, for graph topology and ``fire``;
- the **overlay store** (:class:`~spikuit_tutor.store.TutorStore`) —
  the tutor-owned ``fsrs_card`` database;
- an **FSRS ``Scheduler``** — the scheduling algorithm itself.

On a review it loads the card, runs ``Scheduler.review_card``,
persists the updated card to the overlay, then calls ``substrate.fire``
so the substrate still gets its grade-driven plasticity (propagation,
STDP, pressure). The substrate is a callee now, not the conductor
(§4.2).

It also answers the FSRS *queries* the substrate used to —
``due_neurons`` / ``near_due_neurons`` — reimplemented over the overlay
store, with the lazy-card "new neuron" union of §4.4.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fsrs import Card, Rating, Scheduler
from spikuit_core.appkit import Grade

if TYPE_CHECKING:
    from spikuit_core.appkit import NeuronView, SubstrateView, Spike

    from .store import TutorStore


# Grade → FSRS Rating. Relocated verbatim from ``Circuit`` (§5.2): the
# substrate keeps ``Grade`` — its plasticity is grade-driven — but no
# longer maps it onto FSRS. That mapping is the tutor's now.
_GRADE_TO_RATING: dict[Grade, Rating] = {
    Grade.MISS: Rating.Again,
    Grade.WEAK: Rating.Hard,
    Grade.FIRE: Rating.Good,
    Grade.STRONG: Rating.Easy,
}


def _meta_or_summary(neuron: "NeuronView") -> bool:
    """True for auto-generated neurons that are never reviewable —
    ``_meta``-domain neurons and community summaries.
    """
    return (
        getattr(neuron, "domain", None) == "_meta"
        or getattr(neuron, "type", None) == "community_summary"
    )


class TutorScheduler:
    """Owns FSRS scheduling for one substrate/overlay pair.

    Constructed with an already-connected substrate and an unopened
    :class:`TutorStore`; :meth:`open` opens the store (reconciling
    orphan cards) and :meth:`close` closes it.
    """

    def __init__(
        self,
        substrate: "SubstrateView",
        store: "TutorStore",
        *,
        fsrs_scheduler: Scheduler | None = None,
    ) -> None:
        self.substrate = substrate
        self.store = store
        self._fsrs: Scheduler = fsrs_scheduler or Scheduler()

    # -- Lifecycle ----------------------------------------------------------

    async def open(self) -> list[str]:
        """Open the overlay store, reconciling orphan cards (§4.4).

        Returns the neuron IDs whose cards were pruned because their
        neuron no longer exists in the substrate.
        """
        neurons = await self.substrate.list_neurons(limit=1_000_000)
        known = {n.id for n in neurons}
        return await self.store.open(known_neuron_ids=known)

    async def close(self) -> None:
        await self.store.close()

    # -- Reads --------------------------------------------------------------

    def get_card(self, neuron_id: str) -> Card | None:
        """The FSRS card for a neuron, or ``None`` if it has never been
        reviewed (cards are created lazily on first review, §4.4).
        """
        return self.store.get_card(neuron_id)

    async def get_neuron(self, neuron_id: str) -> "NeuronView | None":
        """Substrate passthrough — the neuron content/topology view."""
        return await self.substrate.get_neuron(neuron_id)

    # -- Review -------------------------------------------------------------

    async def review(self, spike: "Spike") -> Card:
        """Process a review: schedule with FSRS, then fire the substrate.

        The tutor is the orchestrator (§4.2): it (a) loads the card,
        creating a fresh one on first review; (b) runs
        ``Scheduler.review_card``; (c) persists the updated card to the
        overlay; and (d) calls ``substrate.fire`` so the substrate
        applies its grade-driven plasticity. Returns the updated card.
        """
        card = self.store.get_card(spike.neuron_id) or Card()
        rating = _GRADE_TO_RATING[spike.grade]
        updated, _log = self._fsrs.review_card(card, rating, spike.fired_at)
        await self.store.upsert_card(spike.neuron_id, updated)
        await self.substrate.fire(spike)
        return updated

    # -- FSRS queries -------------------------------------------------------

    async def due_neurons(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> list[str]:
        """Neuron IDs due for review — past-due cards, then new neurons.

        The lazy-card union of §4.4: bucket 1 is cards whose ``due`` is
        in the past; bucket 2 is reviewable neurons with no card at all
        (never reviewed). New neurons surface naturally without the
        substrate eager-creating a card for every neuron.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        past_due = [
            nid for nid, card in self.store.cards().items() if card.due <= now
        ]
        carded = self.store.card_ids()
        new_ids: list[str] = []
        for neuron in await self.substrate.list_neurons(limit=1_000_000):
            if neuron.id in carded or _meta_or_summary(neuron):
                continue
            new_ids.append(neuron.id)
        return (past_due + new_ids)[:limit]

    async def near_due_neurons(
        self,
        *,
        days_ahead: int = 2,
        limit: int = 20,
        exclude_ids: set[str] | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Neuron IDs whose next review falls within ``days_ahead`` days
        but is not yet due. Interleaving uses this to pull near-due work
        from other domains. Only carded neurons can be near-due — a
        never-reviewed neuron has no scheduled ``due``.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=days_ahead)
        exclude = exclude_ids or set()
        near: list[tuple[datetime, str]] = []
        for nid, card in self.store.cards().items():
            if nid in exclude:
                continue
            if now < card.due <= horizon:
                near.append((card.due, nid))
        near.sort(key=lambda x: x[0])
        return [nid for _, nid in near[:limit]]
