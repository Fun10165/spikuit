"""Tutor — scaffolded review sessions driven by ExamPlan.

Declarative session abstraction: an ExamPlan describes the sequence of
quizzes + transition rules + pedagogical policy. TutorSession is a pure
interpreter that walks the plan.

LLM-dependent quiz grading is handled through the injectable
``LLMGrader`` Protocol (see ``spikuit_tutor.quiz.grader``). The tutor
package is self-sufficient: Flashcards work without any grader,
FreeResponseQuiz falls back to self-grade or can use any LLMGrader
implementation.
"""

from __future__ import annotations

from .builder import plan_exam
from .plan import (
    ExamPlan,
    ExamStep,
    FollowUp,
    FollowUpGenerator,
    FollowUpResult,
    InterleaveMode,
    TransitionEvent,
    TransitionResult,
)
from .session import TutorSession

__all__ = [
    "ExamPlan",
    "ExamStep",
    "FollowUp",
    "FollowUpGenerator",
    "FollowUpResult",
    "InterleaveMode",
    "TransitionEvent",
    "TransitionResult",
    "TutorSession",
    "plan_exam",
]
