"""M4 in-process rate limiting + in-flight protection (design M4 §12).

A per-client-IP sliding-window token bucket on ``POST /searches`` plus a global
cap on the number of concurrently running searches. Excess requests get an
explicit HTTP 429. In-process (single backend instance) — no Redis needed; this
is deliberately the mechanism, with limits read from settings so they can be
calibrated from real traffic.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Search, SearchStatus


class SlidingWindowLimiter:
    """Allow at most ``max_requests`` calls per ``window_seconds`` per key."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        queue = self._hits[key]
        while queue and queue[0] <= now - self.window:
            queue.popleft()
        if len(queue) >= self.max_requests:
            return False
        queue.append(now)
        return True


_limiter: SlidingWindowLimiter | None = None


def limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter(
            settings.rate_limit_requests, settings.rate_limit_window_seconds
        )
    return _limiter


def reset_limiter() -> None:
    """Recreate the limiter (used by tests to pick up monkeypatched settings)."""
    global _limiter
    _limiter = None


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_create_limits(request: Request, session: Session) -> None:
    """Raise HTTP 429 if the client exceeds its bucket or the in-flight cap."""
    if not limiter().allow(client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many searches; slow down and try again shortly.",
        )
    running = (
        session.scalar(
            select(func.count())
            .select_from(Search)
            .where(Search.status == SearchStatus.RUNNING.value)
        )
        or 0
    )
    if running >= settings.max_in_flight_searches:
        raise HTTPException(
            status_code=429,
            detail="Too many searches in progress; try again shortly.",
        )
