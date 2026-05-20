"""Quiz v2 data models — response and result shapes.

Lives in spikuit-cli because v0.6.2 keeps the Quiz abstraction out of
spikuit-core. If a future version needs these in core, they can promote
without a rename.

See docs/design/quiz-v2.md for the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from spikuit_core import Grade

RenderMode = Literal["tui", "gui", "json"]


@dataclass
class RenderedContent:
    """A renderable side of a quiz card (front or back).

    Attributes:
        title: Short heading, typically the neuron title.
        body: Main content (markdown).
        hints: Optional hint lines shown below the body.
    """

    title: str = ""
    body: str = ""
    hints: list[str] = field(default_factory=list)


@dataclass
class GradeChoice:
    """One option in the numeric grade input."""

    key: str          # "1" .. "4"
    grade: Grade
    label: str        # User-facing short label (localized)


@dataclass
class RenderResponse:
    """Everything an agent/frontend needs to display a quiz.

    Returned by ``BaseQuiz.render()``. The ``mode`` tells the caller
    whether to start a Textual TUI, launch a GUI, or hand the payload
    off as JSON to a frontend.
    """

    quiz_type: str
    mode: RenderMode
    front: RenderedContent
    back: RenderedContent
    grade_choices: list[GradeChoice] = field(default_factory=list)
    accepts_notes: bool = True


@dataclass
class QuizResponse:
    """Learner's submission for a quiz.

    ``answer`` interpretation depends on ``quiz_type``:
        flashcard      → ignored; ``self_grade`` carries the rating
        multiple_choice→ the chosen option id
        free_text      → the learner's written answer
        cloze          → dict of blank_id → filled text
        reorder        → list of item ids in chosen order
    """

    answer: Any = None
    self_grade: Grade | None = None
    notes: str | None = None
    confidence: int | None = None
    time_spent_ms: int | None = None


@dataclass
class QuizResult:
    """Outcome of grading a QuizResponse.

    For mechanically-gradable quizzes, ``grade`` is set directly. For
    rubric-driven quizzes, ``needs_tutor_grading`` is True and a Tutor
    grader skill must fill in ``grade`` and ``feedback`` using the
    ``grading_rubric`` plus ``canonical_answer`` and ``student_response``.
    """

    grade: Grade | None = None
    needs_tutor_grading: bool = False
    grading_rubric: str | None = None
    canonical_answer: str | None = None
    student_response: str | None = None
    user_notes: str | None = None
    correctness: float | None = None
    feedback: str | None = None
