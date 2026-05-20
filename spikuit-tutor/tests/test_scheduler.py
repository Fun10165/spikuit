"""Tests for spikuit_tutor.scheduler — the TutorScheduler review engine.

TutorScheduler is the Stage-2 review orchestrator: it owns the FSRS
``Scheduler`` and the overlay store, and drives the substrate's ``fire``
as a callee (``tutor-extraction-stage2.md`` §4.2).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Grade, Neuron, Spike

from spikuit_tutor import TutorScheduler, TutorStore


@pytest_asyncio.fixture
async def substrate(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    for nid, title in [("n1", "Monad"), ("n2", "Functor"), ("n3", "Applicative")]:
        await c.add_neuron(
            Neuron.create(f"# {title}\n\nbody.", id=nid, type="concept", domain="math")
        )
    yield c
    await c.close()


@pytest_asyncio.fixture
async def scheduler(substrate, tmp_path):
    sched = TutorScheduler(substrate, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    yield sched
    await sched.close()


# -- lifecycle ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_on_fresh_db_prunes_nothing(scheduler):
    # The fixture already opened; a fresh overlay has no orphans.
    assert scheduler.store.card_ids() == set()


# -- review ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_card_none_before_review(scheduler):
    assert scheduler.get_card("n1") is None


@pytest.mark.asyncio
async def test_review_creates_card_and_records_spike(scheduler):
    card = await scheduler.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    assert card is not None
    # The card landed in the overlay store...
    assert scheduler.get_card("n1") is not None
    # ...and the substrate recorded the spike.
    spikes = await scheduler.substrate.get_spikes_for("n1", limit=10)
    assert len(spikes) == 1
    assert spikes[0].grade == Grade.FIRE


@pytest.mark.asyncio
async def test_review_persists_across_reopen(substrate, tmp_path):
    overlay = tmp_path / "test.tutor.db"

    s1 = TutorScheduler(substrate, TutorStore(overlay))
    await s1.open()
    await s1.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    await s1.close()

    s2 = TutorScheduler(substrate, TutorStore(overlay))
    await s2.open()
    assert s2.get_card("n1") is not None
    await s2.close()


# -- due_neurons -------------------------------------------------------------


@pytest.mark.asyncio
async def test_due_neurons_includes_never_reviewed(scheduler):
    """Lazy cards (§4.4): a never-reviewed neuron has no card but still
    surfaces as due via the new/unlearned bucket.
    """
    due = await scheduler.due_neurons(limit=10)
    assert set(due) == {"n1", "n2", "n3"}


@pytest.mark.asyncio
async def test_due_neurons_drops_reviewed_neuron(scheduler):
    """After a review the card's next due is in the future, so the
    neuron leaves the due queue (no longer past-due, no longer new).
    """
    await scheduler.review(Spike(neuron_id="n1", grade=Grade.STRONG))
    due = await scheduler.due_neurons(limit=10)
    assert "n1" not in due
    assert {"n2", "n3"} <= set(due)


@pytest.mark.asyncio
async def test_due_neurons_respects_limit(scheduler):
    due = await scheduler.due_neurons(limit=2)
    assert len(due) == 2


# -- near_due_neurons --------------------------------------------------------


@pytest.mark.asyncio
async def test_near_due_neurons_empty_without_cards(scheduler):
    assert await scheduler.near_due_neurons(days_ahead=7) == []


@pytest.mark.asyncio
async def test_near_due_neurons_excludes_ids(scheduler):
    await scheduler.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    await scheduler.review(Spike(neuron_id="n2", grade=Grade.FIRE))
    near = await scheduler.near_due_neurons(days_ahead=30, exclude_ids={"n1"})
    assert "n1" not in near


# -- reconcile-on-open -------------------------------------------------------


@pytest.mark.asyncio
async def test_open_reconciles_orphan_cards(substrate, tmp_path):
    """A card whose neuron was deleted in the substrate is pruned when
    the scheduler next opens (§4.4 reconcile-on-open).
    """
    overlay = tmp_path / "test.tutor.db"

    s1 = TutorScheduler(substrate, TutorStore(overlay))
    await s1.open()
    await s1.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    await s1.close()

    # n1 is deleted from the substrate between sessions.
    await substrate.remove_neuron("n1")

    s2 = TutorScheduler(substrate, TutorStore(overlay))
    pruned = await s2.open()
    assert pruned == ["n1"]
    assert s2.get_card("n1") is None
    await s2.close()
