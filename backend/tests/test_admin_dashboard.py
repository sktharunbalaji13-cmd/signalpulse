"""M20.1 admin dashboard session tests (ADR 0016).

Verifies the login/cookie boundary: X-Admin-Key is validated server-side,
a short-lived HttpOnly cookie is issued, the original key never appears in
any response, and the dashboard endpoints accept either the header or the
session cookie.
"""


from app.core.config import settings
from app.services import admin_session

_KEY = {"X-Admin-Key": "test-admin-key"}


def _login(client, headers=None):
    return client.post("/api/v1/admin/login", headers=headers or _KEY)


class TestLogin:
    def test_valid_key_returns_ok_and_cookie(self, client):
        r = _login(client)
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        cookie = r.cookies.get(admin_session.COOKIE_NAME)
        assert cookie is not None
        assert len(cookie) >= 32

    def test_cookie_is_httponly_and_path_scoped(self, client):
        r = _login(client)
        set_cookie = r.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie
        assert "Path=/api/v1/admin" in set_cookie
        # Over plain http (tests) the cookie is SameSite=lax (not Secure);
        # over https it must be SameSite=None; Secure for cross-origin use.
        assert "SameSite=lax" in set_cookie
        secure_attrs = admin_session.cookie_attributes(secure=True)
        assert secure_attrs["secure"] is True
        assert secure_attrs["samesite"] == "none"
        assert secure_attrs["httponly"] is True

    def test_missing_key_401(self, client):
        assert client.post("/api/v1/admin/login").status_code == 401

    def test_wrong_key_401(self, client):
        assert _login(client, {"X-Admin-Key": "wrong"}).status_code == 401

    def test_empty_configured_key_denies_all(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_api_key", "")
        assert _login(client).status_code == 401
        assert _login(client, {"X-Admin-Key": ""}).status_code == 401

    def test_login_response_never_returns_key(self, client):
        r = _login(client)
        text = r.text
        assert "test-admin-key" not in text
        assert "x-admin-key" not in text.lower() or "X-Admin-Key" not in text


class TestSessionAcceptance:
    def test_cookie_token_accepted_by_stats(self, client):
        r = _login(client)
        cookie = {admin_session.COOKIE_NAME: r.cookies[admin_session.COOKIE_NAME]}
        stats = client.get("/api/v1/admin/stats?window=7d", cookies=cookie)
        assert stats.status_code == 200
        assert "searches" in stats.json()

    def test_header_still_accepted(self, client):
        """The original X-Admin-Key contract is unchanged."""
        stats = client.get("/api/v1/admin/stats?window=7d", headers=_KEY)
        assert stats.status_code == 200

    def test_stats_without_credentials_401(self, client):
        assert client.get("/api/v1/admin/stats").status_code == 401

    def test_invalid_token_rejected(self, client):
        assert (
            client.get(
                "/api/v1/admin/stats?window=7d",
                cookies={admin_session.COOKIE_NAME: "garbage-token"},
            ).status_code
            == 401
        )

    def test_expired_token_rejected(self, client, monkeypatch):
        r = _login(client)
        token = r.cookies[admin_session.COOKIE_NAME]
        # Force expiry by rewinding the token's expiry below now.
        monkeypatch.setattr(settings, "admin_session_ttl_seconds", -1)
        admin_session.revoke_token(token)
        # issue a token that is already expired via direct store manipulation
        from app.services.admin_session import _tokens

        with admin_session._lock:
            _tokens[token] = 0.0  # expiry long past
        assert (
            client.get(
                "/api/v1/admin/stats?window=7d",
                cookies={admin_session.COOKIE_NAME: token},
            ).status_code
            == 401
        )

    def test_logout_revokes_token(self, client):
        r = _login(client)
        token = r.cookies[admin_session.COOKIE_NAME]
        assert admin_session.validate_token(token)
        assert client.post("/api/v1/admin/logout").status_code == 200
        assert not admin_session.validate_token(token)


class TestKeyNeverPersisted:
    def test_no_persistence_of_original_key(self, client, session_factory):
        from sqlalchemy import text as sa_text

        _login(client)
        with session_factory() as session:
            tables = session.execute(
                sa_text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        # Admin tokens live only in memory - no table holds them.
        for (table,) in tables:
            assert "admin" not in table and "session" not in table

    def test_active_token_count(self, client):
        before = admin_session.active_token_count()
        _login(client)
        assert admin_session.active_token_count() == before + 1