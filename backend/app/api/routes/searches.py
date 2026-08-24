from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Result, Search, SearchStatus, SourceEvent
from app.db.session import get_session
from app.schemas.search import (
    SearchCreate,
    SearchCreated,
    SearchHistoryItem,
    SearchHistoryResponse,
    SearchResultItem,
    SearchResultsResponse,
    SearchStatusResponse,
    SourceStatus,
)
from app.services.filters import filter_conditions
from app.services.rate_limit import enforce_create_limits
from app.services.search_pipeline import run_search_job
from app.sources.registry import registry

router = APIRouter(tags=["searches"])

SessionDep = Annotated[Session, Depends(get_session)]


async def _enforce_create_limits(request: Request, session: SessionDep) -> None:
    """M4 rate limiting + in-flight protection on search creation (HTTP 429)."""
    enforce_create_limits(request, session)


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _get_search_or_404(session: Session, search_id: str) -> Search:
    search = session.get(Search, search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return search


def _count_results(session: Session, search_id: str) -> int:
    count = select(func.count()).select_from(Result).where(Result.search_id == search_id)
    return session.scalar(count) or 0


@router.post(
    "/searches",
    status_code=202,
    response_model=SearchCreated,
    dependencies=[Depends(_enforce_create_limits)],
)
async def create_search(
    payload: SearchCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> SearchCreated:
    # M21.3 (ADR 0017): a search needs at least one configured/enabled source.
    # If every registered source is disabled, creating a search would be an
    # empty operation - reject it rather than fabricate a result.
    if not registry.has_enabled():
        raise HTTPException(
            status_code=503,
            detail="No search sources are currently enabled.",
        )
    search = Search(
        query=payload.query,
        normalized_query=normalize_query(payload.query),
        window_hours=payload.window_hours,
        status=SearchStatus.RUNNING.value,
    )
    session.add(search)
    session.commit()
    session.refresh(search)
    background_tasks.add_task(run_search_job, search.id)
    log_event("search_created", search_id=search.id)
    return SearchCreated(search_id=search.id, status=SearchStatus.RUNNING.value)


@router.get("/searches/{search_id}", response_model=SearchStatusResponse)
async def get_search(
    search_id: str,
    session: SessionDep,
) -> SearchStatusResponse:
    search = _get_search_or_404(session, search_id)
    events = (
        session.scalars(
            select(SourceEvent)
            .where(SourceEvent.search_id == search_id)
            .order_by(SourceEvent.created_at)
        )
        .all()
    )
    sources = [
        SourceStatus(
            name=event.source_name,
            status=event.status,
            result_count=event.result_count,
            latency_ms=event.latency_ms,
            error_type=event.error_type,
            error=event.error_message,
        )
        for event in events
    ]
    return SearchStatusResponse(
        search_id=search.id,
        query=search.query,
        status=search.status,
        created_at=search.created_at,
        completed_at=search.completed_at,
        duration_ms=search.duration_ms,
        result_count=_count_results(session, search_id),
        sources=sources,
    )


@router.get("/searches/{search_id}/results", response_model=SearchResultsResponse)
async def get_search_results(
    search_id: str,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    source_type: Annotated[
        list[Literal["news", "social", "reference", "research"]] | None, Query()
    ] = None,
    time: Annotated[Literal["24h", "7d", "30d", "all"], Query()] = "all",
    duplicates: Annotated[Literal["all", "canonical"], Query()] = "all",
    language: Annotated[str | None, Query(pattern=r"^[a-z]{2,3}$")] = None,
) -> SearchResultsResponse:
    search = _get_search_or_404(session, search_id)
    # M3-E: filters are a read-only view over the persisted rank_position order
    # (design §6). Conditions select a subset; ordering and pagination then
    # operate on that subset. No re-ranking, no writes, no retrieval.
    conditions = [Result.search_id == search_id] + filter_conditions(
        source_types=source_type,
        time_window=time,
        duplicates=duplicates,
        language=language,
        completed_at=search.completed_at,
        created_at=search.created_at,
    )
    total = session.scalar(select(func.count()).select_from(Result).where(*conditions)) or 0
    # M3-D: serve results in the ranker's final order (rank_position, the
    # C4 total order incl. the diversity pass). Unranked rows (search still
    # running) fall back to the tie-break keys, deterministically.
    rows = (
        session.scalars(
            select(Result)
            .where(*conditions)
            .order_by(
                Result.rank_position.asc().nullslast(),
                case(
                    (Result.source_type == "news", 0),
                    (Result.source_type == "social", 1),
                    (Result.source_type == "reference", 2),
                    else_=9,
                ),
                Result.published_at.desc().nullslast(),
                Result.url,
            )
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .all()
    )
    items = [
        SearchResultItem(
            source_type=row.source_type,
            source_name=row.source_name,
            title=row.title,
            description=row.description,
            url=row.url,
            author=row.author,
            published_at=row.published_at,
            retrieved_at=row.retrieved_at,
            language=row.language,
            is_duplicate=row.is_duplicate,
            duplicate_group_id=row.duplicate_group_id,
        )
        for row in rows
    ]
    return SearchResultsResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/searches", response_model=SearchHistoryResponse)
async def list_searches(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchHistoryResponse:
    """M19.1 (ADR 0015): operational history only. Query text is intentionally
    excluded - "history" means searches previously initiated from this browser,
    tracked client-side; the server never publishes a global query list."""
    searches = session.scalars(select(Search).order_by(Search.created_at.desc()).limit(limit)).all()
    items = [
        SearchHistoryItem(
            search_id=search.id,
            status=search.status,
            created_at=search.created_at,
            completed_at=search.completed_at,
            duration_ms=search.duration_ms,
            result_count=_count_results(session, search.id),
        )
        for search in searches
    ]
    return SearchHistoryResponse(items=items)