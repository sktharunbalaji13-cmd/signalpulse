from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

DESCRIPTION_LIMIT = 500
HACKER_NEWS_DISCUSSION_URL = "https://news.ycombinator.com/item?id={item_id}"


class HackerNewsAdapter(BaseSourceAdapter):
    """Hacker News adapter using the public Algolia HN Search API (M17.5.1).

    Keyless and auth-free: Algolia serves HN's search index publicly
    (~10k requests/hour/IP courtesy budget; SignalPulse issues one request
    per search). ``tags=story`` restricts hits to link/text submissions;
    ``numericFilters=created_at_i>...`` implements the shared time-window
    semantics server-side. The relevance endpoint is always used — no second
    strategy.

    URL policy mirrors Reddit's canonical-URL rule: the external article URL
    is the navigation target when present; text posts fall back to the stable
    HN discussion link built from ``objectID``.
    """

    source_type = "news"
    source_name = "Hacker News"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _build_params(
        self, query: str, limit: int, window_hours: int | None
    ) -> dict:
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": str(limit),
        }
        if window_hours is not None:
            since = int(datetime.now(UTC).timestamp()) - window_hours * 3600
            params["numericFilters"] = f"created_at_i>{since}"
        return params

    @staticmethod
    def _published_at(created_at_i: object) -> datetime | None:
        if not isinstance(created_at_i, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(created_at_i, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    @staticmethod
    def _hit_url(hit: dict) -> str | None:
        url = hit.get("url")
        if isinstance(url, str) and url.strip():
            return url
        item_id = hit.get("objectID")
        if isinstance(item_id, str) and item_id:
            return HACKER_NEWS_DISCUSSION_URL.format(item_id=item_id)
        return None

    def _parse_results(self, payload: dict) -> list[SourceResult]:
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise SourceError("Hacker News response is missing hits")
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = hit.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            url = self._hit_url(hit)
            if not url:
                continue
            story_text = str(hit.get("story_text") or "").strip()
            normalized.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=title,
                    description=story_text[:DESCRIPTION_LIMIT] or None,
                    url=url,
                    author=hit.get("author") or None,
                    published_at=self._published_at(hit.get("created_at_i")),
                    retrieved_at=now,
                    language=None,
                    # Keyless public endpoint: hits carry only public story
                    # metadata, so provenance keeps the hit verbatim.
                    raw=hit,
                )
            )
        return normalized

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.hacker_news_max_results
        window_hours = params.window_hours if params else None
        request_params = self._build_params(query, limit, window_hours)
        headers = {"User-Agent": settings.hacker_news_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.hacker_news_api_url,
                params=request_params,
                headers=headers,
                timeout=settings.hacker_news_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("Hacker News request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "Hacker News rate limited the request", kind="rate_limited"
                ) from exc
            raise SourceError(f"Hacker News returned HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise SourceError("Hacker News request failed", kind="failed") from exc
        except ValueError as exc:
            raise SourceError("Hacker News returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("Hacker News returned a non-object JSON response")
        return self._parse_results(payload)