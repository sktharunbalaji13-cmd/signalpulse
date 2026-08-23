"""M12 read-only production observability data functions (admin scope).

Aggregates existing search/source/dedup/semantic data. Pure business logic -
no HTTP/routing concerns. Called from main.py's route registration.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DuplicateGroup, Result, Search, SourceEvent

_VALID_WINDOWS = {"24h": 1, "7d": 7, "30d": 30}


def validate_window(window: str) -> str:
    if window not in _VALID_WINDOWS:
        raise ValueError(
            f"Invalid window {window!r}; expected one of {sorted(_VALID_WINDOWS)}"
        )
    return window


def get_admin_stats(session: Session, window: str) -> dict[str, Any]:
    """Aggregated production observability metrics over a time window."""
    validate_window(window)
    cutoff = None
    days = _VALID_WINDOWS.get(window)
    if days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=days)

    searches = session.query(Search).all()
    if cutoff:
        filtered = []
        for s in searches:
            ca = s.created_at
            if ca and ca.tzinfo is None:
                ca = ca.replace(tzinfo=UTC)
            if ca and ca >= cutoff:
                filtered.append(s)
        searches = filtered
    total = len(searches)

    by_status: dict[str, int] = {}
    durations: list[float] = []
    semantic: dict[str, int] = {}
    sem_ms_values: list[float] = []
    stage_searches = 0
    empty_result_count = 0
    normalized_counts: dict[str, int] = defaultdict(int)

    results_per_search: dict[str, int] = defaultdict(int)
    for r in session.query(Result.search_id).all():
        results_per_search[r[0]] += 1

    for s in searches:
        by_status[s.status] = by_status.get(s.status, 0) + 1
        if s.duration_ms is not None:
            durations.append(s.duration_ms)
        normalized_counts[s.normalized_query] += 1
        if results_per_search.get(s.id, 0) == 0 and s.status != "running":
            empty_result_count += 1

        stats = s.stats or {}
        sem = stats.get("semantic", {})
        st = sem.get("status")
        if st is not None:
            semantic[st] = semantic.get(st, 0) + 1
            stage_searches += 1
            ms = sem.get("ms")
            if ms is not None:
                sem_ms_values.append(float(ms))

    source_events = session.query(SourceEvent).all()
    sources: dict[str, dict[str, Any]] = {}
    search_ids = {s.id for s in searches}
    for e in source_events:
        if e.search_id not in search_ids:
            continue
        entry = sources.setdefault(e.source_name, {})
        key_map = {"success": "success", "failed": "failed",
                   "timeout": "timeout", "rate_limited": "rate_limited"}
        key = key_map.get(e.status, e.status)
        entry[key] = entry.get(key, 0) + 1
        if e.latency_ms is not None:
            lats = entry.setdefault("_latencies", [])
            lats.append(e.latency_ms)
        if e.result_count is not None:
            ress = entry.setdefault("_results", [])
            ress.append(e.result_count)

    for name in list(sources):
        entry = sources[name]
        lats = entry.pop("_latencies", None)
        ress = entry.pop("_results", None)
        if lats:
            entry["avg_latency_ms"] = round(sum(lats) / len(lats))
        if ress:
            entry["avg_results"] = round(sum(ress) / len(ress))

    dup_groups = session.query(DuplicateGroup).all()
    dedup_total_groups = len(dup_groups)
    dedup_removed = sum(d.member_count - 1 for d in dup_groups)

    top_queries = sorted(normalized_counts.items(), key=lambda x: (-x[1], x[0]))[:10]

    def pctl(pct: float) -> float | None:
        if not durations:
            return None
        ordered = sorted(durations)
        idx = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
        return round(float(ordered[idx]), 1)

    return {
        "window": window,
        "generated_at": datetime.now(UTC).isoformat(),
        "retention": {
            "days": settings.retention_days,
            "clock": "searches.created_at",
            "note": "M15.1: searches older than this are deleted automatically "
            "(on startup/cold start) and via POST /api/v1/admin/purge-expired",
        },
        "searches": {"total": total, "by_status": dict(sorted(by_status.items()))},
        "latency_ms": {
            "p50": pctl(50),
            "p95": pctl(95),
            "p99": pctl(99),
        },
        "sources": sources,
        "dedup": {
            "total_groups": dedup_total_groups,
            "duplicates_removed": dedup_removed,
        },
        "semantic": {
            **semantic,
            "searches_with_stage": stage_searches,
            "avg_ms": (
                round(sum(sem_ms_values) / len(sem_ms_values))
                if sem_ms_values else None
            ),
            "note": "SEM1 dormant by default; activate via SEMANTIC_ENABLED=true",
        },
        "queries": {
            "empty_result_count": empty_result_count,
            "top_normalized_queries": [
                {"query": q, "count": n} for q, n in top_queries
            ],
            "privacy_note": (
                "normalized query strings only; no raw user text beyond "
                "what is already persisted"
            ),
        },
    }