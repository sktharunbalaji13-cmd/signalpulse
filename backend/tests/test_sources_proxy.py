"""M19.1 sources-proxy hardening tests.

The proxy now shares the per-IP sliding-window budget with search creation
(same limiter instance — one mechanism, one policy, no second implementation).
"""

import pytest
import respx

from app.core.config import settings
from app.services.rate_limit import limiter, reset_limiter
from tests.helpers import mock_wikipedia_success

PROXY_URL = "/api/v1/sources/wikipedia/search?q=test"


@pytest.fixture(autouse=True)
def _reset():
    reset_limiter()
    yield
    reset_limiter()


@respx.mock
def test_proxy_allowed_request_works(client):
    mock_wikipedia_success()
    response = client.get(PROXY_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "Wikipedia"
    assert isinstance(body["results"], list)


@respx.mock
def test_proxy_unknown_source_404(client):
    assert client.get("/api/v1/sources/nope/search?q=x").status_code == 404


@respx.mock
def test_proxy_missing_query_422(client):
    assert client.get("/api/v1/sources/wikipedia/search").status_code == 422


@respx.mock
def test_proxy_excessive_requests_rejected(client, monkeypatch):
    mock_wikipedia_success()
    monkeypatch.setattr(settings, "rate_limit_requests", 3)
    reset_limiter()
    statuses = [client.get(PROXY_URL).status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3:] == [429, 429]


@respx.mock
def test_proxy_and_search_creation_share_one_budget_per_ip(client, monkeypatch):
    """One mechanism: proxy calls consume the same per-IP bucket as POST /searches."""
    from app.core.config import settings as cfg

    mock_wikipedia_success()
    monkeypatch.setattr(cfg, "rate_limit_requests", 2)
    reset_limiter()
    assert client.get(PROXY_URL).status_code == 200
    assert client.get(PROXY_URL).status_code == 200
    # Bucket exhausted -> both proxy and search creation are rejected.
    assert client.get(PROXY_URL).status_code == 429
    assert client.post("/api/v1/searches", json={"query": "x"}).status_code == 429


def test_limiter_is_per_ip_isolated():
    reset_limiter()
    router = limiter()
    router.max_requests = 1
    assert router.allow("ip-a")
    assert not router.allow("ip-a")
    assert router.allow("ip-b")  # other IPs unaffected


@pytest.fixture()
def fast_registry(monkeypatch):
    """No-network pipeline for the one test that lets a search run."""
    from app.sources.registry import registry
    from tests.test_source_timeout import FakeAdapter

    monkeypatch.setattr(
        registry,
        "_adapters",
        {"wikipedia": FakeAdapter("Wikipedia", "reference", count=0)},
    )


@respx.mock
def test_search_creation_rate_limiting_unchanged(client, monkeypatch, fast_registry):
    """Existing POST /searches behavior is untouched by the proxy change."""
    monkeypatch.setattr(settings, "rate_limit_requests", 1)
    reset_limiter()
    assert client.post("/api/v1/searches", json={"query": "a"}).status_code == 202
    assert client.post("/api/v1/searches", json={"query": "a"}).status_code == 429