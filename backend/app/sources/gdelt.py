from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult


class GDELTAdapter(BaseSourceAdapter):
    """GDELT DOC 2.0 API news adapter (gate experiment, M2-C).

    Queries ``ArtList`` mode of the public DOC 2.0 API (no key required).
    This is a go/no-go gate: the adapter is fully offline-tested, and the
    decision to keep it registered lives with the evaluation in
    ``docs/ADR/0005-gdelt-gate.md``.

    Timestamp policy: GDELT's ``seendate`` is the moment GDELT *first saw*
    the article, which is not the article's publication time and can be
    hours or days later. It is therefore never surfaced as ``published_at``
    (always ``None``); the raw payload keeps ``seendate`` for provenance.
    """

    source_type = "news"
    source_name = "GDELT"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    @staticmethod
    def _canonical_url(raw_url: object) -> str | None:
        """Strip query strings and fragments for a stable canonical URL."""
        if not isinstance(raw_url, str) or not raw_url:
            return None
        try:
            parts = urlsplit(raw_url)
        except ValueError:
            return None
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    @classmethod
    def _normalize_article(cls, article: dict) -> SourceResult | None:
        title = article.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        url = cls._canonical_url(article.get("url"))
        if not url:
            return None
        language = article.get("language")
        if not isinstance(language, str) or not language:
            language = None
        return SourceResult(
            source_type=cls.source_type,
            source_name=cls.source_name,
            title=title,
            description=None,
            url=url,
            author=None,
            published_at=None,
            retrieved_at=datetime.now(UTC),
            language=language,
            raw=article,
        )

    @classmethod
    def _parse_payload(cls, payload: dict) -> list[SourceResult]:
        if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
            raise SourceError("GDELT response is missing articles")
        results: list[SourceResult] = []
        for article in payload["articles"]:
            if not isinstance(article, dict):
                continue
            normalized = cls._normalize_article(article)
            if normalized is not None:
                results.append(normalized)
        return results

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.gdelt_max_results
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        timespan = "1d"
        if params is not None and params.window_hours is not None:
            timespan = f"{max(1, int(params.window_hours))}h"
        try:
            response = await client.get(
                settings.gdelt_api_url,
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": str(limit),
                    "timespan": timespan,
                },
                timeout=settings.gdelt_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except SourceError:
            raise
        except httpx.TimeoutException as exc:
            raise SourceError("GDELT search request timed out", kind="timeout") from exc
        except httpx.RequestError as exc:
            raise SourceError("GDELT search request failed", kind="failed") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "GDELT rate limited the request", kind="rate_limited"
                ) from exc
            raise SourceError(f"GDELT search returned HTTP {status}") from exc
        except ValueError as exc:
            raise SourceError("GDELT returned an invalid search response") from exc
        finally:
            if own_client:
                await client.aclose()
        return self._parse_payload(payload)