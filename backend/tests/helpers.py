import json
from pathlib import Path

import httpx
import respx

from app.sources.wikipedia import WIKIPEDIA_API_URL

FIXTURES = Path(__file__).parent / "fixtures"

GUARDIAN_API_URL = "https://content.guardianapis.com/search"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_SEARCH_URL = "https://oauth.reddit.com/search"
GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HACKER_NEWS_API_URL = "https://hn.algolia.com/api/v1/search"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
STACKOVERFLOW_SEARCH_URL = "https://api.stackexchange.com/2.3/search/advanced"
BLUESKY_SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


def load_fixture_text(name: str) -> str:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return f.read()


def mock_wikipedia_success() -> None:
    respx.get(WIKIPEDIA_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("wikipedia_search_success.json"))
    )


def mock_wikipedia_timeout() -> None:
    respx.get(WIKIPEDIA_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", WIKIPEDIA_API_URL))
    )


def mock_wikipedia_rate_limited() -> None:
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(429, text="rate limited"))


def mock_wikipedia_malformed() -> None:
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(200, text="<html>oops</html>"))


def mock_guardian_success() -> None:
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("guardian_search_success.json"))
    )


def mock_guardian_empty() -> None:
    respx.get(GUARDIAN_API_URL).mock(
        return_value=httpx.Response(200, json={"response": {"status": "ok", "results": []}})
    )


def mock_guardian_api_key_error() -> None:
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


def mock_guardian_timeout() -> None:
    respx.get(GUARDIAN_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", GUARDIAN_API_URL))
    )


def mock_reddit_success() -> None:
    respx.post(REDDIT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_token_success.json"))
    )
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_success.json"))
    )


def mock_reddit_empty() -> None:
    respx.post(REDDIT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_token_success.json"))
    )
    respx.get(REDDIT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_search_empty.json"))
    )


def mock_reddit_timeout() -> None:
    respx.post(REDDIT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_token_success.json"))
    )
    respx.get(REDDIT_SEARCH_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", REDDIT_SEARCH_URL)
        )
    )


def mock_reddit_auth_failure() -> None:
    respx.post(REDDIT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("reddit_token_failure.json"))
    )


def mock_gdelt_success() -> None:
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_success.json"))
    )


def mock_gdelt_empty() -> None:
    respx.get(GDELT_API_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdelt_search_empty.json"))
    )


def mock_gdelt_timeout() -> None:
    respx.get(GDELT_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", GDELT_API_URL))
    )


def mock_gdelt_rate_limited() -> None:
    respx.get(GDELT_API_URL).mock(return_value=httpx.Response(429, text="rate limited"))


def mock_hacker_news_success() -> None:
    respx.get(HACKER_NEWS_API_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("hacker_news_search_success.json")
        )
    )


def mock_hacker_news_empty() -> None:
    respx.get(HACKER_NEWS_API_URL).mock(
        return_value=httpx.Response(200, json={"hits": [], "nbHits": 0})
    )


def mock_hacker_news_timeout() -> None:
    respx.get(HACKER_NEWS_API_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", HACKER_NEWS_API_URL)
        )
    )


ARXIV_EMPTY_FEED = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<title>ArXiv Query</title>"
    '<opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0'
    "</opensearch:totalResults>"
    "</feed>"
)


def mock_arxiv_success() -> None:
    respx.get(ARXIV_API_URL).mock(
        return_value=httpx.Response(200, text=load_fixture_text("arxiv_search_success.xml"))
    )


def mock_arxiv_empty() -> None:
    respx.get(ARXIV_API_URL).mock(return_value=httpx.Response(200, text=ARXIV_EMPTY_FEED))


def mock_arxiv_timeout() -> None:
    respx.get(ARXIV_API_URL).mock(
        side_effect=httpx.ConnectTimeout("timeout", request=httpx.Request("GET", ARXIV_API_URL))
    )


GITHUB_EMPTY_PAYLOAD = {"total_count": 0, "incomplete_results": False, "items": []}


def mock_github_success() -> None:
    respx.get(GITHUB_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("github_search_success.json"))
    )


def mock_github_empty() -> None:
    respx.get(GITHUB_SEARCH_URL).mock(return_value=httpx.Response(200, json=GITHUB_EMPTY_PAYLOAD))


def mock_github_timeout() -> None:
    respx.get(GITHUB_SEARCH_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", GITHUB_SEARCH_URL)
        )
    )


STACKOVERFLOW_EMPTY_PAYLOAD = {
    "items": [],
    "has_more": False,
    "quota_max": 10000,
    "quota_remaining": 9990,
}


def mock_stack_overflow_success() -> None:
    respx.get(STACKOVERFLOW_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("stack_overflow_search_success.json"))
    )


def mock_stack_overflow_empty() -> None:
    respx.get(STACKOVERFLOW_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=STACKOVERFLOW_EMPTY_PAYLOAD)
    )


def mock_stack_overflow_timeout() -> None:
    respx.get(STACKOVERFLOW_SEARCH_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", STACKOVERFLOW_SEARCH_URL)
        )
    )


BLUESKY_EMPTY_PAYLOAD = {"cursor": None, "posts": []}


def mock_bluesky_success() -> None:
    respx.get(BLUESKY_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("bluesky_search_success.json"))
    )


def mock_bluesky_empty() -> None:
    respx.get(BLUESKY_SEARCH_URL).mock(return_value=httpx.Response(200, json=BLUESKY_EMPTY_PAYLOAD))


def mock_bluesky_timeout() -> None:
    respx.get(BLUESKY_SEARCH_URL).mock(
        side_effect=httpx.ConnectTimeout(
            "timeout", request=httpx.Request("GET", BLUESKY_SEARCH_URL)
        )
    )