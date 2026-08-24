"""M22.3 Stack Overflow adapter + `qa` source-type tests (ADR 0020).

Questions are the unit of curated problem/solution knowledge. The adapter is
disabled without a free Stack Apps key, decodes HTML entities in titles,
maps creation_date to published_at, and the `qa` type carries its own
ranking constants. Community signals (score/answer_count) are provenance
only - never ranking inputs.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.config import settings
from app.db.models import Result
from app.services.freshness import freshness_score
from app.services.ranking import (
    QA_QUALITY,
    TYPE_PRIORITY,
    WEIGHTS,
    Rankable,
    rank_items,
    source_quality,
)
from tests.helpers import (
    STACKOVERFLOW_SEARCH_URL,
    mock_arxiv_empty,
    mock_github_empty,
    mock_guardian_empty,
    mock_hacker_news_empty,
    mock_reddit_success,
    mock_stack_overflow_success,
    mock_stack_overflow_timeout,
    mock_wikipedia_success,
)


@pytest.fixture()
def guardian_key(monkeypatch):
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")


@pytest.fixture()
def reddit_creds(monkeypatch):
    monkeypatch.setattr(settings, "reddit_client_id", "cid")
    monkeypatch.setattr(settings, "reddit_client_secret", "secret")


@pytest.fixture()
def se_key(monkeypatch):
    monkeypatch.setattr(settings, "stackexchange_api_key", "test-se-key")


class TestStackOverflowAdapter:
    @respx.mock
    def test_maps_question_to_canonical_result_and_unescapes_html(self, se_key):
        mock_stack_overflow_success()
        from app.sources.stack_overflow import StackOverflowAdapter

        results = asyncio.run(StackOverflowAdapter().search("react useEffect cleanup"))
        assert len(results) == 2
        first = next(r for r in results if r.title.startswith("React Hook Warnings"))
        # HTML entity in the raw title is decoded.
        assert "&amp;" not in first.title and "&#39;" not in first.title
        assert first.url == (
            "https://stackoverflow.com/questions/53949400/react-hook-warnings-"
            "for-async-function-in-useeffect-useeffect-function-retur"
        )
        assert first.published_at == datetime(2018, 11, 2, 16, 20, 0, tzinfo=UTC)
        assert first.author == "Sung M Kim"
        assert first.source_type == "qa"
        assert first.source_name == "Stack Overflow"
        assert first.description is None  # bodies/excerpts out of scope (v1)
        assert first.language is None
        assert first.raw["score"] == 594  # provenance only
        second = next(r for r in results if "Git rebase" in r.title)
        assert second.author == "Example Dev & Co"

    @respx.mock
    def test_sends_site_relevance_pagesize_and_key(self, se_key):
        route = respx.get(STACKOVERFLOW_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.base import SearchParams
        from app.sources.stack_overflow import StackOverflowAdapter

        asyncio.run(StackOverflowAdapter().search("sql index", SearchParams(limit=4)))
        sent = dict(route.calls.last.request.url.params)
        assert sent["q"] == "sql index"
        assert sent["site"] == "stackoverflow"
        assert sent["sort"] == "relevance"
        assert sent["pagesize"] == "4"
        assert sent["key"] == "test-se-key"

    @respx.mock
    def test_window_switches_to_creation_sort_with_min_floor(self, se_key):
        route = respx.get(STACKOVERFLOW_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.base import SearchParams
        from app.sources.stack_overflow import StackOverflowAdapter

        asyncio.run(StackOverflowAdapter().search("x", SearchParams(limit=3, window_hours=24)))
        sent = dict(route.calls.last.request.url.params)
        assert sent["sort"] == "creation"
        assert int(sent["min"]) <= int(datetime.now(UTC).timestamp())

    @respx.mock
    def test_http_429_maps_to_rate_limited(self, se_key):
        respx.get(STACKOVERFLOW_SEARCH_URL).mock(return_value=httpx.Response(429))
        from app.sources.base import SourceError
        from app.sources.stack_overflow import StackOverflowAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(StackOverflowAdapter().search("x"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_throttle_violation_body_maps_to_rate_limited(self, se_key):
        respx.get(STACKOVERFLOW_SEARCH_URL).mock(
            return_value=httpx.Response(
                400, json={"error_id": 502, "error_name": "throttle_violation"}
            )
        )
        from app.sources.base import SourceError
        from app.sources.stack_overflow import StackOverflowAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(StackOverflowAdapter().search("x"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_other_http_error_maps_to_failed(self, se_key):
        respx.get(STACKOVERFLOW_SEARCH_URL).mock(return_value=httpx.Response(500))
        from app.sources.base import SourceError
        from app.sources.stack_overflow import StackOverflowAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(StackOverflowAdapter().search("x"))
        assert excinfo.value.kind == "failed"

    @respx.mock
    def test_timeout_maps_to_timeout(self, se_key):
        mock_stack_overflow_timeout()
        from app.sources.base import SourceError
        from app.sources.stack_overflow import StackOverflowAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(StackOverflowAdapter().search("x"))
        assert excinfo.value.kind == "timeout"

    @respx.mock
    def test_empty_items_returns_no_results(self, se_key):
        respx.get(STACKOVERFLOW_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.stack_overflow import StackOverflowAdapter

        assert asyncio.run(StackOverflowAdapter().search("x")) == []

    def test_disabled_without_key(self):
        from app.sources.stack_overflow import StackOverflowAdapter

        assert StackOverflowAdapter().is_configured() is False


class TestQARankingConstants:
    def test_weights_quality_priority_registered(self):
        assert WEIGHTS["qa"] == (0.60, 0.20, 0.20)
        assert TYPE_PRIORITY["qa"] == 5
        assert source_quality("qa", "Stack Overflow") == 0.75
        assert QA_QUALITY == 0.75

    def test_community_scores_are_not_a_quality_signal(self):
        """Identical text/timestamps -> identical scores regardless of the
        question's community score (which lives only in raw)."""
        now = datetime.now(UTC)
        items = [
            Rankable(
                id="hot",
                title="sqlite insert performance",
                description="how to improve insert performance",
                source_type="qa",
                source_name="Stack Overflow",
                published_at=now - timedelta(days=30),
                url="https://stackoverflow.com/q/1",
            ),
            Rankable(
                id="cold",
                title="sqlite insert performance",
                description="how to improve insert performance",
                source_type="qa",
                source_name="Stack Overflow",
                published_at=now - timedelta(days=30),
                url="https://stackoverflow.com/q/2",
            ),
        ]
        ranked = {r.id: r for r in rank_items(items, "index insert performance", now=now)}
        assert ranked["hot"].score == ranked["cold"].score

    def test_qa_freshness_uses_half_year_half_life(self):
        now = datetime.now(UTC)
        fresh = freshness_score(now - timedelta(hours=6), "qa", now=now)
        half = freshness_score(now - timedelta(days=180), "qa", now=now)
        decade = freshness_score(now - timedelta(days=3650), "qa", now=now)
        assert fresh > 0.99
        assert 0.50 < half < 0.55
        assert decade > 0.05  # classic answers keep a long tail

    def test_qa_rows_rank_deterministically(self):
        now = datetime(2026, 8, 24, tzinfo=UTC)
        items = [
            Rankable(
                id="q",
                title="git rebase vs merge",
                source_type="qa",
                source_name="Stack Overflow",
                published_at=datetime(2026, 8, 20, tzinfo=UTC),
                url="https://stackoverflow.com/q/802115",
            ),
            Rankable(
                id="n",
                title="unrelated news",
                source_type="news",
                source_name="Hacker News",
                published_at=now,
                url="https://example.com/n",
            ),
        ]
        ranked = rank_items(items, "rebase merge", now=now)
        assert ranked[0].id == "q"
        assert ranked[0].quality == 0.75


