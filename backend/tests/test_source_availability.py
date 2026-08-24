"""M21.3 source availability & partial-state semantics tests (ADR 0017).

Proves the Option B model: an unconfigured source is *disabled*, not a
failure. Disabled sources are excluded from search status computation, shown
neutrally, and re-enter the enabled set the moment credentials appear.
"""


import httpx
import pytest
import respx

from app.core.config import settings
from app.db.models import SourceEvent
from app.sources.registry import registry
from tests.helpers import (
    HACKER_NEWS_API_URL,
    mock_guardian_empty,
    mock_hacker_news_empty,
    mock_hacker_news_success,
    mock_wikipedia_success,
    mock_wikipedia_timeout,
)


class UnconfiguredAdapter:
    """Duck-typed adapter that is never configured."""

    source_type = "news"
    source_name = "Unconfigured"

    def is_configured(self) -> bool:
        return False

    async def search(self, query, params=None):
        raise AssertionError("disabled source must never be invoked")


def _make_search(client, query="ai"):
    return client.post("/api/v1/searches", json={"query": query}).json()["search_id"]


def _find(events, name):
    """Find by ORM SourceEvent.source_name."""
    return next(e for e in events if e.source_name == name)


def _find_src(sources, name):
    """Find by API SourceStatus.name (dict)."""
    return next(s for s in sources if s["name"] == name)


def _sources(client, search_id):
    return client.get(f"/api/v1/searches/{search_id}").json()["sources"]


def _status(client, search_id):
    return client.get(f"/api/v1/searches/{search_id}").json()["status"]


@pytest.fixture()
def no_reddit_creds(monkeypatch, clean_secrets):
    monkeypatch.setattr(settings, "reddit_client_id", "")
    monkeypatch.setattr(settings, "reddit_client_secret", "")
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")
    return monkeypatch


@pytest.fixture()
def guardian_key(monkeypatch, clean_secrets):
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")


