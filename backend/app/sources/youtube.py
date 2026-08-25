import html
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

DESCRIPTION_LIMIT = 500


class YouTubeAdapter(BaseSourceAdapter):
    """YouTube adapter over the Data API v3 ``search.list`` endpoint
    (M22.7, ADR 0023).

    Multimedia evidence class: official-channel explainers, course content,
    and event coverage that no text source replicates. One ``search.list``
    call per search, relevance-ordered, English-preferred.

    Quota economics are the defining constraint (ADR 0023): ``search.list``
    draws from a separate 100-calls/day bucket. Exhaustion returns HTTP 403
    with reason ``quotaExceeded`` - mapped to ``rate_limited`` because it is
    deterministic-until-midnight-PT temporary unavailability, NOT a source
    failure. Other 403s (bad key, API restriction) map to ``failed``.

    Credential model: backend-held Google Cloud API key sent as the ``key``
    query parameter. Without ``YOUTUBE_API_KEY`` the source reports itself
    unconfigured and the pipeline treats it as *disabled* (M21.3 semantics).

    Timestamp policy: ``publishedAt`` is the upload time supplied by the API.
    Engagement statistics would require a second ``videos.list`` call per
    search - deliberately out of v1 scope to preserve single-call discipline;
    view/like counts therefore never enter raw or ranking.
    """

    source_type = "video"
    source_name = "YouTube"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def is_configured(self) -> bool:
        return bool(settings.youtube_api_key)

    def _build_params(self, query: str, limit: int) -> dict:
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": str(limit),
            "relevanceLanguage": "en",
            "key": settings.youtube_api_key,
        }
        return params

    def _parse_results(self, payload: dict) -> list[SourceResult]:
        items = payload.get("items")
        if not isinstance(items, list):
            raise SourceError("YouTube response is missing items")
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = (item.get("id") or {}).get("videoId")
            snippet = item.get("snippet") or {}
            raw_title = snippet.get("title")
            if not isinstance(video_id, str) or not video_id:
                continue
            if not isinstance(snippet, dict):
                continue
            if not isinstance(raw_title, str) or not raw_title.strip():
                continue
            raw_description = snippet.get("description")
            language = snippet.get("defaultAudioLanguage")
            normalized.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=html.unescape(raw_title),
                    description=html.unescape(raw_description)[:DESCRIPTION_LIMIT]
                    if isinstance(raw_description, str) and raw_description.strip()
                    else None,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    author=snippet.get("channelTitle") or None,
                    published_at=self._parse_published_at(snippet.get("publishedAt")),
                    retrieved_at=now,
                    language=language if isinstance(language, str) and language else None,
                    # Provenance: verbatim search item (no second-call enrichment).
                    raw=item,
                )
            )
        return normalized

    @staticmethod
    def _parse_published_at(raw_value: object) -> datetime | None:
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
        limit = params.limit if params else settings.youtube_max_results
        request_params = self._build_params(query, limit)
        headers = {"User-Agent": settings.youtube_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.youtube_search_url,
                params=request_params,
                headers=headers,
                timeout=settings.youtube_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("YouTube request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "YouTube rate limited the request", kind="rate_limited"
                ) from exc
            # Daily-quota exhaustion arrives as HTTP 403 quotaExceeded: it is
            # temporary (resets midnight PT), so it maps to rate_limited -
            # distinct from genuine failures (bad key / restrictions).
            try:
                error_body = exc.response.json()
            except ValueError:
                error_body = {}
            reasons = [
                e.get("reason")
                for e in (error_body.get("error") or {}).get("errors", [])
                if isinstance(e, dict)
            ]
            if (
                status == 403
                and ((error_body.get("error") or {}).get("reason") == "quotaExceeded"
                     or "quotaExceeded" in reasons)
            ):
                raise SourceError(
                    "YouTube daily quota exhausted", kind="rate_limited"
                ) from exc
            raise SourceError(f"YouTube returned HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise SourceError("YouTube request failed", kind="failed") from exc
        except ValueError as exc:
            raise SourceError("YouTube returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("YouTube returned a non-object JSON response")
        return self._parse_results(payload)
