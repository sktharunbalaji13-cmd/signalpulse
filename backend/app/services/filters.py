"""M3-E query-time filter view (design §6): read-only projection over the frozen C4 order.

Filters are applied at request time as SQL predicates over persisted rows. They
never re-rank (ordering stays by ``rank_position``), never write, and never
trigger retrieval. Time views use the search completion instant as a permanent
cutoff, so a given search + params is deterministic forever (shareable URLs,
stable pagination). Reference rows are always included in time views (timeless
context, M3-C); news/social rows with NULL ``published_at`` are excluded by any
window except ``all``. There is deliberately no hard freshness-score filter:
freshness is a soft weighted ranking signal (M3-C).

Validation of filter values happens at the API layer (FastAPI ``Literal`` /
``pattern`` -> HTTP 422); this module only maps the already-validated params to
SQL predicates.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, or_

from app.db.models import Result

VALID_SOURCE_TYPES = ("news", "social", "reference", "research", "code", "qa")
VALID_TIME_WINDOWS = ("24h", "7d", "30d", "all")
VALID_DUPLICATES = ("all", "canonical")
TIME_WINDOW_HOURS = {"24h": 24, "7d": 168, "30d": 720}


def time_cutoff(completed_at, created_at, time_window: str):
    """Permanent cutoff instant for a time view (design §6.1).

    Returns ``None`` when no window applies (``all``/unset). Uses the search
    completion instant, falling back to creation while a search is still
    running, so the window is anchored to a fixed, stored timestamp.
    """
    if time_window not in TIME_WINDOW_HOURS:
        return None
    base = completed_at or created_at
    return base - timedelta(hours=TIME_WINDOW_HOURS[time_window])


def filter_conditions(
    *,
    source_types: list[str] | None,
    time_window: str,
    duplicates: str,
    language: str | None,
    completed_at,
    created_at,
) -> list:
    """SQL predicates implementing the designed view (design §6.1).

    ``source_type`` (repeatable, OR), ``language`` (exact match, excludes NULL
    rows while active), ``duplicates=canonical`` (hide ``is_duplicate``
    members), and the ``time`` window (news/social only, reference always in,
    NULL ``published_at`` out except ``all``). Combined with AND.
    """
    conditions = []
    if source_types:
        conditions.append(Result.source_type.in_(source_types))
    if language is not None:
        conditions.append(Result.language == language)
    if duplicates == "canonical":
        conditions.append(Result.is_duplicate.is_(False))
    cutoff = time_cutoff(completed_at, created_at, time_window)
    if cutoff is not None:
        conditions.append(
            or_(
                Result.source_type == "reference",
                and_(
                    Result.published_at.is_not(None),
                    Result.published_at >= cutoff,
                ),
            )
        )
    return conditions
