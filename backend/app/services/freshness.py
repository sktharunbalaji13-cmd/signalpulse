"""Freshness scoring (M3-C) — the exact curve validated by the eval experiment.

Implements precisely the model accepted in M3-C (design §4, verified against
the unchanged v2 corpus in ``eval/reports/freshness_eval.md`` and pinned by
``eval/tests/test_freshness_eval.py``)::

    news:        0.05 + 0.95 * 2^(-age_hours / 24)   (24 h half-life)
    social:      0.05 + 0.95 * 2^(-age_hours / 12)   (12 h half-life)
    reference:   0.5  (timeless, ``published_at`` ignored)
    missing:     0.25 (news/social without ``published_at``)

Non-negotiable rules (design §4):

1. Never fabricate: freshness is computed only from ``published_at`` when the
   source provided it. Index-time fields are provenance, never freshness.
2. ``retrieved_at`` is not a freshness signal — this service does not even
   accept it.
3. ``published_at > now`` is clamped to age 0 (never fresher than the present).

The scorer is pure and deterministic when ``now`` is injected; the default is
the real clock. ``published_at`` is expected as an aware ``datetime`` (naive
values are assumed to be UTC). Values are bit-identical to the experiment's
``design`` candidate for the same instants.

No ranking combination here (M3-D), no pipeline wiring (M3-C ends at the
scorer), no caching.
"""

from __future__ import annotations

from datetime import UTC, datetime

NEWS_HALF_LIFE_HOURS = 24.0
SOCIAL_HALF_LIFE_HOURS = 12.0
# M22.1 (ADR 0018): research literature decays far slower than news but is
# not timeless like reference works - fast-moving preprint fields are triaged
# by recency on a ~monthly horizon. Design constant, not corpus-validated
# (the frozen corpus carries no research judgments); it affects research rows
# only and is revisable by future experiments.
RESEARCH_HALF_LIFE_HOURS = 24.0 * 30.0
FRESHNESS_FLOOR = 0.05
MISSING_TIMESTAMP_SCORE = 0.25
REFERENCE_FRESHNESS = 0.5

_SOURCE_TYPES = frozenset({"news", "social", "reference", "research"})


def _as_utc(value: datetime) -> datetime:
    """Normalise to UTC-aware; naive datetimes are assumed to be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decay(age_hours: float, half_life_hours: float) -> float:
    return FRESHNESS_FLOOR + (1.0 - FRESHNESS_FLOOR) * 2.0 ** (-age_hours / half_life_hours)


def freshness_score(
    published_at: datetime | None,
    source_type: str,
    *,
    now: datetime | None = None,
) -> float:
    """The M3-C freshness component in [0, 1] for one result.

    Args:
        published_at: the source's own publication timestamp, or ``None`` when
            the source did not provide one.
        source_type: ``news``, ``social`` or ``reference``.
        now: reference instant (defaults to the real clock). Inject for
            deterministic tests and evaluation.

    Raises:
        ValueError: for any source type the validated model does not cover
            (e.g. a future source type), so a new type is a deliberate design
            decision, never a silent default.
    """
    if source_type not in _SOURCE_TYPES:
        raise ValueError(
            f"freshness is defined only for {sorted(_SOURCE_TYPES)}, got {source_type!r}"
        )
    if source_type == "reference":
        return REFERENCE_FRESHNESS
    if published_at is None:
        return MISSING_TIMESTAMP_SCORE

    instant = _as_utc(now) if now is not None else datetime.now(UTC)
    age_hours = max(0.0, (instant - _as_utc(published_at)).total_seconds() / 3600.0)
    half_life = {
        "news": NEWS_HALF_LIFE_HOURS,
        "social": SOCIAL_HALF_LIFE_HOURS,
        "research": RESEARCH_HALF_LIFE_HOURS,
    }[source_type]
    return _decay(age_hours, half_life)