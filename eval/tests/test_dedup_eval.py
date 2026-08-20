"""Regression tests for the dedup evaluation bridge (offline, deterministic).

These pin the precision-first contract: the conservative exact+fuzzy detector
must never falsely merge distinct stories in the gold corpus (false positives
must be zero), while recall is allowed to trail precision.
"""

from eval import dedup_eval


def test_dedup_eval_is_deterministic():
    assert dedup_eval.evaluate() == dedup_eval.evaluate()


def test_dedup_eval_metric_structure_and_bounds():
    report = dedup_eval.evaluate()
    metrics = report["metrics"]
    required = {"precision", "recall", "f1", "true_positive", "false_positive", "false_negative"}
    assert required <= set(metrics)
    for key in ("precision", "recall", "f1"):
        assert 0.0 <= metrics[key] <= 1.0


def test_dedup_eval_has_no_false_merges():
    report = dedup_eval.evaluate()
    assert report["metrics"]["false_positive"] == 0
    assert report["metrics"]["precision"] == 1.0


def test_dedup_eval_reports_expected_corpus_shape():
    report = dedup_eval.evaluate()
    assert report["gold_cluster_count"] == 17
    assert report["ambiguous_pair_count"] == 4
    assert len(report["per_query"]) == 16
