import asyncio
import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import settings
from app.sources.base import SourceError, SourceResult
from app.sources.reddit import DESCRIPTION_LIMIT, REDDIT_BASE, RedditAdapter

FIXTURES = Path(__file__).parent / "fixtures"

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_SEARCH_URL = "https://oauth.reddit.com/search"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def run_search(adapter: RedditAdapter, query: str) -> list[SourceResult]:
    return asyncio.run(adapter.search(query))


@pytest.fixture(autouse=True)
def reddit_creds(monkeypatch, clean_secrets):
    monkeypatch.setattr(settings, "reddit_client_id", "test-client-id")
    monkeypatch.setattr(settings, "reddit_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "reddit_token_url", REDDIT_TOKEN_URL)
    monkeypatch.setattr(settings, "reddit_api_base", "https://oauth.reddit.com")


def mock_token_success() -> httpx.Response:
    return httpx.Response(200, json=load_fixture("reddit_token_success.json"))


@respx.mock
def test_reddit_successful_authentication():
    token_route = respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_empty.json"))
    )

    run_search(RedditAdapter(), "machine learning")

    assert token_route.called
    request = token_route.calls.last.request
    assert request.headers["authorization"].startswith("Basic ")
    assert request.headers["user-agent"] == settings.reddit_user_agent
    assert "grant_type=client_credentials" in str(request.content)


@respx.mock
def test_reddit_token_cached_across_searches():
    token_route = respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    search_route = respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_empty.json"))
    )

    adapter = RedditAdapter()
    run_search(adapter, "first")
    run_search(adapter, "second")

    assert token_route.call_count == 1
    assert search_route.call_count == 2
    bearer = search_route.calls.last.request.headers["authorization"]
    assert bearer == f"Bearer {load_fixture('reddit_token_success.json')['access_token']}"


@respx.mock
def test_reddit_success_normalizes_results():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_success.json"))
    )

    results = run_search(RedditAdapter(), "transformers")

    assert len(results) == 2
    first = results[0]
    assert isinstance(first, SourceResult)
    assert first.source_type == "social"
    assert first.source_name == "Reddit"
    assert first.title == "Why transformers changed machine learning"
    assert first.description == (
        "A long discussion about the attention mechanism, why it works, and "
        "what it means for the field. This text is short enough to fit the "
        "canonical description limit."
    )
    assert (
        first.url
        == f"{REDDIT_BASE}/r/artificial/comments/1abcd/why_transformers_changed_machine_learning/"
    )
    assert first.author == "ml_enthusiast"
    assert first.language is None


@respx.mock
def test_reddit_empty_results():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_empty.json"))
    )

    results = run_search(RedditAdapter(), "no such topic zzz")

    assert results == []


@respx.mock
def test_reddit_title_normalization_skips_posts_without_title():
    payload = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "1",
                        "subreddit": "x",
                        "permalink": "/r/x/comments/1/",
                    },
                },
                {
                    "kind": "t3",
                    "data": {
                        "id": "2",
                        "subreddit": "x",
                        "title": "  ",
                        "permalink": "/r/x/comments/2/",
                    },
                },
                {
                    "kind": "t3",
                    "data": {
                        "id": "3",
                        "subreddit": "x",
                        "title": "Valid title",
                        "permalink": "/r/x/comments/3/",
                    },
                },
            ]
        },
    }
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(RedditAdapter(), "anything")

    assert len(results) == 1
    assert results[0].title == "Valid title"


@respx.mock
def test_reddit_description_truncated_and_empty_selftext_is_none():
    long_text = "word " * (DESCRIPTION_LIMIT + 50)
    payload = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "1",
                        "subreddit": "x",
                        "title": "Long",
                        "selftext": long_text,
                    },
                },
                {
                    "kind": "t3",
                    "data": {"id": "2", "subreddit": "x", "title": "Empty", "selftext": ""},
                },
                {
                    "kind": "t3",
                    "data": {"id": "3", "subreddit": "x", "title": "No selftext key"},
                },
            ]
        },
    }
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(RedditAdapter(), "anything")

    by_title = {r.title: r for r in results}
    assert len(by_title["Long"].description) == DESCRIPTION_LIMIT
    assert by_title["Empty"].description is None
    assert by_title["No selftext key"].description is None


@respx.mock
def test_reddit_canonical_url_prefers_permalink_over_external_link():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_success.json"))
    )

    results = run_search(RedditAdapter(), "anything")

    second = results[1]
    assert second.title == "Self-supervised learning explained simply"
    assert second.url == (
        f"{REDDIT_BASE}/r/MachineLearning/comments/2wxyz/"
        "self_supervised_learning_explained_simply/"
    )
    assert "example.com" not in second.url


@respx.mock
def test_reddit_canonical_url_fallback_construction():
    payload = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "9zzzz",
                        "subreddit": "askscience",
                        "title": "No permalink",
                        "url": "https://example.com/outbound",
                    },
                },
                {
                    "kind": "t3",
                    "data": {
                        "id": "8yyyy",
                        "subreddit": "askscience",
                        "title": "Already canonical url",
                        "url": (
                            f"{REDDIT_BASE}/r/askscience/comments/8yyyy/"
                        ),
                    },
                },
                {
                    "kind": "t3",
                    "data": {
                        "id": "7xxxx",
                        "title": "No subreddit and no permalink",
                        "url": "https://example.com/other",
                    },
                },
            ]
        },
    }
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(RedditAdapter(), "anything")

    by_title = {r.title: r for r in results}
    expected = {
        "No permalink": f"{REDDIT_BASE}/r/askscience/comments/9zzzz/",
        "Already canonical url": f"{REDDIT_BASE}/r/askscience/comments/8yyyy/",
    }
    assert {t: r.url for t, r in by_title.items()} == expected
    assert "No subreddit and no permalink" not in by_title