class TestDisabledSourceSemantics:
    @respx.mock
    def test_reddit_unconfigured_is_disabled_not_failure(
        self, client, session_factory, no_reddit_creds
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        search_id = _make_search(client)
        assert _status(client, search_id) == "completed"
        sources = _sources(client, search_id)
        reddit = _find_src(sources, "Reddit")
        assert reddit["status"] == "disabled"
        assert reddit["error_type"] == "disabled"
        assert reddit["result_count"] is None
        assert reddit["latency_ms"] is None

    @respx.mock
    def test_disabled_source_does_not_count_as_failure(
        self, client, session_factory, no_reddit_creds
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        search_id = _make_search(client)
        with session_factory() as session:
            events = session.query(SourceEvent).filter_by(search_id=search_id).all()
            assert {e.source_name for e in events} == {
                "Wikipedia",
                "The Guardian",
                "Hacker News",
                "Reddit",
            }
            reddit = next(e for e in events if e.source_name == "Reddit")
            assert reddit.status == "disabled"
            assert reddit.error_type == "disabled"

    @respx.mock
    def test_three_healthy_sources_plus_disabled_is_completed(
        self, client, no_reddit_creds
    ):
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_success()
        search_id = _make_search(client)
        assert _status(client, search_id) == "completed"
        sources = _sources(client, search_id)
        assert {s["status"] for s in sources} == {"success", "disabled"}
        assert _find_src(sources, "Reddit")["status"] == "disabled"

    @respx.mock
    def test_one_enabled_fails_plus_disabled_is_partial(
        self, client, no_reddit_creds
    ):
        mock_wikipedia_timeout()
        mock_guardian_empty()
        mock_hacker_news_empty()
        search_id = _make_search(client)
        assert _status(client, search_id) == "partial"
        sources = _sources(client, search_id)
        assert _find_src(sources, "Wikipedia")["status"] == "timeout"
        assert _find_src(sources, "Reddit")["status"] == "disabled"

    @respx.mock
    def test_all_enabled_fail_plus_disabled_is_failed(
        self, client, no_reddit_creds
    ):
        mock_wikipedia_timeout()
        respx.get("https://content.guardianapis.com/search").mock(
            return_value=httpx.Response(200, json={"response": {"status": "error"}})
        )
        mock_hacker_news_empty()
        respx.get(HACKER_NEWS_API_URL).mock(
            side_effect=httpx.ConnectTimeout(
                "timeout", request=httpx.Request("GET", HACKER_NEWS_API_URL)
            )
        )
        search_id = _make_search(client)
        assert _status(client, search_id) == "failed"
        sources = _sources(client, search_id)
        # Disabled Reddit is present but never counts toward failure.
        assert _find_src(sources, "Reddit")["status"] == "disabled"


class TestNoEnabledSources:
    def test_all_sources_disabled_rejects_search(
        self, client, session_factory, monkeypatch
    ):
        class OffAdapter:
            source_type = "news"
            source_name = "Off"

            def is_configured(self):
                return False

            async def search(self, query, params=None):
                raise AssertionError("must not be called")

        monkeypatch.setattr(registry, "_adapters", {"a": OffAdapter(), "b": OffAdapter()})
        before = client.get("/api/v1/searches?limit=100").json()["items"]
        response = client.post("/api/v1/searches", json={"query": "ai"})
        assert response.status_code == 503
        after = client.get("/api/v1/searches?limit=100").json()["items"]
        assert len(after) == len(before)  # nothing was created

    @respx.mock
    def test_disabled_adapter_never_invoked(self, client, monkeypatch, no_reddit_creds):
        captured = []

        class GuardedAdapter:
            source_type = "news"
            source_name = "Guarded"

            def is_configured(self):
                return False

            async def search(self, query, params=None):
                captured.append(query)
                return []

        from app.sources.base import BaseSourceAdapter
        from app.sources.wikipedia import WikipediaAdapter

        # Replace the whole registry: one disabled fake + one real enabled source.
        monkeypatch.setattr(
            registry,
            "_adapters",
            {
                "guarded": GuardedAdapter(),
                "wikipedia": WikipediaAdapter(),
            },
        )
        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()
        # Guardian + HN remain registered so creation is not rejected.
        from app.sources.guardian import GuardianAdapter
        from app.sources.hacker_news import HackerNewsAdapter

        monkeypatch.setattr(
            registry,
            "_adapters",
            {
                "guarded": GuardedAdapter(),
                "wikipedia": WikipediaAdapter(),
                "guardian": GuardianAdapter(),
                "hacker_news": HackerNewsAdapter(),
            },
        )
        _make_search(client)
        # The disabled adapter was never invoked; search completed via enabled trio.
        assert captured == []
        assert BaseSourceAdapter.is_configured(WikipediaAdapter()) is True


class TestCredentialTransition:
    """The design must not permanently special-case Reddit: credentials
    appearing flips Reddit from disabled back to a normal enabled source."""

    @respx.mock
    def test_reddit_disabled_then_enabled_then_four_source_completed(
        self, client, no_reddit_creds, monkeypatch
    ):
        from tests.helpers import mock_reddit_success

        mock_wikipedia_success()
        mock_guardian_empty()
        mock_hacker_news_empty()

        # Phase 1: no Reddit credentials -> disabled.
        sid1 = _make_search(client, "without reddit")
        assert _status(client, sid1) == "completed"
        assert _find_src(_sources(client, sid1), "Reddit")["status"] == "disabled"

        # Phase 2: credentials appear (e.g. Render env updated + restart).
        monkeypatch.setattr(settings, "reddit_client_id", "test-client-id")
        monkeypatch.setattr(settings, "reddit_client_secret", "test-client-secret")
        mock_reddit_success()

        # Phase 3: Reddit is enabled and participates -> four-source completed.
        sid2 = _make_search(client, "with reddit")
        assert _status(client, sid2) == "completed"
        reddit = _find_src(_sources(client, sid2), "Reddit")
        assert reddit["status"] == "success"
        assert reddit["result_count"] == 2
        results = client.get(f"/api/v1/searches/{sid2}/results?per_page=100").json()
        reddit_names = {i["source_name"] for i in results["items"]}
        assert "Reddit" in reddit_names