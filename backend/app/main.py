import asyncio
import hashlib
import json
import re
import secrets
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from app.services.admin_session import (
    COOKIE_NAME,
    cookie_attributes,
    issue_token,
    validate_token,
)
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


# --------------------------------------------------------------------------
# M22.12 TEMPORARY Bluesky 403 diagnostic (Probe B). Single admin-gated,
# telemetry-free endpoint; removed entirely by the follow-up revert commit.
_DIAG_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
_DIAG_QUERY = {"q": "test", "limit": "1"}
_DIAG_ALLOW_HEADERS = {
    "retry-after",
    "cf-ray",
    "cf-mitigated",
    "server",
    "content-type",
    "date",
    "via",
}


def _diag_redact(value: str) -> str:
    """M22.12: mask credential/identity-like material before it can leave."""
    value = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
    value = re.sub(r"did:(?:plc|web):[A-Za-z0-9:._-]+", "[DID]", value)
    value = re.sub(r"[A-Za-z0-9.-]+\.bsky\.social", "[HANDLE]", value)
    value = re.sub(
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}", "[JWT]", value
    )
    return value


def _diag_classify_body(content_type: str, raw_text: str) -> dict:
    """M22.12: classify the response body without ever returning it raw."""
    ctype = content_type.lower()
    if "json" in ctype:
        try:
            parsed = json.loads(raw_text)
        except ValueError:
            return {"body_class": "JSON_UNPARSEABLE"}
        if not isinstance(parsed, dict):
            return {"body_class": "JSON", "json_keys": type(parsed).__name__}
        out: dict = {"body_class": "JSON", "json_keys": sorted(parsed.keys())}
        for field in ("error", "message"):
            if field in parsed:
                out[f"json_{field}"] = _diag_redact(str(parsed[field]))[:300]
        return out
    if "<html" in raw_text.lower():
        label = (
            "EDGE_RULE_HTML"
            if "administrative rules" in raw_text.lower()
            else "HTML_BLOCK_PAGE_OTHER"
        )
        return {"body_class": label}
    return {"body_class": "OTHER", "other_prefix": repr(_diag_redact(raw_text[:120]))}


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

    def _verify_admin(request: Request) -> None:
        """M20.1 (ADR 0016): accept the original X-Admin-Key header (API use)
        OR a valid admin-session cookie (dashboard use). Fails closed."""
        provided = request.headers.get("x-admin-key", "")
        expected = settings.admin_api_key
        key_ok = bool(expected) and secrets.compare_digest(provided, expected)
        cookie_ok = validate_token(request.cookies.get(COOKIE_NAME))
        if not (key_ok or cookie_ok):
            raise HTTPException(status_code=401, detail="Admin authentication required")

    def admin_login_endpoint(request: Request) -> JSONResponse:
        """M20.1: exchange a valid X-Admin-Key for a short-lived HttpOnly cookie.

        The real ADMIN_API_KEY is validated here and never returned or stored;
        the response carries only the session cookie (SameSite=None; Secure).
        """
        _verify_admin_key(request)
        token = issue_token()
        response = JSONResponse({"ok": True})
        response.set_cookie(**cookie_attributes(secure=request.url.scheme == "https"), value=token)
        return response

    def admin_logout_endpoint(request: Request) -> JSONResponse:
        """M20.1: drop the admin session cookie."""
        from app.services.admin_session import revoke_token

        revoke_token(request.cookies.get(COOKIE_NAME))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/api/v1/admin")
        return response

    def admin_stats_endpoint(
        request: Request,
        window: str = "7d",
        session: Session = Depends(get_session),  # noqa: B008
    ):
        _verify_admin(request)
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
        _verify_admin(request)
        counts = purge_search(session, search_id)
        if counts is None:
            raise HTTPException(status_code=404, detail="Search not found")
        return AdminPurgeResponse(**counts.as_dict())

    def admin_purge_expired_endpoint(
        request: Request,
        session: Session = Depends(get_session),  # noqa: B008
    ) -> AdminPurgeResponse:
        """M15.1: purge every search older than the retention cutoff."""
        _verify_admin(request)
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

    def admin_bluesky_diag_endpoint(request: Request) -> dict:
        """M22.12 TEMPORARY single-shot Bluesky 403 diagnostic (Probe B).

        Removed entirely by the follow-up revert commit. Performs exactly one
        outbound request shaped like the production adapter's request,
        persists nothing (no DB session exists in this scope), and returns
        classified, redacted data only — never the raw body.
        """
        _verify_admin(request)
        started = perf_counter()
        try:
            resp = httpx.get(
                _DIAG_URL,
                params=_DIAG_QUERY,
                headers={
                    "User-Agent": settings.bluesky_user_agent,
                    "Accept": "application/json",
                },
                timeout=settings.bluesky_timeout_seconds,
            )
        except httpx.TimeoutException:
            return {
                "outcome": "timeout",
                "elapsed_ms": round((perf_counter() - started) * 1000),
            }
        except httpx.HTTPError as exc:
            return {"outcome": f"request_error:{type(exc).__name__}"}
        elapsed_ms = round((perf_counter() - started) * 1000)
        captured_headers = {
            name.lower(): value
            for name, value in resp.headers.items()
            if name.lower() in _DIAG_ALLOW_HEADERS or "ratelimit" in name.lower()
        }
        body = _diag_classify_body(
            resp.headers.get("content-type", ""), resp.text[:4096]
        )
        log_event(
            "bluesky_diag", status=resp.status_code, body_class=body.get("body_class")
        )
        return {
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "headers": captured_headers,
            **body,
            "body_sha256_12": hashlib.sha256(resp.content).hexdigest()[:12],
        }

    app.add_api_route(
        "/api/v1/admin/diag/bluesky403",
        admin_bluesky_diag_endpoint,
        methods=["GET"],
        tags=["admin"],
        name="admin_bluesky_diag",
    )

    app.add_api_route(
        "/api/v1/admin/login",
        admin_login_endpoint,
        methods=["POST"],
        tags=["admin"],
        name="admin_login",
    )
    app.add_api_route(
        "/api/v1/admin/logout",
        admin_logout_endpoint,
        methods=["POST"],
        tags=["admin"],
        name="admin_logout",
    )

    return app


app = create_app()