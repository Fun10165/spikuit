"""GeneratedQuiz — renders a stored/generated ``QuizItem``.

A :class:`~spikuit_core.appkit.QuizItem` carries a pre-composed ``question`` +
``answer`` (+ progressive ``hints`` and free-text ``grading_criteria``),
produced by an LLM generator (Path B) or authored manually and cached in the
``quiz_items`` table. GeneratedQuiz is the **type-agnostic** renderer for those
items — the stored question is shown on the front, the answer on the back. It
is how contextual cloze / short-answer / any generated question reaches the
review loop without a per-type renderer.

The FSRS grade is the learner's self-grade (as with Flashcard/Cloze), keeping
the review loop LLM-free; ``answer`` + ``grading_criteria`` ride along on the
result for reference and future LLM grading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ._answers import extract_answer_value
from .base import BaseQuiz
from .flashcard import FLASHCARD_GRADE_CHOICES
from .models import GradeChoice, QuizResponse, QuizResult, RenderedContent

if TYPE_CHECKING:
    from spikuit_core.appkit import QuizItem

    from ..scaffold import Scaffold


class GeneratedQuiz(BaseQuiz):
    """Render a stored ``QuizItem`` as a self-graded quiz."""

    quiz_type: ClassVar[str] = "generated"

    def __init__(self, item: QuizItem, scaffold: Scaffold) -> None:
        super().__init__()
        self.item = item
        self.scaffold = scaffold

    def front(self) -> RenderedContent:
        return RenderedContent(title="", body=self.item.question, hints=[])

    def back(self) -> RenderedContent:
        return RenderedContent(
            title="Answer",
            body=self.item.answer,
            hints=list(self.item.hints),
        )

    def grade(self, response: QuizResponse) -> QuizResult:
        if response.self_grade is None:
            raise ValueError("GeneratedQuiz requires self_grade in QuizResponse")
        answer = extract_answer_value(response.answer)
        return QuizResult(
            grade=response.self_grade,
            needs_tutor_grading=False,
            canonical_answer=self.item.answer,
            grading_rubric=self.item.grading_criteria or None,
            student_response=str(answer) if answer is not None else None,
            user_notes=response.notes,
        )

    def grade_choices_spec(self) -> list[GradeChoice]:
        return FLASHCARD_GRADE_CHOICES
