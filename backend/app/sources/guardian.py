from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

DESCRIPTION_LIMIT = 500


class GuardianAdapter(BaseSourceAdapter):
    """The Guardian news adapter using the official Open Platform Content API.

    Calls ``GET /search`` with the ``api-key`` query parameter (no scraping),
    maps ``webTitle``/``webUrl``/``webPublicationDate``/``fields`` into the
    canonical ``SourceResult``, and preserves each raw item for provenance.
    """

    source_type = "news"
    source_name = "The Guardian"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def is_configured(self) -> bool:
        return bool(settings.guardian_api_key)
    def _build_params(self, query: str, limit: int) -> dict:
        return {
            "q": query,
            "api-key": settings.guardian_api_key,
            "page-size": str(limit),
            "page": "1",
            "order-by": "relevance",
            "show-fields": "trailText,byline",
            "format": "json",
        }

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _error_kind(message: str) -> str:
        lowered = message.lower()
        if "ratelimit" in lowered or "rate limit" in lowered:
            return "rate_limited"
        if "apikey" in lowered or "unauthorised" in lowered or "unauthorized" in lowered:
            return "failed"
        return "failed"

    def _parse_results(self, payload: dict) -> list[SourceResult]:
        response = payload.get("response")
        if not isinstance(response, dict):
            raise SourceError("The Guardian response is missing the response object")
        if response.get("status") == "error":
            message = str(response.get("message") or "The Guardian returned an error")
            raise SourceError(message, kind=self._error_kind(message))
        results = response.get("results")
        if not isinstance(results, list):
            raise SourceError("The Guardian response is missing response.results")
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = item.get("webTitle")
            if not title:
                continue
            fields = item.get("fields") or {}
            description = str(fields.get("trailText") or "").strip() or None
            if description and len(description) > DESCRIPTION_LIMIT:
                description = description[:DESCRIPTION_LIMIT]
            byline = str(fields.get("byline") or "").strip() or None
            normalized.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=str(title),
                    description=description,
                    url=str(item.get("webUrl") or ""),
                    author=byline,
                    published_at=self._parse_timestamp(item.get("webPublicationDate")),
                    retrieved_at=now,
                    language="en",
                    raw=item,
                )
            )
        return normalized

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        if not settings.guardian_api_key:
            raise SourceError("The Guardian API key is not configured", kind="failed")
        limit = params.limit if params else settings.guardian_max_results
        request_params = self._build_params(query, limit)
        headers = {"User-Agent": settings.guardian_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.guardian_api_url,
                params=request_params,
                headers=headers,
                timeout=settings.guardian_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("The Guardian request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "The Guardian rate limited the request", kind="rate_limited"
                ) from exc
            raise SourceError(f"The Guardian returned HTTP {status}") from exc
        except ValueError as exc:
            raise SourceError("The Guardian returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("The Guardian returned a non-object JSON response")
        return self._parse_results(payload)