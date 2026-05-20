"""ExamPlan — declarative data for a tutor session.

An ExamPlan is a sequence of ExamSteps plus policy knobs. TutorSession
(session.py) interprets it. Pedagogical decisions are all here, not in
the interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from spikuit_core import Neuron, Scaffold

    from ..quiz import BaseQuiz, QuizResult


class InterleaveMode(str, Enum):
    NONE = "none"
    DOMAIN = "domain"
    COMMUNITY = "community"


class TransitionEvent(str, Enum):
    ADVANCE = "advance"
    RETRY_NEEDED = "retry_needed"
    REVEAL_ANSWER = "reveal_answer"
    ENTER_FOLLOW_UP = "enter_follow_up"
    REQUEUE = "requeue"


@dataclass
class FollowUp:
    """A deepening question triggered after a correct answer.

    Follow-ups are LLM-graded for feedback but NEVER fire FSRS. Results
    are transcribed into spike.notes on the parent step so the next
    review can reference them.
    """

    prompt: str
    rubric: str
    related_neuron_ids: list[str] = field(default_factory=list)


@runtime_checkable
class FollowUpGenerator(Protocol):
    """Builds a deepening prompt for a neuron, given an anchor neighbor.

    Builders/tests can plug in an LLM-driven implementation without the
    tutor package depending on any LLM stack. The default builder falls
    back to a static "How does X relate to Y?" template if no generator
    is supplied.
    """

    async def generate_follow_up(
        self, *, neuron: "Neuron", anchor: "Neuron", scaffold: "Scaffold"
    ) -> "FollowUp": ...


@dataclass
class FollowUpResult:
    """Outcome of a follow-up.

    Deliberately NOT a QuizResult: the type-level distinction guarantees
    follow-up grades never reach ``circuit.fire``.
    """

    follow_up: FollowUp
    student_response: str
    correctness: float
    feedback: str
    note_for_next_review: str


@dataclass
class ExamStep:
    """One step in an ExamPlan — a neuron, its quiz, its scaffold, and
    runtime state mutated by the interpreter.
    """

    neuron_id: str
    quiz: "BaseQuiz"
    scaffold: "Scaffold"
    follow_ups: list[FollowUp] = field(default_factory=list)

    # Runtime state
    attempts: int = 0
    requeue_count: int = 0
    confidence: int | None = None
    final_result: "QuizResult | None" = None
    follow_up_results: list[FollowUpResult] = field(default_factory=list)
    revealed: bool = False


@dataclass
class ExamPlan:
    """Declarative tutor session plan."""

    steps: list[ExamStep]

    # Policy knobs (from coaching-theory.md survey)
    interleave_by: InterleaveMode = InterleaveMode.NONE
    require_mastery: bool = False
    mastery_max_requeues: int = 2
    elaborate_on_correct: bool = False
    collect_confidence: bool = True
    max_attempts: int = 3
    interleave_pull_ratio: float = 0.20
    near_due_days: int = 2


@dataclass
class TransitionResult:
    """Result of feeding a response into the interpreter.

    The ``next_step`` is filled in by the interpreter on ADVANCE /
    REQUEUE events; transitions themselves don't walk the queue.
    """

    event: TransitionEvent
    next_step: ExamStep | None = None
    follow_up: FollowUp | None = None
