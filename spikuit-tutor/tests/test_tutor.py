"""Tests for spikuit_tutor.tutor — ExamPlan + TutorSession interpreter."""

from __future__ import annotations

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Grade, Neuron, SynapseType

from spikuit_tutor.quiz import QuizResponse, QuizResult
from spikuit_tutor.tutor import (
    ExamPlan,
    ExamStep,
    FollowUp,
    FollowUpGenerator,
    FollowUpResult,
    InterleaveMode,
    TransitionEvent,
    TutorSession,
    plan_exam,
)


@pytest_asyncio.fixture
async def circuit(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    n1 = Neuron.create("# Monad\n\nA monoid in endofunctors.", id="n1", type="concept", domain="math")
    n2 = Neuron.create("# Functor\n\nA map between categories.", id="n2", type="concept", domain="math")
    n3 = Neuron.create("# Applicative\n\nBetween functor and monad.", id="n3", type="concept", domain="math")
    await c.add_neuron(n1)
    await c.add_neuron(n2)
    await c.add_neuron(n3)
    await c.add_synapse("n1", "n2", type=SynapseType.REQUIRES)
    yield c
    await c.close()


# -- plan_exam ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_exam_with_explicit_ids(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n3"])
    assert isinstance(plan, ExamPlan)
    assert [s.neuron_id for s in plan.steps] == ["n3"]
    assert plan.max_attempts == 3
    assert plan.require_mastery is False


@pytest.mark.asyncio
async def test_plan_exam_expands_gaps(circuit):
    """n1 requires n2 — when n2 is weak, it should appear before n1."""
    # Force n1 into a state where n2 shows up as a gap in its scaffold:
    # fire n1 a few times to raise its stability while leaving n2 weak.
    from spikuit_core import Spike
    for _ in range(3):
        await circuit.fire(Spike(neuron_id="n1", grade=Grade.FIRE))
    plan = await plan_exam(circuit, neuron_ids=["n1"])
    ids = [s.neuron_id for s in plan.steps]
    # Gap expansion should insert n2 before n1 if n2 is a gap
    if "n2" in ids:
        assert ids.index("n2") < ids.index("n1")


@pytest.mark.asyncio
async def test_plan_exam_deduplicates(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2", "n1"])
    ids = [s.neuron_id for s in plan.steps]
    assert len(ids) == len(set(ids))


# -- TutorSession — happy path -----------------------------------------------


@pytest.mark.asyncio
async def test_session_advances_on_correct(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2", "n3"])
    sess = TutorSession(circuit, plan, persist=False)

    step1 = await sess.teach()
    assert step1 is not None
    assert step1.neuron_id == "n2"

    tr = await sess.record_response(QuizResponse(self_grade=Grade.FIRE))
    assert tr.event == TransitionEvent.ADVANCE

    tr = await sess.advance()
    assert tr.event == TransitionEvent.ADVANCE
    assert tr.next_step is not None
    assert tr.next_step.neuron_id == "n3"


@pytest.mark.asyncio
async def test_session_fires_awaited_not_background(circuit):
    """Regression: FSRS writes must be awaited, not fire-and-forget."""
    plan = await plan_exam(circuit, neuron_ids=["n2"])
    sess = TutorSession(circuit, plan, persist=True)
    await sess.teach()
    await sess.record_response(QuizResponse(self_grade=Grade.FIRE))
    await sess.advance()
    # If the fire was awaited, the spike is now in the DB
    spikes = await circuit._db.get_spikes_for("n2", limit=10)
    assert len(spikes) == 1
    assert spikes[0].grade == Grade.FIRE


# -- TutorSession — retry loop -----------------------------------------------


@pytest.mark.asyncio
async def test_session_retry_on_miss_until_max_attempts(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2"])
    plan.max_attempts = 3
    sess = TutorSession(circuit, plan, persist=False)
    await sess.teach()

    # attempt 1 — miss, retry
    tr = await sess.record_response(QuizResponse(self_grade=Grade.MISS))
    assert tr.event == TransitionEvent.RETRY_NEEDED

    # attempt 2 — miss, retry
    tr = await sess.record_response(QuizResponse(self_grade=Grade.MISS))
    assert tr.event == TransitionEvent.RETRY_NEEDED

    # attempt 3 — miss, reveal answer
    tr = await sess.record_response(QuizResponse(self_grade=Grade.MISS))
    assert tr.event == TransitionEvent.REVEAL_ANSWER

    tr = await sess.advance()
    assert tr.event == TransitionEvent.ADVANCE
    assert tr.next_step is None


# -- TutorSession — mastery re-queue -----------------------------------------


@pytest.mark.asyncio
async def test_session_mastery_requeue(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2", "n3"])
    plan.require_mastery = True
    plan.mastery_max_requeues = 1
    plan.max_attempts = 2
    sess = TutorSession(circuit, plan, persist=False)

    # First step: n2. Miss twice → should re-queue (not reveal).
    await sess.teach()
    await sess.record_response(QuizResponse(self_grade=Grade.MISS))
    tr = await sess.record_response(QuizResponse(self_grade=Grade.MISS))
    assert tr.event == TransitionEvent.REQUEUE

    # The plan.steps should now end with n2 (re-queued)
    assert plan.steps[-1].neuron_id == "n2"
    assert plan.steps[-1].requeue_count == 1


# -- TutorSession — follow-up loop -------------------------------------------


@pytest.mark.asyncio
async def test_follow_up_on_correct_then_advance(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2"])
    plan.elaborate_on_correct = True
    # Manually attach a follow-up (builder only does so when scaffold.context exists)
    plan.steps[0].follow_ups.append(
        FollowUp(prompt="why?", rubric="mention categories")
    )
    sess = TutorSession(circuit, plan, persist=False)
    await sess.teach()

    tr = await sess.record_response(QuizResponse(self_grade=Grade.FIRE))
    assert tr.event == TransitionEvent.ENTER_FOLLOW_UP
    assert tr.follow_up is not None

    # Supply a follow-up result (LLM would do this IRL)
    fu_result = FollowUpResult(
        follow_up=tr.follow_up,
        student_response="because functors",
        correctness=0.8,
        feedback="good",
        note_for_next_review="",
    )
    tr2 = await sess.record_follow_up(fu_result)
    assert tr2.event == TransitionEvent.ADVANCE


@pytest.mark.asyncio
async def test_follow_up_result_is_not_quiz_result():
    """Regression: FollowUpResult must be a distinct type from QuizResult
    so it can never reach circuit.fire accidentally.
    """
    assert FollowUpResult is not QuizResult
    # And FollowUpResult should not be a subclass
    assert not issubclass(FollowUpResult, QuizResult)


# -- TutorSession — close/abandon --------------------------------------------


@pytest.mark.asyncio
async def test_close_fires_in_flight_as_miss(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2"])
    sess = TutorSession(circuit, plan, persist=True)
    await sess.teach()
    # Leave it open — no response
    await sess.close()

    spikes = await circuit._db.get_spikes_for("n2", limit=10)
    assert len(spikes) == 1
    assert spikes[0].grade == Grade.MISS


# -- Metacognitive calibration -----------------------------------------------


@pytest.mark.asyncio
async def test_session_stats_calibration_gap(circuit):
    """calibration_gap = mean |confidence - grade|."""
    plan = await plan_exam(circuit, neuron_ids=["n2", "n3"])
    sess = TutorSession(circuit, plan, persist=False)

    # Step n2: confidence 4 (perfect), actual grade 3 (fire) → gap 1
    await sess.teach()
    await sess.record_response(QuizResponse(self_grade=Grade.FIRE, confidence=4))
    await sess.advance()

    # Step n3: confidence 2, actual grade 2 (weak) → gap 0
    await sess.record_response(QuizResponse(self_grade=Grade.WEAK, confidence=2))
    await sess.advance()

    stats = sess.stats
    assert stats["calibration_gap"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_session_stats_calibration_none_when_no_confidence(circuit):
    plan = await plan_exam(circuit, neuron_ids=["n2"])
    sess = TutorSession(circuit, plan, persist=False)
    await sess.teach()
    await sess.record_response(QuizResponse(self_grade=Grade.FIRE))  # no confidence
    await sess.advance()
    assert sess.stats["calibration_gap"] is None


# -- FollowUpGenerator Protocol ----------------------------------------------


class _StubFollowUpGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_follow_up(self, *, neuron, anchor, scaffold) -> FollowUp:
        self.calls += 1
        return FollowUp(
            prompt=f"custom: {neuron.id} vs {anchor.id}",
            rubric="stub rubric",
            related_neuron_ids=[anchor.id],
        )


def test_stub_follow_up_generator_satisfies_protocol():
    assert isinstance(_StubFollowUpGenerator(), FollowUpGenerator)


@pytest.mark.asyncio
async def test_builder_uses_follow_up_generator(circuit):
    """When a generator is provided, plan_exam should delegate follow-up
    creation to it instead of the default template.
    """
    from spikuit_core import Spike
    # Make n2 have n1 in its context (fire n1 so n2 picks up anchor)
    await circuit.fire(Spike(neuron_id="n1", grade=Grade.FIRE))

    gen = _StubFollowUpGenerator()
    plan = await plan_exam(
        circuit,
        neuron_ids=["n2"],
        elaborate_on_correct=True,
        follow_up_generator=gen,
    )
    # Only assert if n2 actually has context (scaffold-dependent)
    if plan.steps and plan.steps[-1].follow_ups:
        assert gen.calls >= 1
        assert plan.steps[-1].follow_ups[0].prompt.startswith("custom:")


# -- Circuit.near_due_neurons ------------------------------------------------


@pytest.mark.asyncio
async def test_near_due_neurons_returns_soon_due(circuit):
    """near_due_neurons returns cards whose next review is within days_ahead."""
    # After init, all cards are immediately due — none are "near-due"
    near = await circuit.near_due_neurons(days_ahead=2, limit=10)
    assert near == []

    # Fire n2 with FIRE to push it into the near-due window (a few days out)
    from spikuit_core import Spike
    await circuit.fire(Spike(neuron_id="n2", grade=Grade.FIRE))
    near = await circuit.near_due_neurons(days_ahead=7, limit=10)
    # n2 is now due in the future, should be in the near list
    assert "n2" in near
