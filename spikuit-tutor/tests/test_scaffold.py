"""Tests for spikuit_tutor.scaffold — ZPD-inspired scaffolding.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.5) moved
``compute_scaffold`` out of ``spikuit-core``: it reads FSRS card state,
which now lives in the tutor's overlay store. It still reaches graph
*topology* (neighbors, predecessors, edge type) through the appkit
contract.

These tests port the substrate-era ``test_scaffold.py``, rewritten for
the lazy-card model (§4.4): a neuron has no card until its first
review, so an unreviewed target — and any unreviewed neighbor — is
treated as needing full support / being a gap.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fsrs import Card, State

from spikuit_core import Circuit, Neuron, SynapseType

from spikuit_tutor import ScaffoldLevel, TutorScheduler, TutorStore, compute_scaffold


@pytest_asyncio.fixture
async def scheduler(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    sched = TutorScheduler(c, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    yield sched
    await sched.close()
    await c.close()


def _make_neuron(nid: str, content: str = "") -> Neuron:
    return Neuron.create(content or f"# {nid}", id=nid)


async def _give_card(
    sched: TutorScheduler,
    nid: str,
    *,
    state: State = State.Learning,
    stability: float | None = None,
) -> None:
    """Plant an FSRS card for a neuron at a controlled state/stability."""
    card = Card()
    card.state = state
    if stability is not None:
        card.stability = stability
    await sched.store.upsert_card(nid, card)


# -- Level from FSRS state --------------------------------------------------


@pytest.mark.asyncio
async def test_unreviewed_neuron_gets_full_scaffold(scheduler):
    """A neuron with no card yet (never reviewed) → FULL scaffold."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.level == ScaffoldLevel.FULL


@pytest.mark.asyncio
async def test_unknown_neuron_gets_full_scaffold(scheduler):
    """A neuron id not in the substrate → no card → FULL scaffold."""
    scaffold = compute_scaffold(scheduler, "nonexistent")
    assert scaffold.level == ScaffoldLevel.FULL


@pytest.mark.asyncio
async def test_learning_state_gives_full(scheduler):
    """A card still in Learning state → FULL scaffold."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    await _give_card(scheduler, "n1", state=State.Learning)
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.level == ScaffoldLevel.FULL


@pytest.mark.asyncio
async def test_review_low_stability_gives_guided(scheduler):
    """Review state with low stability (<5) → GUIDED."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    await _give_card(scheduler, "n1", state=State.Review, stability=3.0)
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.level == ScaffoldLevel.GUIDED


@pytest.mark.asyncio
async def test_review_mid_stability_gives_minimal(scheduler):
    """Review state with mid stability (5–21) → MINIMAL."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    await _give_card(scheduler, "n1", state=State.Review, stability=10.0)
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.level == ScaffoldLevel.MINIMAL


@pytest.mark.asyncio
async def test_review_high_stability_gives_none(scheduler):
    """Review state with high stability (>=21) → NONE."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    await _give_card(scheduler, "n1", state=State.Review, stability=30.0)
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.level == ScaffoldLevel.NONE


@pytest.mark.asyncio
async def test_relearning_gives_guided(scheduler):
    """Relearning state → GUIDED."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    await _give_card(scheduler, "n1", state=State.Relearning, stability=10.0)
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.level == ScaffoldLevel.GUIDED


# -- Context and gaps from graph neighbors ----------------------------------


@pytest.mark.asyncio
async def test_strong_neighbor_becomes_context(scheduler):
    """A well-known neighbour (Review, stability>5) is scaffolding context."""
    sub = scheduler.substrate
    await sub.add_neuron(_make_neuron("n1"))
    await sub.add_neuron(_make_neuron("n2"))
    await sub.add_synapse("n1", "n2", SynapseType.REQUIRES)
    await _give_card(scheduler, "n1", state=State.Review, stability=3.0)
    await _give_card(scheduler, "n2", state=State.Review, stability=10.0)

    scaffold = compute_scaffold(scheduler, "n1")
    assert "n2" in scaffold.context


@pytest.mark.asyncio
async def test_unreviewed_prerequisite_becomes_gap(scheduler):
    """A required neighbour with no card (never reviewed) is a gap."""
    sub = scheduler.substrate
    await sub.add_neuron(_make_neuron("n1"))
    await sub.add_neuron(_make_neuron("n2"))
    await sub.add_synapse("n1", "n2", SynapseType.REQUIRES)
    await _give_card(scheduler, "n1", state=State.Review, stability=3.0)
    # n2 has no card — never reviewed.

    scaffold = compute_scaffold(scheduler, "n1")
    assert "n2" in scaffold.gaps


@pytest.mark.asyncio
async def test_weak_prerequisite_becomes_gap(scheduler):
    """A required neighbour with a weak card (not strong) is a gap."""
    sub = scheduler.substrate
    await sub.add_neuron(_make_neuron("n1"))
    await sub.add_neuron(_make_neuron("n2"))
    await sub.add_synapse("n1", "n2", SynapseType.REQUIRES)
    await _give_card(scheduler, "n1", state=State.Review, stability=3.0)
    await _give_card(scheduler, "n2", state=State.Review, stability=2.0)

    scaffold = compute_scaffold(scheduler, "n1")
    assert "n2" in scaffold.gaps


@pytest.mark.asyncio
async def test_predecessor_can_be_context(scheduler):
    """Incoming edges: a strong predecessor adds to context."""
    sub = scheduler.substrate
    await sub.add_neuron(_make_neuron("n1"))
    await sub.add_neuron(_make_neuron("n2"))
    # Edge n2→n1, so n2 is a predecessor of n1.
    await sub.add_synapse("n2", "n1", SynapseType.REQUIRES)
    await _give_card(scheduler, "n1", state=State.Review, stability=3.0)
    await _give_card(scheduler, "n2", state=State.Review, stability=10.0)

    scaffold = compute_scaffold(scheduler, "n1")
    assert "n2" in scaffold.context


@pytest.mark.asyncio
async def test_extends_neighbor_with_weak_card_not_gap(scheduler):
    """A weak neighbour reached by a non-``requires`` edge is not a gap."""
    sub = scheduler.substrate
    await sub.add_neuron(_make_neuron("n1"))
    await sub.add_neuron(_make_neuron("n2"))
    await sub.add_synapse("n1", "n2", SynapseType.EXTENDS)
    await _give_card(scheduler, "n1", state=State.Review, stability=3.0)
    # n2 has a card but is weak — only a `requires` edge would make it a gap.
    await _give_card(scheduler, "n2", state=State.Review, stability=2.0)

    scaffold = compute_scaffold(scheduler, "n1")
    assert "n2" not in scaffold.gaps


@pytest.mark.asyncio
async def test_isolated_neuron_no_context_no_gaps(scheduler):
    """A neuron with no edges has empty context and gaps."""
    await scheduler.substrate.add_neuron(_make_neuron("n1"))
    await _give_card(scheduler, "n1", state=State.Review, stability=10.0)
    scaffold = compute_scaffold(scheduler, "n1")
    assert scaffold.context == []
    assert scaffold.gaps == []
