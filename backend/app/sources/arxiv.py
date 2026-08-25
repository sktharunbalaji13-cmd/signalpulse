import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.sources.base import BaseSourceAdapter, SearchParams, SourceError, SourceResult

DESCRIPTION_LIMIT = 500
# M22.9: results.author is String(200). Large collaborations (100s of authors)
# exceed the column limit and made the whole source fail as an unexpected
# error. Cap the joined author string at the column limit. (Authors are not
# captured in raw - provenance stores the unmapped entry fields verbatim.)
AUTHOR_LIMIT = 200

_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"
_OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"


def _clean_text(value: str | None) -> str:
    """Collapse the whitespace arXiv scatters through titles/summaries."""
    return " ".join((value or "").split())


def _parse_published(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        # Atom timestamps are ISO 8601 with a trailing Z.
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class ArxivAdapter(BaseSourceAdapter):
    """arXiv adapter using the public Atom export API (M22.1, ADR 0018).

    Keyless and auth-free: ``export.arxiv.org`` serves the full corpus
    publicly with a courtesy budget of ~1 request per 3 seconds; SignalPulse
    issues exactly one request per search. ``sortBy=relevance`` uses arXiv's
    own ranking engine; ``search_query=all:...`` searches title, abstract,
    authors, comments, journal reference and categories jointly.

    Time-window semantics mirror the Hacker News adapter: when a window is
    requested it is pushed server-side via the ``submittedDate`` range
    operator so arXiv never returns rows we would discard anyway.
    """

    source_type = "research"
    source_name = "arXiv"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _build_params(
        self, query: str, limit: int, window_hours: int | None
    ) -> dict:
        search_query = f"all:{query}"
        if window_hours is not None:
            end = datetime.now(UTC)
            start_ts = int(end.timestamp()) - window_hours * 3600
            fmt = "%Y%m%d%H%M"
            search_query += (
                f" AND submittedDate:[{datetime.fromtimestamp(start_ts, tz=UTC).strftime(fmt)}"
                f" TO {end.strftime(fmt)}]"
            )
        return {
            "search_query": search_query,
            "start": "0",
            "max_results": str(limit),
            "sortBy": "relevance",
        }

    @staticmethod
    def _entry_url(entry: ET.Element) -> str | None:
        for link in entry.findall(f"{{{_ATOM}}}link"):
            if link.get("rel") == "alternate" and link.get("href"):
                return link.get("href")
        entry_id = _clean_text(entry.findtext(f"{{{_ATOM}}}id"))
        return entry_id or None

    def _parse_entry(self, entry: ET.Element, now: datetime) -> SourceResult | None:
        title = _clean_text(entry.findtext(f"{{{_ATOM}}}title"))
        if not title:
            return None
        url = self._entry_url(entry)
        if not url:
            return None
        authors = [
            _clean_text(author.findtext(f"{{{_ATOM}}}name"))
            for author in entry.findall(f"{{{_ATOM}}}author")
        ]
        authors = [name for name in authors if name]
        # Provenance rule (PROJECT_SPEC §16): keep every entry field we do not
        # map to a contract column, serialized to plain values, so each result
        # stays auditable against the source response.
        raw: dict[str, object] = {}
        for child in entry:
            localname = child.tag.split("}", 1)[-1]
            text = _clean_text(child.text)
            if text:
                raw[localname] = text
        raw["categories"] = [
            category.get("term") for category in entry.findall(f"{{{_ATOM}}}category")
        ]
        primary = entry.find(f"{{{_ARXIV}}}primary_category")
        if primary is not None:
            raw["primary_category"] = primary.get("term")
        return SourceResult(
            source_type=self.source_type,
            source_name=self.source_name,
            title=title,
            description=_clean_text(entry.findtext(f"{{{_ATOM}}}summary"))[:DESCRIPTION_LIMIT]
            or None,
            url=url,
            author=(", ".join(authors) or None)[:AUTHOR_LIMIT],
            published_at=_parse_published(entry.findtext(f"{{{_ATOM}}}published")),
            retrieved_at=now,
            language=None,
            raw=raw,
        )

    def _parse_feed(self, payload_xml: str) -> list[SourceResult]:
        try:
            root = ET.fromstring(payload_xml)
        except ET.ParseError as exc:
            raise SourceError("arXiv returned an invalid XML response") from exc
        now = datetime.now(UTC)
        normalized: list[SourceResult] = []
        for entry in root.findall(f"{{{_ATOM}}}entry"):
            result = self._parse_entry(entry, now)
            if result is not None:
                normalized.append(result)
        return normalized

    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        limit = params.limit if params else settings.arxiv_max_results
        window_hours = params.window_hours if params else None
        request_params = self._build_params(query, limit, window_hours)
        headers = {"User-Agent": settings.arxiv_user_agent}
        own_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.get(
                settings.arxiv_api_url,
                params=request_params,
                headers=headers,
                timeout=settings.arxiv_timeout_seconds,
            )
            response.raise_for_status()
            payload_xml = response.text
        except httpx.TimeoutException as exc:
            raise SourceError("arXiv request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise SourceError("arXiv rate limited the request", kind="rate_limited") from exc
            raise SourceError(f"arXiv returned HTTP {status}") from exc
        except httpx.RequestError as exc:
            raise SourceError("arXiv request failed", kind="failed") from exc
        finally:
            if own_client:
                await client.aclose()
        return self._parse_feed(payload_xml)
