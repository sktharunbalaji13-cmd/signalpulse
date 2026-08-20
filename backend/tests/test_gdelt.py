import asyncio
import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx
from app.core.config import settings
from app.sources.base import SearchParams, SourceError, SourceResult
from app.sources.gdelt import GDELTAdapter

FIXTURES = Path(__file__).parent / "fixtures"

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def run_search(
    adapter: GDELTAdapter, query: str, params: SearchParams | None = None
) -> list[SourceResult]:
    return asyncio.run(adapter.search(query, params))


@pytest.fixture(autouse=True)
def gdelt_url(monkeypatch, clean_secrets):
    monkeypatch.setattr(settings, "gdelt_api_url", GDELT_API_URL)


@respx.mock
def test_gdelt_successful_search_returns_normalized_results():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "artificial intelligence")

    assert len(results) == 2
    first = results[0]
    assert first.source_type == "news"
    assert first.source_name == "GDELT"
    assert first.title == "AI adoption accelerates in hospitals worldwide"
    assert first.url == "https://example-news.com/2026/08/18/ai-in-healthcare"
    assert first.description is None
    assert first.author is None
    assert first.language == "eng"
    assert first.published_at is None


@respx.mock
def test_gdelt_empty_results():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_empty.json"))
    )

    results = run_search(GDELTAdapter(), "no such topic zzz")

    assert results == []


@respx.mock
def test_gdelt_skips_whitespace_titles():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "anything")

    assert {r.title for r in results} == {
        "AI adoption accelerates in hospitals worldwide",
        "New AI model predicts extreme weather a week ahead",
    }


@respx.mock
def test_gdelt_canonical_url_strips_query_and_fragment():
    payload = {
        "articles": [
            {
                "url": "https://tech-daily.example/articles/ai-weather?utm_source=gdelt&page=2#frag",
                "title": "Weather story",
                "seendate": "20260818121500Z",
                "language": "eng",
            }
        ]
    }
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GDELTAdapter(), "weather")

    assert results[0].url == "https://tech-daily.example/articles/ai-weather"


@respx.mock
def test_gdelt_drops_invalid_urls():
    payload = {
        "articles": [
            {
                "url": "not-a-url",
                "title": "Bad url",
                "seendate": "20260818121500Z",
            },
            {
                "url": "",
                "title": "Empty url",
                "seendate": "20260818121500Z",
            },
            {
                "url": "ftp://files.example/x",
                "title": "FTP url",
                "seendate": "20260818121500Z",
            },
        ]
    }
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GDELTAdapter(), "anything")

    assert results == []


@respx.mock
def test_gdelt_keeps_http_scheme_url():
    payload = {
        "articles": [
            {
                "url": "http://legacy.example/story?page=2",
                "title": "Legacy http",
                "seendate": "20260818121500Z",
            }
        ]
    }
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GDELTAdapter(), "anything")

    assert results[0].url == "http://legacy.example/story"


@respx.mock
def test_gdelt_description_always_none():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "anything")

    assert all(r.description is None for r in results)


@respx.mock
def test_gdelt_author_always_none():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "anything")

    assert all(r.author is None for r in results)


@respx.mock
def test_gdelt_published_at_never_derived_from_seendate():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "anything")

    assert all(r.published_at is None for r in results)
    assert all("seendate" in r.raw for r in results)


@respx.mock
def test_gdelt_retrieved_at_is_aware_utc():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "anything")

    for result in results:
        assert result.retrieved_at is not None
        assert result.retrieved_at.tzinfo is not None
        assert result.retrieved_at.utcoffset() == UTC.utcoffset(None)


@respx.mock
def test_gdelt_language_missing_becomes_none():
    payload = {
        "articles": [
            {
                "url": "https://news.example/story",
                "title": "No language",
                "seendate": "20260818121500Z",
                "language": "",
            }
        ]
    }
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GDELTAdapter(), "anything")

    assert results[0].language is None


@respx.mock
def test_gdelt_raw_preserves_seendate_and_sourcecountry():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )

    results = run_search(GDELTAdapter(), "anything")

    first = results[0]
    assert first.raw["seendate"] == "20260818143000Z"
    assert first.raw["domain"] == "example-news.com"
    assert first.raw["sourcecountry"] == "US"


@respx.mock
def test_gdelt_timeout_raises_timeout_error():
    respx.get(GDELT_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", GDELT_API_URL))
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(GDELTAdapter(), "anything")

    assert exc_info.value.kind == "timeout"
    assert "timed out" in str(exc_info.value)


@respx.mock
def test_gdelt_rate_limited_raises_rate_limited():
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(429, text="please slow down"))

    with pytest.raises(SourceError) as exc_info:
        run_search(GDELTAdapter(), "anything")

    assert exc_info.value.kind == "rate_limited"


@respx.mock
def test_gdelt_http_error_raises_failed():
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(SourceError) as exc_info:
        run_search(GDELTAdapter(), "anything")

    assert exc_info.value.kind == "failed"
    assert "500" in str(exc_info.value)


@respx.mock
def test_gdelt_malformed_json_raises_failed():
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(SourceError) as exc_info:
        run_search(GDELTAdapter(), "anything")

    assert exc_info.value.kind == "failed"


@respx.mock
def test_gdelt_missing_articles_key_raises_failed():
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json={"error": "invalid query"})
    )

    with pytest.raises(SourceError, match="missing articles"):
        run_search(GDELTAdapter(), "anything")


@respx.mock
def test_gdelt_articles_not_a_list_raises_failed():
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, json={"articles": {}}))

    with pytest.raises(SourceError, match="missing articles"):
        run_search(GDELTAdapter(), "anything")


@respx.mock
def test_gdelt_non_dict_articles_are_skipped():
    payload = {"articles": [{"title": "ok", "url": "https://ok.example/1"}, None, "text", 42]}
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GDELTAdapter(), "anything")

    assert len(results) == 1


@respx.mock
def test_gdelt_request_sends_expected_params():
    route = respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_empty.json"))
    )

    run_search(GDELTAdapter(), "climate change", params=SearchParams(limit=5, window_hours=48))

    request = route.calls.last.request
    assert request.url.params["query"] == "climate change"
    assert request.url.params["mode"] == "ArtList"
    assert request.url.params["format"] == "json"
    assert request.url.params["maxrecords"] == "5"
    assert request.url.params["timespan"] == "48h"


@respx.mock
def test_gdelt_default_timespan_is_one_day():
    route = respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_empty.json"))
    )

    run_search(GDELTAdapter(), "anything")

    assert route.calls.last.request.url.params["timespan"] == "1d"


@respx.mock
def test_gdelt_timespan_floors_to_one_hour():
    route = respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_empty.json"))
    )

    run_search(GDELTAdapter(), "anything", params=SearchParams(window_hours=0))

    assert route.calls.last.request.url.params["timespan"] == "1h"


@respx.mock
def test_gdelt_default_maxrecords_from_settings():
    route = respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_empty.json"))
    )

    run_search(GDELTAdapter(), "anything")

    assert route.calls.last.request.url.params["maxrecords"] == str(settings.gdelt_max_results)