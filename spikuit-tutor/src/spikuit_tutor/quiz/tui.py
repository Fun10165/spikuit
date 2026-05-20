"""Textual TUI for Quiz v2.

Runs a review session over a queue of BaseQuiz instances. For v0.6.2
this is wired up only to Flashcard, but the screen is generic over
BaseQuiz so future quiz types can reuse it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static

from spikuit_core import Grade

from .base import BaseQuiz
from .models import QuizResponse, QuizResult


@dataclass
class ReviewSessionResult:
    """Summary returned by QuizApp after the session closes."""

    reviewed: int = 0
    grades: dict[str, int] = field(
        default_factory=lambda: {"miss": 0, "weak": 0, "fire": 0, "strong": 0}
    )
    notes: list[tuple[str, str]] = field(default_factory=list)  # (neuron_id, note)
    stopped_early: bool = False


class NotesModal(ModalScreen[str | None]):
    """A one-line free-text input for the learner's notes."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    NotesModal {
        align: center middle;
    }
    NotesModal > Vertical {
        width: 70;
        height: 7;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    NotesModal Label {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Add a note (Enter to save, Esc to cancel):")
            yield Input(placeholder="e.g. unclear about functorial laws", id="note-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class QuizCardView(Static):
    """A flippable card widget displaying front or back of a quiz."""

    DEFAULT_CSS = """
    QuizCardView {
        padding: 1 2;
        border: round $primary;
        background: $surface;
        min-height: 10;
        content-align: left top;
    }
    """


class GradeBar(Static):
    """Grade key hint bar, only visible on the back side."""

    DEFAULT_CSS = """
    GradeBar {
        padding: 0 2;
        color: $text-muted;
    }
    """


class QuizApp(App[ReviewSessionResult]):
    """Main review session app.

    Walks through a queue of (quiz, record_fn) pairs. On submit the
    caller's record callback is invoked with the neuron_id and grade,
    then the next quiz is shown.
    """

    CSS = """
    Screen {
        layout: vertical;
    }
    #progress-bar {
        padding: 0 2;
        color: $accent;
        text-style: bold;
    }
    #card-container {
        height: 1fr;
        padding: 1 2;
    }
    #footer-hint {
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("space", "flip", "Flip", priority=True),
        Binding("1", "grade('1')", "Forgot", show=False),
        Binding("2", "grade('2')", "Uncertain", show=False),
        Binding("3", "grade('3')", "Got it", show=False),
        Binding("4", "grade('4')", "Perfect", show=False),
        Binding("n", "open_notes", "Note"),
        Binding("q", "quit_session", "Quit"),
    ]

    flipped: reactive[bool] = reactive(False)

    def __init__(
        self,
        queue: list[tuple[str, BaseQuiz]],
        record: Callable[[str, Grade, str | None], None],
    ) -> None:
        super().__init__()
        self._queue = queue
        self._record = record
        self._idx = 0
        self._current_quiz: BaseQuiz | None = None
        self._current_neuron_id: str | None = None
        self._current_started_ms: float = 0.0
        self._pending_note: str | None = None
        self._result = ReviewSessionResult()

    # -- lifecycle --------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="progress-bar")
        with Container(id="card-container"):
            yield QuizCardView("", id="card")
        yield GradeBar("", id="grade-bar")
        yield Static("", id="footer-hint")
        yield Footer()

    def on_mount(self) -> None:
        if not self._queue:
            self.exit(self._result)
            return
        self._show_current()

    # -- rendering --------------------------------------------------------

    def _show_current(self) -> None:
        if self._idx >= len(self._queue):
            self.exit(self._result)
            return
        neuron_id, quiz = self._queue[self._idx]
        self._current_quiz = quiz
        self._current_neuron_id = neuron_id
        self._current_started_ms = time.monotonic() * 1000
        self._pending_note = None
        self.flipped = False
        self._refresh_card()
        self._refresh_progress()

    def _refresh_card(self) -> None:
        assert self._current_quiz is not None
        content = (
            self._current_quiz.back() if self.flipped else self._current_quiz.front()
        )
        card = self.query_one("#card", QuizCardView)
        body_lines: list[str] = []
        if content.title:
            body_lines.append(f"[bold]# {content.title}[/bold]")
            body_lines.append("")
        if content.body:
            body_lines.append(content.body)
            body_lines.append("")
        for hint in content.hints:
            body_lines.append(f"[dim]• {hint}[/dim]")
        if not self.flipped and self._current_quiz.__class__.__name__ == "Flashcard":
            body_lines.append("")
            body_lines.append("[dim italic](Recall, then press Space to flip)[/dim italic]")
        card.update("\n".join(body_lines))

        grade_bar = self.query_one("#grade-bar", GradeBar)
        if self.flipped:
            choices = self._current_quiz.grade_choices_spec()
            if choices:
                parts = [f"[{c.key}] {c.label}" for c in choices]
                grade_bar.update("How well did you know this?  " + "   ".join(parts))
            else:
                grade_bar.update("")
        else:
            grade_bar.update("")

        footer_hint = self.query_one("#footer-hint", Static)
        hint_parts = ["[Space] Flip"]
        if self.flipped:
            hint_parts.append("[1-4] Grade")
        hint_parts.extend(["[n] Note", "[q] Quit"])
        if self._pending_note:
            hint_parts.append(f"[green]note saved[/green]")
        footer_hint.update("  ".join(hint_parts))

    def _refresh_progress(self) -> None:
        bar = self.query_one("#progress-bar", Static)
        total = len(self._queue)
        bar.update(f"[{self._idx + 1}/{total}]  reviewed: {self._result.reviewed}")

    def watch_flipped(self, _flipped: bool) -> None:
        if self._current_quiz is not None:
            self._refresh_card()

    # -- actions ----------------------------------------------------------

    def action_flip(self) -> None:
        self.flipped = not self.flipped

    def action_grade(self, key: str) -> None:
        if not self.flipped or self._current_quiz is None:
            return
        choices = {c.key: c for c in self._current_quiz.grade_choices_spec()}
        choice = choices.get(key)
        if choice is None:
            return
        assert self._current_neuron_id is not None
        elapsed_ms = int(time.monotonic() * 1000 - self._current_started_ms)
        response = QuizResponse(
            self_grade=choice.grade,
            notes=self._pending_note,
            time_spent_ms=elapsed_ms,
        )
        result: QuizResult = self._current_quiz.grade(response)
        # Record
        self._record(
            self._current_neuron_id,
            result.grade or choice.grade,
            self._pending_note,
        )
        grade_name = (result.grade or choice.grade).name.lower()
        self._result.grades[grade_name] = self._result.grades.get(grade_name, 0) + 1
        self._result.reviewed += 1
        if self._pending_note:
            self._result.notes.append((self._current_neuron_id, self._pending_note))
        self._idx += 1
        self._show_current()

    def action_open_notes(self) -> None:
        def _apply(note: str | None) -> None:
            if note:
                self._pending_note = note
                self._refresh_card()
        self.push_screen(NotesModal(), _apply)

    def action_quit_session(self) -> None:
        self._result.stopped_early = True
        self.exit(self._result)
