"""Scaffold — how much support a learner needs for a neuron.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.5) moves
scaffolding out of ``spikuit-core``. It reads FSRS card state — which
after Stage 2 lives in the tutor's overlay store, not the substrate —
so it has no choice but to live here.

It still needs graph *topology* (neighbors, predecessors, edge type);
those come from the substrate live through the appkit contract. The
``ScaffoldLevel`` / ``Scaffold`` result types moved here with the
function.

Inspired by Vygotsky's Zone of Proximal Development.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import msgspec
from fsrs import Card, State

if TYPE_CHECKING:
    from .scheduler import TutorScheduler


class ScaffoldLevel(str, Enum):
    """How much support the learner needs (ZPD-inspired).

    Attributes:
        FULL: New or struggling — max hints, context, easy questions.
        GUIDED: Progressing — hints on request, some context.
        MINIMAL: Competent — harder questions, less hand-holding.
        NONE: Mastered — application / synthesis level.
    """

    FULL = "full"
    GUIDED = "guided"
    MINIMAL = "minimal"
    NONE = "none"


class Scaffold(msgspec.Struct, kw_only=True):
    """Scaffolding state computed from substrate topology + FSRS cards.

    Attributes:
        level: Current support level.
        hints: Auto-generated hint strings.
        context: IDs of strong neighbors (scaffolding material).
        gaps: IDs of weak prerequisites (should study first).
    """

    level: ScaffoldLevel = ScaffoldLevel.FULL
    hints: list[str] = msgspec.field(default_factory=list)
    context: list[str] = msgspec.field(default_factory=list)
    gaps: list[str] = msgspec.field(default_factory=list)


def compute_scaffold(scheduler: "TutorScheduler", neuron_id: str) -> Scaffold:
    """Compute scaffolding for a neuron from substrate state + FSRS cards.

    Returns a Scaffold with:
    - level: how much support to provide
    - context: strong neighbor IDs (scaffolding material)
    - gaps: weak prerequisite IDs (should study first)
    """
    card = scheduler.get_card(neuron_id)
    if card is None:
        # No card yet — never reviewed (lazy creation, §4.4) — full support.
        return Scaffold(level=ScaffoldLevel.FULL)

    level = _level_from_fsrs(card)
    substrate = scheduler.substrate

    context: list[str] = []
    gaps: list[str] = []

    # Outgoing edges — things this neuron requires / extends.
    for neighbor_id in substrate.neighbors(neuron_id):
        neighbor_card = scheduler.get_card(neighbor_id)
        if neighbor_card is None:
            gaps.append(neighbor_id)
            continue

        edge_type = substrate.edge_type(neuron_id, neighbor_id) or "relates_to"

        if neighbor_card.state == State.Review and (neighbor_card.stability or 0) > 5.0:
            # Learner knows this well — useful as scaffolding context.
            context.append(neighbor_id)
        elif edge_type == "requires":
            # A prerequisite, and it's weak — that's a gap.
            gaps.append(neighbor_id)

    # Incoming edges — things that require this neuron.
    for pred_id in substrate.predecessors(neuron_id):
        pred_card = scheduler.get_card(pred_id)
        if (
            pred_card is not None
            and pred_card.state == State.Review
            and (pred_card.stability or 0) > 5.0
        ):
            context.append(pred_id)

    return Scaffold(level=level, context=context, gaps=gaps)


def _level_from_fsrs(card: Card) -> ScaffoldLevel:
    """Map an FSRS card's state + stability to a scaffold level."""
    stability = card.stability or 0.0

    if card.state == State.Learning:
        return ScaffoldLevel.FULL
    if card.state == State.Relearning:
        return ScaffoldLevel.GUIDED

    # State.Review — use stability to determine level.
    if stability < 5.0:
        return ScaffoldLevel.GUIDED
    if stability < 21.0:
        return ScaffoldLevel.MINIMAL
    return ScaffoldLevel.NONE
