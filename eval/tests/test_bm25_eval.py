"""Regression tests for the M3-B BM25 evaluation bridge (offline, deterministic).

Research artifact preserved under ADR 0007 (BM25 rejected as production
relevance core). The pinned numbers are the honest measurement against the
unchanged v2 corpus — NOT a passing target. If they change, that is a
regression (or an intentional, documented retune).
"""

from eval import bm25_eval

_VARIANTS = ("baseline", "bm25_core", "bm25_full")


def test_bm25_eval_is_deterministic():
    assert bm25_eval.evaluate() == bm25_eval.evaluate()


def test_bm25_eval_metric_structure_and_bounds():
    report = bm25_eval.evaluate()
    for variant in _VARIANTS:
        means = report[variant]["means"]
        assert set(means) == {
            "precision_at_5",
            "precision_at_10",
            "reciprocal_rank",
            "ndcg_at_10",
        }
        for value in means.values():
            assert 0.0 <= value <= 1.0
        assert len(report[variant]["per_query"]) == 16
    assert report["query_count"] == 16


def test_bm25_first_measurement_is_pinned():
    report = bm25_eval.evaluate()
    assert round(report["baseline"]["means"]["ndcg_at_10"], 4) == 0.6909
    assert round(report["bm25_core"]["means"]["ndcg_at_10"], 4) == 0.5674
    assert round(report["bm25_full"]["means"]["ndcg_at_10"], 4) == 0.5834


def test_bm25_eval_reports_deltas():
    report = bm25_eval.evaluate()
    deltas = report["delta_vs_baseline"]
    for key in ("precision_at_5", "precision_at_10", "reciprocal_rank", "ndcg_at_10"):
        assert "core" in deltas[key] and "full" in deltas[key]
