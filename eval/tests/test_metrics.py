"""Metric calculation tests: ranking and deduplication (offline, deterministic)."""

import pytest

from eval.metrics import dedup_metrics, ranking_metrics

# Gold relevance over a fixed 10-item candidate set.
GOLD = {
    "a": 2,
    "b": 2,
    "c": 1,
    "d": 1,
    "e": 0,
    "f": 0,
    "g": 0,
    "h": 0,
    "i": 0,
    "j": 0,
}


def test_perfect_ranking():
    ranked = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
    m = ranking_metrics(ranked, GOLD)
    assert m["precision_at_5"] == pytest.approx(0.8)
    assert m["precision_at_10"] == pytest.approx(0.4)
    assert m["reciprocal_rank"] == pytest.approx(1.0)
    assert m["ndcg_at_10"] == pytest.approx(1.0)


def test_completely_wrong_ranking():
    ranked = ["j", "i", "h", "g", "f", "e", "d", "c", "b", "a"]
    m = ranking_metrics(ranked, GOLD)
    assert m["precision_at_5"] == pytest.approx(0.0)
    assert m["precision_at_10"] == pytest.approx(0.4)
    assert m["reciprocal_rank"] == pytest.approx(1.0 / 7.0)
    assert m["ndcg_at_10"] == pytest.approx(0.4154, abs=1e-3)


def test_partial_ranking():
    ranked = ["a", "e", "c", "b", "f", "d", "g", "h", "i", "j"]
    m = ranking_metrics(ranked, GOLD)
    assert m["precision_at_5"] == pytest.approx(0.6)
    assert m["precision_at_10"] == pytest.approx(0.4)
    assert m["reciprocal_rank"] == pytest.approx(1.0)
    assert m["ndcg_at_10"] == pytest.approx(0.8840, abs=1e-3)


def test_ndcg_zero_when_no_relevant():
    rel = {f"i{n}": 0 for n in range(10)}
    ranked = list(rel)
    assert ranking_metrics(ranked, rel)["ndcg_at_10"] == 0.0


def test_perfect_deduplication():
    m = dedup_metrics([("a", "b"), ("c", "d")], [("a", "b"), ("c", "d")])
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0


def test_zero_match_deduplication():
    m = dedup_metrics([("a", "b"), ("c", "d")], [])
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
    assert m["f1"] == 0.0


def test_partial_deduplication():
    m = dedup_metrics([("a", "b"), ("c", "d")], [("a", "b"), ("e", "f")])
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(0.5)


def test_ambiguous_pairs_excluded_from_dedup_scoring():
    m = dedup_metrics(
        gold_pairs=[("a", "b"), ("c", "d")],
        predicted_pairs=[("a", "b"), ("c", "d")],
        ambiguous_pairs=[("c", "d")],
    )
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0
    assert m["true_positive"] == 1
