import re
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

# app.bsky.feed.post record text is capped at 300 graphemes by the lexicon, so
# the post text fits entirely in the title field; no separate description.
TEXT_LIMIT = 300

_RKEY_RE = re.compile(r"/([a-z0-9]{13})$")


class BlueskyAdapter(BaseSourceAdapter):
    """Bluesky adapter over the public AppView searchPosts API (M22.4, ADR 0021).

    Activates the dormant ``social`` evidence class (Reddit is externally
    blocked; Mastodon and X were NO-GO/blocked in M22.0). Anonymous reads
    against ``api.bsky.app`` need no token.

    Scope discipline (ADR 0021): **single-page, first-25 only**. Bluesky
    blocks anonymous ``cursor`` pagination (403 since July 2026) and the
    public ``public.api.bsky.app`` host returns 403 for search since
    mid-2026 - this adapter pins ``api.bsky.app`` and never paginates.
    ``until``-walk and authentication are explicitly out of v1 scope.

    Contract mapping: post text is the content (``title``, lexicon-capped at
    300 chars); ``record.createdAt`` is the author-stated publish time
    (``indexedAt`` is index time, not publish time); language from
    ``record.langs``; the canonical URL is derived from the post ``uri``
    (``at://.../app.bsky.feed.post/{rkey}``) using the author handle.
    Engagement counts are provenance only - never ranking inputs.
    """

    source_type = "social"
    source_name = "Bluesky"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _build_params(self, query: str, limit: int) -> dict:
        # API cap is 25 per page; single-page v1.
        return {"q": query, "limit": str(min(limit, settings.bluesky_max_results))}

    @staticmethod
    def _canonical_url(uri: str, handle: str) -> str | None:
        match = _RKEY_RE.search(uri)
        if not match:
            return None
        return f"https://bsky.app/profile/{handle}/post/{match.group(1)}"

    def _parse_results(self, payload: dict) -> list[SourceResult]:
        posts = payload.get("posts")
        if not isinstance(posts, list):
            raise SourceError("Bluesky response is missing posts")
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            uri = post.get("uri")
            author = post.get("author") or {}
            record = post.get("record") or {}
            if not isinstance(uri, str) or not uri:
                continue
            if not isinstance(record, dict):
                continue
            text = record.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            handle = author.get("handle") if isinstance(author, dict) else None
            if not isinstance(handle, str) or not handle:
                continue
            url = self._canonical_url(uri, handle)
            if not url:
                continue
            langs = record.get("langs")
            display_name = author.get("displayName")
            normalized.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=text[:TEXT_LIMIT],
                    description=None,
                    url=url,
                    author=handle if isinstance(display_name, str) and display_name else handle,
                    published_at=self._parse_created_at(record.get("createdAt")),
                    retrieved_at=now,
                    language=langs[0] if isinstance(langs, list) and langs else None,
                    # Public record + engagement counts, verbatim (provenance).
                    raw={
                        "uri": uri,
                        "record": record,
                        "like_count": post.get("likeCount"),
                        "repost_count": post.get("repostCount"),
                        "reply_count": post.get("replyCount"),
                        "quote_count": post.get("quoteCount"),
                        "indexed_at": post.get("indexedAt"),
                    },
                )
            )
        return normalized

    @staticmethod
    def _parse_created_at(raw_value: object) -> datetime | None:
        if not isinstance(raw_value, str) or not raw_value:
            return None
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.bluesky_max_results
        request_params = self._build_params(query, limit)
        headers = {"User-Agent": settings.bluesky_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.bluesky_search_url,
                params=request_params,
                headers=headers,
                timeout=settings.bluesky_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("Bluesky request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError("Bluesky rate limited the request", kind="rate_limited") from exc
            # 403 is Bluesky's pagination/host restriction signal; it also
            # covers an anonymous cursor attempt (structural limit in v1).
            raise SourceError(f"Bluesky returned HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise SourceError("Bluesky request failed", kind="failed") from exc
        except ValueError as exc:
            raise SourceError("Bluesky returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("Bluesky returned a non-object JSON response")
        return self._parse_results(payload)
