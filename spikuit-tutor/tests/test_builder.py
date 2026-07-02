"""Unit tests for spikuit_tutor.tutor.builder._choose_quiz.

Desirable-difficulties mapping (see builder.py docstring):
    MINIMAL / NONE       → FreeResponseQuiz (hardest)
    FULL / GUIDED        → Cloze, for vocab-shaped neurons
    FULL / GUIDED        → Flashcard, for bare concept neurons
"""

from __future__ import annotations

import pytest

from spikuit_core import Neuron

from spikuit_tutor.quiz import Cloze, Flashcard, FreeResponseQuiz
from spikuit_tutor.scaffold import Scaffold, ScaffoldLevel
from spikuit_tutor.tutor.builder import _choose_quiz


def _neuron(content: str, type: str = "concept") -> Neuron:
    return Neuron(id="n-test", content=content, type=type, domain="math")


def _sc(level: ScaffoldLevel) -> Scaffold:
    return Scaffold(level=level)


@pytest.mark.parametrize("level", [ScaffoldLevel.FULL, ScaffoldLevel.GUIDED])
def test_vocab_shaped_neuron_gets_cloze(level):
    n = _neuron("# rôder (Verb)\n\nprowl, lurk, to prowl", type="vocabulary")
    quiz = _choose_quiz(n, _sc(level))
    assert isinstance(quiz, Cloze)


@pytest.mark.parametrize("level", [ScaffoldLevel.FULL, ScaffoldLevel.GUIDED])
def test_bare_concept_neuron_gets_flashcard(level):
    n = _neuron("# Functor\n\nA map between categories.")
    quiz = _choose_quiz(n, _sc(level))
    assert isinstance(quiz, Flashcard)


@pytest.mark.parametrize("level", [ScaffoldLevel.FULL, ScaffoldLevel.GUIDED])
def test_pseudo_vocab_shaped_concept_title_still_gets_flashcard(level):
    # Review finding 5 / WP-A A3: a trailing acronym or an ASCII-hyphenated
    # enumeration must not be mistaken for a vocab TERM (POS) / TERM — MEANING
    # shape, or existing concept Flashcards regress to a bare Cloze front.
    olg = _neuron("# Overlapping generations model (OLG)\n\nHouseholds live two periods.")
    assert isinstance(_choose_quiz(olg, _sc(level)), Flashcard)

    enum = _neuron("# Aiyagari - Bewley - Huggett models\n\nHeterogeneous-agent models.")
    assert isinstance(_choose_quiz(enum, _sc(level)), Flashcard)


@pytest.mark.parametrize("level", [ScaffoldLevel.MINIMAL, ScaffoldLevel.NONE])
def test_mature_scaffold_always_gets_free_response(level):
    vocab = _neuron("# rôder (Verb)\n\nprowl, lurk, to prowl", type="vocabulary")
    concept = _neuron("# Functor\n\nA map between categories.")
    assert isinstance(_choose_quiz(vocab, _sc(level)), FreeResponseQuiz)
    assert isinstance(_choose_quiz(concept, _sc(level)), FreeResponseQuiz)
