"""Tests for AgentLLMGrader — Protocol compliance + response parsing."""

from __future__ import annotations

import pytest

from spikuit_agents.tutor import AgentLLMGrader, build_grade_prompt
from spikuit_tutor.quiz import LLMGrader
from spikuit_core import Grade


def _make_fn(raw: str):
    async def fn(_prompt: str) -> str:
        return raw
    return fn


def test_satisfies_llm_grader_protocol():
    grader = AgentLLMGrader(_make_fn('{"grade": 3, "correctness": 0.8, "feedback": "ok"}'))
    assert isinstance(grader, LLMGrader)


@pytest.mark.asyncio
async def test_grade_plain_json():
    grader = AgentLLMGrader(
        _make_fn('{"grade": 4, "correctness": 0.95, "feedback": "perfect"}')
    )
    result = await grader.grade_free_response(
        question="What is a functor?",
        rubric="mentions morphisms",
        canonical_answer="a structure-preserving map",
        student_response="a map between categories",
    )
    assert result.grade == Grade.STRONG
    assert result.correctness == pytest.approx(0.95)
    assert result.feedback == "perfect"
    assert result.needs_tutor_grading is False


@pytest.mark.asyncio
async def test_grade_json_wrapped_in_markdown_fence():
    grader = AgentLLMGrader(
        _make_fn('```json\n{"grade": 1, "correctness": 0.1, "feedback": "wrong"}\n```')
    )
    result = await grader.grade_free_response(
        question="q", rubric="r", canonical_answer="c", student_response="s",
    )
    assert result.grade == Grade.MISS


@pytest.mark.asyncio
async def test_grade_json_with_prose_prefix():
    raw = 'Here is my judgment: {"grade": 2, "correctness": 0.4, "feedback": "partial"}'
    grader = AgentLLMGrader(_make_fn(raw))
    result = await grader.grade_free_response(
        question="q", rubric="r", canonical_answer="c", student_response="s",
    )
    assert result.grade == Grade.WEAK


@pytest.mark.asyncio
async def test_grade_out_of_range_raises():
    grader = AgentLLMGrader(_make_fn('{"grade": 5, "correctness": 1.0, "feedback": "?"}'))
    with pytest.raises(ValueError, match="out of range"):
        await grader.grade_free_response(
            question="q", rubric="r", canonical_answer="c", student_response="s",
        )


@pytest.mark.asyncio
async def test_grade_missing_json_raises():
    grader = AgentLLMGrader(_make_fn("I cannot grade this"))
    with pytest.raises(ValueError, match="No JSON"):
        await grader.grade_free_response(
            question="q", rubric="r", canonical_answer="c", student_response="s",
        )


def test_build_grade_prompt_contains_all_sections():
    prompt = build_grade_prompt(
        question="What is X?",
        rubric="must mention Y",
        canonical_answer="X is Y",
        student_response="X is Z",
    )
    assert "What is X?" in prompt
    assert "must mention Y" in prompt
    assert "X is Y" in prompt
    assert "X is Z" in prompt
    assert "1-4" in prompt


@pytest.mark.asyncio
async def test_end_to_end_with_tutor_session(tmp_path):
    """AgentLLMGrader result should be feedable to TutorSession.record_llm_graded."""
    from spikuit_tutor.quiz import FreeResponseQuiz, QuizResponse
    from spikuit_tutor.tutor import TutorSession
    from spikuit_tutor.tutor.plan import ExamPlan, ExamStep, TransitionEvent
    from spikuit_core import Circuit, Neuron
    from spikuit_tutor import TutorScheduler, TutorStore, compute_scaffold

    circuit = Circuit(db_path=tmp_path / "test.db")
    await circuit.connect()
    n = Neuron.create("# Functor\n\nA map.", id="n1", type="concept", domain="math")
    await circuit.add_neuron(n)
    scheduler = TutorScheduler(circuit, TutorStore(tmp_path / "test.tutor.db"))
    await scheduler.open()
    try:
        neuron = await circuit.get_neuron("n1")
        scaffold = compute_scaffold(scheduler, "n1")

        step = ExamStep(
            neuron_id="n1",
            quiz=FreeResponseQuiz(neuron, scaffold),
            scaffold=scaffold,
        )
        plan = ExamPlan(steps=[step])
        sess = TutorSession(scheduler, plan, persist=True)
        await sess.teach()

        grader = AgentLLMGrader(
            _make_fn('{"grade": 3, "correctness": 0.8, "feedback": "solid"}')
        )
        raw = step.quiz.grade(QuizResponse(answer="a map between categories"))
        final = await grader.grade_free_response(
            question="q",
            rubric=raw.grading_rubric or "",
            canonical_answer=raw.canonical_answer or "",
            student_response=raw.student_response or "",
        )
        tr = await sess.record_llm_graded(final)
        assert tr.event == TransitionEvent.ADVANCE

        await sess.advance()
        spikes = await circuit.get_spikes_for("n1", limit=10)
        assert len(spikes) == 1
        assert spikes[0].grade == Grade.FIRE
    finally:
        await scheduler.close()
        await circuit.close()
