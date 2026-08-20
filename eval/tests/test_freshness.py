"""Freshness invariant-check tests (offline, deterministic).

The production freshness scorer (M3-C) does not exist yet; these tests prove
the *harness* enforces the right invariants by feeding it a well-behaved and a
mis-behaved scorer.
"""

from eval.metrics import _FIXED_NOW, check_freshness
from eval.schema import _parse_ts


def _good_scorer(published_at, retrieved_at, source_type):
    """Reference behaviour: missing-ts neutral by type; decay otherwise."""
    del retrieved_at  # intentionally unused -> satisfies no_retrieved_substitution
    if published_at is None:
        return 0.25 if source_type == "news" else 0.5
    age_hours = max(0.0, (_FIXED_NOW - _parse_ts(published_at)).total_seconds() / 3600.0)
    return 0.05 + 0.95 * (2 ** (-age_hours / 24.0))


def _bad_scorer(published_at, retrieved_at, source_type):
    """Violates the contract by letting retrieved_at drive the score."""
    del published_at, source_type
    return 0.8 if retrieved_at >= "2026-08-01T00:00:00Z" else 0.1


def test_good_scorer_passes_all_invariants():
    result = check_freshness(_good_scorer)
    assert result["missing_timestamp_handled"] is True
    assert result["no_retrieved_substitution"] is True
    assert result["monotonic_with_age"] is True
    assert result["future_clamped"] is True


def test_bad_scorer_fails_retrieved_substitution():
    result = check_freshness(_bad_scorer)
    assert result["no_retrieved_substitution"] is False


def test_future_timestamp_is_clamped():
    future = "2026-08-20T12:00:00Z"
    now = "2026-08-19T12:00:00Z"
    assert _good_scorer(future, "2026-08-19T12:00:00Z", "news") <= _good_scorer(
        now, "2026-08-19T12:00:00Z", "news"
    )


def test_monotonic_decay_with_age():
    # published_at advances hour-by-hour toward the fixed "now" (12:00), so the
    # item gets NEWER and its freshness must be non-decreasing.
    scores = [
        _good_scorer(f"2026-08-19T{hours:02d}:00:00Z", "2026-08-19T12:00:00Z", "news")
        for hours in range(0, 12)
    ]
    assert all(scores[i] <= scores[i + 1] for i in range(len(scores) - 1))


def test_reference_and_news_missing_ts_can_differ():
    result = check_freshness(_good_scorer)
    assert result["reference_missing_ts_score"] != result["news_missing_ts_score"]
