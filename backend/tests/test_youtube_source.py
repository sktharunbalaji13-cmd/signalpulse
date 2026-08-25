"""M22.7 YouTube adapter + `video` source-type tests (ADR 0023).

Videos are a distinct multimedia evidence class. The adapter is disabled
without a backend-held key; daily-quota exhaustion (403 quotaExceeded) maps
to rate_limited, not failure. Engagement statistics are out of v1 scope.
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
    TYPE_PRIORITY,
    VIDEO_QUALITY,
    WEIGHTS,
    Rankable,
    rank_items,
    source_quality,
)
from tests.helpers import (
    YOUTUBE_SEARCH_URL,
    mock_arxiv_empty,
    mock_bluesky_empty,
    mock_github_empty,
    mock_guardian_empty,
    mock_hacker_news_empty,
    mock_reddit_success,
    mock_stack_overflow_empty,
    mock_wikipedia_success,
    mock_youtube_quota_exceeded,
    mock_youtube_success,
)


@pytest.fixture()
def guardian_key(monkeypatch):
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")


@pytest.fixture()
def reddit_creds(monkeypatch):
    monkeypatch.setattr(settings, "reddit_client_id", "cid")
    monkeypatch.setattr(settings, "reddit_client_secret", "secret")


@pytest.fixture()
def youtube_key(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", "test-yt-key")


class TestYouTubeAdapter:
    @respx.mock
    def test_maps_video_to_canonical_result(self, youtube_key):
        mock_youtube_success()
        from app.sources.youtube import YouTubeAdapter

        results = asyncio.run(YouTubeAdapter().search("pytorch tutorial"))
        assert len(results) == 2
        first = next(r for r in results if "Full Course" in r.title)
        assert first.source_type == "video"
        assert first.source_name == "YouTube"
        assert first.url == "https://www.youtube.com/watch?v=3mtumohmxpf"
        assert first.published_at == datetime(2026, 8, 20, 14, 0, 9, tzinfo=UTC)
        assert first.author == "freeCodeCamp.org"
        assert first.language == "en"
        assert first.description.startswith("Learn PyTorch from scratch")
        # Provenance: verbatim search item.
        assert first.raw["id"]["videoId"] == "3mtumohmxpf"
        second = next(r for r in results if "visually" in r.title)
        assert second.language is None  # honest null when API omits it

    @respx.mock
    def test_decodes_html_entities_in_title(self, youtube_key):
        respx.get(YOUTUBE_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": {"videoId": "abc123"},
                            "snippet": {
                                "title": "Async &amp; Await &#39;Explained&#39;",
                                "channelTitle": "Ch",
                                "publishedAt": "2026-01-01T00:00:00Z",
                            },
                        }
                    ]
                },
            )
        )
        from app.sources.youtube import YouTubeAdapter

        results = asyncio.run(YouTubeAdapter().search("async"))
        assert results[0].title == "Async & Await 'Explained'"

    @respx.mock
    def test_sends_relevance_params_and_key(self, youtube_key):
        route = respx.get(YOUTUBE_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        from app.sources.base import SearchParams
        from app.sources.youtube import YouTubeAdapter

        asyncio.run(YouTubeAdapter().search("rust", SearchParams(limit=5)))
        sent = dict(route.calls.last.request.url.params)
        assert sent["q"] == "rust"
        assert sent["type"] == "video"
        assert sent["maxResults"] == "5"
        assert sent["relevanceLanguage"] == "en"
        assert sent["key"] == "test-yt-key"

    @respx.mock
    def test_quota_exceeded_403_maps_to_rate_limited(self, youtube_key):
        mock_youtube_quota_exceeded()
        from app.sources.base import SourceError
        from app.sources.youtube import YouTubeAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(YouTubeAdapter().search("x"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_other_403_maps_to_failed(self, youtube_key):
        respx.get(YOUTUBE_SEARCH_URL).mock(
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "errors": [{"reason": "forbidden"}],
                    }
                },
            )
        )
        from app.sources.base import SourceError
        from app.sources.youtube import YouTubeAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(YouTubeAdapter().search("x"))
        assert excinfo.value.kind == "failed"

    @respx.mock
    def test_http_429_maps_to_rate_limited(self, youtube_key):
        respx.get(YOUTUBE_SEARCH_URL).mock(return_value=httpx.Response(429))
        from app.sources.base import SourceError
        from app.sources.youtube import YouTubeAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(YouTubeAdapter().search("x"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_timeout_maps_to_timeout(self, youtube_key):
        respx.get(YOUTUBE_SEARCH_URL).mock(
            side_effect=httpx.ConnectTimeout(
                "timeout", request=httpx.Request("GET", YOUTUBE_SEARCH_URL)
            )
        )
        from app.sources.base import SourceError
        from app.sources.youtube import YouTubeAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(YouTubeAdapter().search("x"))
        assert excinfo.value.kind == "timeout"

    @respx.mock
    def test_missing_items_key_is_a_failure(self, youtube_key):
        respx.get(YOUTUBE_SEARCH_URL).mock(return_value=httpx.Response(200, json={"nope": 1}))
        from app.sources.base import SourceError
        from app.sources.youtube import YouTubeAdapter

        with pytest.raises(SourceError):
            asyncio.run(YouTubeAdapter().search("x"))

    def test_disabled_without_key(self):
        from app.sources.youtube import YouTubeAdapter

        assert YouTubeAdapter().is_configured() is False


class TestVideoRankingConstants:
    def test_weights_quality_priority_registered(self):
        assert WEIGHTS["video"] == (0.55, 0.25, 0.20)
        assert TYPE_PRIORITY["video"] == 6
        assert source_quality("video", "YouTube") == 0.60
        assert VIDEO_QUALITY == 0.60

    def test_video_freshness_uses_72h_half_life(self):
        now = datetime.now(UTC)
        fresh = freshness_score(now - timedelta(hours=2), "video", now=now)
        half = freshness_score(now - timedelta(days=3), "video", now=now)
        year_old = freshness_score(now - timedelta(days=365), "video", now=now)
        assert fresh > 0.98
        assert 0.50 < half < 0.55
        # A year-old video has fully decayed to the floor (72h half-life).
        assert year_old <= 0.051

    def test_video_rows_rank_deterministically(self):
        now = datetime(2026, 8, 25, tzinfo=UTC)
        items = [
            Rankable(
                id="v",
                title="kubernetes explained",
                source_type="video",
                source_name="YouTube",
                published_at=datetime(2026, 8, 20, tzinfo=UTC),
                url="https://www.youtube.com/watch?v=k8s",
            ),
            Rankable(
                id="n",
                title="unrelated story",
                source_type="news",
                source_name="Hacker News",
                published_at=now,
                url="https://example.com/n",
            ),
        ]
        ranked = rank_items(items, "kubernetes explained", now=now)
        assert ranked[0].id == "v"
        assert ranked[0].quality == 0.60


class TestPipelineIntegration:
    @respx.mock
    def test_search_includes_youtube_and_persists_video_results(
        self, client, session_factory, guardian_key, reddit_creds, youtube_key
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()
        mock_stack_overflow_empty()
        mock_bluesky_empty()
        mock_reddit_success()
        mock_youtube_success()

        search_id = client.post("/api/v1/searches", json={"query": "pytorch"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        yt = next(s for s in body["sources"] if s["name"] == "YouTube")
        assert yt["status"] == "success"
        assert yt["result_count"] == 2

        with session_factory() as session:
            rows = (
                session.query(Result)
                .filter(Result.search_id == search_id, Result.source_name == "YouTube")
                .all()
            )
            assert len(rows) == 2

    @respx.mock
    def test_quota_exhaustion_degrades_to_partial_as_rate_limited(
        self, client, guardian_key, reddit_creds, youtube_key
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()
        mock_stack_overflow_empty()
        mock_bluesky_empty()
        mock_reddit_success()
        mock_youtube_quota_exceeded()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "partial"
        yt = next(s for s in body["sources"] if s["name"] == "YouTube")
        assert yt["status"] == "rate_limited"

    @respx.mock
    def test_absent_key_yields_disabled_not_failure(self, client, no_yt_key):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()
        mock_stack_overflow_empty()
        mock_bluesky_empty()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        yt = next(s for s in body["sources"] if s["name"] == "YouTube")
        assert yt["status"] == "disabled"
        assert yt["error_type"] == "disabled"

    @pytest.fixture()
    def no_yt_key(self, monkeypatch):
        monkeypatch.setattr(settings, "youtube_api_key", "")


class TestFilterAllowList:
    def test_video_source_type_filter_accepted(self, client):
        resp = client.get("/api/v1/searches/no-such-id/results?source_type=video")
        assert resp.status_code == 404  # filter passed validation; search unknown
