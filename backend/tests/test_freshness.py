"""Unit tests for the M3-C production freshness scorer (validated curve).

The probe-grid pins are the exact values measured in the M3-C experiment
(``eval/reports/freshness_eval.md``, ``design`` candidate): the production
implementation must reproduce them bit-for-bit at the same instants. The
cross-harness reproduction check lives in
``eval/tests/test_freshness_eval.py``.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.freshness import (
    FRESHNESS_FLOOR,
    MISSING_TIMESTAMP_SCORE,
    NEWS_HALF_LIFE_HOURS,
    REFERENCE_FRESHNESS,
    SOCIAL_HALF_LIFE_HOURS,
    freshness_score,
)

NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


def _ts(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def _news(hours_ago: float) -> float:
    return freshness_score(_ts(hours_ago), "news", now=NOW)


def _social(hours_ago: float) -> float:
    return freshness_score(_ts(hours_ago), "social", now=NOW)


def test_constants_match_the_validated_model():
    assert NEWS_HALF_LIFE_HOURS == 24.0
    assert SOCIAL_HALF_LIFE_HOURS == 12.0
    assert FRESHNESS_FLOOR == 0.05
    assert MISSING_TIMESTAMP_SCORE == 0.25
    assert REFERENCE_FRESHNESS == 0.5


def test_fixed_probe_grid_matches_experiment_news():
    expected = [1.0, 0.973, 0.7218, 0.525, 0.2875, 0.0574, 0.05, 0.05, 0.05]
    ages = [0.0, 1.0, 12.0, 24.0, 48.0, 168.0, 720.0, 8760.0, 17520.0]
    for age, exp in zip(ages, expected, strict=True):
        assert round(_news(age), 4) == exp, age


def test_fixed_probe_grid_matches_experiment_social():
    expected = [1.0, 0.9467, 0.525, 0.2875, 0.1094, 0.0501, 0.05, 0.05, 0.05]
    ages = [0.0, 1.0, 12.0, 24.0, 48.0, 168.0, 720.0, 8760.0, 17520.0]
    for age, exp in zip(ages, expected, strict=True):
        assert round(_social(age), 4) == exp, age


def test_age_zero_scores_exactly_one():
    assert _news(0.0) == 1.0
    assert _social(0.0) == 1.0


def test_social_decays_faster_than_news():
    assert _social(24.0) < _news(24.0)


def test_monotonic_with_age():
    scores = [_news(h) for h in (1.0, 24.0, 48.0, 168.0, 720.0)]
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


def test_missing_timestamp_scores():
    assert freshness_score(None, "news", now=NOW) == MISSING_TIMESTAMP_SCORE
    assert freshness_score(None, "social", now=NOW) == MISSING_TIMESTAMP_SCORE
    assert freshness_score(None, "reference", now=NOW) == REFERENCE_FRESHNESS


def test_reference_is_timeless():
    for hours_ago in (0.0, 168.0, 17520.0):
        assert freshness_score(_ts(hours_ago), "reference", now=NOW) == REFERENCE_FRESHNESS


def test_future_timestamp_is_clamped():
    future = NOW + timedelta(hours=24)
    assert freshness_score(future, "news", now=NOW) == freshness_score(NOW, "news", now=NOW)
    assert freshness_score(future, "news", now=NOW) == 1.0


def test_naive_published_at_is_assumed_utc():
    naive = _ts(24.0).replace(tzinfo=None)
    assert freshness_score(naive, "news", now=NOW) == _news(24.0)


def test_now_injection_is_deterministic():
    a = freshness_score(_ts(24.0), "news", now=NOW)
    b = freshness_score(_ts(24.0), "news", now=NOW)
    assert a == b
    later = freshness_score(_ts(24.0), "news", now=NOW + timedelta(hours=6))
    assert later < a


def test_default_now_uses_the_clock():
    score = freshness_score(datetime.now(UTC) - timedelta(hours=24), "news")
    assert FRESHNESS_FLOOR <= score <= 1.0


@pytest.mark.parametrize("source_type", ["video", "", "NEWS", "news/social"])
def test_unknown_source_type_raises(source_type):
    with pytest.raises(ValueError):
        freshness_score(NOW, source_type, now=NOW)