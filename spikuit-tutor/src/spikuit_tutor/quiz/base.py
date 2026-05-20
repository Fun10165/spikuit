"""BaseQuiz — abstract base for all Quiz v2 types.

Each concrete Quiz subclass owns its own presentation and grading logic.
Generation (path B) is handled outside the quiz hierarchy by Tutor
generator skills; see docs/design/quiz-v2.md.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import ClassVar

from .models import (
    QuizResponse,
    QuizResult,
    RenderedContent,
    RenderMode,
    RenderResponse,
)


class BaseQuiz(ABC):
    """Base class for every Quiz v2 type.

    Subclasses implement ``front``, ``back``, ``grade``, and optionally
    ``preferred_mode`` / ``grade_choices_spec``. They are constructed with
    enough state to render themselves; selection, scheduling, and
    persistence are the caller's concern.
    """

    quiz_type: ClassVar[str]

    def __init__(self) -> None:
        self._submitted: asyncio.Event = asyncio.Event()
        self._response: QuizResponse | None = None

    @abstractmethod
    def front(self) -> RenderedContent:
        """Return the initial (question) side."""

    @abstractmethod
    def back(self) -> RenderedContent:
        """Return the answer side — shown after flip or submit."""

    @abstractmethod
    def grade(self, response: QuizResponse) -> QuizResult:
        """Grade a response. Return QuizResult with needs_tutor_grading
        set to True if the quiz type cannot grade mechanically."""

    def preferred_mode(self) -> RenderMode:
        """Preferred render mode. Override for audio/image quizzes."""
        return "tui"

    def grade_choices_spec(self) -> list:
        """Grade choices shown to the learner. Default: empty (quiz type
        provides its own grade input widget)."""
        return []

    def render(self) -> RenderResponse:
        """Return the full render payload for an agent or TUI."""
        return RenderResponse(
            quiz_type=self.quiz_type,
            mode=self.preferred_mode(),
            front=self.front(),
            back=self.back(),
            grade_choices=self.grade_choices_spec(),
            accepts_notes=True,
        )

    async def submit(self, response: QuizResponse) -> None:
        """Record a response and release anyone waiting on submission."""
        self._response = response
        self._submitted.set()

    async def wait_for_submit(self) -> QuizResponse:
        """Block until a response is submitted via ``submit``."""
        await self._submitted.wait()
        assert self._response is not None
        return self._response
