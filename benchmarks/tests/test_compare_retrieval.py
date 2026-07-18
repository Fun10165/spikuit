from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.compare_retrieval import compare, load_config, main
from benchmarks.io import BenchmarkDataError


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    judgments = tmp_path / "judgments.jsonl"
    judgments.write_text(
        '{"query":"alpha","relevant":[{"id":"a","grade":2},{"id":"b","grade":1}]}\n'
        '{"query":"beta","relevant":[{"id":"c","grade":2}]}\n',
        encoding="utf-8",
    )
    full = tmp_path / "full.jsonl"
    full.write_text(
        '{"query":"alpha","hits":[{"id":"a","score":1.0},{"id":"b","score":0.8}]}\n'
        '{"query":"beta","hits":[{"id":"c","score":0.9}]}\n',
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.jsonl"
    candidate.write_text(
        '{"query":"alpha","hits":[{"id":"b","score":0.7},{"id":"a","score":0.6}]}\n'
        '{"query":"beta","hits":[{"id":"x","score":0.5}]}\n',
        encoding="utf-8",
    )
    return judgments, full, candidate


def _write_config(
    tmp_path: Path,
    *,
    baseline: str = "full",
    candidate_path: str = "candidate.jsonl",
    output: str = "report.json",
) -> Path:
    config = tmp_path / "ablation.toml"
    config.write_text(
        "schema_version = 1\n"
        'judgments = "judgments.jsonl"\n'
        "cutoffs = [1, 2]\n"
        f'baseline = "{baseline}"\n'
        f'output = "{output}"\n\n'
        "[runs]\n"
        f'candidate = "{candidate_path}"\n'
        'full = "full.jsonl"\n',
        encoding="utf-8",
    )
    return config


def test_load_config_orders_baseline_first_and_resolves_paths(tmp_path: Path):
    _write_inputs(tmp_path)
    config_path = _write_config(tmp_path)

    config = load_config(config_path)

    assert config.baseline == "full"
    assert config.cutoffs == (1, 2)
    assert [name for name, _path in config.runs] == ["full", "candidate"]
    assert all(path.is_absolute() for _name, path in config.runs)


def test_compare_reports_aggregate_and_query_paired_deltas(tmp_path: Path):
    _write_inputs(tmp_path)
    config = load_config(_write_config(tmp_path))

    report = compare(config)

    assert report["baseline"] == "full"
    assert report["run_count"] == 2
    assert report["query_count"] == 2
    baseline, candidate = report["matrix"]
    assert baseline["run"] == "full"
    assert set(baseline["delta_vs_baseline"].values()) == {0.0}
    assert candidate["run"] == "candidate"
    assert candidate["delta_vs_baseline"]["recall@1"] == pytest.approx(-0.5)
    paired = report["paired_deltas"]["candidate"]
    assert [item["query"] for item in paired] == ["alpha", "beta"]
    mean_delta = sum(item["metrics"]["recall@1"] for item in paired) / len(paired)
    assert mean_delta == pytest.approx(candidate["delta_vs_baseline"]["recall@1"])
    assert set(report["inputs"]["run_sha256"]) == {"full", "candidate"}


@pytest.mark.parametrize(
    ("baseline", "candidate_path", "output", "message"),
    [
        ("missing", "candidate.jsonl", "report.json", "not defined in runs"),
        ("full", "full.jsonl", "report.json", "run paths must be unique"),
        ("full", "candidate.jsonl", "full.jsonl", "must not overwrite"),
    ],
)
def test_load_config_rejects_invalid_run_relationships(
    tmp_path: Path,
    baseline: str,
    candidate_path: str,
    output: str,
    message: str,
):
    _write_inputs(tmp_path)
    config_path = _write_config(
        tmp_path,
        baseline=baseline,
        candidate_path=candidate_path,
        output=output,
    )

    with pytest.raises(BenchmarkDataError, match=message):
        load_config(config_path)


def test_main_writes_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    _write_inputs(tmp_path)
    config_path = _write_config(tmp_path)

    assert main(["--config", str(config_path)]) == 0

    report_path = tmp_path / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["baseline"] == "full"
    assert report["matrix"][1]["run"] == "candidate"
    assert capsys.readouterr().out.strip() == str(report_path)
