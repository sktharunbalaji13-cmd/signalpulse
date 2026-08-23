import asyncio
import secrets
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes.admin import get_admin_stats, validate_window
from app.api.routes.health import router as health_router
from app.api.routes.searches import router as searches_router
from app.api.routes.sources import router as sources_router
from app.core.config import settings
from app.core.logging import log_event
from app.db.models import Base
from app.db.session import engine, get_session
from app.schemas.search import AdminPurgeResponse
from app.services.retention import (
    purge_expired,
    purge_search,
    retention_cutoff,
    run_scheduled_cleanup,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # M15.1: enforce retention in the background so startup and health checks
    # are never delayed by database work. Render free tier has no scheduler;
    # this runs once per process start (deploy/cold start), so retention is
    # eventually consistent between restarts. Failures inside the job are
    # isolated there and only logged as operational metrics.
    cleanup_task = asyncio.create_task(asyncio.to_thread(run_scheduled_cleanup))
    yield
    cleanup_task.cancel()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """M4 observability: log method/path/status/latency for every request."""

    async def dispatch(self, request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        latency_ms = (perf_counter() - started) * 1000
        log_event(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=round(latency_ms, 1),
        )
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(sources_router, prefix="/api/v1/sources")
    app.include_router(searches_router, prefix="/api/v1")

    def _verify_admin_key(request: Request) -> None:
        """M14.1: constant-time admin key check. Fails closed."""
        provided = request.headers.get("x-admin-key", "")
        expected = settings.admin_api_key
        if not expected or not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Admin authentication required")

    def admin_stats_endpoint(
        request: Request,
        window: str = "7d",
        session: Session = Depends(get_session),  # noqa: B008
    ):
        _verify_admin_key(request)
        try:
            validate_window(window)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return get_admin_stats(session, window)

    app.add_api_route(
        "/api/v1/admin/stats",
        admin_stats_endpoint,
        methods=["GET"],
        tags=["admin"],
        name="admin_stats",
    )

    def admin_purge_search_endpoint(
        search_id: str,
        request: Request,
        session: Session = Depends(get_session),  # noqa: B008
    ) -> AdminPurgeResponse:
        """M15.1: purge one search and its dependent rows (admin-only)."""
        _verify_admin_key(request)
        counts = purge_search(session, search_id)
        if counts is None:
            raise HTTPException(status_code=404, detail="Search not found")
        return AdminPurgeResponse(**counts.as_dict())

    def admin_purge_expired_endpoint(
        request: Request,
        session: Session = Depends(get_session),  # noqa: B008
    ) -> AdminPurgeResponse:
        """M15.1: purge every search older than the retention cutoff."""
        _verify_admin_key(request)
        cutoff = retention_cutoff()
        try:
            counts = purge_expired(session, cutoff=cutoff)
        except Exception:
            raise HTTPException(status_code=500) from None
        return AdminPurgeResponse(cutoff_utc=cutoff, **counts.as_dict())

    app.add_api_route(
        "/api/v1/admin/searches/{search_id}",
        admin_purge_search_endpoint,
        methods=["DELETE"],
        tags=["admin"],
        name="admin_purge_search",
    )
    app.add_api_route(
        "/api/v1/admin/purge-expired",
        admin_purge_expired_endpoint,
        methods=["POST"],
        tags=["admin"],
        name="admin_purge_expired",
    )

    return app


app = create_app()