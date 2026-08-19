import json
from pathlib import Path

import httpx
import respx

from app.sources.wikipedia import WIKIPEDIA_API_URL

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


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