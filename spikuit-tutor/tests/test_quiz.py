"""Unit tests for spikuit_tutor.quiz (BaseQuiz + Flashcard)."""

from __future__ import annotations

import pytest

from spikuit_core import Grade, Neuron

from spikuit_tutor.quiz import (
    FLASHCARD_GRADE_CHOICES,
    Flashcard,
    QuizResponse,
    QuizResult,
    RenderResponse,
)
from spikuit_tutor.scaffold import Scaffold, ScaffoldLevel


def _neuron(content: str, nid: str = "n-test") -> Neuron:
    return Neuron(id=nid, content=content, type="concept", domain="math")


def _scaffold(level: ScaffoldLevel, **kwargs) -> Scaffold:
    return Scaffold(level=level, **kwargs)


# -- rendering --------------------------------------------------------------


def test_flashcard_front_full_shows_first_paragraph():
    n = _neuron("# Functor\n\nA map between categories.\n\nPreserves composition.")
    card = Flashcard(n, _scaffold(ScaffoldLevel.FULL))
    front = card.front()
    assert front.title == "Functor"
    assert front.body == "A map between categories."


def test_flashcard_front_guided_hides_body():
    n = _neuron("# Monad\n\nA monoid in the category of endofunctors.")
    card = Flashcard(n, _scaffold(ScaffoldLevel.GUIDED))
    front = card.front()
    assert front.title == "Monad"
    assert front.body == ""


def test_flashcard_front_minimal_title_only():
    n = _neuron("# Yoneda\n\nNatural transformations correspond to elements.")
    card = Flashcard(n, _scaffold(ScaffoldLevel.MINIMAL))
    front = card.front()
    assert front.body == ""
    assert front.hints == []


def test_flashcard_back_always_full_body():
    n = _neuron("# Adjoint\n\nHom(Fa,b) ≅ Hom(a,Gb).")
    card = Flashcard(n, _scaffold(ScaffoldLevel.NONE))
    back = card.back()
    assert back.title == "Adjoint"
    assert "Hom(Fa,b)" in back.body


def test_flashcard_hints_include_gaps_and_context():
    n = _neuron("# Limit\n\nA universal cone.")
    sc = _scaffold(
        ScaffoldLevel.FULL,
        context=["n-cat", "n-functor"],
        gaps=["n-diagram"],
    )
    card = Flashcard(n, sc)
    hints = card.front().hints
    assert any("Related concepts" in h for h in hints)
    assert any("Prerequisites" in h for h in hints)


def test_flashcard_render_returns_full_response():
    n = _neuron("# Functor\n\nBody text.")
    card = Flashcard(n, _scaffold(ScaffoldLevel.FULL))
    r = card.render()
    assert isinstance(r, RenderResponse)
    assert r.quiz_type == "flashcard"
    assert r.mode == "tui"
    assert r.accepts_notes is True
    assert len(r.grade_choices) == 4
    assert [c.key for c in r.grade_choices] == ["1", "2", "3", "4"]


# -- grading ----------------------------------------------------------------


@pytest.mark.parametrize(
    "grade",
    [Grade.MISS, Grade.WEAK, Grade.FIRE, Grade.STRONG],
)
def test_flashcard_grade_round_trip(grade):
    n = _neuron("# X\n\nbody")
    card = Flashcard(n, _scaffold(ScaffoldLevel.FULL))
    resp = QuizResponse(self_grade=grade, notes="hmm")
    result = card.grade(resp)
    assert isinstance(result, QuizResult)
    assert result.grade == grade
    assert result.needs_tutor_grading is False
    assert result.user_notes == "hmm"
    assert result.canonical_answer == "body"


def test_flashcard_grade_requires_self_grade():
    n = _neuron("# X\n\nbody")
    card = Flashcard(n, _scaffold(ScaffoldLevel.FULL))
    with pytest.raises(ValueError):
        card.grade(QuizResponse())


def test_flashcard_grade_choices_map_to_full_grade_range():
    assert len(FLASHCARD_GRADE_CHOICES) == 4
    grades = {c.grade for c in FLASHCARD_GRADE_CHOICES}
    assert grades == {Grade.MISS, Grade.WEAK, Grade.FIRE, Grade.STRONG}
