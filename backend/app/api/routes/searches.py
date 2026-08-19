from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
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
from app.services.search_pipeline import run_search_job

router = APIRouter(tags=["searches"])

SessionDep = Annotated[Session, Depends(get_session)]


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


@router.post("/searches", status_code=202, response_model=SearchCreated)
async def create_search(
    payload: SearchCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> SearchCreated:
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
) -> SearchResultsResponse:
    _get_search_or_404(session, search_id)
    total = _count_results(session, search_id)
    rows = (
        session.scalars(
            select(Result)
            .where(Result.search_id == search_id)
            .order_by(Result.id)
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
        )
        for row in rows
    ]
    return SearchResultsResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/searches", response_model=SearchHistoryResponse)
async def list_searches(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchHistoryResponse:
    searches = session.scalars(select(Search).order_by(Search.created_at.desc()).limit(limit)).all()
    items = [
        SearchHistoryItem(
            search_id=search.id,
            query=search.query,
            status=search.status,
            created_at=search.created_at,
            completed_at=search.completed_at,
            duration_ms=search.duration_ms,
            result_count=_count_results(session, search.id),
        )
        for search in searches
    ]
    return SearchHistoryResponse(items=items)