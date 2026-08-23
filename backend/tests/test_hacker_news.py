"""M17.5.1 Hacker News adapter tests (ADR 0014).

All HTTP is mocked via respx; the suite never contacts hn.algolia.com.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import settings
from app.sources.base import SearchParams, SourceError
from app.sources.hacker_news import HACKER_NEWS_DISCUSSION_URL, HackerNewsAdapter
from tests.helpers import HACKER_NEWS_API_URL, load_fixture

FIXTURES = Path(__file__).parent / "fixtures"


def make_client():
    return httpx.AsyncClient()


def run(coro):
    return asyncio.run(coro)


def adapter_response(payload):
    return httpx.Response(200, json=payload)


def link_hit(**overrides):
    hit = {
        "objectID": "48387270",
        "title": "Artificial intelligence is not conscious",
        "url": "https://example.com/article",
        "author": "lordleft",
        "points": 800,
        "num_comments": 1382,
        "created_at": "2026-06-03T17:51:37Z",
        "created_at_i": 1780509097,
        "story_text": None,
        "_tags": ["story"],
    }
    hit.update(overrides)
    return hit


def search(adapter, query="ai", params=None):
    return run(adapter.search(query, params))


# --- Success mapping ----------------------------------------------------------


@respx.mock
def test_successful_link_story_mapping():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit()], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert len(results) == 1
    result = results[0]
    assert result.source_type == "news"
    assert result.source_name == "Hacker News"
    assert result.title == "Artificial intelligence is not conscious"
    assert result.url == "https://example.com/article"
    assert result.author == "lordleft"
    assert result.published_at == datetime.fromtimestamp(1780509097, tz=UTC)
    assert result.retrieved_at is not None
    assert result.description is None


@respx.mock
def test_title_missing_is_skipped():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(title=None), link_hit(objectID="2", title="Kept")]}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert [r.title for r in results] == ["Kept"]


@respx.mock
def test_blank_title_is_skipped():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(title="   ")], "nbHits": 0}
    ))
    assert search(HackerNewsAdapter(make_client())) == []


@respx.mock
def test_external_url_mapping_preserved():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(url="https://www.reuters.com/tech/story")], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert results[0].url == "https://www.reuters.com/tech/story"


@respx.mock
def test_null_url_falls_back_to_discussion_link():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(url=None, objectID="41967900")], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert results[0].url == HACKER_NEWS_DISCUSSION_URL.format(item_id="41967900")
    assert results[0].url.startswith("https://news.ycombinator.com/item?id=")


@respx.mock
def test_author_present_and_missing_are_null_safe():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {
            "hits": [
                link_hit(author="pg"),
                link_hit(objectID="2", author=None),
            ],
            "nbHits": 2,
        }
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert [r.author for r in results] == ["pg", None]


def test_published_at_handles_invalid_timestamp():
    assert HackerNewsAdapter._published_at(None) is None
    assert HackerNewsAdapter._published_at("bogus") is None
    assert HackerNewsAdapter._published_at(10**20) is None  # overflow -> None


@respx.mock
def test_created_at_conversion_utc():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(created_at_i=0)], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert results[0].published_at == datetime(1970, 1, 1, tzinfo=UTC)


@respx.mock
def test_story_text_truncated_to_500():
    long_text = "x" * 900
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(story_text=long_text)], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert len(results[0].description) == 500
    assert set(results[0].description) == {"x"}


@respx.mock
def test_empty_story_text_maps_to_none():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit(story_text="   ")], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert results[0].description is None


@respx.mock
def test_language_remains_none():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [link_hit()], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert results[0].language is None


@respx.mock
def test_raw_provenance_preserved_verbatim():
    hit = link_hit()
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": [hit], "nbHits": 1}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert results[0].raw == hit
    assert results[0].raw["points"] == 800
    assert results[0].raw["objectID"] == "48387270"


# --- Params -------------------------------------------------------------------


@respx.mock
def test_limit_propagates_as_hits_per_page():
    route = respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response({"hits": []}))
    search(HackerNewsAdapter(make_client()), params=SearchParams(limit=3))
    request = route.calls.last.request
    assert "hitsPerPage=3" in str(request.url)


@respx.mock
def test_window_hours_propagates_as_numeric_filter():
    route = respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response({"hits": []}))
    search(HackerNewsAdapter(make_client()), params=SearchParams(limit=5, window_hours=24))
    url_params = str(route.calls.last.request.url)
    assert "created_at_i" in url_params
    # The cutoff must be ~24h ago (within a small tolerance).
    import re

    match = re.search(r"created_at_i%3E(\d+)|created_at_i>(\d+)", url_params)
    assert match is not None
    since = int(match.group(1) or match.group(2))
    expected = int(datetime.now(UTC).timestamp()) - 24 * 3600
    assert abs(since - expected) <= 60


@respx.mock
def test_no_window_omits_numeric_filter():
    route = respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response({"hits": []}))
    search(HackerNewsAdapter(make_client()), params=SearchParams(limit=5))
    assert "numericFilters" not in str(route.calls.last.request.url)


@respx.mock
def test_tags_story_always_set():
    route = respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response({"hits": []}))
    search(HackerNewsAdapter(make_client()))
    assert "tags=story" in str(route.calls.last.request.url)


# --- Errors -------------------------------------------------------------------


@respx.mock
def test_http_429_classified_rate_limited():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(SourceError) as excinfo:
        search(HackerNewsAdapter(make_client()))
    assert excinfo.value.kind == "rate_limited"


@pytest.mark.parametrize("status", [500, 502, 503])
@respx.mock
def test_http_5xx_classified_failed(status):
    respx.get(HACKER_NEWS_API_URL).mock(return_value=httpx.Response(status, text="boom"))
    with pytest.raises(SourceError) as excinfo:
        search(HackerNewsAdapter(make_client()))
    assert excinfo.value.kind == "failed"


@respx.mock
def test_timeout_classified_timeout():
    respx.get(HACKER_NEWS_API_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", HACKER_NEWS_API_URL)
        )
    )
    with pytest.raises(SourceError) as excinfo:
        search(HackerNewsAdapter(make_client()))
    assert excinfo.value.kind == "timeout"


@respx.mock
def test_network_failure_classified_failed():
    respx.get(HACKER_NEWS_API_URL).mock(
        side_effect=httpx.ConnectError("refused", request=httpx.Request("GET", HACKER_NEWS_API_URL))
    )
    with pytest.raises(SourceError) as excinfo:
        search(HackerNewsAdapter(make_client()))
    assert excinfo.value.kind == "failed"


@respx.mock
def test_malformed_json_classified_failed():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(SourceError):
        search(HackerNewsAdapter(make_client()))


@respx.mock
def test_non_object_json_classified_failed():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=httpx.Response(200, json=[1, 2]))
    with pytest.raises(SourceError):
        search(HackerNewsAdapter(make_client()))


@respx.mock
def test_missing_hits_key_classified_failed():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=httpx.Response(200, json={"nbHits": 5}))
    with pytest.raises(SourceError):
        search(HackerNewsAdapter(make_client()))


@respx.mock
def test_malformed_hits_skipped_not_fatal():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response(
        {"hits": ["not-a-dict", link_hit(objectID="9", title="Valid")], "nbHits": 2}
    ))
    results = search(HackerNewsAdapter(make_client()))
    assert [r.title for r in results] == ["Valid"]


@respx.mock
def test_zero_results_is_successful_empty_list():
    respx.get(HACKER_NEWS_API_URL).mock(return_value=adapter_response({"hits": [], "nbHits": 0}))
    results = search(HackerNewsAdapter(make_client()))
    assert results == []


# --- Fixture-driven success (matches pipeline mock payload) --------------------


@respx.mock
def test_success_fixture_payload_maps_both_shapes():
    payload = load_fixture("hacker_news_search_success.json")
    respx.get(HACKER_NEWS_API_URL).mock(return_value=httpx.Response(200, json=payload))
    results = search(HackerNewsAdapter(make_client()))
    assert len(results) == 2
    by_title = {r.title: r for r in results}
    linked = by_title["Artificial intelligence is not conscious"]
    assert linked.url.startswith("https://www.theatlantic.com/")
    text_post = by_title["Show HN: SignalPulse intelligence workspace"]
    assert text_post.url == HACKER_NEWS_DISCUSSION_URL.format(item_id="41967900")
    assert len(text_post.description) == 500
    assert text_post.author is None


# --- Config defaults ------------------------------------------------------------


def test_settings_defaults():
    assert settings.hacker_news_api_url == HACKER_NEWS_API_URL
    assert settings.hacker_news_timeout_seconds == 5.0
    assert settings.hacker_news_max_results == 10
    assert "SignalPulse" in settings.hacker_news_user_agent