@respx.mock
def test_reddit_author_deleted_and_missing():
    payload = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "1",
                        "subreddit": "x",
                        "title": "Deleted author",
                        "author": "[deleted]",
                    },
                },
                {
                    "kind": "t3",
                    "data": {"id": "2", "subreddit": "x", "title": "No author key"},
                },
                {
                    "kind": "t3",
                    "data": {
                        "id": "3",
                        "subreddit": "x",
                        "title": "Real author",
                        "author": "user_42",
                    },
                },
            ]
        },
    }
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(RedditAdapter(), "anything")

    by_title = {r.title: r for r in results}
    assert by_title["Deleted author"].author is None
    assert by_title["No author key"].author is None
    assert by_title["Real author"].author == "user_42"


@respx.mock
def test_reddit_published_at_from_created_utc():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_success.json"))
    )

    results = run_search(RedditAdapter(), "anything")

    published = results[0].published_at
    assert published is not None
    assert published.tzinfo == UTC
    assert published.year == 2024


@respx.mock
def test_reddit_retrieved_at_populated_utc():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_success.json"))
    )

    results = run_search(RedditAdapter(), "anything")

    for result in results:
        assert result.retrieved_at is not None
        assert result.retrieved_at.tzinfo == UTC


@respx.mock
def test_reddit_language_is_none_not_fabricated():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_success.json"))
    )

    results = run_search(RedditAdapter(), "anything")

    assert all(result.language is None for result in results)


@respx.mock
def test_reddit_raw_payload_preserved():
    fixture = load_fixture("reddit_search_success.json")
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json=fixture))

    results = run_search(RedditAdapter(), "anything")

    raw = results[0].raw
    assert raw["id"] == "1abcd"
    assert raw["score"] == 1234
    assert raw["num_comments"] == 42
    assert raw["title"] == "Why transformers changed machine learning"


@respx.mock
def test_reddit_raw_excludes_credential_shaped_keys():
    payload = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "1",
                        "subreddit": "x",
                        "title": "Sensitive",
                        "access_token": "should-never-escape",
                        "refresh_token": "should-never-escape",
                        "client_secret": "should-never-escape",
                        "authorization": "should-never-escape",
                        "nested": {"api_key": "should-never-escape", "safe_field": "kept"},
                    },
                }
            ]
        },
    }
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

    results = run_search(RedditAdapter(), "anything")

    raw = results[0].raw
    assert "access_token" not in raw
    assert "refresh_token" not in raw
    assert "client_secret" not in raw
    assert "authorization" not in raw
    assert raw["nested"]["safe_field"] == "kept"
    assert "api_key" not in raw["nested"]
    assert "should-never-escape" not in json.dumps(raw)


@respx.mock
def test_reddit_timeout_raises_source_error():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", REDDIT_SEARCH_URL)
        )
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "timeout"


@respx.mock
def test_reddit_http_401_raises_source_error():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(401, text="unauthorized"))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"
    assert "authentication" in str(exc_info.value)


@respx.mock
def test_reddit_http_403_raises_source_error():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(403, text="forbidden"))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"


@respx.mock
def test_reddit_http_429_rate_limited():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(429, text="rate limited"))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "rate_limited"


@respx.mock
def test_reddit_malformed_auth_response():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"


@respx.mock
def test_reddit_token_response_missing_access_token():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=httpx.Response(200, json={"foo": "bar"}))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"
    assert "token" in str(exc_info.value)


@respx.mock
def test_reddit_malformed_search_response():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"


@respx.mock
def test_reddit_response_missing_children():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(return_value=httpx.Response(200, json={"data": {}}))

    with pytest.raises(SourceError, match="data.children"):
        run_search(RedditAdapter(), "anything")


@respx.mock
def test_reddit_network_failure():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())
    respx.get(REDDIT_SEARCH_URL).mock(
        side_effect=httpx.ConnectError(
            "connection refused", request=httpx.Request("GET", REDDIT_SEARCH_URL)
        )
    )

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"


@respx.mock
def test_reddit_missing_credentials_raises_before_request(monkeypatch):
    monkeypatch.setattr(settings, "reddit_client_id", "")
    monkeypatch.setattr(settings, "reddit_client_secret", "")
    token_route = respx.post(REDDIT_TOKEN_URL).mock(return_value=mock_token_success())

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"
    assert "credentials" in str(exc_info.value)
    assert not token_route.called


@respx.mock
def test_reddit_token_401_authentication_failure():
    respx.post(REDDIT_TOKEN_URL).mock(return_value=httpx.Response(401, text="unauthorized"))

    with pytest.raises(SourceError) as exc_info:
        run_search(RedditAdapter(), "anything")

    assert exc_info.value.kind == "failed"
    assert "authentication failed" in str(exc_info.value)