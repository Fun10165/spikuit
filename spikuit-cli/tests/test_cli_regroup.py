"""Regression tests for the daily-use CLI regroup.

`due` and `quiz` moved under the `tutor` group; the old spellings stay
as hidden deprecated aliases.
"""

from __future__ import annotations

import json
import shutil

import pytest
from typer.testing import CliRunner

from spikuit_cli.main import app

runner = CliRunner()


@pytest.fixture
def brain(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    monkeypatch.chdir(tmp_path)
    for var in ("NAME", "EMAIL"):
        monkeypatch.setenv(f"GIT_AUTHOR_{var}", "test")
        monkeypatch.setenv(f"GIT_COMMITTER_{var}", "test")
    r = runner.invoke(app, ["init", "-p", "none", "--json"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        app,
        ["neuron", "add", "# Functor\n\nbody.", "-t", "concept", "-d", "math", "--json"],
    )
    assert r.exit_code == 0, r.output
    return tmp_path


def test_tutor_due_lists_due_neurons(brain):
    r = runner.invoke(app, ["tutor", "due", "--json"])
    assert r.exit_code == 0, r.output
    items = json.loads(r.output.strip().splitlines()[-1])
    assert len(items) == 1


def test_neuron_due_deprecated_still_works(brain):
    r = runner.invoke(app, ["neuron", "due", "--json"])
    assert r.exit_code == 0, r.output
    assert "deprecated" in r.output.lower()
    assert "spkt tutor due" in r.output


def test_top_level_due_deprecated_points_at_tutor(brain):
    r = runner.invoke(app, ["due", "--json"])
    assert r.exit_code == 0, r.output
    assert "spkt tutor due" in r.output


def test_quiz_deprecated_still_works(brain):
    r = runner.invoke(app, ["quiz", "--json", "-n", "10"])
    assert r.exit_code == 0, r.output
    assert "spkt tutor quiz" in r.output
    payload = json.loads(r.output.strip().splitlines()[-1])
    assert payload["status"] == "due"


def test_due_and_quiz_hidden_from_top_level_help():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    # `tutor` group is visible; the bare `due` / `quiz` aliases are not.
    assert "tutor" in r.output
    for hidden in ("\n  due ", "\n  quiz "):
        assert hidden not in r.output
