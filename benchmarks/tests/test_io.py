from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.io import (
    BenchmarkDataError,
    load_judgments,
    load_runs,
    match_runs,
)


def _write_jsonl(path: Path, records: list[object]) -> Path:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_loaders_parse_valid_contract_and_match_queries(tmp_path: Path) -> None:
    judgments = load_judgments(
        _write_jsonl(
            tmp_path / "judgments.jsonl",
            [
                {
                    "query": "alpha",
                    "relevant": [
                        {"id": "n1", "grade": 2},
                        {"id": "n2", "grade": 0},
                    ],
                }
            ],
        )
    )
    runs = load_runs(
        _write_jsonl(
            tmp_path / "run.jsonl",
            [
                {
                    "query": "alpha",
                    "hits": [
                        {"id": "n1", "score": 0.75},
                        {"id": "n3"},
                    ],
                }
            ],
        )
    )

    assert judgments[0].relevance == (("n1", 2), ("n2", 0))
    assert runs[0].hits[0].score == 0.75
    assert runs[0].hits[1].score is None
    assert match_runs(judgments, runs) == {"alpha": runs[0]}


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"query": "alpha", "relevant": []}, "positive relevance"),
        (
            {"query": "alpha", "relevant": [{"id": "n1", "grade": True}]},
            "grade must be one of",
        ),
        (
            {
                "query": "alpha",
                "relevant": [
                    {"id": "n1", "grade": 2},
                    {"id": "n1", "grade": 1},
                ],
            },
            "duplicate relevance id",
        ),
        (
            {
                "query": "alpha",
                "relevant": [{"id": "n1", "grade": 2}],
                "typo": 1,
            },
            "unknown keys",
        ),
    ],
)
def test_judgment_loader_rejects_invalid_records(
    tmp_path: Path, record: object, message: str
) -> None:
    path = _write_jsonl(tmp_path / "judgments.jsonl", [record])

    with pytest.raises(BenchmarkDataError, match=message):
        load_judgments(path)


def test_run_loader_rejects_duplicate_hits_and_non_finite_scores(
    tmp_path: Path,
) -> None:
    duplicate = _write_jsonl(
        tmp_path / "duplicate.jsonl",
        [
            {
                "query": "alpha",
                "hits": [{"id": "n1"}, {"id": "n1"}],
            }
        ],
    )
    non_finite = tmp_path / "non-finite.jsonl"
    non_finite.write_text(
        '{"query":"alpha","hits":[{"id":"n1","score":NaN}]}\n',
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkDataError, match="duplicate hit id"):
        load_runs(duplicate)
    with pytest.raises(BenchmarkDataError, match="score must be finite"):
        load_runs(non_finite)


def test_match_runs_reports_missing_and_unexpected_queries(tmp_path: Path) -> None:
    judgments = load_judgments(
        _write_jsonl(
            tmp_path / "judgments.jsonl",
            [
                {
                    "query": "expected",
                    "relevant": [{"id": "n1", "grade": 2}],
                }
            ],
        )
    )
    runs = load_runs(
        _write_jsonl(
            tmp_path / "run.jsonl",
            [{"query": "unexpected", "hits": []}],
        )
    )

    with pytest.raises(BenchmarkDataError, match="missing queries.*unexpected queries"):
        match_runs(judgments, runs)
