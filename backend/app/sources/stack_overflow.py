import html
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

DESCRIPTION_LIMIT = 500


class StackOverflowAdapter(BaseSourceAdapter):
    """Stack Overflow adapter over the Stack Exchange /search/advanced API
    (M22.3, ADR 0020).

    Questions are the unit of curated problem/solution knowledge; answers,
    comments and bodies are deliberately out of scope (bodies require heavy
    HTML filters - a possible future experiment if lexical relevance proves
    insufficient).

    Credential model: a free Stack Apps API key sent as the ``key`` query
    parameter (10,000 requests/day keyed vs 300/day shared per IP keyless -
    unusable on a shared egress IP). Without ``STACKEXCHANGE_API_KEY`` the
    source reports itself unconfigured and the pipeline treats it as
    *disabled* (M21.3 semantics) - never as a failure.

    Backoff compliance: the API's ``backoff`` field mandates waiting between
    calls. This adapter is stateless and issues exactly one request per
    search with no automatic retries, so it can never hammer the endpoint
    within a backoff window; quota/throttle responses map to ``rate_limited``
    so the pipeline records them honestly.

    Timestamp policy: ``published_at`` is ``creation_date`` - the question's
    birth is the artifact's identity. ``last_activity_date`` is rejected:
    trivial edits would let decade-old questions masquerade as fresh.

    Time-window semantics: unwindowed searches use ``sort=relevance``.
    Windowed searches switch to ``sort=creation`` with a ``min`` floor - the
    Stack Exchange API applies ``min`` against the active sort field, so this
    is the one honest way to push a date filter server-side; results inside
    the window come back newest-first instead of relevance-ordered (documented
    trade-off, mirroring how HN/GitHub keep their windows server-side).
    """

    source_type = "qa"
    source_name = "Stack Overflow"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def is_configured(self) -> bool:
        return bool(settings.stackexchange_api_key)

    def _build_params(
        self, query: str, limit: int, window_hours: int | None
    ) -> dict:
        params = {
            "q": query,
            "site": "stackoverflow",
            "order": "desc",
            "sort": "relevance",
            "pagesize": str(limit),
        }
        if settings.stackexchange_api_key:
            params["key"] = settings.stackexchange_api_key
        if window_hours is not None:
            since = int(datetime.now(UTC).timestamp()) - window_hours * 3600
            # creation-date floor pushed server-side where the API supports it.
            params["min"] = str(since)
            params["sort"] = "creation"
        return params

    def _parse_results(self, payload: dict) -> list[SourceResult]:
        error_name = payload.get("error_name")
        if error_name == "throttle_violation":
            raise SourceError("Stack Overflow throttled the request", kind="rate_limited")
        items = payload.get("items")
        if not isinstance(items, list):
            raise SourceError("Stack Overflow response is missing items")
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_title = item.get("title")
            link = item.get("link")
            if not isinstance(raw_title, str) or not raw_title.strip():
                continue
            if not isinstance(link, str) or not link.strip():
                continue
            title = html.unescape(raw_title)
            owner = item.get("owner") or {}
            # Provenance rule: community signals stay auditable in raw but are
            # NOT ranking inputs (same discipline as GitHub stars).
            normalized.append(
                SourceResult(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    title=title,
                    description=None,
                    url=link,
                    author=html.unescape(owner.get("display_name"))
                    if isinstance(owner, dict)
                    else None,
                    published_at=self._parse_creation_date(item.get("creation_date")),
                    retrieved_at=now,
                    language=None,
                    raw=item,
                )
            )
        return normalized

    @staticmethod
    def _parse_creation_date(raw_value: object) -> datetime | None:
        if not isinstance(raw_value, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(raw_value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.stackoverflow_max_results
        window_hours = params.window_hours if params else None
        request_params = self._build_params(query, limit, window_hours)
        headers = {"User-Agent": settings.stackoverflow_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.stackoverflow_search_url,
                params=request_params,
                headers=headers,
                timeout=settings.stackoverflow_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceError("Stack Overflow request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError(
                    "Stack Overflow rate limited the request", kind="rate_limited"
                ) from exc
            # Stack Exchange reports throttling as a 400 whose body carries
            # error_name=throttle_violation - inspect before treating as failure.
            try:
                body = exc.response.json()
            except ValueError:
                body = {}
            if isinstance(body, dict) and body.get("error_name") == "throttle_violation":
                raise SourceError(
                    "Stack Overflow throttled the request", kind="rate_limited"
                ) from exc
            raise SourceError(f"Stack Overflow returned HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise SourceError("Stack Overflow request failed", kind="failed") from exc
        except ValueError as exc:
            raise SourceError("Stack Overflow returned an invalid JSON response") from exc
        finally:
            if own_client:
                await client.aclose()
        if not isinstance(payload, dict):
            raise SourceError("Stack Overflow returned a non-object JSON response")
        return self._parse_results(payload)
