"""Textual pilot tests for QuizApp."""

from __future__ import annotations

import pytest

from spikuit_core import Grade, Neuron

from spikuit_tutor.quiz import Flashcard
from spikuit_tutor.scaffold import Scaffold, ScaffoldLevel
from spikuit_tutor.quiz.tui import QuizApp


def _card(nid: str, title: str) -> tuple[str, Flashcard]:
    n = Neuron(id=nid, content=f"# {title}\n\nbody of {title}.", type="concept", domain="math")
    return nid, Flashcard(n, Scaffold(level=ScaffoldLevel.FULL))


@pytest.mark.asyncio
async def test_quiz_app_full_session_flip_and_grade():
    records: list[tuple[str, Grade, str | None]] = []

    def rec(nid: str, grade: Grade, notes: str | None) -> None:
        records.append((nid, grade, notes))

    queue = [_card("n-1", "Functor"), _card("n-2", "Monad")]
    app = QuizApp(queue, rec)

    async with app.run_test() as pilot:
        # card 1 — flip + grade 3
        await pilot.press("space")
        await pilot.press("3")
        # card 2 — flip + grade 1
        await pilot.press("space")
        await pilot.press("1")
        await pilot.pause()

    assert [r[0] for r in records] == ["n-1", "n-2"]
    assert records[0][1] == Grade.FIRE
    assert records[1][1] == Grade.MISS
    assert app.return_value is not None
    assert app.return_value.reviewed == 2
    assert app.return_value.grades["fire"] == 1
    assert app.return_value.grades["miss"] == 1
    assert app.return_value.stopped_early is False


@pytest.mark.asyncio
async def test_quiz_app_grade_ignored_before_flip():
    records: list[tuple[str, Grade, str | None]] = []
    queue = [_card("n-1", "Functor")]
    app = QuizApp(queue, lambda n, g, nt: records.append((n, g, nt)))

    async with app.run_test() as pilot:
        await pilot.press("3")  # not flipped — should be ignored
        await pilot.pause()
        assert records == []
        await pilot.press("space")
        await pilot.press("4")
        await pilot.pause()

    assert len(records) == 1
    assert records[0][1] == Grade.STRONG


@pytest.mark.asyncio
async def test_quiz_app_quit_early():
    records: list[tuple[str, Grade, str | None]] = []
    queue = [_card("n-1", "A"), _card("n-2", "B")]
    app = QuizApp(queue, lambda n, g, nt: records.append((n, g, nt)))

    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()

    assert records == []
    assert app.return_value.stopped_early is True
    assert app.return_value.reviewed == 0
