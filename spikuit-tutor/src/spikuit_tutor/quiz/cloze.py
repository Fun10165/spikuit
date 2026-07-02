"""Cloze — scaffold-directional vocab recall Quiz v2 type.

:class:`Flashcard`'s front can leak the answer: a vocab neuron shows both the
term and its meaning, so there is nothing to recall. Cloze hides one side and
asks the learner to recall the other. **Which** side is hidden follows the
scaffold level (receptive-precedes-productive):

    recognition  (FULL / GUIDED — new or still-learning)
        show the TERM, recall the meaning
            front:  un pari
    production   (MINIMAL / NONE — mature)
        show the MEANING, recall the term  (harder; better transfer)
            front:  賭け / wager
                    ▁▁▁▁ = 賭け、ベット、wager。…   ← term blanked (shape 1)
            front:  prowl, lurk, to prowl            ← meaning-only body (shape 2)

    back (both directions): full title + content, everything revealed.

Applicable only to vocab-shaped titles — a dash separator (``TERM — MEANING``,
always space-padded so a digit range like ``1990–2000`` or an enumeration
like ``A - B - C`` doesn't misparse as a separator) or a trailing
part-of-speech tag (``TERM (POS)``, POS drawn from a small whitelist so an
arbitrary parenthetical like ``(OLG)`` or ``(1994)`` doesn't misfire);
otherwise :meth:`try_build` returns ``None`` and the caller falls back to
Flashcard. Term matching (for blanking and answer-checking) is
case-insensitive, unicode-normalized, and word-boundary aware, so a
capitalized restatement doesn't leak and a short term doesn't match inside an
unrelated longer word. Grading is mechanical: the FSRS grade is the learner's
self-grade. In the production direction a typed ``answer``, if provided, is
checked against the term for feedback. No LLM.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, ClassVar, Literal

from ..scaffold import ScaffoldLevel
from ._answers import extract_answer_value
from ._content import extract_body, extract_title
from .base import BaseQuiz
from .flashcard import FLASHCARD_GRADE_CHOICES
from .models import GradeChoice, QuizResponse, QuizResult, RenderedContent

if TYPE_CHECKING:
    from spikuit_core.appkit import NeuronView

    from ..scaffold import Scaffold

BLANK = "▁▁▁▁"
Direction = Literal["recognition", "production"]
_RECOGNITION_LEVELS = (ScaffoldLevel.FULL, ScaffoldLevel.GUIDED)

# Em dash / en dash / horizontal bar, always padded by whitespace on both
# sides. Padding is required so a digit range ("1990–2000") or an enumerated
# list of ASCII-hyphenated names ("Aiyagari - Bewley - Huggett models") is
# never mistaken for a TERM — MEANING separator.
_DASH_RE = re.compile(r"\s+[—–―]\s+")
# A trailing part-of-speech / note tag: "(Verb)", "（動詞）".
_TAG_RE = re.compile(r"\s*[（(]([^（）()]*)[)）]\s*$")
# characters stripped off an extracted term (markdown emphasis / quotes / spaces)
_STRIP = "`*_ 　\"'"

# Recognized part-of-speech tags (case-insensitive, trailing "." stripped).
# Deliberately narrow: an arbitrary trailing parenthetical ("(OLG)", "(1994)")
# must NOT satisfy the vocab gate, or non-vocab concept neurons regress from
# Flashcard to a bare, contextless Cloze front.
_POS_TAGS = frozenset({
    "n", "nm", "nf", "m", "f", "noun",
    "v", "vt", "vi", "verb",
    "adj", "adjective",
    "adv", "adverb",
    "prep", "adp", "preposition",
    "conj", "conjunction",
    "pron", "pronoun",
    "interj", "interjection",
    "det", "determiner", "article",
    "num", "numeral",
    "aux", "auxiliary",
    "part", "particle",
    "propn", "proper noun",
})


def _is_pos_tag(text: str) -> bool:
    return text.strip().strip(".").lower() in _POS_TAGS


def _first_paragraph(body: str) -> str:
    return body.split("\n\n", 1)[0] if body else ""


def _term_and_cue(title: str) -> tuple[str, str]:
    """``TERM — MEANING`` → (TERM, MEANING); ``TERM (POS)`` → (TERM, "")."""
    parts = _DASH_RE.split(title, maxsplit=1)
    if len(parts) >= 2:
        term, cue = parts[0], parts[1].strip()
    else:
        term, cue = title, ""
    term = _TAG_RE.sub("", term).strip().strip(_STRIP)
    return term, cue


def _term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive, word-boundary-aware matcher for ``term``.

    Matches the bare term or a backtick-wrapped code span (``` `term` ```);
    never matches inside a longer word, so blanking "or" doesn't touch
    "encore".
    """
    return re.compile(r"(?<!\w)`?" + re.escape(term) + r"`?(?!\w)", re.IGNORECASE)


