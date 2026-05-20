"""Spikuit agents — tutor grading backends.

Concrete ``LLMGrader`` implementations. The tutor package defines the
``LLMGrader`` Protocol in ``spikuit_tutor.quiz.grader``; this module
satisfies it with LLM-backed strategies. Dependency flow stays
``core ← tutor ← agents``.
"""

from __future__ import annotations

from .agent_grader import AgentLLMGrader, GradeFn, build_grade_prompt

__all__ = ["AgentLLMGrader", "GradeFn", "build_grade_prompt"]
