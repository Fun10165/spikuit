"""Flashcard — the simplest Quiz v2 type.

Shows neuron content at the current scaffold level on the front, reveals
the full content on the back, and asks the learner to self-grade 1–4.
No LLM required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from spikuit_core import Grade, ScaffoldLevel

from ._content import extract_body, extract_title
from .base import BaseQuiz
from .models import GradeChoice, QuizResponse, QuizResult, RenderedContent

if TYPE_CHECKING:
    from spikuit_core import Neuron, Scaffold


FLASHCARD_GRADE_CHOICES: list[GradeChoice] = [
    GradeChoice(key="1", grade=Grade.MISS, label="Forgot"),
    GradeChoice(key="2", grade=Grade.WEAK, label="Uncertain"),
    GradeChoice(key="3", grade=Grade.FIRE, label="Got it"),
    GradeChoice(key="4", grade=Grade.STRONG, label="Perfect"),
]


def _first_paragraph(body: str) -> str:
    if not body:
        return ""
    return body.split("\n\n", 1)[0]


class Flashcard(BaseQuiz):
    """Self-graded flashcard over one neuron.

    Front shows a scaffold-appropriate preview; back shows full content.
    Grading is mechanical — the response's ``self_grade`` is the result.
    """

    quiz_type: ClassVar[str] = "flashcard"

    def __init__(self, neuron: Neuron, scaffold: Scaffold) -> None:
        super().__init__()
        self.neuron = neuron
        self.scaffold = scaffold
        self._title = extract_title(neuron.content)
        self._body = extract_body(neuron.content)

    def front(self) -> RenderedContent:
        level = self.scaffold.level
        title = self._title or self.neuron.id

        if level == ScaffoldLevel.FULL:
            body = _first_paragraph(self._body)
            return RenderedContent(title=title, body=body, hints=self._hint_lines())
        if level == ScaffoldLevel.GUIDED:
            return RenderedContent(title=title, body="", hints=self._hint_lines())
        # MINIMAL / NONE: title only
        return RenderedContent(title=title, body="", hints=[])

    def back(self) -> RenderedContent:
        title = self._title or self.neuron.id
        return RenderedContent(
            title=title,
            body=self._body,
            hints=self._hint_lines(),
        )

    def grade(self, response: QuizResponse) -> QuizResult:
        if response.self_grade is None:
            raise ValueError("Flashcard requires self_grade in QuizResponse")
        return QuizResult(
            grade=response.self_grade,
            needs_tutor_grading=False,
            canonical_answer=self._body,
            student_response=None,
            user_notes=response.notes,
        )

    def grade_choices_spec(self) -> list[GradeChoice]:
        return FLASHCARD_GRADE_CHOICES

    def _hint_lines(self) -> list[str]:
        """Scaffold-derived hint lines shown below the card body."""
        lines: list[str] = []
        if self.scaffold.level == ScaffoldLevel.FULL and self.scaffold.context:
            lines.append(
                f"Related concepts you know: {', '.join(self.scaffold.context[:3])}"
            )
        if self.scaffold.gaps:
            lines.append(
                f"Prerequisites to review: {', '.join(self.scaffold.gaps[:3])}"
            )
        return lines
