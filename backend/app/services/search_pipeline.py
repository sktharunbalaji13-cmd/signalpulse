import asyncio
from time import monotonic

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import log_event
from app.db import session as db_session
from app.db.models import (
    DuplicateGroup,
    Result,
    Search,
    SearchStatus,
    SourceEvent,
    new_uuid,
    utcnow,
)
from app.services import semantic
from app.services.canonicalize import dedupe_key
from app.services.dedup import Candidate, detect_duplicates, select_canonical
from app.services.ranking import Rankable, doc_key, rank_items
from app.services.semantic import SemanticUnavailable
from app.sources.base import SearchParams, SourceError
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


async def _run_source(search: Search, source_name: str) -> dict:
    """Execute one adapter in its own session and record its source event.

    Each source runs inside a dedicated SQLAlchemy session so concurrent
    fan-out never shares a transaction across adapters. Returns its status
    dict; never raises Ã¢â‚¬â€ failures are isolated and recorded per source.
    """
    adapter = registry.get(source_name)
    if adapter is None:
        return {"name": source_name, "status": "failed", "error": "unknown source"}
    display_name = adapter.source_name
    log_event("source_started", search_id=search.id, source=display_name)
    started = monotonic()
    with db_session.SessionLocal() as session:
        try:
            # M7.1: sources receive the normalized intake query (casing +
            # whitespace collapsed); the original query remains on the Search
            # row for display/history.
            results = await adapter.search(
                search.normalized_query or search.query,
                SearchParams(window_hours=search.window_hours),
            )
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


def _annotate_duplicates(session: Session, search_id: str) -> dict:
    """Annotate (never delete) duplicate relationships for a finished search.

    Sets ``dedupe_key`` on every result, detects exact+fuzzy duplicates, picks a
    deterministic canonical per group, and persists ``DuplicateGroup`` rows plus
    the ``duplicate_group_id`` / ``is_duplicate`` columns on each member.
    Returns a small stats dict for ``search.stats``.
    """
    results = (
        session.query(Result)
        .filter(Result.search_id == search_id)
        .order_by(Result.source_name, Result.url)
        .all()
    )
    for result in results:
        result.dedupe_key = dedupe_key(result.url)

    if len(results) < 2:
        return {"groups": 0, "duplicates": 0}

    candidates = [
        Candidate(
            id=result.id,
            url=result.url,
            title=result.title,
            source_type=result.source_type,
            published_at=result.published_at,
            description=result.description,
        )
        for result in results
    ]
    groups = detect_duplicates(candidates)
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    result_by_id = {result.id: result for result in results}

    duplicate_count = 0
    for group in groups:
        member_ids = list(group.members)
        canonical_id = select_canonical([candidate_by_id[mid] for mid in member_ids])
        group_id = new_uuid()
        session.add(
            DuplicateGroup(
                id=group_id,
                search_id=search_id,
                canonical_result_id=canonical_id,
                member_count=len(member_ids),
                duplicate_evidence={"methods": sorted(group.methods)},
            )
        )
        for member_id in member_ids:
            result = result_by_id[member_id]
            result.duplicate_group_id = group_id
            result.is_duplicate = member_id != canonical_id
        duplicate_count += len(member_ids) - 1

    return {"groups": len(groups), "duplicates": duplicate_count}


def _apply_ranking(
    session: Session, search_id: str, semantic_scores: dict[str, float] | None = None
) -> dict:
    """Rank all results of a finished search with the M3-D C4 model.

    Persists ``rank_score`` and ``rank_components`` on every ``Result`` row
    (design Ã‚Â§5: activate the dormant columns). The results endpoint then
    serves rows in rank order with the same total order as the ranker.
    """
    search = session.get(Search, search_id)
    if search is None:
        return {"ranked": 0}
    results = (
        session.query(Result)
        .filter(Result.search_id == search_id)
        .order_by(Result.id)
        .all()
    )
    if not results:
        return {"ranked": 0}
    results_by_id = {result.id: result for result in results}
    rankables = [
        Rankable(
            id=result.id,
            title=result.title,
            description=result.description,
            source_type=result.source_type,
            source_name=result.source_name,
            published_at=result.published_at,
            url=result.url,
            duplicate_group_id=result.duplicate_group_id,
            is_duplicate=result.is_duplicate,
        )
        for result in results
    ]
    ranked = rank_items(
        rankables, search.query, now=utcnow(), semantic_scores=semantic_scores
    )
    for position, row in enumerate(ranked):
        result = results_by_id[row.id]
        result.rank_position = position
        result.rank_score = row.score
        result.rank_components = {
            "relevance": row.relevance,
            "freshness": row.freshness,
            "quality": row.quality,
        }
    session.commit()
    return {"ranked": len(ranked)}


