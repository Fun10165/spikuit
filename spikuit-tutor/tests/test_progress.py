"""Tests for spikuit_tutor.progress — the learner-facing retention report.

Stage 2 (``docs/design/tutor-extraction-stage2.md`` §4.3, §5.2) moves
``Circuit.progress`` wholesale into the tutor as ``compute_progress``.
It reads FSRS card state from the overlay store and review history /
graph topology from the substrate through the appkit contract.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Grade, Neuron, Spike, SynapseType

from spikuit_tutor import TutorScheduler, TutorStore, compute_progress


@pytest_asyncio.fixture
async def scheduler(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    await c.add_neuron(
        Neuron.create("# Monad\n\nbody.", id="n1", type="concept", domain="math")
    )
    await c.add_neuron(
        Neuron.create("# Functor\n\nbody.", id="n2", type="concept", domain="math")
    )
    await c.add_neuron(
        Neuron.create("# Verb\n\nbody.", id="n3", type="concept", domain="french")
    )
    await c.add_synapse("n1", "n2", type=SynapseType.REQUIRES)

    sched = TutorScheduler(c, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    yield sched
    await sched.close()
    await c.close()


# -- shape -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_progress_returns_expected_keys(scheduler):
    report = await compute_progress(scheduler)
    assert set(report) == {
        "domain_filter",
        "mastery",
        "retention",
        "velocity",
        "weak_spots",
        "adherence",
    }
    assert report["domain_filter"] is None


@pytest.mark.asyncio
async def test_compute_progress_domain_filter(scheduler):
    report = await compute_progress(scheduler, domain="french")
    assert report["domain_filter"] == "french"
    # Only the single french neuron is in scope.
    assert report["adherence"]["total_neurons"] == 1
    assert report["velocity"]["total_neurons"] == 1


# -- retention tracks reviews ------------------------------------------------


@pytest.mark.asyncio
async def test_retention_tracks_reviews(scheduler):
    """retention.total_reviews counts spikes recorded via review()."""
    before = await compute_progress(scheduler)
    assert before["retention"]["total_reviews"] == 0
    assert before["retention"]["overall"] is None

    await scheduler.review(Spike(neuron_id="n1", grade=Grade.FIRE))
    await scheduler.review(Spike(neuron_id="n2", grade=Grade.MISS))

    after = await compute_progress(scheduler)
    assert after["retention"]["total_reviews"] == 2
    # One of two reviews was a success (FIRE) → 0.5.
    assert after["retention"]["overall"] == pytest.approx(0.5)


# -- adherence tracks first review -------------------------------------------


@pytest.mark.asyncio
async def test_adherence_tracks_reviewed_at_least_once(scheduler):
    before = await compute_progress(scheduler)
    assert before["adherence"]["reviewed_at_least_once"] == 0
    assert before["adherence"]["total_neurons"] == 3

    await scheduler.review(Spike(neuron_id="n1", grade=Grade.FIRE))

    after = await compute_progress(scheduler)
    assert after["adherence"]["reviewed_at_least_once"] == 1
    # adherence_rate is rounded to 3 decimals: round(1/3, 3) == 0.333.
    assert after["adherence"]["adherence_rate"] == 0.333


# -- mastery reflects overlay cards ------------------------------------------


@pytest.mark.asyncio
async def test_mastery_reflects_reviewed_cards(scheduler):
    await scheduler.review(Spike(neuron_id="n1", grade=Grade.STRONG))
    report = await compute_progress(scheduler)
    math_stats = report["mastery"]["math"]
    assert math_stats["neuron_count"] == 2
    assert math_stats["reviewed_count"] == 1
    assert math_stats["avg_stability"] is not None
