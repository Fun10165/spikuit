"""Focused tests for deterministic retrieval metrics."""

import math

import pytest

from benchmarks.metrics import (
    aggregate_metrics,
    dcg_at_k,
    evaluate_query,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)


RELEVANCE = {"high": 2, "low": 1, "other": 1, "none": 0}
METRICS = (dcg_at_k, ndcg_at_k, mrr_at_k, recall_at_k)


def test_dcg_uses_exponential_gain_and_truncates_at_cutoff():
    score = dcg_at_k(["low", "high", "other"], RELEVANCE, 2)

    assert score == pytest.approx(1.0 + 3.0 / math.log2(3))


def test_ndcg_normalizes_against_ideal_graded_ranking():
    actual = 1.0 + 3.0 / math.log2(3)
    ideal = 3.0 + 1.0 / math.log2(3)

    assert ndcg_at_k(["low", "high"], RELEVANCE, 2) == pytest.approx(actual / ideal)
    assert ndcg_at_k(["high", "low"], RELEVANCE, 2) == pytest.approx(1.0)


def test_mrr_truncates_and_returns_zero_when_no_hit_is_in_range():
    retrieved = ["absent-a", "absent-b", "low"]

    assert mrr_at_k(retrieved, RELEVANCE, 2) == 0.0
    assert mrr_at_k(retrieved, RELEVANCE, 3) == pytest.approx(1.0 / 3.0)
    assert mrr_at_k(["absent-a"], RELEVANCE, 5) == 0.0


def test_recall_counts_positive_judgments_and_ignores_absent_ids():
    retrieved = ["absent", "other", "none", "high"]

    assert recall_at_k(retrieved, RELEVANCE, 3) == pytest.approx(1.0 / 3.0)
    assert recall_at_k(retrieved, RELEVANCE, 4) == pytest.approx(2.0 / 3.0)
    assert recall_at_k(["absent"], RELEVANCE, 10) == 0.0


def test_evaluate_query_returns_exact_keys_in_canonical_order():
    result = evaluate_query(["low", "high"], RELEVANCE, [2, 1])

    assert list(result) == [
        "ndcg@1",
        "mrr@1",
        "recall@1",
        "ndcg@2",
        "mrr@2",
        "recall@2",
    ]
    assert result["ndcg@1"] == pytest.approx(1.0 / 3.0)
    assert result["mrr@1"] == 1.0
    assert result["recall@1"] == pytest.approx(1.0 / 3.0)


def test_aggregate_metrics_computes_arithmetic_means():
    first = {
        "ndcg@1": 0.25,
        "mrr@1": 0.5,
        "recall@1": 0.0,
    }
    second = {
        "recall@1": 1.0,
        "mrr@1": 1.0,
        "ndcg@1": 0.75,
    }

    assert aggregate_metrics([first, second]) == {
        "ndcg@1": 0.5,
        "mrr@1": 0.75,
        "recall@1": 0.5,
    }


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("cutoff", [0, -1, 1.5, True])
def test_metric_functions_reject_invalid_cutoffs(metric, cutoff):
    with pytest.raises(ValueError, match="positive integer"):
        metric(["high"], RELEVANCE, cutoff)


def test_evaluate_query_rejects_duplicate_and_non_positive_cutoffs():
    with pytest.raises(ValueError, match="duplicate cutoff"):
        evaluate_query(["high"], RELEVANCE, [1, 1])
    with pytest.raises(ValueError, match="positive integer"):
        evaluate_query(["high"], RELEVANCE, [0])


@pytest.mark.parametrize("metric", METRICS)
def test_metric_functions_reject_duplicate_retrieved_ids(metric):
    with pytest.raises(ValueError, match="duplicate retrieved id"):
        metric(["high", "high"], RELEVANCE, 2)


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("grade", [-1, 3, 1.5, True])
def test_metric_functions_reject_invalid_grades(metric, grade):
    with pytest.raises(ValueError, match="one of 0, 1, or 2"):
        metric(["high"], {"high": grade}, 1)


@pytest.mark.parametrize("metric", METRICS)
def test_metric_functions_require_positive_relevance(metric):
    with pytest.raises(ValueError, match="at least one positive grade"):
        metric(["none"], {"none": 0}, 1)


def test_evaluate_query_validates_query_inputs_itself():
    with pytest.raises(ValueError, match="duplicate retrieved id"):
        evaluate_query(["high", "high"], RELEVANCE, [1])
    with pytest.raises(ValueError, match="one of 0, 1, or 2"):
        evaluate_query(["high"], {"high": -1}, [1])
    with pytest.raises(ValueError, match="at least one positive grade"):
        evaluate_query(["none"], {"none": 0}, [1])


def test_aggregate_metrics_rejects_empty_input():
    with pytest.raises(ValueError, match="must not be empty"):
        aggregate_metrics([])


def test_aggregate_metrics_rejects_inconsistent_metric_keys():
    complete = {"ndcg@1": 1.0, "mrr@1": 1.0, "recall@1": 1.0}
    different = {"ndcg@2": 1.0, "mrr@2": 1.0, "recall@2": 1.0}

    with pytest.raises(ValueError, match="inconsistent metric keys"):
        aggregate_metrics([complete, different])


@pytest.mark.parametrize(
    "metrics",
    [
        {"precision@1": 1.0},
        {"ndcg@0": 1.0, "mrr@0": 1.0, "recall@0": 1.0},
        {"ndcg@1": 1.0, "mrr@1": 1.0},
    ],
)
def test_aggregate_metrics_rejects_invalid_or_incomplete_metric_keys(metrics):
    with pytest.raises(ValueError, match="invalid metric key|incomplete metric set"):
        aggregate_metrics([metrics])
