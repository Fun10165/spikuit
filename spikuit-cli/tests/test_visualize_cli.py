"""Integration test for `spkt visualize --json`."""

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


def test_visualize_json_dumps_the_payload(brain):
    r = runner.invoke(app, ["visualize", "--json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output.strip())
    assert payload["meta"]["neuron_count"] == 2
    assert {n["label"] for n in payload["nodes"]} == {"Functor", "Monad"}


def test_visualize_json_does_not_require_tutor_overlay(brain):
    r = runner.invoke(app, ["visualize", "--json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output.strip())
    assert payload["meta"]["overlay"] is None
    assert all(n["tutor"] is None for n in payload["nodes"])
    assert not (brain / ".spikuit" / "circuit.tutor.db").exists()


def test_visualize_json_with_tutor_overlay(brain):
    r = runner.invoke(app, ["visualize", "--json", "--overlay", "tutor"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output.strip())
    assert payload["meta"]["overlay"] == "tutor"
