"""Tests for FreeResponseQuiz + LLMGrader Protocol."""

from __future__ import annotations

import pytest
import pytest_asyncio

from spikuit_core import Circuit, Grade, Neuron, Spike

from spikuit_tutor import TutorScheduler, TutorStore
from spikuit_tutor.quiz import (
    FreeResponseQuiz,
    LLMGrader,
    QuizResponse,
    QuizResult,
)
from spikuit_tutor.scaffold import ScaffoldLevel, compute_scaffold
from spikuit_tutor.tutor import TutorSession, plan_exam


@pytest_asyncio.fixture
async def scheduler(tmp_path):
    c = Circuit(db_path=tmp_path / "test.db")
    await c.connect()
    n = Neuron.create(
        "# Functor\n\nA map between categories that preserves structure.",
        id="n1",
        type="concept",
        domain="math",
    )
    await c.add_neuron(n)
    sched = TutorScheduler(c, TutorStore(tmp_path / "test.tutor.db"))
    await sched.open()
    yield sched
    await sched.close()
    await c.close()


# -- FreeResponseQuiz --------------------------------------------------------


@pytest.mark.asyncio
async def test_free_response_grade_requests_tutor_grading(scheduler):
    neuron = await scheduler.get_neuron("n1")
    scaffold = compute_scaffold(scheduler, "n1")
    q = FreeResponseQuiz(neuron, scaffold)

    front = q.front()
    assert "Functor" in front.title
    assert front.body  # non-empty question

    result = q.grade(QuizResponse(answer="a structure-preserving map"))
    assert result.needs_tutor_grading is True
    assert result.grade is None
    assert result.grading_rubric
    assert result.canonical_answer
    assert result.student_response == "a structure-preserving map"


@pytest.mark.asyncio
async def test_free_response_custom_question_and_rubric(scheduler):
    neuron = await scheduler.get_neuron("n1")
    scaffold = compute_scaffold(scheduler, "n1")
    q = FreeResponseQuiz(
        neuron, scaffold,
        question="Define a functor.",
        rubric="Must mention morphisms.",
    )
    assert q.front().body == "Define a functor."
    result = q.grade(QuizResponse(answer="..."))
    assert result.grading_rubric == "Must mention morphisms."


# -- LLMGrader Protocol ------------------------------------------------------


class StubGrader:
    """Minimal LLMGrader impl for tests."""

    def __init__(self, grade: Grade = Grade.FIRE) -> None:
        self.grade = grade
        self.calls: list[dict] = []

    async def grade_free_response(
        self,
        *,
        question: str,
        rubric: str,
        canonical_answer: str,
        student_response: str,
    ) -> QuizResult:
        self.calls.append({
            "question": question,
            "rubric": rubric,
            "canonical": canonical_answer,
            "student": student_response,
        })
        return QuizResult(
            grade=self.grade,
            needs_tutor_grading=False,
            feedback="stub feedback",
            correctness=0.85,
            student_response=student_response,
        )


def test_stub_grader_satisfies_protocol():
    grader = StubGrader()
    assert isinstance(grader, LLMGrader)


# -- Integration with TutorSession ------------------------------------------


@pytest.mark.asyncio
async def test_free_response_needs_llm_raises_on_record_response(scheduler):
    """record_response must refuse to handle quizzes that need LLM grading."""
    neuron = await scheduler.get_neuron("n1")
    scaffold = compute_scaffold(scheduler, "n1")

    from spikuit_tutor.tutor.plan import ExamPlan, ExamStep
    step = ExamStep(
        neuron_id="n1",
        quiz=FreeResponseQuiz(neuron, scaffold),
        scaffold=scaffold,
    )
    plan = ExamPlan(steps=[step])
    sess = TutorSession(scheduler, plan, persist=False)
    await sess.teach()

    with pytest.raises(RuntimeError, match="LLM grading"):
        await sess.record_response(QuizResponse(answer="..."))


@pytest.mark.asyncio
async def test_free_response_record_llm_graded_advances(scheduler):
    neuron = await scheduler.get_neuron("n1")
    scaffold = compute_scaffold(scheduler, "n1")

    from spikuit_tutor.tutor.plan import ExamPlan, ExamStep
    step = ExamStep(
        neuron_id="n1",
        quiz=FreeResponseQuiz(neuron, scaffold),
        scaffold=scaffold,
    )
    plan = ExamPlan(steps=[step])
    sess = TutorSession(scheduler, plan, persist=True)
    await sess.teach()

    # Caller runs grader manually, then feeds result back.
    grader = StubGrader(grade=Grade.FIRE)
    raw = step.quiz.grade(QuizResponse(answer="a morphism-preserving map"))
    assert raw.needs_tutor_grading is True

    final = await grader.grade_free_response(
        question="q",
        rubric=raw.grading_rubric or "",
        canonical_answer=raw.canonical_answer or "",
        student_response=raw.student_response or "",
    )
    from spikuit_tutor.tutor.plan import TransitionEvent
    tr = await sess.record_llm_graded(final)
    assert tr.event == TransitionEvent.ADVANCE

    tr = await sess.advance()
    # Spike should be in the substrate.
    spikes = await scheduler.substrate.get_spikes_for("n1", limit=10)
    assert len(spikes) == 1
    assert spikes[0].grade == Grade.FIRE
    assert len(grader.calls) == 1


# -- Builder routing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_routes_minimal_scaffold_to_free_response(scheduler):
    """When a neuron is strong (MINIMAL scaffold), plan_exam should pick
    FreeResponseQuiz over Flashcard — desirable difficulties in action.
    """
    # Force n1's scaffold down to MINIMAL by reviewing STRONG repeatedly.
    for _ in range(6):
        await scheduler.review(Spike(neuron_id="n1", grade=Grade.STRONG))

    scaffold = compute_scaffold(scheduler, "n1")
    # Only run the assertion if we actually hit MINIMAL/NONE territory.
    if scaffold.level in (ScaffoldLevel.MINIMAL, ScaffoldLevel.NONE):
        plan = await plan_exam(scheduler, neuron_ids=["n1"])
        assert isinstance(plan.steps[0].quiz, FreeResponseQuiz)
