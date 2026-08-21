"""Regression tests for M4 production hardening (design M4).

Covers the in-process per-IP rate limit + in-flight cap (429), DB readiness on
/health (503 when the DB is down), and request-logging observability.
"""

import logging
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.db.models import Search
from app.sources.registry import registry
from tests.test_source_timeout import FakeAdapter


@pytest.fixture(autouse=True)
def fast_registry(monkeypatch):
    """Route POST /searches' background job to a fast fake source (no network)."""
    monkeypatch.setattr(
        registry,
        "_adapters",
        {"wikipedia": FakeAdapter("Wikipedia", "reference", count=2)},
    )


def test_rate_limit_429_when_bucket_exceeded(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_requests", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60.0)
    from app.services.rate_limit import reset_limiter

    reset_limiter()
    assert client.post("/api/v1/searches", json={"query": "ai"}).status_code == 202
    assert client.post("/api/v1/searches", json={"query": "ai"}).status_code == 202
    third = client.post("/api/v1/searches", json={"query": "ai"})
    assert third.status_code == 429
    assert "slow down" in third.json()["detail"].lower()


def test_in_flight_cap_returns_429(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "max_in_flight_searches", 1)
    from app.services.rate_limit import reset_limiter

    reset_limiter()
    with session_factory() as session:
        session.add(
            Search(
                query="x",
                normalized_query="x",
                status="running",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    response = client.post("/api/v1/searches", json={"query": "ai"})
    assert response.status_code == 429
    assert "in progress" in response.json()["detail"].lower()


def test_health_reports_ok_when_db_reachable(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_returns_503_when_db_down(client, monkeypatch):
    class _DownEngine:
        def connect(self):
            raise RuntimeError("db unreachable")

    import app.api.routes.health as health_mod

    monkeypatch.setattr(health_mod, "engine", _DownEngine())
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["detail"]["db"] == "down"


def test_request_logging_middleware_emits_request_event(client, caplog):
    with caplog.at_level(logging.INFO, logger="signalpulse"):
        client.get("/api/v1/health")
    assert any("request" in record.getMessage() for record in caplog.records)
