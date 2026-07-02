"""Unit tests for spikuit_tutor.quiz.generated (GeneratedQuiz)."""

from __future__ import annotations

import pytest

from spikuit_core import Grade, QuizItem, QuizItemRole

from spikuit_tutor.quiz import GeneratedQuiz, QuizResponse, QuizResult
from spikuit_tutor.scaffold import Scaffold, ScaffoldLevel


def _item() -> QuizItem:
    return QuizItem(
        question="… les voir ▁▁▁▁ à l'extérieur. → ?",
        answer="rôder",
        hints=["prowl / lurk", "starts with r"],
        grading_criteria="accept rôder / roder",
        scaffold_level="full",
        neuron_ids={"n-1": QuizItemRole.PRIMARY},
    )


def _sc() -> Scaffold:
    return Scaffold(level=ScaffoldLevel.FULL)


def test_front_is_the_stored_question():
    card = GeneratedQuiz(_item(), _sc())
    front = card.front()
    assert "▁▁▁▁" in front.body            # the generated question, verbatim
    assert "rôder" not in front.body        # answer not on the front


def test_back_reveals_answer_and_hints():
    card = GeneratedQuiz(_item(), _sc())
    back = card.back()
    assert back.body == "rôder"
    assert back.hints == ["prowl / lurk", "starts with r"]


@pytest.mark.parametrize("grade", [Grade.MISS, Grade.WEAK, Grade.FIRE, Grade.STRONG])
def test_grade_uses_self_grade(grade):
    card = GeneratedQuiz(_item(), _sc())
    result = card.grade(QuizResponse(self_grade=grade, notes="n"))
    assert isinstance(result, QuizResult)
    assert result.grade == grade
    assert result.needs_tutor_grading is False
    assert result.canonical_answer == "rôder"
    assert result.grading_rubric == "accept rôder / roder"
    assert result.user_notes == "n"


def test_grade_requires_self_grade():
    card = GeneratedQuiz(_item(), _sc())
    with pytest.raises(ValueError):
        card.grade(QuizResponse())


def test_render_reports_generated_type():
    r = GeneratedQuiz(_item(), _sc()).render()
    assert r.quiz_type == "generated"
    assert len(r.grade_choices) == 4


# -- answer extraction (review finding 12 / A7) ------------------------------


def test_dict_answer_extracts_value_not_repr():
    card = GeneratedQuiz(_item(), _sc())
    result = card.grade(QuizResponse(self_grade=Grade.FIRE, answer={"blank1": "rôder"}))
    assert result.student_response == "rôder"


def test_empty_dict_answer_yields_none_not_string():
    card = GeneratedQuiz(_item(), _sc())
    result = card.grade(QuizResponse(self_grade=Grade.FIRE, answer={}))
    assert result.student_response is None


def test_plain_string_answer_still_works():
    card = GeneratedQuiz(_item(), _sc())
    result = card.grade(QuizResponse(self_grade=Grade.FIRE, answer="rôder"))
    assert result.student_response == "rôder"
