"""Deterministic metrics for evaluating ranked retrieval results."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

__all__ = [
    "aggregate_metrics",
    "dcg_at_k",
    "evaluate_query",
    "mrr_at_k",
    "ndcg_at_k",
    "recall_at_k",
]

_METRIC_KEY = re.compile(r"^(ndcg|mrr|recall)@([1-9][0-9]*)$")
_METRIC_ORDER = {"ndcg": 0, "mrr": 1, "recall": 2}


def dcg_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    """Return discounted cumulative gain through rank ``k``.

    Graded relevance uses exponential gain, ``2**grade - 1``, and a
    base-two logarithmic discount. Unjudged retrieved identifiers have zero
    gain.
    """
    _validate_query_inputs(retrieved_ids, relevance, k)
    return _dcg_at_k(retrieved_ids, relevance, k)


def ndcg_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    """Return DCG through rank ``k`` normalized by the ideal ranking."""
    _validate_query_inputs(retrieved_ids, relevance, k)
    return _ndcg_at_k(retrieved_ids, relevance, k)


def mrr_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    """Return reciprocal rank of the first positively relevant hit by ``k``."""
    _validate_query_inputs(retrieved_ids, relevance, k)
    return _mrr_at_k(retrieved_ids, relevance, k)


def recall_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    """Return the fraction of positively relevant identifiers found by ``k``."""
    _validate_query_inputs(retrieved_ids, relevance, k)
    return _recall_at_k(retrieved_ids, relevance, k)


def evaluate_query(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    cutoffs: Sequence[int],
) -> dict[str, float]:
    """Evaluate one ranked result list at each requested cutoff.

    Cutoffs must be non-empty, positive, unique integers. Results use a
    canonical cutoff order and, for every cutoff, the key order nDCG, MRR,
    then recall.
    """
    validated_cutoffs = _validate_cutoffs(cutoffs)
    _validate_query_data(retrieved_ids, relevance)

    metrics: dict[str, float] = {}
    for k in validated_cutoffs:
        metrics[f"ndcg@{k}"] = _ndcg_at_k(retrieved_ids, relevance, k)
        metrics[f"mrr@{k}"] = _mrr_at_k(retrieved_ids, relevance, k)
        metrics[f"recall@{k}"] = _recall_at_k(retrieved_ids, relevance, k)
    return metrics


def aggregate_metrics(
    query_metrics: Sequence[Mapping[str, float]],
) -> dict[str, float]:
    """Return the arithmetic mean of each metric across queries.

    Every query mapping must contain the same complete set of nDCG, MRR, and
    recall keys for one or more positive cutoffs.
    """
    if isinstance(query_metrics, (str, bytes)) or not isinstance(
        query_metrics, Sequence
    ):
        raise ValueError("query_metrics must be a sequence of metric mappings")
    if not query_metrics:
        raise ValueError("query_metrics must not be empty")

    first = query_metrics[0]
    expected_keys = _validate_metric_mapping(first, index=0)
    values_by_key: dict[str, list[float]] = {key: [] for key in expected_keys}

    for index, metrics in enumerate(query_metrics):
        keys = _validate_metric_mapping(metrics, index=index)
        if keys != expected_keys:
            missing = sorted(expected_keys - keys)
            unexpected = sorted(keys - expected_keys)
            details = []
            if missing:
                details.append(f"missing keys {missing}")
            if unexpected:
                details.append(f"unexpected keys {unexpected}")
            raise ValueError(
                f"query_metrics[{index}] has inconsistent metric keys: "
                + "; ".join(details)
            )
        for key, value in metrics.items():
            values_by_key[key].append(float(value))

    query_count = len(query_metrics)
    return {
        key: math.fsum(values_by_key[key]) / query_count
        for key in sorted(expected_keys, key=_metric_sort_key)
    }


def _validate_query_inputs(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> None:
    _validate_cutoff(k)
    _validate_query_data(retrieved_ids, relevance)


def _validate_query_data(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int]
) -> None:
    if isinstance(retrieved_ids, (str, bytes)) or not isinstance(
        retrieved_ids, Sequence
    ):
        raise ValueError("retrieved_ids must be a sequence of identifiers")

    seen: set[str] = set()
    for index, node_id in enumerate(retrieved_ids):
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"retrieved_ids[{index}] must be a non-empty string")
        if node_id in seen:
            raise ValueError(f"duplicate retrieved id {node_id!r}")
        seen.add(node_id)

    if not isinstance(relevance, Mapping):
        raise ValueError("relevance must be a mapping of identifiers to grades")
    has_positive = False
    for node_id, grade in relevance.items():
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("relevance identifiers must be non-empty strings")
        if (
            isinstance(grade, bool)
            or not isinstance(grade, int)
            or grade not in {0, 1, 2}
        ):
            raise ValueError(
                f"relevance grade for {node_id!r} must be one of 0, 1, or 2"
            )
        has_positive = has_positive or grade > 0
    if not has_positive:
        raise ValueError("relevance must contain at least one positive grade")


def _validate_cutoff(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("cutoff must be a positive integer")


def _validate_cutoffs(cutoffs: Sequence[int]) -> tuple[int, ...]:
    if isinstance(cutoffs, (str, bytes)) or not isinstance(cutoffs, Sequence):
        raise ValueError("cutoffs must be a sequence of positive integers")
    if not cutoffs:
        raise ValueError("cutoffs must not be empty")
    seen: set[int] = set()
    for cutoff in cutoffs:
        _validate_cutoff(cutoff)
        if cutoff in seen:
            raise ValueError(f"duplicate cutoff {cutoff}")
        seen.add(cutoff)
    return tuple(sorted(seen))


def _validate_metric_mapping(metrics: Mapping[str, float], index: int) -> set[str]:
    if not isinstance(metrics, Mapping):
        raise ValueError(f"query_metrics[{index}] must be a metric mapping")
    keys = set(metrics)
    cutoffs: set[int] = set()
    for key in keys:
        if not isinstance(key, str):
            raise ValueError(
                f"query_metrics[{index}] has an invalid metric key {key!r}"
            )
        match = _METRIC_KEY.fullmatch(key)
        if match is None:
            raise ValueError(
                f"query_metrics[{index}] has an invalid metric key {key!r}"
            )
        cutoffs.add(int(match.group(2)))
    if not cutoffs:
        raise ValueError(f"query_metrics[{index}] must not be empty")

    complete_keys = {
        f"{metric}@{cutoff}"
        for cutoff in cutoffs
        for metric in ("ndcg", "mrr", "recall")
    }
    if keys != complete_keys:
        missing = sorted(complete_keys - keys)
        raise ValueError(
            f"query_metrics[{index}] has an incomplete metric set; missing keys {missing}"
        )

    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"query_metrics[{index}][{key!r}] must be a finite number")
        if not math.isfinite(value):
            raise ValueError(f"query_metrics[{index}][{key!r}] must be a finite number")
    return keys


def _metric_sort_key(key: str) -> tuple[int, int]:
    match = _METRIC_KEY.fullmatch(key)
    assert match is not None
    return int(match.group(2)), _METRIC_ORDER[match.group(1)]


def _dcg_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    terms = []
    for rank, node_id in enumerate(retrieved_ids, start=1):
        if rank > k:
            break
        gain = (2 ** relevance.get(node_id, 0)) - 1
        terms.append(gain / math.log2(rank + 1))
    return math.fsum(terms)


def _ndcg_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    actual = _dcg_at_k(retrieved_ids, relevance, k)
    ideal_grades = sorted(
        (grade for grade in relevance.values() if grade > 0), reverse=True
    )
    ideal = math.fsum(
        ((2**grade) - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(ideal_grades[:k], start=1)
    )
    return actual / ideal


def _mrr_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    for rank, node_id in enumerate(retrieved_ids, start=1):
        if rank > k:
            break
        if relevance.get(node_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def _recall_at_k(
    retrieved_ids: Sequence[str], relevance: Mapping[str, int], k: int
) -> float:
    relevant_count = sum(grade > 0 for grade in relevance.values())
    retrieved_relevant = 0
    for rank, node_id in enumerate(retrieved_ids, start=1):
        if rank > k:
            break
        retrieved_relevant += relevance.get(node_id, 0) > 0
    return retrieved_relevant / relevant_count
