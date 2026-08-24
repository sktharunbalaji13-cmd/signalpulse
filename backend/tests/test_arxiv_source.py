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
        from app.sources.arxiv import ArxivAdapter
        from app.sources.base import SourceError

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(ArxivAdapter().search("test"))
        assert excinfo.value.kind == "timeout"

    @respx.mock
    def test_empty_feed_returns_no_results(self):
        mock_arxiv_empty()
        from app.sources.arxiv import ArxivAdapter

        assert asyncio.run(ArxivAdapter().search("test")) == []

    def test_keyless_source_is_always_configured(self):
        from app.sources.arxiv import ArxivAdapter

        assert ArxivAdapter().is_configured() is True


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
    def test_arxiv_failure_degrades_to_partial(self, client, guardian_key, reddit_creds):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_timeout()
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
