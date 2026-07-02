"""Unit tests for spikuit_tutor.quiz.cloze (Cloze quiz type).

Direction follows the scaffold level:
    FULL / GUIDED     → recognition (show term, recall meaning)
    MINIMAL / NONE    → production  (show meaning, recall term)
"""

from __future__ import annotations

import unicodedata

import pytest

from spikuit_core import Grade, Neuron

from spikuit_tutor.quiz import Cloze, QuizResponse, QuizResult
from spikuit_tutor.quiz.cloze import BLANK
from spikuit_tutor.scaffold import Scaffold, ScaffoldLevel

PARI = "# un pari — 賭け / wager\n\n`un pari` = 賭け、ベット、wager。"
RODER = "# rôder (Verb)\n\nprowl, lurk, to prowl"
PARMI = "# parmi (Adp)\n\nの中で, 中で, の中に"


def _neuron(content: str, nid: str = "n-test", type: str = "vocab") -> Neuron:
    return Neuron(id=nid, content=content, type=type, domain="language")


def _sc(level: ScaffoldLevel) -> Scaffold:
    return Scaffold(level=level)


# -- applicability ----------------------------------------------------------


@pytest.mark.parametrize("content", [PARI, RODER, PARMI])
def test_cloze_fires_on_vocab_shaped_titles(content):
    assert Cloze.try_build(_neuron(content), _sc(ScaffoldLevel.FULL)) is not None


def test_cloze_skips_bare_concept_title():
    n = _neuron("# Functor\n\nA map between categories.")
    assert Cloze.try_build(n, _sc(ScaffoldLevel.FULL)) is None


def test_cloze_skips_missing_title():
    n = _neuron("no heading, just prose.")
    assert Cloze.try_build(n, _sc(ScaffoldLevel.MINIMAL)) is None


# -- direction selection ----------------------------------------------------


@pytest.mark.parametrize("level", [ScaffoldLevel.FULL, ScaffoldLevel.GUIDED])
def test_new_cards_are_recognition(level):
    card = Cloze.try_build(_neuron(RODER), _sc(level))
    assert card is not None
    assert card._direction == "recognition"  # type: ignore[attr-defined]


@pytest.mark.parametrize("level", [ScaffoldLevel.MINIMAL, ScaffoldLevel.NONE])
def test_mature_cards_are_production(level):
    card = Cloze.try_build(_neuron(RODER), _sc(level))
    assert card is not None
    assert card._direction == "production"  # type: ignore[attr-defined]


# -- recognition: show term, recall meaning (meaning hidden) -----------------


def test_recognition_shows_term_hides_meaning():
    card = Cloze.try_build(_neuron(PARI), _sc(ScaffoldLevel.FULL))
    assert card is not None
    front = card.front()
    assert front.title == "un pari"          # term is the cue
    assert "賭け" not in front.title and "賭け" not in front.body  # meaning hidden
    assert front.body == ""


def test_recognition_shape2_shows_term():
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.GUIDED))
    assert card is not None
    assert card.front().title == "rôder"
    assert "prowl" not in card.front().body   # meaning hidden


# -- production: show meaning, recall term (term hidden) ---------------------


def test_production_shape1_blanks_term():
    card = Cloze.try_build(_neuron(PARI), _sc(ScaffoldLevel.MINIMAL))
    assert card is not None
    front = card.front()
    assert BLANK in front.body
    assert "un pari" not in front.body        # term hidden
    assert front.title == "賭け / wager"        # meaning shown as heading


def test_production_shape2_shows_meaning_heading():
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.NONE))
    assert card is not None
    front = card.front()
    assert front.title == "prowl, lurk, to prowl"  # meaning heading (no empty title)
    assert "rôder" not in front.title and "rôder" not in front.body  # term hidden


# -- front never leaks the hidden side, both directions ----------------------


@pytest.mark.parametrize("content", [PARI, RODER, PARMI])
@pytest.mark.parametrize("level", list(ScaffoldLevel))
def test_front_hides_the_recall_target(content, level):
    card = Cloze.try_build(_neuron(content), _sc(level))
    assert card is not None
    front = card.front()
    shown = f"{front.title}\n{front.body}"
    if card._direction == "recognition":       # type: ignore[attr-defined]
        assert card._term in shown             # type: ignore[attr-defined]
    else:  # production — the term must NOT appear
        assert card._term not in shown         # type: ignore[attr-defined]


def test_back_always_reveals_everything():
    card = Cloze.try_build(_neuron(PARI), _sc(ScaffoldLevel.FULL))
    assert card is not None
    back = card.back()
    assert back.title == "un pari — 賭け / wager"
    assert "un pari" in back.body


# -- grading ----------------------------------------------------------------


@pytest.mark.parametrize("grade", [Grade.MISS, Grade.WEAK, Grade.FIRE, Grade.STRONG])
def test_grade_uses_self_grade(grade):
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.NONE))
    assert card is not None
    result = card.grade(QuizResponse(self_grade=grade, notes="ok"))
    assert isinstance(result, QuizResult)
    assert result.grade == grade
    assert result.needs_tutor_grading is False
    assert result.user_notes == "ok"


def test_grade_requires_self_grade():
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.FULL))
    assert card is not None
    with pytest.raises(ValueError):
        card.grade(QuizResponse())


