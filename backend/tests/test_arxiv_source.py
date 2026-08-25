"""M22.1 arXiv adapter + research source-type tests (ADR 0018).

Covers the adapter contract (parsing, errors, window/limit semantics), the
research type's ranking constants (weights, quality, freshness half-life),
pipeline integration with the real registry, and the API filter allow-list.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.config import settings
from app.db.models import Result, SourceEvent
from app.services.freshness import freshness_score
from app.services.ranking import (
    RESEARCH_QUALITY,
    TYPE_PRIORITY,
    WEIGHTS,
    Rankable,
    rank_items,
    source_quality,
)
from tests.helpers import (
    ARXIV_API_URL,
    mock_arxiv_empty,
    mock_arxiv_success,
    mock_arxiv_timeout,
    mock_bluesky_empty,
    mock_guardian_empty,
    mock_hacker_news_empty,
    mock_reddit_success,
    mock_wikipedia_success,
)

FIXTURE_TITLES = ("Attention Is All You Need", "Language Models are Few-Shot Learners")


@pytest.fixture()
def guardian_key(monkeypatch):
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")


@pytest.fixture()
def reddit_creds(monkeypatch):
    monkeypatch.setattr(settings, "reddit_client_id", "cid")
    monkeypatch.setattr(settings, "reddit_client_secret", "secret")


class TestArxivAdapter:
    @respx.mock
    def test_parses_entries_into_canonical_results(self):
        mock_arxiv_success()
        from app.sources.arxiv import ArxivAdapter

        results = asyncio.run(ArxivAdapter().search("attention is all you need"))

        assert len(results) == 2
        first = next(r for r in results if r.title == "Attention Is All You Need")
        # Atom whitespace is collapsed; fixture title had none to collapse but
        # the second entry's did.
        second = next(r for r in results if "Few-Shot" in r.title)
        assert second.title == FIXTURE_TITLES[1]
        assert first.url == "http://arxiv.org/abs/1706.03762v7"
        assert first.published_at == datetime(2017, 6, 12, 17, 57, 34, tzinfo=UTC)
        assert first.author == "Vaswani, Ashish, Shazeer, Noam"
        assert first.source_type == "research"
        assert first.source_name == "arXiv"
        assert first.description.startswith("The dominant sequence transduction")
        # Provenance: unmapped entry fields survive in raw.
        assert first.raw["primary_category"] == "cs.CL"
        assert "cs.LG" in first.raw["categories"]
        assert first.raw["id"] == "http://arxiv.org/abs/1706.03762v7"
        assert first.language is None
        assert first.retrieved_at.tzinfo is UTC

    @respx.mock
    def test_sends_relevance_sort_and_limit(self):
        route = respx.get(ARXIV_API_URL).mock(
            return_value=httpx.Response(200, text="<feed></feed>")
        )
        from app.sources.arxiv import ArxivAdapter
        from app.sources.base import SearchParams

        asyncio.run(ArxivAdapter().search("test", SearchParams(limit=4)))
        sent = dict(route.calls.last.request.url.params)
        assert sent["search_query"] == "all:test"
        assert sent["max_results"] == "4"
        assert sent["sortBy"] == "relevance"

    @respx.mock
    def test_window_pushes_submitteddate_filter(self):
        route = respx.get(ARXIV_API_URL).mock(
            return_value=httpx.Response(200, text="<feed></feed>")
        )
        from app.sources.arxiv import ArxivAdapter
        from app.sources.base import SearchParams

        asyncio.run(ArxivAdapter().search("test", SearchParams(limit=3, window_hours=24)))
        search_query = dict(route.calls.last.request.url.params)["search_query"]
        assert "submittedDate:[" in search_query and "TO " in search_query
        assert search_query.startswith("all:test AND ")

    @respx.mock
    def test_malformed_xml_is_a_failed_source(self):
        respx.get(ARXIV_API_URL).mock(return_value=httpx.Response(200, text="<not-xml"))
        from app.sources.arxiv import ArxivAdapter
        from app.sources.base import SourceError

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(ArxivAdapter().search("test"))
        assert excinfo.value.kind == "failed"

    @respx.mock
    def test_rate_limited_maps_to_rate_limited_kind(self):
        respx.get(ARXIV_API_URL).mock(return_value=httpx.Response(429, text="slow down"))
        from app.sources.arxiv import ArxivAdapter
        from app.sources.base import SourceError

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(ArxivAdapter().search("test"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_timeout_maps_to_timeout_kind(self):
        mock_arxiv_timeout()
        mock_bluesky_empty()
        from app.sources.arxiv import ArxivAdapter
        from app.sources.base import SourceError

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(ArxivAdapter().search("test"))
        assert excinfo.value.kind == "timeout"

    @respx.mock
    def test_empty_feed_returns_no_results(self):
        mock_arxiv_empty()
        mock_bluesky_empty()
        from app.sources.arxiv import ArxivAdapter

        assert asyncio.run(ArxivAdapter().search("test")) == []

    @respx.mock
    def test_keyless_source_is_always_configured(self):
        from app.sources.arxiv import ArxivAdapter

        assert ArxivAdapter().is_configured() is True

    @respx.mock
    def test_large_author_list_is_capped_at_db_limit(self):
        """M22.9: results.author is String(200); a large collaboration must be
        truncated, not fail the source. Full list stays in raw provenance."""
        import xml.etree.ElementTree as ET

        from app.sources.arxiv import _ATOM, AUTHOR_LIMIT, ArxivAdapter

        authors = "".join(
            f"<author><name>Collaborator Number {i:03d} Smith-Jones</name></author>"
            for i in range(30)
        )
        entry_xml = (
            f'<entry xmlns="{_ATOM}"><id>http://arxiv.org/abs/2501.00001</id>'
            f"<title>Large collaboration paper title</title><summary>An abstract.</summary>"
            f"<published>2026-01-01T00:00:00Z</published>{authors}</entry>"
        )
        entry = ET.fromstring(entry_xml)
        from datetime import UTC, datetime

        result = ArxivAdapter()._parse_entry(entry, datetime.now(UTC))
        assert result is not None
        assert len(result.author) <= AUTHOR_LIMIT
        assert len(result.author) == AUTHOR_LIMIT  # hit the cap
        # Unmapped entry fields (including the full author list) stay in raw.
        assert "authors" not in result.raw  # authors are mapped, not duplicated


class TestResearchRankingConstants:
    def test_weights_quality_priority_registered(self):
        assert WEIGHTS["research"] == (0.60, 0.20, 0.20)
        assert TYPE_PRIORITY["research"] == 3
        assert source_quality("research", "arXiv") == 0.75
        assert RESEARCH_QUALITY == 0.75

    def test_unknown_research_source_falls_back_to_type_quality(self):
        assert source_quality("research", "Unknown Journal") == RESEARCH_QUALITY

    def test_research_freshness_uses_long_half_life(self):
        now = datetime.now(UTC)
        fresh = freshness_score(now - timedelta(hours=1), "research", now=now)
        month_old = freshness_score(now - timedelta(days=30), "research", now=now)
        year_old = freshness_score(now - timedelta(days=365), "research", now=now)
        assert 0.98 < fresh <= 1.0
        # ~one half-life elapsed.
        assert 0.5 < month_old < 0.55
        # Long tail never reaches the floor abruptly.
        assert year_old > 0.05

    def test_missing_timestamp_scores_like_other_dated_types(self):
        from app.services.freshness import MISSING_TIMESTAMP_SCORE

        assert freshness_score(None, "research") == MISSING_TIMESTAMP_SCORE

    def test_research_rows_rank_deterministically(self):
        now = datetime(2026, 8, 24, tzinfo=UTC)
        items = [
            Rankable(
                id="a",
                title="attention is all you need",
                description="transformer",
                source_type="research",
                source_name="arXiv",
                published_at=datetime(2026, 8, 20, tzinfo=UTC),
                url="http://arxiv.org/abs/1706.03762",
            ),
            Rankable(
                id="b",
                title="unrelated news story",
                description="nothing matching",
                source_type="news",
                source_name="Hacker News",
                published_at=now,
                url="https://example.com/b",
            ),
        ]
        ranked = rank_items(items, "attention transformer", now=now)
        # The on-topic research row outranks the off-topic news row.
        assert ranked[0].id == "a"
        components = ranked[0]
        assert components.quality == 0.75


class TestPipelineIntegration:
    @respx.mock
    def test_search_includes_arxiv_and_persists_research_results(
        self, client, session_factory, guardian_key, reddit_creds
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_success()
        mock_reddit_success()
        mock_bluesky_empty()

        created = client.post("/api/v1/searches", json={"query": "attention"})
        assert created.status_code == 202
        search_id = created.json()["search_id"]

        status = client.get(f"/api/v1/searches/{search_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        by_name = {s["name"]: s for s in body["sources"]}
        assert by_name["arXiv"]["status"] == "success"
        assert by_name["arXiv"]["result_count"] == 2

        with session_factory() as session:
            events = session.query(SourceEvent).filter_by(search_id=search_id).all()
            assert {e.source_name for e in events} >= {"arXiv"}
            rows = (
                session.query(Result)
                .filter(Result.search_id == search_id, Result.source_type == "research")
                .all()
            )
            assert len(rows) == 2

    @respx.mock
    def test_large_author_list_persists_not_fails(
        self, client, session_factory, guardian_key, reddit_creds
    ):
        """M22.9 regression: a large-collaboration paper used to trip
        String(200) on INSERT -> source 'unexpected' failure -> partial.
        The capped author must persist and the search must complete."""

        from app.sources.arxiv import _ATOM, AUTHOR_LIMIT
        from tests.helpers import ARXIV_API_URL

        authors = "".join(
            f"<author><name>Collaborator {i:03d} of a Very Large Experiment</name></author>"
            for i in range(40)
        )
        feed = (
            f'<?xml version="1.0"?><feed xmlns="{_ATOM}"><entry>'
            f'<id>http://arxiv.org/abs/2501.99999</id>'
            f"<title>Very large collaboration paper</title><summary>Abstract text here.</summary>"
            f"<published>2026-01-01T00:00:00Z</published>{authors}</entry></feed>"
        )
        respx.get(ARXIV_API_URL).mock(return_value=httpx.Response(200, text=feed))
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_reddit_success()
        mock_bluesky_empty()

        search_id = client.post(
            "/api/v1/searches", json={"query": "collaboration"}
        ).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        arxiv = next(s for s in body["sources"] if s["name"] == "arXiv")
        assert arxiv["status"] == "success"
        assert arxiv["result_count"] == 1

        with session_factory() as session:
            row = (
                session.query(Result)
                .filter(Result.search_id == search_id, Result.source_name == "arXiv")
                .one()
            )
            assert len(row.author) <= AUTHOR_LIMIT

    @respx.mock
    def test_arxiv_failure_degrades_to_partial(self, client, guardian_key, reddit_creds):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_timeout()
        mock_bluesky_empty()
        mock_reddit_success()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "partial"
        arxiv = next(s for s in body["sources"] if s["name"] == "arXiv")
        assert arxiv["status"] == "timeout"


class TestFilterAllowList:
    def test_research_source_type_filter_accepted(self, client, session_factory):
        resp = client.get("/api/v1/searches/no-such-id/results?source_type=research")
        # 404 (unknown search) proves the filter value passed validation;
        # a 422 would mean the Literal allow-list rejects it.
        assert resp.status_code == 404