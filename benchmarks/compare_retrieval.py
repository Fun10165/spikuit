"""Compare multiple recorded retrieval runs against a named baseline."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from benchmarks.io import (
    SCHEMA_VERSION,
    BenchmarkDataError,
    load_judgments,
    load_runs,
    sha256_file,
)
from benchmarks.run_retrieval import evaluate_records, write_report

_RUN_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class AblationConfig:
    config_path: Path
    judgments_path: Path
    output_path: Path
    cutoffs: tuple[int, ...]
    baseline: str
    runs: tuple[tuple[str, Path], ...]


def load_config(path: Path) -> AblationConfig:
    """Load a strict multi-run ablation config."""
    try:
        with path.open("rb") as source:
            raw = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BenchmarkDataError(f"cannot load config {path}: {exc}") from exc

    expected = {
        "schema_version",
        "judgments",
        "cutoffs",
        "baseline",
        "output",
        "runs",
    }
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

    judgments_path = _relative_path(raw["judgments"], "judgments", path)
    output_path = _relative_path(raw["output"], "output", path)
    cutoffs = _cutoffs(raw["cutoffs"], path)

    baseline = raw["baseline"]
    if not isinstance(baseline, str) or not _RUN_NAME.fullmatch(baseline):
        raise BenchmarkDataError(f"{path}: baseline must match {_RUN_NAME.pattern!r}")

    raw_runs = raw["runs"]
    if not isinstance(raw_runs, dict) or len(raw_runs) < 2:
        raise BenchmarkDataError(f"{path}: runs must define at least two entries")
    runs: list[tuple[str, Path]] = []
    seen_paths: set[Path] = set()
    for name, value in raw_runs.items():
        if not isinstance(name, str) or not _RUN_NAME.fullmatch(name):
            raise BenchmarkDataError(
                f"{path}: run name {name!r} must match {_RUN_NAME.pattern!r}"
            )
        run_path = _relative_path(value, f"runs.{name}", path)
        if run_path in seen_paths:
            raise BenchmarkDataError(f"{path}: run paths must be unique")
        seen_paths.add(run_path)
        runs.append((name, run_path))
    run_names = {name for name, _run_path in runs}
    if baseline not in run_names:
        raise BenchmarkDataError(
            f"{path}: baseline {baseline!r} is not defined in runs"
        )

    protected = {path.resolve(), judgments_path, *seen_paths}
    if output_path in protected:
        raise BenchmarkDataError(
            f"{path}: output must not overwrite the config or an input file"
        )

    ordered_runs = sorted(runs, key=lambda item: (item[0] != baseline, item[0]))
    return AblationConfig(
        config_path=path.resolve(),
        judgments_path=judgments_path,
        output_path=output_path,
        cutoffs=cutoffs,
        baseline=baseline,
        runs=tuple(ordered_runs),
    )


def compare(config: AblationConfig) -> dict[str, Any]:
    """Evaluate each run and compute paired deltas from the baseline."""
    judgments = load_judgments(config.judgments_path)
    reports = {
        name: evaluate_records(judgments, load_runs(run_path), config.cutoffs)
        for name, run_path in config.runs
    }

    baseline_report = reports[config.baseline]
    baseline_aggregate = baseline_report["aggregate"]
    baseline_queries = {
        item["query"]: item["metrics"] for item in baseline_report["queries"]
    }
    matrix = []
    paired_deltas: dict[str, list[dict[str, Any]]] = {}
    for name, _run_path in config.runs:
        report = reports[name]
        aggregate = report["aggregate"]
        matrix.append(
            {
                "run": name,
                "metrics": aggregate,
                "delta_vs_baseline": _metric_delta(aggregate, baseline_aggregate),
            }
        )
        if name == config.baseline:
            continue
        paired_deltas[name] = [
            {
                "query": item["query"],
                "metrics": _metric_delta(
                    item["metrics"], baseline_queries[item["query"]]
                ),
            }
            for item in report["queries"]
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "config_sha256": sha256_file(config.config_path),
            "judgments_sha256": sha256_file(config.judgments_path),
            "run_sha256": {
                name: sha256_file(run_path) for name, run_path in config.runs
            },
        },
        "cutoffs": list(config.cutoffs),
        "query_count": baseline_report["query_count"],
        "run_count": len(config.runs),
        "baseline": config.baseline,
        "matrix": matrix,
        "paired_deltas": paired_deltas,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare recorded retrieval runs against a baseline."
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        report = compare(config)
        write_report(report, config.output_path)
    except (BenchmarkDataError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(config.output_path)
    return 0


def _metric_delta(
    metrics: dict[str, float], baseline: dict[str, float]
) -> dict[str, float]:
    if set(metrics) != set(baseline):
        raise BenchmarkDataError("run metric keys do not match the baseline")
    return {key: metrics[key] - baseline[key] for key in metrics}


def _cutoffs(value: object, config_path: Path) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkDataError(f"{config_path}: cutoffs must be a non-empty array")
    cutoffs: list[int] = []
    for index, cutoff in enumerate(value):
        if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff <= 0:
            raise BenchmarkDataError(
                f"{config_path}: cutoffs[{index}] must be a positive integer"
            )
        if cutoff in cutoffs:
            raise BenchmarkDataError(f"{config_path}: duplicate cutoff {cutoff}")
        cutoffs.append(cutoff)
    return tuple(sorted(cutoffs))


def _relative_path(value: object, name: str, config_path: Path) -> Path:
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
