"""Strict JSONL contracts for retrieval judgments and recorded runs."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1


class BenchmarkDataError(ValueError):
    """Raised when benchmark input violates the versioned data contract."""


@dataclass(frozen=True)
class Judgment:
    query: str
    relevance: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RetrievalHit:
    node_id: str
    score: float | None


@dataclass(frozen=True)
class RetrievalRun:
    query: str
    hits: tuple[RetrievalHit, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_judgments(path: Path) -> tuple[Judgment, ...]:
    judgments: list[Judgment] = []
    seen_queries: set[str] = set()
    for line_number, record in _jsonl_records(path):
        _require_keys(record, {"query", "relevant"}, path, line_number)
        query = _non_empty_string(record["query"], "query", path, line_number)
        if query in seen_queries:
            raise _error(path, line_number, f"duplicate query {query!r}")
        seen_queries.add(query)

        raw_relevant = record["relevant"]
        if not isinstance(raw_relevant, list):
            raise _error(path, line_number, "relevant must be a JSON array")
        relevance: list[tuple[str, int]] = []
        seen_ids: set[str] = set()
        for index, raw_item in enumerate(raw_relevant):
            item = _object(raw_item, f"relevant[{index}]", path, line_number)
            _require_keys(item, {"id", "grade"}, path, line_number)
            node_id = _non_empty_string(
                item["id"], f"relevant[{index}].id", path, line_number
            )
            if node_id in seen_ids:
                raise _error(
                    path,
                    line_number,
                    f"duplicate relevance id {node_id!r} for query {query!r}",
                )
            seen_ids.add(node_id)
            grade = item["grade"]
            if (
                isinstance(grade, bool)
                or not isinstance(grade, int)
                or grade not in {0, 1, 2}
            ):
                raise _error(
                    path,
                    line_number,
                    f"relevant[{index}].grade must be one of 0, 1, or 2",
                )
            relevance.append((node_id, grade))
        if not any(grade > 0 for _node_id, grade in relevance):
            raise _error(
                path,
                line_number,
                f"query {query!r} must have at least one positive relevance label",
            )
        judgments.append(Judgment(query=query, relevance=tuple(relevance)))

    if not judgments:
        raise BenchmarkDataError(f"{path}: judgment file contains no records")
    return tuple(judgments)


def load_runs(path: Path) -> tuple[RetrievalRun, ...]:
    runs: list[RetrievalRun] = []
    seen_queries: set[str] = set()
    for line_number, record in _jsonl_records(path):
        _require_keys(record, {"query", "hits"}, path, line_number)
        query = _non_empty_string(record["query"], "query", path, line_number)
        if query in seen_queries:
            raise _error(path, line_number, f"duplicate query {query!r}")
        seen_queries.add(query)

        raw_hits = record["hits"]
        if not isinstance(raw_hits, list):
            raise _error(path, line_number, "hits must be a JSON array")
        hits: list[RetrievalHit] = []
        seen_ids: set[str] = set()
        for index, raw_hit in enumerate(raw_hits):
            hit = _object(raw_hit, f"hits[{index}]", path, line_number)
            unknown = set(hit) - {"id", "score"}
            missing = {"id"} - set(hit)
            if unknown or missing:
                _raise_key_error(path, line_number, missing, unknown)
            node_id = _non_empty_string(
                hit["id"], f"hits[{index}].id", path, line_number
            )
            if node_id in seen_ids:
                raise _error(
                    path,
                    line_number,
                    f"duplicate hit id {node_id!r} for query {query!r}",
                )
            seen_ids.add(node_id)
            raw_score = hit.get("score")
            if raw_score is None:
                score = None
            elif isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                raise _error(
                    path,
                    line_number,
                    f"hits[{index}].score must be a finite number or null",
                )
            else:
                score = float(raw_score)
                if not math.isfinite(score):
                    raise _error(
                        path,
                        line_number,
                        f"hits[{index}].score must be finite",
                    )
            hits.append(RetrievalHit(node_id=node_id, score=score))
        runs.append(RetrievalRun(query=query, hits=tuple(hits)))

    if not runs:
        raise BenchmarkDataError(f"{path}: run file contains no records")
    return tuple(runs)


def match_runs(
    judgments: tuple[Judgment, ...],
    runs: tuple[RetrievalRun, ...],
) -> dict[str, RetrievalRun]:
    expected = {judgment.query for judgment in judgments}
    by_query = {run.query: run for run in runs}
    actual = set(by_query)
    if expected != actual:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing queries: {missing}")
        if unexpected:
            details.append(f"unexpected queries: {unexpected}")
        raise BenchmarkDataError("run/query mismatch: " + "; ".join(details))
    return by_query


def _jsonl_records(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    try:
        source = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise BenchmarkDataError(f"cannot read {path}: {exc}") from exc
    with source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                raw_record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise _error(path, line_number, f"invalid JSON: {exc.msg}") from exc
            yield line_number, _object(raw_record, "record", path, line_number)


def _object(value: Any, name: str, path: Path, line_number: int) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _error(path, line_number, f"{name} must be a JSON object")
    return value


def _non_empty_string(value: Any, name: str, path: Path, line_number: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(path, line_number, f"{name} must be a non-empty string")
    return value


def _require_keys(
    record: dict[str, Any],
    expected: set[str],
    path: Path,
    line_number: int,
) -> None:
    missing = expected - set(record)
    unknown = set(record) - expected
    if missing or unknown:
        _raise_key_error(path, line_number, missing, unknown)


def _raise_key_error(
    path: Path,
    line_number: int,
    missing: set[str],
    unknown: set[str],
) -> None:
    details = []
    if missing:
        details.append(f"missing keys {sorted(missing)}")
    if unknown:
        details.append(f"unknown keys {sorted(unknown)}")
    raise _error(path, line_number, "; ".join(details))


def _error(path: Path, line_number: int, message: str) -> BenchmarkDataError:
    return BenchmarkDataError(f"{path}:{line_number}: {message}")
