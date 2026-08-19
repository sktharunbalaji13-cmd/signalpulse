import asyncio
import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import settings
from app.sources.base import SourceError, SourceResult
from app.sources.guardian import DESCRIPTION_LIMIT, GuardianAdapter

FIXTURES = Path(__file__).parent / "fixtures"

GUARDIAN_API_URL = "https://content.guardianapis.com/search"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def run_search(adapter: GuardianAdapter, query: str) -> list[SourceResult]:
    return asyncio.run(adapter.search(query))


@pytest.fixture(autouse=True)
def guardian_key(monkeypatch):
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")
    monkeypatch.setattr(settings, "guardian_api_url", GUARDIAN_API_URL)


@respx.mock
def test_guardian_success_normalizes_results():
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("guardian_search_success.json"))
    )

    results = run_search(GuardianAdapter(), "artificial intelligence")

    assert len(results) == 2
    first = results[0]
    assert isinstance(first, SourceResult)
    assert first.source_type == "news"
    assert first.source_name == "The Guardian"
    assert first.title == "EU passes landmark AI Act"
    assert first.description.startswith("The European Union has approved sweeping rules")
    assert first.url == "https://www.theguardian.com/technology/2024/jan/15/artificial-intelligence-act-eu"
    assert first.author == "Elena Morris"
    assert first.language == "en"
    assert first.raw["id"] == "technology/2024/jan/15/artificial-intelligence-act-eu"


@respx.mock
def test_guardian_empty_result_set_returns_no_results():
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(200, json={"response": {"status": "ok", "results": []}})
    )

    results = run_search(GuardianAdapter(), "no such topic zzz")

    assert results == []


@respx.mock
def test_guardian_malformed_json_raises_source_error():
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(SourceError, match="invalid JSON"):
        run_search(GuardianAdapter(), "artificial intelligence")


@respx.mock
def test_guardian_missing_response_object_raises_source_error():
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(SourceError, match="missing the response object"):
        run_search(GuardianAdapter(), "artificial intelligence")


@respx.mock
def test_guardian_timeout_raises_source_error():
    respx.get(GUARDIAN_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", GUARDIAN_API_URL))
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(GuardianAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "timeout"


@respx.mock
def test_guardian_http_401_raises_source_error():
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(401, text="unauthorized"))

    with pytest.raises(SourceError) as exc_info:
        run_search(GuardianAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "failed"
    assert "401" in str(exc_info.value)


@respx.mock
def test_guardian_http_429_rate_limited():
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(429, text="rate limited"))

    with pytest.raises(SourceError) as exc_info:
        run_search(GuardianAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "rate_limited"


@respx.mock
def test_guardian_body_error_rate_limited():
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "status": "error",
                    "message": "RateLimitExceededError: The API rate limit has been exceeded",
                }
            },
        )
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(GuardianAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "rate_limited"


@respx.mock
def test_guardian_body_error_api_key_invalid():
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "status": "error",
                    "message": "ApiKeyInvalidError: The supplied API key is invalid",
                }
            },
        )
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(GuardianAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "failed"


@respx.mock
def test_guardian_timestamp_normalized_to_utc():
    payload = {
        "response": {
            "status": "ok",
            "results": [
                {
                    "id": "x",
                    "webTitle": "Offset story",
                    "webUrl": "https://www.theguardian.com/x",
                    "webPublicationDate": "2024-01-15T12:30:00+02:00",
                    "fields": {},
                }
            ],
        }
    }
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GuardianAdapter(), "artificial intelligence")

    published = results[0].published_at
    assert published is not None
    assert published.tzinfo == UTC
    assert published.hour == 10


@respx.mock
def test_guardian_invalid_timestamp_not_fabricated():
    payload = {
        "response": {
            "status": "ok",
            "results": [
                {
                    "id": "x",
                    "webTitle": "Bad date",
                    "webUrl": "https://www.theguardian.com/x",
                    "webPublicationDate": "not-a-date",
                    "fields": {},
                }
            ],
        }
    }
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GuardianAdapter(), "artificial intelligence")

    assert results[0].published_at is None


@respx.mock
def test_guardian_raw_payload_preserved():
    fixture = load_fixture("guardian_search_success.json")
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, json=fixture))

    results = run_search(GuardianAdapter(), "artificial intelligence")

    expected = fixture["response"]["results"][0]
    assert results[0].raw == expected
    assert results[0].raw["fields"]["byline"] == "Elena Morris"


@respx.mock
def test_guardian_description_truncated_to_canonical_limit():
    long_text = "word " * (DESCRIPTION_LIMIT + 50)
    payload = {
        "response": {
            "status": "ok",
            "results": [
                {
                    "id": "x",
                    "webTitle": "Long story",
                    "webUrl": "https://www.theguardian.com/x",
                    "webPublicationDate": "2024-01-15T10:30:00Z",
                    "fields": {"trailText": long_text},
                }
            ],
        }
    }
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GuardianAdapter(), "artificial intelligence")

    assert len(results[0].description) == DESCRIPTION_LIMIT


@respx.mock
def test_guardian_missing_fields_and_byline():
    payload = {
        "response": {
            "status": "ok",
            "results": [
                {
                    "id": "x",
                    "webTitle": "No fields",
                    "webUrl": "https://www.theguardian.com/x",
                    "webPublicationDate": "2024-01-15T10:30:00Z",
                }
            ],
        }
    }
    respx.get(GUARDIAN_API_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(GuardianAdapter(), "artificial intelligence")

    assert results[0].description is None
    assert results[0].author is None
    assert results[0].published_at is not None


@respx.mock
def test_guardian_sends_api_key_and_user_agent():
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(200, json={"response": {"status": "ok", "results": []}})
    )

    run_search(GuardianAdapter(), "artificial intelligence")

    request = respx.calls.last.request
    assert request.url.params["api-key"] == "test-key"
    assert "SignalPulse" in request.headers["user-agent"]
    assert request.url.params["page-size"] == "10"
    assert request.url.params["show-fields"] == "trailText,byline"


@respx.mock
def test_guardian_missing_api_key_raises_before_request(monkeypatch):
    monkeypatch.setattr(settings, "guardian_api_key", "")
    route = respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(200, json={"response": {"status": "ok", "results": []}})
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(GuardianAdapter(), "artificial intelligence")

    assert exc_info.value.kind == "failed"
    assert "API key" in str(exc_info.value)
    assert not route.called
