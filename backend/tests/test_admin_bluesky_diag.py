"""M22.12 temporary Bluesky 403 diagnostic endpoint tests (Probe B).

Proves the diagnostic is fail-closed behind admin auth, fires exactly one
outbound request matching the production adapter's shape, persists nothing,
and never leaks raw bodies or credential-like material.
"""

import inspect

import httpx
import pytest
import respx

from app.core.config import settings
from app.db import session as db_session
from app.db.models import DuplicateGroup, Result, Search, SourceEvent
from app.main import app

DIAG_PATH = "/api/v1/admin/diag/bluesky403"
KEY_HEADERS = {"X-Admin-Key": "test-admin-key"}
EDGE_403_HTML = (
    "<html><body><h1>403 Forbidden</h1>"
    "Request forbidden by administrative rules.</body></html>"
)


def _mock_edge_403():
    return respx.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts").mock(
        return_value=httpx.Response(
            403,
            headers={"content-type": "text/html; charset=utf-8"},
            text=EDGE_403_HTML,
        )
    )


def _diag_handler():
    matches = [r for r in app.routes if getattr(r, "path", "") == DIAG_PATH]
    assert len(matches) == 1, f"expected exactly one {DIAG_PATH} route"
    return matches[0].endpoint


class TestAdminAuthFailClosed:
    def test_missing_key_returns_401(self, client):
        assert client.get(DIAG_PATH).status_code == 401

    def test_wrong_key_returns_401(self, client):
        r = client.get(DIAG_PATH, headers={"X-Admin-Key": "wrong-key"})
        assert r.status_code == 401

    @pytest.mark.parametrize(
        "headers", [{}, {"X-Admin-Key": ""}, {"X-Admin-Key": "anything"}]
    )
    def test_empty_configured_key_denies_all(self, client, monkeypatch, headers):
        monkeypatch.setattr(settings, "admin_api_key", "")
        assert client.get(DIAG_PATH, headers=headers).status_code == 401


class TestSingleRequestAndShape:
    @respx.mock
    def test_exactly_one_upstream_request(self, client):
        route = _mock_edge_403()
        r = client.get(DIAG_PATH, headers=KEY_HEADERS)
        assert r.status_code == 200
        assert route.call_count == 1

    @respx.mock
    def test_request_matches_production_shape(self, client):
        route = _mock_edge_403()
        client.get(DIAG_PATH, headers=KEY_HEADERS)
        request = route.calls.last.request
        assert request.url.params["q"] == "test"
        assert request.url.params["limit"] == "1"
        assert request.headers["user-agent"] == settings.bluesky_user_agent
        assert request.headers["accept"] == "application/json"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers


class TestNoTelemetry:
    def test_endpoint_has_no_db_session_parameter(self):
        handler = _diag_handler()
        assert "session" not in inspect.signature(handler).parameters

    @respx.mock
    def test_no_rows_persisted(self, client):
        _mock_edge_403()
        with db_session.SessionLocal() as probe_session:
            before = tuple(
                probe_session.query(model).count()
                for model in (Search, SourceEvent, Result, DuplicateGroup)
            )
        client.get(DIAG_PATH, headers=KEY_HEADERS)
        with db_session.SessionLocal() as probe_session:
            after = tuple(
                probe_session.query(model).count()
                for model in (Search, SourceEvent, Result, DuplicateGroup)
            )
        assert before == after


class TestCaptureRules:
    @respx.mock
    def test_edge_rule_html_classified_raw_body_absent(self, client):
        _mock_edge_403()
        r = client.get(DIAG_PATH, headers=KEY_HEADERS)
        payload = r.json()
        assert payload["status_code"] == 403
        assert isinstance(payload["elapsed_ms"], int)
        assert payload["body_class"] == "EDGE_RULE_HTML"
        serialized = r.text
        assert "<html" not in serialized
        assert "<h1>" not in serialized
        assert "administrative rules" not in serialized
        assert len(payload["body_sha256_12"]) == 12

    @respx.mock
    def test_header_allowlist_filters_set_cookie(self, client):
        respx.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts").mock(
            return_value=httpx.Response(
                403,
                headers={
                    "content-type": "text/html",
                    "retry-after": "60",
                    "x-ratelimit-remaining": "0",
                    "set-cookie": "session=secretvalue; Path=/",
                    "cf-ray": "abc123",
                },
                text=EDGE_403_HTML,
            )
        )
        payload = client.get(DIAG_PATH, headers=KEY_HEADERS).json()
        assert payload["headers"]["retry-after"] == "60"
        assert payload["headers"]["x-ratelimit-remaining"] == "0"
        assert payload["headers"]["cf-ray"] == "abc123"
        assert "set-cookie" not in payload["headers"]

    @respx.mock
    def test_json_redaction_applied(self, client):
        respx.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts").mock(
            return_value=httpx.Response(
                403,
                headers={"content-type": "application/json"},
                json={
                    "error": "RateLimitExceeded",
                    "message": (
                        "contact ops@example.com owner did:plc:abcdef123456 "
                        "joe.bsky.social token eyJAAAAAAAAAAAAA.BBBBBBBBBBBBBBBB.CCCCC"
                    ),
                },
            )
        )
        payload = client.get(DIAG_PATH, headers=KEY_HEADERS).json()
        assert payload["body_class"] == "JSON"
        assert payload["json_error"] == "RateLimitExceeded"
        message = payload["json_message"]
        assert "ops@example.com" not in message
        assert "did:plc:abcdef123456" not in message
        assert "joe.bsky.social" not in message
        assert "eyJAAAAAAAAAAAAA" not in message
        assert "[EMAIL]" in message
        assert "[DID]" in message
        assert "[HANDLE]" in message
        assert "[JWT]" in message

    @respx.mock
    def test_timeout_maps_cleanly_without_retry(self, client):
        route = respx.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts").mock(
            side_effect=httpx.ConnectTimeout("boom")
        )
        r = client.get(DIAG_PATH, headers=KEY_HEADERS)
        assert r.status_code == 200
        assert r.json()["outcome"] == "timeout"
        assert route.call_count == 1
