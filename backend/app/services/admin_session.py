"""M20.1 admin dashboard session (ADR 0016).

A short-lived, in-memory admin token issued by ``POST /admin/login`` when the
caller presents a valid ``X-Admin-Key``. The browser holds only this token in
an HttpOnly+Secure+SameSite cookie; the real ``ADMIN_API_KEY`` never enters
the frontend bundle, browser storage, or the network after login.

Tokens live solely in process memory (no database, no files). Expired tokens
are pruned lazily on validation and on demand. The store is single-process
(intentionally matching the single-worker deployment; restart invalidates
all sessions, which is acceptable for an ops dashboard).
"""

import secrets
import threading
from time import monotonic

from app.core.config import settings

COOKIE_NAME = "signalpulse_admin"
_LOGIN_PATH = "/api/v1/admin"

_tokens: dict[str, float] = {}  # token -> expiry (monotonic seconds)
_lock = threading.Lock()


def issue_token() -> str:
    """Create an in-memory admin token valid for the configured TTL."""
    token = secrets.token_urlsafe(32)
    with _lock:
        _tokens[token] = monotonic() + settings.admin_session_ttl_seconds
    return token


def validate_token(token: str | None) -> bool:
    """True when the token exists and has not expired; prunes if expired."""
    if not token:
        return False
    with _lock:
        expiry = _tokens.get(token)
        if expiry is None:
            return False
        if monotonic() > expiry:
            _tokens.pop(token, None)
            return False
        return True


def revoke_token(token: str | None) -> None:
    """Drop a token (logout). No-op for unknown/expired tokens."""
    if token:
        with _lock:
            _tokens.pop(token, None)


def prune_expired() -> int:
    """Drop every expired token; returns how many were removed."""
    now = monotonic()
    removed = 0
    with _lock:
        expired = [t for t, exp in _tokens.items() if now > exp]
        for t in expired:
            _tokens.pop(t, None)
        removed = len(expired)
    return removed


def active_token_count() -> int:
    """Current number of live admin tokens (observability/test helper)."""
    prune_expired()
    with _lock:
        return len(_tokens)


def cookie_attributes(secure: bool) -> dict:
    """Cookie kwargs for the admin session.

    ``SameSite=None`` is required because the dashboard frontend and the API
    live on different origins (Render static host vs. web service) and the
    cookie must be sent on cross-site requests. ``SameSite=None`` is only
    accepted by browsers together with ``Secure``, hence the coupling.
    """
    attrs = {
        "key": COOKIE_NAME,
        "path": _LOGIN_PATH,
        "httponly": True,
        "max_age": int(settings.admin_session_ttl_seconds),
    }
    if secure:
        attrs["secure"] = True
        attrs["samesite"] = "none"
    else:
        attrs["samesite"] = "lax"
    return attrs