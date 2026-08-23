"""M15.1 data retention service (ADR 0013).

Deletes searches older than the configured retention window together with
their dependent rows (``duplicate_groups`` -> ``source_events`` -> ``results``
-> ``searches``, the dependency-safe order for the current FK graph, where
every FK is ON DELETE NO ACTION and ``duplicate_groups.canonical_result_id``
references ``results.id``).

Design constraints from M15.0/M15.1:
- Deletion runs in batches so an ever-growing history never has to be loaded
  into memory at once; each batch commits atomically, so a failure can never
  leave a search with partially deleted children.
- The retention clock is ``searches.created_at``.
- Idempotent: purging when nothing is expired deletes nothing.
- Operational logging only: search counts, durations, error *types*. Query
  text and secrets are never logged.
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import log_event
from app.db import session as db_session
from app.db.models import DuplicateGroup, Result, Search, SourceEvent

BATCH_SIZE = 200

_cleanup_lock = threading.Lock()


@dataclass
class PurgeCounts:
    """Operational outcome of a purge run. Contains no content."""

    searches: int = 0
    results: int = 0
    source_events: int = 0
    duplicate_groups: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "searches_deleted": self.searches,
            "results_deleted": self.results,
            "source_events_deleted": self.source_events,
            "duplicate_groups_deleted": self.duplicate_groups,
        }


def retention_cutoff(
    now: datetime | None = None, retention_days: int | None = None
) -> datetime:
    """UTC timestamp before which searches are considered expired."""
    days = retention_days if retention_days is not None else settings.retention_days
    return (now or datetime.now(UTC)) - timedelta(days=days)


def _delete_children(session: Session, search_ids: list[str]) -> PurgeCounts:
    """Delete all dependent rows of the given searches (no commit here).

    Order matters: ``duplicate_groups.canonical_result_id`` references
    ``results.id``, so duplicate groups must go before results. All child
    tables reference ``searches.id``, so searches are deleted last by the
    caller.
    """
    dups = (
        session.query(DuplicateGroup)
        .filter(DuplicateGroup.search_id.in_(search_ids))
        .delete(synchronize_session=False)
    )
    events = (
        session.query(SourceEvent)
        .filter(SourceEvent.search_id.in_(search_ids))
        .delete(synchronize_session=False)
    )
    results = (
        session.query(Result)
        .filter(Result.search_id.in_(search_ids))
        .delete(synchronize_session=False)
    )
    return PurgeCounts(
        results=results, source_events=events, duplicate_groups=dups
    )


def purge_search(session: Session, search_id: str) -> PurgeCounts | None:
    """Purge one search and its dependent rows.

    Returns the deleted-row counts, or ``None`` when the search does not
    exist. Commits on success; raises after rollback on failure so the batch
    stays atomic.
    """
    if session.get(Search, search_id) is None:
        return None
    try:
        counts = _delete_children(session, [search_id])
        session.query(Search).filter(Search.id == search_id).delete(
            synchronize_session=False
        )
        counts.searches = 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return counts


def purge_expired(session: Session, cutoff: datetime) -> PurgeCounts:
    """Delete every search created before ``cutoff`` with its dependents.

    Batches through expired ids; each batch (children + searches) commits
    atomically. Safe to run repeatedly - a cutoff that matches nothing is a
    no-op.
    """
    totals = PurgeCounts()
    while True:
        batch = list(
            session.scalars(
                select(Search.id)
                .where(Search.created_at < cutoff)
                .limit(BATCH_SIZE)
            )
        )
        if not batch:
            break
        try:
            counts = _delete_children(session, batch)
            deleted = (
                session.query(Search)
                .filter(Search.id.in_(batch))
                .delete(synchronize_session=False)
            )
            counts.searches = deleted
            totals.searches += counts.searches
            totals.results += counts.results
            totals.source_events += counts.source_events
            totals.duplicate_groups += counts.duplicate_groups
            session.commit()
        except Exception:
            session.rollback()
            raise
    return totals


def run_scheduled_cleanup() -> PurgeCounts | None:
    """One automatic cleanup pass against the configured database.

    Skips (never queues behind) a concurrent run via a non-reentrant lock so
    overlapping startup/admin triggers cannot interleave batches. Failures are
    isolated and logged without query text or secrets.
    """
    if not _cleanup_lock.acquire(blocking=False):
        log_event("retention_cleanup_skipped", reason="already_running")
        return None
    try:
        started = monotonic()
        log_event("retention_cleanup_started", retention_days=settings.retention_days)
        with db_session.SessionLocal() as session:
            counts = purge_expired(session, cutoff=retention_cutoff())
        duration_ms = int((monotonic() - started) * 1000)
        log_event(
            "retention_cleanup_completed",
            **counts.as_dict(),
            duration_ms=duration_ms,
        )
        return counts
    except Exception as exc:  # noqa: BLE001 - cleanup must never crash the app
        log_event("retention_cleanup_failed", error=type(exc).__name__)
        return None
    finally:
        _cleanup_lock.release()
