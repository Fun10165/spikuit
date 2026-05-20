"""LLMGrader — Protocol for quiz types that need LLM grading.

Any Quiz whose ``grade()`` returns ``needs_tutor_grading=True`` must be
finished by an LLMGrader implementation. The Protocol lives here so that:

- the cli package stays self-sufficient (Flashcards need no grader);
- agents, a one-shot LLM client, or any other backend can satisfy it
  without cli depending on agents.

Dependency flow: ``spikuit-core ← spikuit-cli ← spikuit-agents``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import QuizResult


@runtime_checkable
class LLMGrader(Protocol):
    """Grades free-response answers using an LLM.

    Implementations: ``spikuit_agents.tutor.AgentLLMGrader`` (agent-backed),
    or any user-supplied one-shot client that wraps an OpenAI-compatible
    endpoint. Both satisfy this Protocol structurally.
    """

    async def grade_free_response(
        self,
        *,
        question: str,
        rubric: str,
        canonical_answer: str,
        student_response: str,
    ) -> QuizResult:
        """Grade a free-response answer.

        Must return a ``QuizResult`` with ``grade`` set (never None) and
        ``needs_tutor_grading=False`` so the caller can fire FSRS.
        ``feedback`` and ``correctness`` should be populated for the UI.
        """
        ...
