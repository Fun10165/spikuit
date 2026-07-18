from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.io import BenchmarkDataError
from benchmarks.run_retrieval import evaluate, load_config, write_report

ROOT = Path(__file__).resolve().parents[2]
SMOKE_CONFIG = ROOT / "benchmarks/configs/synthetic-smoke.toml"


def test_smoke_config_evaluates_to_stable_aggregate() -> None:
    report = evaluate(load_config(SMOKE_CONFIG))

    assert report["schema_version"] == 1
    assert report["cutoffs"] == [1, 3]
    assert report["query_count"] == 3
    assert report["aggregate"]["ndcg@1"] == pytest.approx(1 / 3)
    assert report["aggregate"]["mrr@1"] == pytest.approx(1 / 3)
    assert report["aggregate"]["recall@1"] == pytest.approx(1 / 6)
    assert report["aggregate"]["mrr@3"] == pytest.approx(2 / 3)
    assert report["aggregate"]["recall@3"] == pytest.approx(1.0)
    assert [item["query"] for item in report["queries"]] == [
        "category theory abstraction",
        "gradient descent optimization",
        "French noun plurals",
    ]
    assert all(len(digest) == 64 for digest in report["inputs"].values())


def test_report_write_is_byte_stable_and_atomic(tmp_path: Path) -> None:
    report = evaluate(load_config(SMOKE_CONFIG))
    output = tmp_path / "nested/report.json"

    write_report(report, output)
    first = output.read_bytes()
    write_report(report, output)

    assert output.read_bytes() == first
    assert not output.with_name("report.json.tmp").exists()
    assert json.loads(first)["query_count"] == 3


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("cutoffs = [1, 1]", "duplicate cutoff"),
        ("cutoffs = [0]", "positive integer"),
        ('judgments = "/absolute/judgments.jsonl"', "must be relative"),
        ("unknown = true", "unknown keys"),
        ("schema_version = 2", "schema_version must be 1"),
        ("schema_version = 1.0", "schema_version must be 1"),
        (
            'output = "../data/synthetic-smoke-run.jsonl"',
            "output must not overwrite",
        ),
    ],
)
def test_config_validation_rejects_ambiguous_or_non_reproducible_values(
    tmp_path: Path, replacement: str, message: str
) -> None:
    source = SMOKE_CONFIG.read_text(encoding="utf-8")
    if replacement.startswith("cutoffs"):
        source = source.replace("cutoffs = [1, 3]", replacement)
    elif replacement.startswith(("judgments", "output")):
        key = "judgments" if replacement.startswith("judgments") else "output"
        original = next(line for line in source.splitlines() if line.startswith(key))
        source = source.replace(original, replacement)
    elif replacement.startswith("schema_version"):
        source = source.replace("schema_version = 1", replacement)
    else:
        source += replacement + "\n"
    config = tmp_path / "benchmark.toml"
    config.write_text(source, encoding="utf-8")

    with pytest.raises(BenchmarkDataError, match=message):
        load_config(config)


def test_config_canonicalizes_cutoff_order(tmp_path: Path) -> None:
    source = SMOKE_CONFIG.read_text(encoding="utf-8").replace(
        "cutoffs = [1, 3]", "cutoffs = [3, 1]"
    )
    config_path = tmp_path / "benchmark.toml"
    config_path.write_text(source, encoding="utf-8")

    assert load_config(config_path).cutoffs == (1, 3)
