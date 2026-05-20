"""TutorSession — pure interpreter for an ExamPlan.

Walks an ExamPlan step by step. All pedagogical policy lives on the
plan; this class just routes events through transitions and calls
circuit.fire for the primary quiz result.

Follow-up results are transcribed into spike.notes but never fired,
guaranteed by the FollowUpResult type being distinct from QuizResult.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spikuit_core import Grade, Spike

from .plan import (
    ExamPlan,
    ExamStep,
    FollowUp,
    FollowUpResult,
    TransitionEvent,
    TransitionResult,
)

if TYPE_CHECKING:
    from spikuit_core import Circuit

    from ..quiz.models import QuizResponse


class TutorSession:
    """Interprets an ExamPlan."""

    def __init__(
        self,
        circuit: "Circuit",
        plan: ExamPlan,
        *,
        persist: bool = True,
    ) -> None:
        self.circuit = circuit
        self.plan = plan
        self.persist = persist
        self._idx = 0
        self._current: ExamStep | None = None
        self._history: list[ExamStep] = []

    # -- Lifecycle ----------------------------------------------------------

    async def teach(self) -> ExamStep | None:
        """Advance to the next step, returning None when exhausted."""
        # Skip already-completed steps (can happen if re-queued steps
        # are walked past before being re-presented)
        while self._idx < len(self.plan.steps):
            step = self.plan.steps[self._idx]
            if step.final_result is not None and step.requeue_count == 0:
                self._idx += 1
                continue
            self._current = step
            return step
        self._current = None
        return None

    async def record_response(
        self, response: "QuizResponse"
    ) -> TransitionResult:
        """Grade the current step's quiz and return the next transition."""
        if self._current is None:
            raise RuntimeError("No active step. Call teach() first.")

        step = self._current
        step.attempts += 1
        if response.confidence is not None:
            step.confidence = response.confidence

        result = step.quiz.grade(response)
        step.final_result = result

        if result.needs_tutor_grading:
            # LLM grading is caller's responsibility — they inject the
            # grader, call it, and then call record_llm_graded() instead.
            raise RuntimeError(
                "Quiz requires LLM grading; use record_llm_graded() after "
                "invoking your LLMGrader."
            )

        return self._transition(step, result.grade)

    async def record_llm_graded(
        self, result: "QuizResult"
    ) -> TransitionResult:
        """Accept a pre-graded QuizResult (from an LLMGrader) for the
        current step. Used when ``Quiz.grade()`` returned
        ``needs_tutor_grading=True``.
        """
        if self._current is None:
            raise RuntimeError("No active step.")
        step = self._current
        step.final_result = result
        return self._transition(step, result.grade)

    async def record_follow_up(
        self, fu_result: FollowUpResult
    ) -> TransitionResult:
        """Record a follow-up result and either emit the next follow-up
        or advance past the step.

        FollowUpResult is a distinct type from QuizResult — by design,
        these never reach circuit.fire.
        """
        if self._current is None:
            raise RuntimeError("No active step.")
        step = self._current
        step.follow_up_results.append(fu_result)

        seen_prompts = {r.follow_up.prompt for r in step.follow_up_results}
        remaining = [fu for fu in step.follow_ups if fu.prompt not in seen_prompts]
        if remaining:
            return TransitionResult(
                event=TransitionEvent.ENTER_FOLLOW_UP,
                follow_up=remaining[0],
            )
        return await self._complete_and_advance(step)

    async def close(self) -> None:
        """End the session. Any in-flight step with no grade is
        fired as MISS (matches legacy TutorSession behavior).
        """
        if self._current is not None and self._current.final_result is None:
            await self._fire_step(self._current, Grade.MISS, revealed=True)
            self._history.append(self._current)
            self._current = None

    # -- Properties ---------------------------------------------------------

    @property
    def current(self) -> ExamStep | None:
        return self._current

    @property
    def history(self) -> list[ExamStep]:
        return list(self._history)

    @property
    def stats(self) -> dict:
        correct = weak = missed = revealed = 0
        gap_sum = 0
        gap_n = 0
        for s in self._history:
            if s.revealed:
                revealed += 1
            grade = s.final_result.grade if s.final_result else None
            if grade is None:
                continue
            if grade >= Grade.FIRE:
                correct += 1
            elif grade == Grade.WEAK:
                weak += 1
            elif grade == Grade.MISS:
                missed += 1
            if s.confidence is not None:
                gap_sum += abs(int(s.confidence) - int(grade))
                gap_n += 1
        return {
            "taught": len(self._history),
            "correct": correct,
            "weak": weak,
            "missed": missed,
            "revealed": revealed,
            "remaining": max(0, len(self.plan.steps) - self._idx - 1),
            "calibration_gap": (gap_sum / gap_n) if gap_n else None,
        }

    # -- Internal -----------------------------------------------------------

    def _transition(self, step: ExamStep, grade: Grade | None) -> TransitionResult:
        if grade is None:
            raise RuntimeError("grade must be set on transition")

        if grade >= Grade.FIRE:
            if self.plan.elaborate_on_correct and step.follow_ups:
                return TransitionResult(
                    event=TransitionEvent.ENTER_FOLLOW_UP,
                    follow_up=step.follow_ups[0],
                )
            return TransitionResult(event=TransitionEvent.ADVANCE)

        if step.attempts < self.plan.max_attempts:
            return TransitionResult(event=TransitionEvent.RETRY_NEEDED)

        if (
            self.plan.require_mastery
            and step.requeue_count < self.plan.mastery_max_requeues
        ):
            step.requeue_count += 1
            step.attempts = 0
            step.final_result = None  # allow re-grading later
            # Append a fresh copy position to the end of the queue
            self.plan.steps.append(step)
            return TransitionResult(event=TransitionEvent.REQUEUE)

        step.revealed = True
        return TransitionResult(event=TransitionEvent.REVEAL_ANSWER)

    async def advance(self) -> TransitionResult:
        """Commit the current step (fire FSRS) and advance the cursor.

        Called by the caller after handling ADVANCE / REVEAL_ANSWER
        transitions. Kept separate from ``record_response`` so callers
        can interleave follow-ups / UI before committing.
        """
        if self._current is None:
            raise RuntimeError("No active step to advance.")
        return await self._complete_and_advance(self._current)

    async def _complete_and_advance(self, step: ExamStep) -> TransitionResult:
        """Fire FSRS for the primary quiz result (awaited, not
        fire-and-forget), then move cursor to next step.
        """
        if self.persist and step.final_result is not None and step.final_result.grade is not None:
            notes = self._compose_notes(step)
            await self.circuit.fire(
                Spike(
                    neuron_id=step.neuron_id,
                    grade=step.final_result.grade,
                    notes=notes,
                )
            )

        self._history.append(step)
        self._current = None
        self._idx += 1

        # Prepare next step if any
        next_step = await self.teach()
        return TransitionResult(event=TransitionEvent.ADVANCE, next_step=next_step)

    async def _fire_step(
        self, step: ExamStep, grade: Grade, *, revealed: bool
    ) -> None:
        """Manually fire a step (used by close() for abandoned sessions)."""
        step.revealed = revealed
        from ..quiz.models import QuizResult

        step.final_result = QuizResult(grade=grade, user_notes=None)
        if self.persist:
            notes = self._compose_notes(step)
            await self.circuit.fire(
                Spike(neuron_id=step.neuron_id, grade=grade, notes=notes)
            )

    def _compose_notes(self, step: ExamStep) -> str | None:
        """Aggregate user notes + weak follow-up observations into
        spike.notes so future reviews can reference them.
        """
        parts: list[str] = []
        if step.final_result and step.final_result.user_notes:
            parts.append(step.final_result.user_notes)
        for fu_result in step.follow_up_results:
            if fu_result.correctness < 0.7 and fu_result.note_for_next_review:
                parts.append(fu_result.note_for_next_review)
        return " | ".join(parts) if parts else None
