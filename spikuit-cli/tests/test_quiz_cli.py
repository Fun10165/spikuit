"""Integration tests for `spkt tutor quiz --json` and `--no-tui`."""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest
from typer.testing import CliRunner

from spikuit_cli.main import app

runner = CliRunner()


@pytest.fixture
def brain(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")

    r = runner.invoke(app, ["init", "-p", "none", "--json"])
    assert r.exit_code == 0, r.output

    for title in ("Functor", "Monad"):
        r = runner.invoke(
            app,
            ["neuron", "add", f"# {title}\n\nbody of {title}.", "-t", "concept", "-d", "math", "--json"],
        )
        assert r.exit_code == 0, r.output
    return tmp_path


def _last_json(output: str) -> dict:
    return json.loads(output.strip().splitlines()[-1])


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
