"""Evaluate a recorded retrieval run from a version-controlled TOML config."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from benchmarks.io import (
    SCHEMA_VERSION,
    BenchmarkDataError,
    Judgment,
    RetrievalRun,
    load_judgments,
    load_runs,
    match_runs,
    sha256_file,
)
from benchmarks.metrics import aggregate_metrics, evaluate_query


@dataclass(frozen=True)
class RetrievalBenchmarkConfig:
    config_path: Path
    judgments_path: Path
    run_path: Path
    output_path: Path
    cutoffs: tuple[int, ...]


def load_config(path: Path) -> RetrievalBenchmarkConfig:
    """Load and strictly validate a retrieval benchmark config."""
    try:
        with path.open("rb") as source:
            raw = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BenchmarkDataError(f"cannot load config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BenchmarkDataError(f"{path}: config root must be a TOML table")

    expected = {"schema_version", "judgments", "run", "cutoffs", "output"}
    missing = expected - set(raw)
    unknown = set(raw) - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing keys {sorted(missing)}")
        if unknown:
            details.append(f"unknown keys {sorted(unknown)}")
        raise BenchmarkDataError(f"{path}: " + "; ".join(details))

    version = raw["schema_version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != SCHEMA_VERSION
    ):
        raise BenchmarkDataError(
            f"{path}: schema_version must be {SCHEMA_VERSION}, got {version!r}"
        )
    judgments_path = _config_path(raw["judgments"], "judgments", path)
    run_path = _config_path(raw["run"], "run", path)
    output_path = _config_path(raw["output"], "output", path)
    protected_paths = {path.resolve(), judgments_path, run_path}
    if output_path in protected_paths:
        raise BenchmarkDataError(
            f"{path}: output must not overwrite the config or an input file"
        )

    raw_cutoffs = raw["cutoffs"]
    if not isinstance(raw_cutoffs, list) or not raw_cutoffs:
        raise BenchmarkDataError(f"{path}: cutoffs must be a non-empty array")
    cutoffs: list[int] = []
    for index, cutoff in enumerate(raw_cutoffs):
        if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff <= 0:
            raise BenchmarkDataError(
                f"{path}: cutoffs[{index}] must be a positive integer"
            )
        if cutoff in cutoffs:
            raise BenchmarkDataError(f"{path}: duplicate cutoff {cutoff}")
        cutoffs.append(cutoff)

    return RetrievalBenchmarkConfig(
        config_path=path.resolve(),
        judgments_path=judgments_path,
        run_path=run_path,
        output_path=output_path,
        cutoffs=tuple(sorted(cutoffs)),
    )


def evaluate(config: RetrievalBenchmarkConfig) -> dict[str, Any]:
    """Evaluate all configured queries and return a stable report object."""
    evaluation = evaluate_records(
        load_judgments(config.judgments_path),
        load_runs(config.run_path),
        config.cutoffs,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "config_sha256": sha256_file(config.config_path),
            "judgments_sha256": sha256_file(config.judgments_path),
            "run_sha256": sha256_file(config.run_path),
        },
        "cutoffs": list(config.cutoffs),
        **evaluation,
    }


def evaluate_records(
    judgments: Sequence[Judgment],
    runs: Sequence[RetrievalRun],
    cutoffs: Sequence[int],
) -> dict[str, Any]:
    """Evaluate loaded records without repeating input parsing."""
    runs_by_query = match_runs(judgments, runs)
    query_reports: list[dict[str, Any]] = []
    query_metrics: list[dict[str, float]] = []
    for judgment in judgments:
        run = runs_by_query[judgment.query]
        metrics = evaluate_query(
            tuple(hit.node_id for hit in run.hits),
            dict(judgment.relevance),
            cutoffs,
        )
        query_metrics.append(metrics)
        query_reports.append(
            {
                "query": judgment.query,
                "hit_count": len(run.hits),
                "metrics": metrics,
            }
        )

    return {
        "query_count": len(judgments),
        "aggregate": aggregate_metrics(query_metrics),
        "queries": query_reports,
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    """Atomically write canonical, byte-stable JSON output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(output_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a recorded Spikuit retrieval benchmark run."
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        report = evaluate(config)
        write_report(report, config.output_path)
    except (BenchmarkDataError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(config.output_path)
    return 0


def _config_path(value: object, name: str, config_path: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkDataError(f"{config_path}: {name} must be a path string")
    candidate = Path(value)
    if candidate.is_absolute():
        raise BenchmarkDataError(
            f"{config_path}: {name} must be relative to the config file"
        )
    return (config_path.parent / candidate).resolve()


if __name__ == "__main__":
    sys.exit(main())
