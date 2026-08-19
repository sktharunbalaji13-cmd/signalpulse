from time import monotonic

from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db import session as db_session
from app.db.models import Result, Search, SearchStatus, SourceEvent, utcnow
from app.sources.base import SourceError
from app.sources.registry import registry


def _persist_results(session: Session, search_id: str, source_results: list) -> int:
    for source_result in source_results:
        session.add(
            Result(
                search_id=search_id,
                source_type=source_result.source_type,
                source_name=source_result.source_name,
                title=source_result.title,
                description=source_result.description,
                url=source_result.url,
                author=source_result.author,
                published_at=source_result.published_at,
                retrieved_at=source_result.retrieved_at,
                language=source_result.language,
                raw=source_result.raw,
            )
        )
    session.commit()
    return len(source_results)


async def _run_source(session: Session, search: Search, source_name: str) -> dict:
    """Execute one adapter and record its source event. Returns its status dict."""
    adapter = registry.get(source_name)
    display_name = adapter.source_name
    log_event("source_started", search_id=search.id, source=display_name)
    started = monotonic()
    try:
        results = await adapter.search(search.query)
        count = _persist_results(session, search.id, results)
        latency_ms = int((monotonic() - started) * 1000)
        session.add(
            SourceEvent(
                search_id=search.id,
                source_name=display_name,
                status="success",
                result_count=count,
                latency_ms=latency_ms,
            )
        )
        session.commit()
        log_event(
            "source_completed",
            search_id=search.id,
            source=display_name,
            count=count,
            latency_ms=latency_ms,
        )
        return {"name": display_name, "status": "success", "result_count": count}
    except SourceError as exc:
        latency_ms = int((monotonic() - started) * 1000)
        session.add(
            SourceEvent(
                search_id=search.id,
                source_name=display_name,
                status=exc.kind,
                latency_ms=latency_ms,
                error_type=exc.kind,
                error_message=str(exc)[:500],
            )
        )
        session.commit()
        log_event("source_failed", search_id=search.id, source=display_name, error=exc.kind)
        return {"name": display_name, "status": exc.kind, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - unexpected errors must not kill the job
        latency_ms = int((monotonic() - started) * 1000)
        session.add(
            SourceEvent(
                search_id=search.id,
                source_name=display_name,
                status="failed",
                latency_ms=latency_ms,
                error_type="unexpected",
                error_message=f"{type(exc).__name__}: {exc}"[:500],
            )
        )
        session.commit()
        log_event("source_failed", search_id=search.id, source=display_name, error="unexpected")
        return {"name": display_name, "status": "failed", "error": "unexpected error"}


async def run_search_job(search_id: str) -> None:
    """Background job: run every enabled source, persist results and events.

    Structured so adding an adapter (registry registration only) needs no
    changes here. Fan-out stays sequential for now; one source per search.
    """
    log_event("search_started", search_id=search_id)
    started = monotonic()
    with db_session.SessionLocal() as session:
        search = session.get(Search, search_id)
        if search is None:
            log_event("search_failed", search_id=search_id, error="search row missing")
            return
        source_statuses = [
            await _run_source(session, search, name) for name in sorted(registry.names())
        ]

        failed = sum(1 for s in source_statuses if s["status"] != "success")
        total_sources = len(source_statuses)
        if failed == 0:
            status = SearchStatus.COMPLETED.value
        elif failed < total_sources:
            status = SearchStatus.PARTIAL.value
        else:
            status = SearchStatus.FAILED.value

        search.status = status
        search.completed_at = utcnow()
        search.duration_ms = int((monotonic() - started) * 1000)
        search.stats = {"sources": source_statuses}
        session.commit()
        log_event(
            "search_completed" if status == SearchStatus.COMPLETED.value else "search_failed",
            search_id=search_id,
            status=status,
            duration_ms=search.duration_ms,
        )