def test_production_answer_is_checked_against_term():
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.NONE))
    assert card is not None
    right = card.grade(QuizResponse(self_grade=Grade.FIRE, answer="  Rôder "))
    assert right.correctness == 1.0
    assert right.canonical_answer == "rôder"
    wrong = card.grade(QuizResponse(self_grade=Grade.MISS, answer="marcher"))
    assert wrong.correctness == 0.0


def test_recognition_answer_not_auto_checked():
    # The meaning is free-form → no mechanical correctness.
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.FULL))
    assert card is not None
    result = card.grade(QuizResponse(self_grade=Grade.FIRE, answer="prowl"))
    assert result.correctness is None
    assert result.canonical_answer == "prowl, lurk, to prowl"  # the meaning


def test_render_reports_cloze_type():
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.FULL))
    assert card is not None
    r = card.render()
    assert r.quiz_type == "cloze"
    assert len(r.grade_choices) == 4


# -- gate: whitelist POS tags, reject arbitrary parentheticals --------------


@pytest.mark.parametrize("content", [
    "# Overlapping generations model (OLG)\n\nHouseholds live two periods.",
    "# Some paper (1994)\n\nA seminal contribution.",
])
def test_cloze_skips_non_pos_parenthetical(content):
    assert Cloze.try_build(_neuron(content, type="concept"), _sc(ScaffoldLevel.FULL)) is None


def test_cloze_skips_ascii_hyphen_enumeration():
    n = _neuron(
        "# Aiyagari - Bewley - Huggett models\n\nHeterogeneous-agent models.",
        type="concept",
    )
    assert Cloze.try_build(n, _sc(ScaffoldLevel.FULL)) is None


# -- leak regressions (review findings 2/3/4) --------------------------------


def test_production_blanking_is_case_insensitive():
    content = (
        "# un pari — 賭け\n\n"
        "Un pari est un engagement. `un pari` = 賭け。"
    )
    card = Cloze.try_build(_neuron(content), _sc(ScaffoldLevel.MINIMAL))
    assert card is not None
    front = card.front()
    shown = f"{front.title}\n{front.body}"
    assert "un pari" not in shown.lower()
    assert BLANK in front.body


def test_production_cue_embedding_term_is_blanked_not_leaked():
    content = "# un pari — 賭け (faire un pari)\n\n`un pari` = 賭け。"
    card = Cloze.try_build(_neuron(content), _sc(ScaffoldLevel.MINIMAL))
    assert card is not None
    front = card.front()
    shown = f"{front.title}\n{front.body}"
    assert "un pari" not in shown.lower()
    assert BLANK in front.title


def test_production_blanking_respects_word_boundaries():
    content = "# or — gold\n\nencore une fois, l or brille."
    card = Cloze.try_build(_neuron(content), _sc(ScaffoldLevel.MINIMAL))
    assert card is not None
    front = card.front()
    assert "encore" in front.body  # untouched — "or" inside it must not blank
    assert BLANK in front.body
    assert " or " not in f" {front.body} "  # the standalone occurrence is gone


# -- title-only vocab neuron (review finding 6 / A4) -------------------------


def test_title_only_vocab_neuron_still_builds_production():
    n = _neuron("# un pari — 賭け / wager", nid="n-title-only")
    card = Cloze.try_build(n, _sc(ScaffoldLevel.NONE))
    assert card is not None
    front = card.front()
    assert front.title == "賭け / wager"
    assert "un pari" not in front.title.lower()


def test_title_only_vocab_neuron_recognition_still_works():
    n = _neuron("# un pari — 賭け / wager", nid="n-title-only")
    card = Cloze.try_build(n, _sc(ScaffoldLevel.FULL))
    assert card is not None
    assert card.front().title == "un pari"


# -- en-dash-in-term (review finding 9) --------------------------------------


def test_en_dash_inside_term_is_not_a_separator():
    content = "# 1990–2000 — the era\n\nA period of change."
    card = Cloze.try_build(_neuron(content, type="concept"), _sc(ScaffoldLevel.FULL))
    assert card is not None
    assert card._term == "1990–2000"  # type: ignore[attr-defined]
    assert card._meaning == "the era"  # type: ignore[attr-defined]


def test_internal_hyphen_term_is_preserved():
    content = "# peut-être — maybe\n\n`peut-être` est un adverbe."
    card = Cloze.try_build(_neuron(content), _sc(ScaffoldLevel.NONE))
    assert card is not None
    assert card._term == "peut-être"  # type: ignore[attr-defined]
    front = card.front()
    assert "peut-être" not in f"{front.title}\n{front.body}".lower()
    assert BLANK in front.body


# -- unicode normalization for grading (review finding 7 / A5) --------------


def test_production_answer_nfd_input_matches_nfc_term():
    content = "# rôder (Verb)\n\nprowl, lurk, to prowl"
    card = Cloze.try_build(_neuron(content), _sc(ScaffoldLevel.NONE))
    assert card is not None
    nfd_answer = unicodedata.normalize("NFD", "rôder")
    result = card.grade(QuizResponse(self_grade=Grade.FIRE, answer=nfd_answer))
    assert result.correctness == 1.0


def test_production_dict_answer_extracts_value():
    card = Cloze.try_build(_neuron(RODER), _sc(ScaffoldLevel.NONE))
    assert card is not None
    result = card.grade(QuizResponse(self_grade=Grade.FIRE, answer={"blank1": "rôder"}))
    assert result.correctness == 1.0
