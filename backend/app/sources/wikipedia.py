from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"


class WikipediaAdapter(BaseSourceAdapter):
    """Wikipedia reference-source adapter using the official MediaWiki action API.

    Uses ``generator=search`` plus ``prop=extracts`` to get article titles and
    intro text in a single request. No scraping, no API key.
    """

    source_type = "reference"
    source_name = "Wikipedia"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _build_params(self, query: str, limit: int) -> dict:
        return {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "0",
            "gsrlimit": str(limit),
            "prop": "extracts|info",
            "exintro": "1",
            "explaintext": "1",
            "exlimit": "max",
            "redirects": "1",
            "format": "json",
            "utf8": "1",
            "maxlag": "5",
        }

    @staticmethod
    def _article_url(title: str) -> str:
        encoded = quote(title.replace(" ", "_"), safe="")
        return f"https://{settings.wikipedia_lang}.wikipedia.org/wiki/{encoded}"

    def _parse_results(self, payload: dict, query: str) -> list[SourceResult]:
        pages = payload.get("query", {}).get("pages")
        if not isinstance(pages, dict):
            raise SourceError("Wikipedia response missing query.pages")
        results: list[SourceResult] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            title = page.get("title")
            if not title:
                continue
            title = str(title).replace("_", " ")
            extract = str(page.get("extract") or "").strip()
            results.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=title,
                    description=extract[:500] or None,
                    url=self._article_url(title),
                    author=None,
                    published_at=None,
                    retrieved_at=datetime.now(UTC),
                    language=settings.wikipedia_lang,
                    raw=page,
                )
            )
        return results

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.wikipedia_max_results
        request_params = self._build_params(query, limit)
        headers = {"User-Agent": settings.wikipedia_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                WIKIPEDIA_API_URL,
                params=request_params,
                headers=headers,
                timeout=settings.wikipedia_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("Wikipedia request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise SourceError("Wikipedia rate limited", kind="rate_limited") from exc
            raise SourceError(f"Wikipedia returned HTTP {exc.response.status_code}") from exc
        except ValueError as exc:
            raise SourceError("Wikipedia returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("Wikipedia returned a non-object JSON response")
        return self._parse_results(payload, query)