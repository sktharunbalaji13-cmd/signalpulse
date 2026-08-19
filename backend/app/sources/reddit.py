import re
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult
from app.sources.reddit_auth import RedditAuth

DESCRIPTION_LIMIT = 500
REDDIT_BASE = "https://www.reddit.com"

SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|credential|authorization|password|api[-_]?key)", re.IGNORECASE
)


def _strip_sensitive(value):
    """Recursively drop credential-shaped keys from a payload before storage."""
    if isinstance(value, dict):
        return {
            key: _strip_sensitive(item)
            for key, item in value.items()
            if not SENSITIVE_KEY_PATTERN.search(key)
        }
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value


class RedditAdapter(BaseSourceAdapter):
    """Reddit social-source adapter using the official OAuth2 API.

    Uses the documented client-credentials flow (``/api/v1/access_token``)
    then searches ``/search`` on the OAuth endpoint. No scraping, no
    unauthenticated fallback. Reddit is user-generated content: nothing here
    treats it as verified fact.
    """

    source_type = "social"
    source_name = "Reddit"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._auth = RedditAuth()

    def _auth_for(self) -> RedditAuth:
        return self._auth

    @staticmethod
    def _canonical_url(post: dict) -> str | None:
        """Build the canonical Reddit post URL, never trusting outbound links.

        Prefers the API permalink; falls back to a constructed
        ``/r/{subreddit}/comments/{id}/`` URL; only then accepts a URL that is
        already a canonical reddit.com URL. Arbitrary external URLs (the post's
        link target) are never used as the navigation target.
        """
        permalink = post.get("permalink")
        if isinstance(permalink, str) and permalink:
            if permalink.startswith("/"):
                return f"{REDDIT_BASE}{permalink}"
            return permalink
        post_id = post.get("id")
        subreddit = post.get("subreddit")
        if post_id and subreddit:
            return f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}/"
        url = post.get("url")
        if isinstance(url, str) and url.startswith(f"{REDDIT_BASE}/"):
            return url
        return None

    @staticmethod
    def _normalize_author(author: object) -> str | None:
        if not author:
            return None
        text = str(author)
        if text == "[deleted]":
            return None
        return text

    @staticmethod
    def _published_at(created_utc: object) -> datetime | None:
        if not isinstance(created_utc, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(created_utc, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    def _normalize_post(self, post: dict) -> SourceResult | None:
        title = post.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        url = self._canonical_url(post)
        if not url:
            return None
        selftext = str(post.get("selftext") or "").strip()
        return SourceResult(
            source_type=self.source_type,
            source_name=self.source_name,
            title=title,
            description=selftext[:DESCRIPTION_LIMIT] or None,
            url=url,
            author=self._normalize_author(post.get("author")),
            published_at=self._published_at(post.get("created_utc")),
            retrieved_at=datetime.now(UTC),
            language=None,
            raw=_strip_sensitive(post),
        )

    def _parse_listing(self, payload: dict) -> list[SourceResult]:
        if not isinstance(payload, dict):
            raise SourceError("Reddit returned a non-object search response")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SourceError("Reddit response is missing data.children")
        children = data.get("children")
        if not isinstance(children, list):
            raise SourceError("Reddit response is missing data.children")
        results: list[SourceResult] = []
        for child in children:
            if not isinstance(child, dict) or child.get("kind") != "t3":
                continue
            post = child.get("data")
            if not isinstance(post, dict):
                continue
            normalized = self._normalize_post(post)
            if normalized is not None:
                results.append(normalized)
        return results

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.reddit_max_results
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            auth = self._auth_for()
            token = await auth.get_access_token(client)
            response = await client.get(
                f"{settings.reddit_api_base}/search",
                params={"q": query, "limit": str(limit), "sort": "relevance", "type": "link"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": settings.reddit_user_agent,
                },
                timeout=settings.reddit_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except SourceError:
            raise
        except httpx.TimeoutException as exc:
            raise SourceError("Reddit search request timed out", kind="timeout") from exc
        except httpx.RequestError as exc:
            raise SourceError("Reddit search request failed", kind="failed") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError("Reddit rate limited the request", kind="rate_limited") from exc
            if status in (401, 403):
                raise SourceError("Reddit search authentication failed", kind="failed") from exc
            raise SourceError(f"Reddit search returned HTTP {status}") from exc
        except ValueError as exc:
            raise SourceError("Reddit returned an invalid search response") from exc
        finally:
            if own_client:
                await client.aclose()
        return self._parse_listing(payload)