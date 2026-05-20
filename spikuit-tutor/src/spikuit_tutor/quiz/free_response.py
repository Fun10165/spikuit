"""FreeResponseQuiz — open-ended prompt graded by an LLMGrader.

Unlike ``Flashcard``, this quiz cannot grade mechanically. ``grade()``
returns a ``QuizResult`` with ``needs_tutor_grading=True`` and all the
context an ``LLMGrader`` needs to complete the judgment. The caller is
responsible for invoking the grader and then handing the finished
result back to ``TutorSession.record_llm_graded``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from spikuit_core import ScaffoldLevel

from ._content import extract_body, extract_title
from .base import BaseQuiz
from .models import QuizResponse, QuizResult, RenderedContent

if TYPE_CHECKING:
    from spikuit_core import Neuron, Scaffold


def _default_question(title: str, level: ScaffoldLevel) -> str:
    t = title or "this concept"
    if level == ScaffoldLevel.MINIMAL:
        return f"Explain {t} in your own words, including a concrete example."
    if level == ScaffoldLevel.NONE:
        return f"Define {t} from scratch and give an example."
    return f"Describe {t} and why it matters."


def _default_rubric(title: str) -> str:
    t = title or "the concept"
    return (
        f"A good answer defines {t} accurately, uses correct terminology, "
        f"and includes a concrete example or application. Minor wording "
        f"differences are acceptable."
    )


class FreeResponseQuiz(BaseQuiz):
    """Open-ended prompt over one neuron.

    ``grade()`` always returns ``needs_tutor_grading=True`` — the caller
    must run an ``LLMGrader`` and feed the finished result back to the
    tutor session via ``record_llm_graded``.
    """

    quiz_type: ClassVar[str] = "free_response"

    def __init__(
        self,
        neuron: "Neuron",
        scaffold: "Scaffold",
        *,
        question: str | None = None,
        rubric: str | None = None,
    ) -> None:
        super().__init__()
        self.neuron = neuron
        self.scaffold = scaffold
        self._title = extract_title(neuron.content)
        self._body = extract_body(neuron.content)
        self._question = question or _default_question(self._title, scaffold.level)
        self._rubric = rubric or _default_rubric(self._title)

    def front(self) -> RenderedContent:
        return RenderedContent(
            title=self._title or self.neuron.id,
            body=self._question,
            hints=self._hint_lines(),
        )

    def back(self) -> RenderedContent:
        return RenderedContent(
            title=self._title or self.neuron.id,
            body=self._body,
            hints=[],
        )

    def grade(self, response: QuizResponse) -> QuizResult:
        student = ""
        if isinstance(response.answer, str):
            student = response.answer
        elif response.notes:
            student = response.notes
        return QuizResult(
            grade=None,
            needs_tutor_grading=True,
            grading_rubric=self._rubric,
            canonical_answer=self._body,
            student_response=student,
            user_notes=response.notes,
        )

    def _hint_lines(self) -> list[str]:
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
