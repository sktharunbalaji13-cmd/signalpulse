import asyncio
import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx
from app.sources.base import SourceError, SourceResult
from app.sources.wikipedia import WIKIPEDIA_API_URL, WikipediaAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def run_search(adapter: WikipediaAdapter, query: str) -> list[SourceResult]:
    return asyncio.run(adapter.search(query))


@respx.mock
def test_wikipedia_success_normalizes_results():
    respx.get(WIKIPEDIA_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("wikipedia_search_success.json"))
    )

    results = run_search(WikipediaAdapter(), "artificial intelligence")

    assert len(results) == 2
    first = results[0]
    assert isinstance(first, SourceResult)
    assert first.source_type == "reference"
    assert first.source_name == "Wikipedia"
    assert first.title == "Artificial intelligence"
    assert first.description.startswith("Artificial intelligence (AI)")
    assert first.url == "https://en.wikipedia.org/wiki/Artificial_intelligence"
    assert first.language == "en"
    assert first.raw["pageid"] == 1


@respx.mock
def test_wikipedia_retrieved_at_populated_and_published_at_not_fabricated():
    respx.get(WIKIPEDIA_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("wikipedia_search_success.json"))
    )

    results = run_search(WikipediaAdapter(), "artificial intelligence")

    assert len(results) == 2
    for result in results:
        assert result.retrieved_at is not None
        assert result.retrieved_at.tzinfo is not None
        assert result.retrieved_at.tzinfo == UTC
        assert result.published_at is None


@respx.mock
def test_wikipedia_empty_response_returns_no_results():
    respx.get(WIKIPEDIA_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("wikipedia_search_empty.json"))
    )

    results = run_search(WikipediaAdapter(), "no such topic zzz")

    assert results == []


@respx.mock
def test_wikipedia_malformed_json_raises_source_error():
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(SourceError, match="invalid JSON"):
        run_search(WikipediaAdapter(), "artificial intelligence")


@respx.mock
def test_wikipedia_missing_pages_raises_source_error():
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(200, json={"batchcomplete": ""}))

    with pytest.raises(SourceError, match="query.pages"):
        run_search(WikipediaAdapter(), "artificial intelligence")


@respx.mock
def test_wikipedia_timeout_raises_source_error():
    respx.get(WIKIPEDIA_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", WIKIPEDIA_API_URL))
    )

    with pytest.raises(SourceError, match="timed out"):
        run_search(WikipediaAdapter(), "artificial intelligence")


@respx.mock
def test_wikipedia_http_error_raises_source_error():
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(429, text="rate limited"))

    with pytest.raises(SourceError) as exc_info:
        run_search(WikipediaAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "rate_limited"


@respx.mock
def test_wikipedia_title_with_special_chars_produces_normalized_url():
    payload = {
        "query": {
            "pages": {
                "3": {
                    "pageid": 3,
                    "ns": 0,
                    "title": "C++",
                    "index": 1,
                    "extract": "C++ is a high-level programming language.",
                }
            }
        }
    }
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(WikipediaAdapter(), "c++")

    assert results[0].url == "https://en.wikipedia.org/wiki/C%2B%2B"


@respx.mock
def test_wikipedia_sends_user_agent_and_maxlag():
    route = respx.get(WIKIPEDIA_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("wikipedia_search_empty.json"))
    )

    run_search(WikipediaAdapter(), "artificial intelligence")

    request = route.calls.last.request
    assert "SignalPulse" in request.headers["user-agent"]
    assert request.url.params["maxlag"] == "5"
    assert request.url.params["format"] == "json"