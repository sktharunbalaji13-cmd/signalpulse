"""Regression tests for the end-to-end production-pipeline dedup evaluation.

These prove the wired pipeline (real job → DB persistence → duplicate groups →
API) reproduces the offline bridge's dedup behavior: same precision/recall/F1,
zero false positives, zero ambiguous pairs merged, deterministic canonical
selection, and identical per-query detections.
"""

from eval import e2e_dedup_eval


def test_e2e_dedup_metrics_match_bridge():
    report = e2e_dedup_eval.evaluate()
    metrics = report["metrics"]
    assert metrics["precision"] == 1.0
    assert metrics["false_positive"] == 0
    assert metrics["true_positive"] == 124
    assert metrics["false_negative"] == 69
    assert round(metrics["recall"], 4) == 0.6425
    assert round(metrics["f1"], 4) == 0.7823


def test_e2e_dedup_is_deterministic():
    assert e2e_dedup_eval.evaluate() == e2e_dedup_eval.evaluate()


def test_e2e_ambiguous_pairs_never_merged():
    report = e2e_dedup_eval.evaluate()
    assert report["ambiguous_pairs_incorrectly_merged"] == 0


def test_e2e_canonical_selection_is_correct():
    report = e2e_dedup_eval.evaluate()
    assert report["canonical_selection_total"] > 0
    assert report["canonical_selection_correct"] == report["canonical_selection_total"]


def test_e2e_pipeline_preserves_rows_and_api_contract():
    report = e2e_dedup_eval.evaluate()
    assert report["rows_preserved"] is True
    assert report["api_serialization_verified"] is True
    assert report["pipeline_matches_bridge"] is True