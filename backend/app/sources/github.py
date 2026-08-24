from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult


class GitHubAdapter(BaseSourceAdapter):
    """GitHub adapter over the REST repository-search API (M22.2, ADR 0019).

    Repositories are the unit of engineering evidence; issue search is
    deliberately out of scope (ADR 0019). One request per search against
    ``/search/repositories`` using GitHub's own best-match ordering (no
    ``sort`` parameter - stars/popularity are NOT ranking inputs).

    Credential model: a backend-held fine-grained PAT with zero extra scopes
    (public read-only is implicit). Without ``GITHUB_API_TOKEN`` the source
    reports itself unconfigured and the pipeline treats it as *disabled*
    (M21.3 semantics) - never as a failure. (The env var deliberately avoids
    the name ``GITHUB_TOKEN``, which GitHub Actions injects into every CI
    job it runs.)

    Time-window semantics: requested windows are pushed server-side via the
    ``pushed:>`` search qualifier so GitHub never returns rows we would
    discard anyway.

    Timestamp policy: ``published_at`` is ``pushed_at`` (last engineering
    activity), not ``created_at`` - creation date would bury maintained
    classics. ``language`` stays None: the repo-language field is a
            programming language, not the human language of a document.
    """

    source_type = "code"
    source_name = "GitHub"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def is_configured(self) -> bool:
        return bool(settings.github_api_token)

    def _build_params(
        self, query: str, limit: int, window_hours: int | None
    ) -> dict:
        search_query = query
        if window_hours is not None:
            since = (datetime.now(UTC) - timedelta(hours=window_hours)).strftime("%Y-%m-%d")
            search_query += f" pushed:>{since}"
        return {"q": search_query, "per_page": str(limit)}

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": settings.github_user_agent,
        }
        if settings.github_api_token:
            headers["Authorization"] = f"Bearer {settings.github_api_token}"
        return headers

    def _parse_results(self, payload: dict) -> list[SourceResult]:
        items = payload.get("items")
        if not isinstance(items, list):
            raise SourceError("GitHub response is missing items")
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            full_name = item.get("full_name")
            url = item.get("html_url")
            if not isinstance(full_name, str) or not full_name.strip():
                continue
            if not isinstance(url, str) or not url.strip():
                continue
            owner = item.get("owner") or {}
            description = item.get("description")
            normalized.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=full_name,
                    description=description[:500] if isinstance(description, str) else None,
                    url=url,
                    author=owner.get("login") if isinstance(owner, dict) else None,
                    published_at=self._parse_pushed_at(item.get("pushed_at")),
                    retrieved_at=now,
                    language=None,
                    # Keyless-of-secrets public payload: keep the item verbatim
                    # so stars/forks/topics/license remain auditable provenance
                    # (they are explicitly NOT ranking inputs).
                    raw=item,
                )
            )
        return normalized

    @staticmethod
    def _parse_pushed_at(raw_value: object) -> datetime | None:
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
        limit = params.limit if params else settings.github_max_results
        window_hours = params.window_hours if params else None
        request_params = self._build_params(query, limit, window_hours)
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.github_api_url,
                params=request_params,
                headers=self._headers(),
                timeout=settings.github_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("GitHub request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "GitHub rate limited the request", kind="rate_limited"
                ) from exc
            raise SourceError(f"GitHub returned HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise SourceError("GitHub request failed", kind="failed") from exc
        except ValueError as exc:
            raise SourceError("GitHub returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("GitHub returned a non-object JSON response")
        return self._parse_results(payload)
