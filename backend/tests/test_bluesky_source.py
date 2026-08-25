"""M22.4 Bluesky adapter + social-class activation tests (ADR 0021).

Bluesky activates the dormant `social` evidence class (Reddit externally
blocked). It adds no new type/weights/freshness - only the per-source quality
constant SOURCE_QUALITY["Bluesky"]=0.45. Single-page anonymous search only.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.config import settings
from app.db.models import Result
from app.services.freshness import freshness_score
from app.services.ranking import SOURCE_QUALITY, TYPE_PRIORITY, WEIGHTS, rank_items
from tests.helpers import (
    BLUESKY_SEARCH_URL,
    mock_arxiv_empty,
    mock_bluesky_success,
    mock_bluesky_timeout,
    mock_github_empty,
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
def bluesky_enabled(monkeypatch):
    """M22.13 (Option C): opt an individual test back into an active Bluesky."""
    monkeypatch.setattr(settings, "bluesky_anonymous_enabled", True)


class TestBlueskyAdapter:
    @respx.mock
    def test_maps_post_to_canonical_result(self):
        mock_bluesky_success()
        from app.sources.bluesky import BlueskyAdapter

        results = asyncio.run(BlueskyAdapter().search("pytorch"))
        assert len(results) == 3
        first = next(r for r in results if "Facial Expression" in r.title)
        assert first.source_type == "social"
        assert first.source_name == "Bluesky"
        assert first.url == (
            "https://bsky.app/profile/prepub-neurodegen.bsky.social/post/3mtumohmxpf2j"
        )
        assert first.published_at == datetime(2026, 8, 25, 4, 11, 9, tzinfo=UTC)
        assert first.language == "en"
        assert first.author == "prepub-neurodegen.bsky.social"
        assert first.description is None
        # Provenance: engagement counts + uri preserved, not ranking inputs.
        assert first.raw["like_count"] == 4
        assert first.raw["repost_count"] == 1
        assert first.raw["uri"].startswith("at://")
        # FreeCodeCamp post has no langs -> language None.
        fc = next(r for r in results if "Neural networks" in r.title)
        assert fc.language is None
        assert fc.raw["like_count"] == 12

    @respx.mock
    def test_sends_query_and_single_page_limit(self):
        route = respx.get(BLUESKY_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"posts": []})
        )
        from app.sources.base import SearchParams
        from app.sources.bluesky import BlueskyAdapter

        asyncio.run(BlueskyAdapter().search("rust", SearchParams(limit=10)))
        sent = dict(route.calls.last.request.url.params)
        assert sent["q"] == "rust"
        assert sent["limit"] == "10"
        sent_headers = route.calls.last.request.headers
        assert "authorization" not in sent_headers
        assert "cookie" not in sent_headers

    @respx.mock
    def test_single_page_limit_capped_at_25(self):
        route = respx.get(BLUESKY_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"posts": []})
        )
        from app.sources.base import SearchParams
        from app.sources.bluesky import BlueskyAdapter

        asyncio.run(BlueskyAdapter().search("rust", SearchParams(limit=50)))
        assert dict(route.calls.last.request.url.params)["limit"] == "25"

    @respx.mock
    def test_http_429_maps_to_rate_limited(self):
        respx.get(BLUESKY_SEARCH_URL).mock(return_value=httpx.Response(429))
        from app.sources.base import SourceError
        from app.sources.bluesky import BlueskyAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(BlueskyAdapter().search("x"))
        assert excinfo.value.kind == "rate_limited"

    @respx.mock
    def test_http_403_maps_to_failed(self):
        respx.get(BLUESKY_SEARCH_URL).mock(return_value=httpx.Response(403))
        from app.sources.base import SourceError
        from app.sources.bluesky import BlueskyAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(BlueskyAdapter().search("x"))
        assert excinfo.value.kind == "failed"

    @respx.mock
    def test_timeout_maps_to_timeout(self):
        mock_bluesky_timeout()
        from app.sources.base import SourceError
        from app.sources.bluesky import BlueskyAdapter

        with pytest.raises(SourceError) as excinfo:
            asyncio.run(BlueskyAdapter().search("x"))
        assert excinfo.value.kind == "timeout"

    @respx.mock
    def test_missing_posts_key_is_a_failure(self):
        respx.get(BLUESKY_SEARCH_URL).mock(return_value=httpx.Response(200, json={"oops": 1}))
        from app.sources.base import SourceError
        from app.sources.bluesky import BlueskyAdapter

        with pytest.raises(SourceError):
            asyncio.run(BlueskyAdapter().search("x"))

    def test_disabled_by_default(self):
        """M22.13: anonymous Bluesky ships disabled (edge-block evidence)."""
        from app.sources.bluesky import BlueskyAdapter

        assert BlueskyAdapter().is_configured() is False

    def test_flag_enables_through_normal_path(self, monkeypatch):
        """M22.13 transition: flipping the setting re-enables the source via the
        normal registry/config path (no special-casing)."""
        from app.sources.bluesky import BlueskyAdapter

        assert BlueskyAdapter().is_configured() is False
        monkeypatch.setattr(settings, "bluesky_anonymous_enabled", True)
        assert BlueskyAdapter().is_configured() is True

    def test_no_authenticated_behavior_exists(self):
        """M22.13 invariant: the adapter carries zero authentication code paths."""
        import inspect

        from app.sources import bluesky as module

        source = inspect.getsource(module)
        for forbidden in (
            "createSession",
            "Bearer",
            "app_password",
            "accessJwt",
            "Authorization",
        ):
            assert forbidden not in source, f"unexpected auth material: {forbidden}"


class TestSocialClassActivation:
    def test_bluesky_uses_existing_social_type(self):
        # No new type/weights/freshness introduced - only a quality constant.
        assert "Bluesky" in SOURCE_QUALITY
        assert SOURCE_QUALITY["Bluesky"] == 0.45
        assert TYPE_PRIORITY["social"] == 1  # unchanged
        assert WEIGHTS["social"] == (0.55, 0.30, 0.15)  # unchanged

    def test_social_freshness_half_life_unchanged(self):
        from app.services.freshness import SOCIAL_HALF_LIFE_HOURS

        now = datetime.now(UTC)
        fresh = freshness_score(now - timedelta(hours=1), "social", now=now)
        stale = freshness_score(now - timedelta(hours=24), "social", now=now)
        assert SOCIAL_HALF_LIFE_HOURS == 12.0
        assert 0.94 < fresh <= 1.0
        assert stale < 0.4

    def test_engagement_counts_are_not_a_ranking_signal(self):
        now = datetime.now(UTC)
        items = [
            {
                "id": "high",
                "title": "pytorch profiling tips",
                "source_type": "social",
                "source_name": "Bluesky",
                "published_at": now - timedelta(hours=2),
                "url": "https://bsky.app/profile/a/post/1",
            },
            {
                "id": "low",
                "title": "pytorch profiling tips",
                "source_type": "social",
                "source_name": "Bluesky",
                "published_at": now - timedelta(hours=2),
                "url": "https://bsky.app/profile/b/post/2",
            },
        ]
        from app.services.ranking import Rankable

        ranked = {r.id: r for r in rank_items([Rankable(**i) for i in items], "pytorch", now=now)}
        assert ranked["high"].score == ranked["low"].score


class TestPipelineIntegration:
    @respx.mock
    def test_search_includes_bluesky_and_persists_social_results(
        self, client, session_factory, guardian_key, reddit_creds, bluesky_enabled
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()
        mock_reddit_success()
        mock_bluesky_success()

        search_id = client.post("/api/v1/searches", json={"query": "pytorch"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        bs = next(s for s in body["sources"] if s["name"] == "Bluesky")
        assert bs["status"] == "success"
        assert bs["result_count"] == 3

        with session_factory() as session:
            rows = (
                session.query(Result)
                .filter(Result.search_id == search_id, Result.source_name == "Bluesky")
                .all()
            )
            assert len(rows) == 3

    @respx.mock
    def test_bluesky_failure_degrades_to_partial(
        self, client, guardian_key, reddit_creds, bluesky_enabled
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()
        mock_reddit_success()
        mock_bluesky_timeout()

        search_id = client.post("/api/v1/searches", json={"query": "ai"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "partial"
        bs = next(s for s in body["sources"] if s["name"] == "Bluesky")
        assert bs["status"] == "timeout"


class TestDisabledByDefaultPipeline:
    @respx.mock
    def test_disabled_bluesky_excluded_from_status_math(
        self, client, guardian_key, reddit_creds
    ):
        """M22.13: with Bluesky disabled, a healthy search completes and a
        neutral disabled event is recorded — with no Bluesky network call
        (unmocked under respx, so any adapter invocation would fail the test)."""
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        mock_arxiv_empty()
        mock_github_empty()
        mock_reddit_success()
        # Deliberately NO bluesky route mocked: the source must not fire.

        search_id = client.post("/api/v1/searches", json={"query": "pytorch"}).json()["search_id"]
        body = client.get(f"/api/v1/searches/{search_id}").json()
        assert body["status"] == "completed"
        bs = next(s for s in body["sources"] if s["name"] == "Bluesky")
        assert bs["status"] == "disabled"
        assert bs["result_count"] is None


class TestDedupCanonicalization:
    def test_uri_produces_stable_canonical_url(self):
        from app.sources.bluesky import BlueskyAdapter

        # Deterministic: same handle+rkey -> same canonical web URL.
        url1 = BlueskyAdapter._canonical_url(
            "at://did:plc:abc/app.bsky.feed.post/3mtumohmxpf2j", "user.bsky.social"
        )
        url2 = BlueskyAdapter._canonical_url(
            "at://did:plc:abc/app.bsky.feed.post/3mtumohmxpf2j", "user.bsky.social"
        )
        assert url1 == url2 == "https://bsky.app/profile/user.bsky.social/post/3mtumohmxpf2j"

    def test_distinct_rkeys_produce_distinct_urls(self):
        from app.sources.bluesky import BlueskyAdapter

        a = BlueskyAdapter._canonical_url(
            "at://did:plc:abc/app.bsky.feed.post/aaaaaaaaaaaaa", "u.bsky.social"
        )
        b = BlueskyAdapter._canonical_url(
            "at://did:plc:abc/app.bsky.feed.post/bbbbbbbbbbbbb", "u.bsky.social"
        )
        assert a != b