class TestPipelineIntegration:
    @respx.mock
    def test_search_includes_stack_overflow_and_persists_qa_results(
        self, client, session_factory, guardian_key, reddit_creds, se_key
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_reddit_success()
        mock_github_empty()
        mock_stack_overflow_success()

        search_id = client.post("/api/v1/searches", json={"query": "use effect"}).json()[
            "search_id"
        ]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        so = next(s for s in body["sources"] if s["name"] == "Stack Overflow")
        assert so["status"] == "success"
        assert so["result_count"] == 2

        with session_factory() as session:
            rows = (
                session.query(Result)
                .filter(Result.search_id == search_id, Result.source_type == "qa")
                .all()
            )
            assert len(rows) == 2

    @respx.mock
    def test_stack_overflow_failure_degrades_to_partial(
        self, client, guardian_key, reddit_creds, se_key
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_reddit_success()
        mock_github_empty()
        mock_stack_overflow_timeout()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "partial"
        so = next(s for s in body["sources"] if s["name"] == "Stack Overflow")
        assert so["status"] == "timeout"

    @respx.mock
    def test_absent_key_yields_disabled_not_failure(self, client, no_se_key):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        so = next(s for s in body["sources"] if s["name"] == "Stack Overflow")
        assert so["status"] == "disabled"
        assert so["error_type"] == "disabled"

    @pytest.fixture()
    def no_se_key(self, monkeypatch):
        monkeypatch.setattr(settings, "stackexchange_api_key", "")


class TestFilterAllowList:
    def test_qa_source_type_filter_accepted(self, client):
        resp = client.get("/api/v1/searches/no-such-id/results?source_type=qa")
        assert resp.status_code == 404  # filter passed validation; search unknown
