from time import monotonic

import httpx

from app.core.config import settings
from app.sources.base import SourceError

TOKEN_SAFETY_MARGIN_SECONDS = 60


class RedditAuth:
    """OAuth2 client-credentials token exchange for Reddit's official API.

    Authentication is kept separate from result normalization: this class
    only acquires and caches an access token. Credentials come from settings
    and are never logged or exposed in errors. The token is reused for the
    lifetime Reddit reports (minus a safety margin) instead of re-fetching it
    on every search.

    The httpx client is passed per call rather than owned here so the cache
    never outlives (or references) a closed client.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._cache_key: tuple[str, str] | None = None

    def _cached_token(self) -> str | None:
        key = (settings.reddit_client_id or "", settings.reddit_client_secret or "")
        if (
            self._token
            and self._cache_key == key
            and monotonic() < self._expires_at
        ):
            return self._token
        self._token = None
        self._cache_key = key
        return None

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        cached = self._cached_token()
        if cached is not None:
            return cached
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            raise SourceError("Reddit client credentials are not configured", kind="failed")
        try:
            response = await client.post(
                settings.reddit_token_url,
                data={"grant_type": "client_credentials"},
                auth=(settings.reddit_client_id, settings.reddit_client_secret),
                headers={"User-Agent": settings.reddit_user_agent},
                timeout=settings.reddit_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("Reddit token request timed out", kind="timeout") from exc
        except httpx.RequestError as exc:
            raise SourceError("Reddit token request failed", kind="failed") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "Reddit rate limited the token request", kind="rate_limited"
                ) from exc
            if status in (401, 403):
                raise SourceError("Reddit authentication failed", kind="failed") from exc
            raise SourceError(f"Reddit token request returned HTTP {status}") from exc
        except ValueError as exc:
            raise SourceError("Reddit returned an invalid token response") from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise SourceError("Reddit returned an invalid token response")
        self._token = str(payload["access_token"])
        try:
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        self._expires_at = monotonic() + expires_in - TOKEN_SAFETY_MARGIN_SECONDS
        return self._token