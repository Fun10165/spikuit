"""AgentLLMGrader — satisfies ``spikuit_tutor.quiz.LLMGrader`` via an
injected async grade function.

The grade_fn is backend-agnostic: a Strands agent tool, a raw OpenAI-
compatible HTTP call, an Anthropic SDK call, or a local LM Studio
shell-out. All it has to do is take a prompt string and return a JSON
payload matching the schema below.

Expected grade_fn output (JSON):

    {"grade": 1-4, "correctness": 0.0-1.0, "feedback": "..."}

``grade`` maps to ``Grade`` (MISS=1, WEAK=2, FIRE=3, STRONG=4).
"""

from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from spikuit_tutor.quiz import QuizResult
from spikuit_core.appkit import Grade

GradeFn = Callable[[str], Awaitable[str]]


_PROMPT_TEMPLATE = """\
You are grading a learner's free-response answer against a rubric.

Question:
{question}

Rubric:
{rubric}

Canonical answer (reference, not a required verbatim match):
{canonical_answer}

Learner's response:
{student_response}

Grade the response on this 4-point scale:
  1 = miss: fundamentally wrong or empty
  2 = weak: partially correct, missing key ideas
  3 = fire: correct with minor gaps
  4 = strong: accurate, complete, uses correct terminology

Return ONLY a JSON object on a single line, no prose, no markdown fence:
{{"grade": <1-4>, "correctness": <0.0-1.0>, "feedback": "<one short sentence>"}}
"""


def build_grade_prompt(
    *,
    question: str,
    rubric: str,
    canonical_answer: str,
    student_response: str,
) -> str:
    return _PROMPT_TEMPLATE.format(
        question=question.strip(),
        rubric=rubric.strip(),
        canonical_answer=canonical_answer.strip(),
        student_response=student_response.strip(),
    )


def _parse_payload(raw: str) -> dict:
    """Extract the first JSON object from the LLM's response.

    Tolerates minor wrapping (markdown fences, leading prose) that
    otherwise trips json.loads.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"No JSON object in grader response: {raw!r}")
    return json.loads(match.group(0))


class AgentLLMGrader:
    """``LLMGrader`` backed by an arbitrary async ``grade_fn``.

    Use with a Strands agent, an OpenAI-compat client, or any function
    that takes a prompt string and returns a JSON payload. See
    ``build_grade_prompt`` for the exact format this grader hands off.
    """

    def __init__(self, grade_fn: GradeFn) -> None:
        self.grade_fn = grade_fn

    async def grade_free_response(
        self,
        *,
        question: str,
        rubric: str,
        canonical_answer: str,
        student_response: str,
    ) -> QuizResult:
        prompt = build_grade_prompt(
            question=question,
            rubric=rubric,
            canonical_answer=canonical_answer,
            student_response=student_response,
        )
        raw = await self.grade_fn(prompt)
        payload = _parse_payload(raw)

        grade_int = int(payload["grade"])
        if grade_int not in (1, 2, 3, 4):
            raise ValueError(f"grade out of range: {grade_int}")
        grade = Grade(grade_int)

        correctness = payload.get("correctness")
        if correctness is not None:
            correctness = float(correctness)

        return QuizResult(
            grade=grade,
            needs_tutor_grading=False,
            correctness=correctness,
            feedback=payload.get("feedback"),
            canonical_answer=canonical_answer,
            student_response=student_response,
        )
