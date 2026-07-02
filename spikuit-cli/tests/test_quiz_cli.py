"""Integration tests for `spkt tutor quiz --json` and `--no-tui`."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3

import pytest
from typer.testing import CliRunner

from spikuit_cli.helpers import _get_circuit
from spikuit_cli.main import app
from spikuit_core.appkit import QuizItem, QuizItemRole

runner = CliRunner()


@pytest.fixture
def empty_brain(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")

    r = runner.invoke(app, ["init", "-p", "none", "--json"])
    assert r.exit_code == 0, r.output
    return tmp_path


@pytest.fixture
def brain(empty_brain):
    for title in ("Functor", "Monad"):
        r = runner.invoke(
            app,
            ["neuron", "add", f"# {title}\n\nbody of {title}.", "-t", "concept", "-d", "math", "--json"],
        )
        assert r.exit_code == 0, r.output
    return empty_brain


def _last_json(output: str) -> dict:
    return json.loads(output.strip().splitlines()[-1])


def _neuron_id(add_output: str) -> str:
    return json.loads(add_output)["id"]


def _add_vocab_neuron(content: str) -> str:
    r = runner.invoke(app, ["neuron", "add", content, "-t", "vocabulary", "-d", "french", "--json"])
    assert r.exit_code == 0, r.output
    return _neuron_id(r.output)


def _seed_quiz_item(neuron_id: str, *, question: str = "Q?", answer: str = "A.") -> None:
    async def _add() -> None:
        circuit = _get_circuit(None)
        await circuit.connect()
        try:
            await circuit.add_quiz_item(
                QuizItem(
                    question=question,
                    answer=answer,
                    neuron_ids={neuron_id: QuizItemRole.PRIMARY},
                )
            )
        finally:
            await circuit.close()

    asyncio.run(_add())


def test_quiz_json_dumps_due_payloads(brain):
    r = runner.invoke(app, ["tutor", "quiz", "--json", "-n", "10"])
    assert r.exit_code == 0, r.output
    payload = _last_json(r.output)
    assert payload["status"] == "due"
    assert payload["count"] == 2
    item = payload["items"][0]
    assert item["quiz_type"] == "flashcard"
    assert item["mode"] == "tui"
    assert len(item["grade_choices"]) == 4
    assert {c["key"] for c in item["grade_choices"]} == {"1", "2", "3", "4"}


def test_quiz_no_tui_records_grades_and_notes(brain):
    stdin = (
        json.dumps({"self_grade": "FIRE", "notes": "clean"})
        + "\n"
        + json.dumps({"self_grade": "WEAK"})
        + "\n"
    )
    r = runner.invoke(app, ["tutor", "quiz", "--no-tui", "-n", "10"], input=stdin)
    assert r.exit_code == 0, r.output

    payload = _last_json(r.output)
    assert payload["status"] == "done"
    assert payload["reviewed"] == 2
    assert payload["grades"]["fire"] == 1
    assert payload["grades"]["weak"] == 1
    assert len(payload["notes"]) == 1
    assert payload["notes"][0]["note"] == "clean"

    db = brain / ".spikuit" / "circuit.db"
    with sqlite3.connect(db) as con:
        rows = con.execute("SELECT grade, notes FROM spike ORDER BY id").fetchall()
    assert len(rows) == 2
    grades_notes = {(g, n) for g, n in rows}
    assert (3, "clean") in grades_notes  # FIRE=3
    assert (2, None) in grades_notes  # WEAK=2


# -- Path A / B / fallback routing (review findings 5, WP-A A3) -------------


def test_quiz_routes_generated_for_stored_primary_item(empty_brain):
    nid = _add_vocab_neuron("# rôder (Verb)\n\nprowl, lurk, to prowl")
    _seed_quiz_item(nid, question="Translate: to prowl", answer="rôder")

    r = runner.invoke(app, ["tutor", "quiz", "--json", "-n", "10"])
    assert r.exit_code == 0, r.output
    payload = _last_json(r.output)
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["quiz_type"] == "generated"
    assert item["front"]["body"] == "Translate: to prowl"


def test_quiz_routes_cloze_for_vocab_shaped_neuron_without_stored_item(empty_brain):
    _add_vocab_neuron("# rôder (Verb)\n\nprowl, lurk, to prowl")

    r = runner.invoke(app, ["tutor", "quiz", "--json", "-n", "10"])
    assert r.exit_code == 0, r.output
    payload = _last_json(r.output)
    assert payload["count"] == 1
    assert payload["items"][0]["quiz_type"] == "cloze"


def test_quiz_routes_flashcard_for_bare_concept_neuron(brain):
    r = runner.invoke(app, ["tutor", "quiz", "--json", "-n", "10"])
    assert r.exit_code == 0, r.output
    payload = _last_json(r.output)
    assert payload["count"] == 2
    assert all(item["quiz_type"] == "flashcard" for item in payload["items"])


def test_quiz_no_tui_forwards_answer_without_error(empty_brain):
    # Regression test for review finding 8: the --no-tui loop used to build
    # NewQuizResponse(self_grade=..., notes=...) and silently drop `answer`,
    # so a typed answer never reached Quiz.grade() at all. This doesn't
    # assert on `correctness` (a new card scaffolds at FULL/recognition,
    # where Cloze doesn't mechanically check answers, and the --no-tui
    # summary doesn't surface per-item correctness) — it pins that an
    # `answer` field in the request line is accepted and the review still
    # completes, which the pre-fix code path did not exercise at all.
    _add_vocab_neuron("# rôder (Verb)\n\nprowl, lurk, to prowl")

    stdin = json.dumps({"self_grade": "FIRE", "answer": "rôder"}) + "\n"
    r = runner.invoke(app, ["tutor", "quiz", "--no-tui", "-n", "10"], input=stdin)
    assert r.exit_code == 0, r.output

    payload = _last_json(r.output)
    assert payload["status"] == "done"
    assert payload["reviewed"] == 1