def _blank_out(text: str, term: str) -> str | None:
    """Blank all occurrences of ``term`` in ``text``. ``None`` if absent."""
    if not term or not text:
        return None
    pat = _term_pattern(term)
    return pat.sub(BLANK, text) if pat.search(text) else None


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip().strip(_STRIP)).casefold()


class Cloze(BaseQuiz):
    """Directional vocab recall over one vocab-shaped neuron.

    Construct via :meth:`try_build`, which returns ``None`` when the neuron is
    not cloze-shaped. The direction (recognition vs production) is chosen from
    the scaffold level at construction time.
    """

    quiz_type: ClassVar[str] = "cloze"

    def __init__(
        self,
        neuron: NeuronView,
        scaffold: Scaffold,
        *,
        title: str,
        body: str,
        term: str,
        meaning: str,
        direction: Direction,
        prod_title: str,
        prod_body: str,
    ) -> None:
        super().__init__()
        self.neuron = neuron
        self.scaffold = scaffold
        self._title = title
        self._body = body
        self._term = term
        self._meaning = meaning
        self._direction: Direction = direction
        self._prod_title = prod_title
        self._prod_body = prod_body

    @classmethod
    def try_build(cls, neuron: NeuronView, scaffold: Scaffold) -> "Cloze | None":
        title = extract_title(neuron.content)
        if not title:
            return None
        # Only fire on vocab-shaped titles — a dash separator (TERM — MEANING)
        # or a whitelisted part-of-speech tag (TERM (POS)). Bare concept
        # titles (including ones with a trailing "(OLG)" or "(1994)", or an
        # ASCII-hyphenated enumeration) fall back to Flashcard.
        tag_match = _TAG_RE.search(title)
        has_valid_tag = tag_match is not None and _is_pos_tag(tag_match.group(1))
        if not (_DASH_RE.search(title) or has_valid_tag):
            return None
        term, cue = _term_and_cue(title)
        if not term:
            return None
        body = extract_body(neuron.content)
        first_para = _first_paragraph(body)
        if not cue and not first_para:
            return None  # nothing usable as the meaning side, either shape

        # Build the production front (meaning shown, term hidden). Prefer
        # blanking the term out of the body (shape 1, cue as heading); when
        # the body doesn't mention the term, fall back to the cue alone
        # (shape 2), or to the bare first paragraph when there is no cue at
        # all (tag-only title). The cue itself is blanked too if it happens
        # to embed the term (e.g. a collocation note like "(faire un pari)"),
        # never handed back verbatim.
        clozed_body = _blank_out(first_para, term) if first_para else None
        if clozed_body is not None:
            prod_body = clozed_body
            prod_title = (_blank_out(cue, term) or cue) if cue else ""
        elif cue:
            prod_title = _blank_out(cue, term) or cue
            prod_body = ""
        else:
            prod_title, prod_body = first_para, ""

        meaning = cue or first_para
        direction: Direction = (
            "recognition" if scaffold.level in _RECOGNITION_LEVELS else "production"
        )
        return cls(
            neuron, scaffold,
            title=title, body=body, term=term, meaning=meaning,
            direction=direction, prod_title=prod_title, prod_body=prod_body,
        )

    def front(self) -> RenderedContent:
        if self._direction == "recognition":
            # Show the term; recall the meaning. Meaning stays hidden.
            return RenderedContent(title=self._term, body="", hints=[])
        # production: show the meaning; recall the term. Term stays hidden.
        return RenderedContent(title=self._prod_title, body=self._prod_body, hints=[])

    def back(self) -> RenderedContent:
        title = self._title or self.neuron.id
        return RenderedContent(title=title, body=self._body, hints=[])

    def grade(self, response: QuizResponse) -> QuizResult:
        if response.self_grade is None:
            raise ValueError("Cloze requires self_grade in QuizResponse")
        # The recalled target depends on direction; only the production target
        # (a single term) is mechanically checkable.
        canonical = self._term if self._direction == "production" else self._meaning
        student: str | None = None
        correctness: float | None = None
        ans = extract_answer_value(response.answer)
        if ans is not None:
            student = str(ans).strip()
            if self._direction == "production":
                correctness = 1.0 if _normalize(student) == _normalize(self._term) else 0.0
        return QuizResult(
            grade=response.self_grade,
            needs_tutor_grading=False,
            canonical_answer=canonical,
            student_response=student,
            correctness=correctness,
            user_notes=response.notes,
        )

    def grade_choices_spec(self) -> list[GradeChoice]:
        return FLASHCARD_GRADE_CHOICES
