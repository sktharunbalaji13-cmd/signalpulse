"""M22.2 GitHub adapter + `code` source-type tests (ADR 0019).

Repositories are the unit of engineering evidence. The adapter is disabled
without a backend-held token (never a failure), maps pushed_at to
published_at, and the `code` type carries its own ranking constants.
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
    CODE_QUALITY,
    TYPE_PRIORITY,
    WEIGHTS,
    Rankable,
    rank_items,
    source_quality,
)
from tests.helpers import (
    GITHUB_SEARCH_URL,
    mock_arxiv_empty,
    mock_github_success,
    mock_github_timeout,
    mock_guardian_empty,
    mock_hacker_news_empty,
    mock_reddit_success,
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
def github_token(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "test-token")


class TestGitHubAdapter:
    @respx.mock
    def test_maps_repository_to_canonical_result(self, github_token):
        mock_github_success()
        from app.sources.github import GitHubAdapter

        results = asyncio.run(GitHubAdapter().search("graph neural networks"))
        assert len(results) == 2
        first = next(r for r in results if r.title == "pyg-team/pytorch_geometric")
        assert first.url == "https://github.com/pyg-team/pytorch_geometric"
        assert first.author == "pyg-team"
        assert first.published_at == datetime(2026, 8, 17, 21, 3, 55, tzinfo=UTC)
        assert first.description == "Graph Neural Network Library for PyTorch"
        assert first.source_type == "code"
        assert first.source_name == "GitHub"
        assert first.language is None  # repo language is not a human language
        # Provenance: stars/topics/license stay auditable but are NOT signals.
        assert first.raw["stargazers_count"] == 24030
        assert "graph-neural-networks" in first.raw["topics"]
        second = next(r for r in results if r.title == "thunlp/GNNPapers")
        assert second.description.startswith("Must-read papers")

    @respx.mock
    def test_sends_best_match_order_and_limit(self, github_token):
        route = respx.get(GITHUB_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.base import SearchParams
        from app.sources.github import GitHubAdapter

        asyncio.run(GitHubAdapter().search("cli tool", SearchParams(limit=4)))
        sent = dict(route.calls.last.request.url.params)
        assert sent["q"] == "cli tool"
        assert sent["per_page"] == "4"
        assert "sort" not in sent  # best-match relevance, never popularity

    @respx.mock
    def test_sends_bearer_token_when_configured(self, github_token):
        route = respx.get(GITHUB_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.github import GitHubAdapter

        asyncio.run(GitHubAdapter().search("x"))
        auth = route.calls.last.request.headers.get("Authorization")
        assert auth == "Bearer test-token"

    @respx.mock
    def test_window_pushes_pushed_qualifier(self, github_token):
        route = respx.get(GITHUB_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.base import SearchParams
        from app.sources.github import GitHubAdapter

        asyncio.run(GitHubAdapter().search("x", SearchParams(limit=3, window_hours=24)))
        q = dict(route.calls.last.request.url.params)["q"]
        assert q.startswith("x pushed:>")
        assert len(q.split("-")) == 3  # YYYY-MM-DD

    @respx.mock
    def test_rate_limited_maps_to_rate_limited(self, github_token):
        respx.get(GITHUB_SEARCH_URL).mock(return_value=httpx.Response(429, text="slow down"))
        from app.sources.base import SourceError
        from app.sources.github import GitHubAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(GitHubAdapter().search("x"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_http_error_maps_to_failed(self, github_token):
        respx.get(GITHUB_SEARCH_URL).mock(return_value=httpx.Response(500, text="boom"))
        from app.sources.base import SourceError
        from app.sources.github import GitHubAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(GitHubAdapter().search("x"))
        assert excinfo.value.kind == "failed"

    @respx.mock
    def test_timeout_maps_to_timeout(self, github_token):
        mock_github_timeout()
        from app.sources.base import SourceError
        from app.sources.github import GitHubAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(GitHubAdapter().search("x"))
        assert excinfo.value.kind == "timeout"

    @respx.mock
    def test_missing_items_key_is_a_failure(self, github_token):
        respx.get(GITHUB_SEARCH_URL).mock(return_value=httpx.Response(200, json={"oops": 1}))
        from app.sources.base import SourceError
        from app.sources.github import GitHubAdapter

        with pytest.raises(SourceError):
            asyncio.run(GitHubAdapter().search("x"))

    def test_disabled_without_token(self):
        from app.sources.github import GitHubAdapter

        assert GitHubAdapter().is_configured() is False


class TestCodeRankingConstants:
    def test_weights_quality_priority_registered(self):
        assert WEIGHTS["code"] == (0.60, 0.15, 0.25)
        assert TYPE_PRIORITY["code"] == 4
        assert source_quality("code", "GitHub") == 0.70
        assert CODE_QUALITY == 0.70

    def test_stars_are_not_a_quality_signal(self):
        """Two repos from the same source type share the quality constant."""
        now = datetime.now(UTC)
        items = [
            Rankable(
                id="big",
                title="owner/mega-repo",
                description="vector database",
                source_type="code",
                source_name="GitHub",
                published_at=now - timedelta(days=10),
                url="https://github.com/owner/mega-repo",
            ),
            Rankable(
                id="small",
                title="owner/nano-repo",
                description="vector database",
                source_type="code",
                source_name="GitHub",
                published_at=now - timedelta(days=10),
                url="https://github.com/owner/nano-repo",
            ),
        ]
        ranked = rank_items(items, "vector database", now=now)
        by_id = {r.id: r for r in ranked}
        assert by_id["big"].score == by_id["small"].score

    def test_code_freshness_uses_quarterly_half_life(self):
        now = datetime.now(UTC)
        fresh = freshness_score(now - timedelta(hours=6), "code", now=now)
        quarter = freshness_score(now - timedelta(days=90), "code", now=now)
        two_years = freshness_score(now - timedelta(days=730), "code", now=now)
        assert fresh > 0.99
        assert 0.50 < quarter < 0.55  # ~one half-life (floor lifts it above 0.50)
        assert two_years > 0.05

    def test_code_rows_rank_deterministically(self):
        now = datetime(2026, 8, 24, tzinfo=UTC)
        items = [
            Rankable(
                id="repo",
                title="pyg-team/pytorch_geometric",
                description="graph neural network library for pytorch",
                source_type="code",
                source_name="GitHub",
                published_at=datetime(2026, 8, 20, tzinfo=UTC),
                url="https://github.com/pyg-team/pytorch_geometric",
            ),
            Rankable(
                id="noise",
                title="unrelated story",
                source_type="news",
                source_name="Hacker News",
                published_at=now,
                url="https://example.com/n",
            ),
        ]
        ranked = rank_items(items, "graph neural networks", now=now)
        assert ranked[0].id == "repo"
        assert ranked[0].quality == 0.70


class TestPipelineIntegration:
    @respx.mock
    def test_search_includes_github_and_persists_code_results(
        self, client, session_factory, guardian_key, reddit_creds, github_token
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_reddit_success()
        mock_github_success()

        search_id = client.post("/api/v1/searches", json={"query": "gnn"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        gh = next(s for s in body["sources"] if s["name"] == "GitHub")
        assert gh["status"] == "success"
        assert gh["result_count"] == 2

        with session_factory() as session:
            rows = (
                session.query(Result)
                .filter(Result.search_id == search_id, Result.source_type == "code")
                .all()
            )
            assert len(rows) == 2

    @respx.mock
    def test_github_failure_degrades_to_partial(
        self, client, guardian_key, reddit_creds, github_token
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_reddit_success()
        mock_github_timeout()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "partial"
        gh = next(s for s in body["sources"] if s["name"] == "GitHub")
        assert gh["status"] == "timeout"

    @respx.mock
    def test_absent_token_yields_disabled_not_failure(self, client, no_token):
        """No GITHUB_TOKEN -> GitHub records a disabled event; enabled trio completes."""
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        gh = next(s for s in body["sources"] if s["name"] == "GitHub")
        assert gh["status"] == "disabled"
        assert gh["error_type"] == "disabled"

    @pytest.fixture()
    def no_token(self, monkeypatch):
        monkeypatch.setattr(settings, "github_token", "")


class TestFilterAllowList:
    def test_code_source_type_filter_accepted(self, client):
        resp = client.get("/api/v1/searches/no-such-id/results?source_type=code")
        assert resp.status_code == 404  # filter passed validation; search unknown
