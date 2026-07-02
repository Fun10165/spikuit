"""Shared helper for unwrapping a ``QuizResponse.answer`` value.

``answer`` is ``Any`` on the wire (see ``models.QuizResponse``): a bare
string for most quiz types, or a ``dict`` of blank-id → filled-text for
multi-blank cloze responses. Every quiz type that grades mechanically needs
the same unwrap, so it lives here instead of being duplicated per type.
"""

from __future__ import annotations

from typing import Any


def extract_answer_value(answer: Any) -> Any:
    """Return the value a learner typed, unwrapping a single-blank dict.

    A dict answer (``{"blank1": "rôder"}``) yields its first value; any
    other shape (including ``None``) passes through unchanged.
    """
    if isinstance(answer, dict):
        return next(iter(answer.values()), None) if answer else None
    return answer