async def _run_source_with_timeout(search: Search, source_name: str) -> dict:
    """Run one source bounded by the pipeline-level timeout (design Ã‚Â§15.3.1).

    ``asyncio.wait_for`` cancels a source that hangs without raising, so a
    misbehaving adapter can never block the whole search indefinitely. The
    per-adapter httpx timeout is defense in depth, not the guarantee. A timed-out
    source is recorded as a ``timeout`` ``SourceEvent`` and the job continues
    (isolation and partial-result behaviour are preserved).
    """
    timeout = settings.source_timeout_seconds
    try:
        return await asyncio.wait_for(_run_source(search, source_name), timeout=timeout)
    except TimeoutError:
        adapter = registry.get(source_name)
        display = adapter.source_name if adapter else source_name
        log_event("source_failed", search_id=search.id, source=display, error="timeout")
        with db_session.SessionLocal() as session:
            session.add(
                SourceEvent(
                    search_id=search.id,
                    source_name=display,
                    status="timeout",
                    latency_ms=int(timeout * 1000),
                    error_type="timeout",
                    error_message=f"source exceeded pipeline timeout of {timeout:g}s",
                )
            )
            session.commit()
        return {
            "name": display,
            "status": "timeout",
            "error": f"pipeline timeout after {timeout:g}s",
        }


async def _run_semantic_stage(
    session: Session, search_id: str, search: Search
) -> tuple[dict[str, float] | None, dict]:
    """M11.1 optional semantic stage (ADR 0012). Never fails a search.

    Embeds the normalized query (LRU-cached) and the deduped result texts via
    local ONNX-int8 MiniLM, then returns per-result cosine scores for the SEM1
    blend. ANY failure/timeout returns (None, failed-status) so ranking
    degrades to byte-equivalent C4. Runs in a worker thread bounded by its own
    timeout so a slow model can never stall the job.
    """
    if not settings.semantic_enabled:
        return None, {"status": "disabled"}
    started = monotonic()

    def work() -> dict[str, float]:
        results = (
            session.query(Result)
            .filter(Result.search_id == search_id)
            .order_by(Result.id)
            .all()
        )
        if not results:
            return {}
        query_text = search.normalized_query or search.query
        qvec = semantic.embed_query(query_text)
        if qvec is None:
            raise SemanticUnavailable("query embedding failed")
        texts = [doc_key(r.title, r.description) for r in results]
        doc_vecs = semantic.embed_texts(texts)
        if doc_vecs is None:
            raise SemanticUnavailable("document embedding failed")
        scores: dict[str, float] = {}
        for result, text in zip(results, texts, strict=True):
            dvec = doc_vecs.get(text)
            if dvec is None:
                continue
            value = semantic.cosine(qvec, dvec)
            if value is not None:
                scores[result.id] = value
        return scores

    try:
        scores = await asyncio.wait_for(
            asyncio.to_thread(work), timeout=settings.semantic_timeout_seconds
        )
        ms = int((monotonic() - started) * 1000)
        log_event("semantic_completed", search_id=search_id, ms=ms)
        return scores, {"status": "ok", "ms": ms}
    except TimeoutError:
        ms = int((monotonic() - started) * 1000)
        log_event("semantic_timeout", search_id=search_id, ms=ms)
        return None, {"status": "timeout", "ms": ms}
    except SemanticUnavailable as exc:
        ms = int((monotonic() - started) * 1000)
        log_event("semantic_unavailable", search_id=search_id, error=str(exc)[:120])
        return None, {"status": "unavailable", "error": type(exc).__name__, "ms": ms}
    except Exception as exc:  # noqa: BLE001 - degrade to C4 on any failure
        ms = int((monotonic() - started) * 1000)
        log_event("semantic_failed", search_id=search_id, error=type(exc).__name__)
        return None, {"status": "failed", "error": type(exc).__name__, "ms": ms}

async def run_search_job(search_id: str) -> None:
    """Background job: run every enabled source concurrently, persist outcomes.

    Uses ``asyncio.gather`` for true fan-out: each adapter runs in its own
    session with isolated exceptions, so one source failing never cancels the
    others. Overall status: completed (all ok) / partial (some ok) / failed
    (none ok).
    """
    log_event("search_started", search_id=search_id)
    started = monotonic()
    with db_session.SessionLocal() as session:
        search = session.get(Search, search_id)
        if search is None:
            log_event("search_failed", search_id=search_id, error="search row missing")
            return
    sources_started = monotonic()
    source_statuses = await asyncio.gather(
        *(_run_source_with_timeout(search, name) for name in sorted(registry.names())),
        return_exceptions=True,
    )
    sources_ms = int((monotonic() - sources_started) * 1000)
    if any(isinstance(status, BaseException) for status in source_statuses):
        source_statuses = [
            {"name": f"source-{index}", "status": "failed", "error": "unexpected error"}
            if isinstance(status, BaseException)
            else status
            for index, status in enumerate(source_statuses)
        ]

    with db_session.SessionLocal() as session:
        search = session.get(Search, search_id)
        if search is None:
            log_event("search_failed", search_id=search_id, error="search row missing")
            return
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
        postpass_started = monotonic()
        dedup_stats = _annotate_duplicates(session, search_id)
        semantic_scores, semantic_stats = await _run_semantic_stage(
            session, search_id, search
        )
        ranking_stats = _apply_ranking(session, search_id, semantic_scores)
        postpass_ms = int((monotonic() - postpass_started) * 1000)
        search.stats = {
            "sources": source_statuses,
            "dedup": dedup_stats,
            "ranking": ranking_stats,
            "semantic": semantic_stats,
            "timing_ms": {
                "sources_ms": sources_ms,
                "postpass_ms": postpass_ms,
                "total_ms": search.duration_ms,
            },
        }
        session.commit()
        log_event(
            "search_completed" if status == SearchStatus.COMPLETED.value else "search_failed",
            search_id=search_id,
            status=status,
            duration_ms=search.duration_ms,
        )