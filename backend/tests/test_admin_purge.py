"""M15.1 admin purge endpoint tests (ADR 0013).

Covers: X-Admin-Key protection (missing/wrong/valid), purge-by-id, purge-
expired with the configured cutoff, public-endpoint invariance, response
shape without query text, and safe unknown-ID behavior.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Result, Search

_KEY = {"X-Admin-Key": "test-admin-key"}


def _seed(session, query="some query", age_days=0.0):
    now = datetime.now(UTC)
    search = Search(
        query=query,
        normalized_query=query,
        status="completed",
        created_at=now - timedelta(days=age_days),
        completed_at=now,
    )
    session.add(search)
    session.commit()
    session.add(
        Result(
            search_id=search.id,
            source_type="news",
            source_name="X",
            title="t",
            url=f"https://example.com/{search.id}",
            retrieved_at=now,
            raw={},
        )
    )
    session.commit()
    return search


@pytest.fixture()
def seeded(session_factory):
    with session_factory() as s:
        search = _seed(s)
        return search.id


class TestPurgeAuth:
    def test_missing_admin_key_401(self, client):
        assert client.delete("/api/v1/admin/searches/whatever").status_code == 401
        assert client.post("/api/v1/admin/purge-expired").status_code == 401

    def test_wrong_admin_key_401(self, client, seeded):
        wrong = {"X-Admin-Key": "not-the-key"}
        assert (
            client.delete(f"/api/v1/admin/searches/{seeded}", headers=wrong).status_code
            == 401
        )
        assert (
            client.post("/api/v1/admin/purge-expired", headers=wrong).status_code == 401
        )

    def test_correct_key_purges_expired(self, client, session_factory):
        with session_factory() as s:
            _seed(s, query="ancient", age_days=31)
        r = client.post("/api/v1/admin/purge-expired", headers=_KEY)
        assert r.status_code == 200
        body = r.json()
        assert body["searches_deleted"] == 1
        assert body["results_deleted"] == 1
        assert body["cutoff_utc"] is not None


class TestPurgeById:
    def test_specific_search_purge(self, client, session_factory, seeded):
        r = client.delete(f"/api/v1/admin/searches/{seeded}", headers=_KEY)
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "searches_deleted": 1,
            "results_deleted": 1,
            "source_events_deleted": 0,
            "duplicate_groups_deleted": 0,
            "cutoff_utc": None,
        }
        with session_factory() as s:
            assert s.get(Search, seeded) is None

    def test_purge_twice_returns_404_second_time(self, client, seeded):
        first = client.delete(f"/api/v1/admin/searches/{seeded}", headers=_KEY)
        second = client.delete(f"/api/v1/admin/searches/{seeded}", headers=_KEY)
        assert first.status_code == 200
        assert second.status_code == 404

    def test_unknown_search_id_safe_response(self, client):
        r = client.delete(
            "/api/v1/admin/searches/00000000-dead-beef-0000-000000000000",
            headers=_KEY,
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "Search not found"


class TestPurgeExpiredCutoff:
    def test_uses_thirty_day_cutoff(self, client, session_factory, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "retention_days", 30)
        with session_factory() as s:
            _seed(s, query="expired", age_days=45)
            _seed(s, query="within retention", age_days=3)
        body = client.post("/api/v1/admin/purge-expired", headers=_KEY).json()
        assert body["searches_deleted"] == 1
        with session_factory() as s:
            remaining = s.query(Search).all()
            assert len(remaining) == 1
            assert remaining[0].query == "within retention"


class TestPublicEndpointsUnchanged:
    def test_health_public(self, client):
        assert client.get("/api/v1/health").status_code == 200

    def test_history_still_lists_retained_searches(self, client, session_factory):
        with session_factory() as s:
            _seed(s, query="kept")
        r = client.get("/api/v1/searches")
        assert r.status_code == 200
        assert [item["query"] for item in r.json()["items"]] == ["kept"]

    def test_search_submission_still_works(self, client):
        r = client.post("/api/v1/searches", json={"query": "privacy check"})
        assert r.status_code == 202


class TestPurgeResponsePrivacy:
    def test_response_contains_counts_not_query_text(self, client, session_factory):
        secret_query = "super-secret-user-query"
        with session_factory() as s:
            _seed(s, query=secret_query, age_days=99)
        body = client.post("/api/v1/admin/purge-expired", headers=_KEY)
        assert body.status_code == 200
        text = body.text
        for key in (
            "searches_deleted",
            "results_deleted",
            "source_events_deleted",
            "duplicate_groups_deleted",
        ):
            assert key in text
        # Operational counts only - no content, no query strings.
        assert "query" not in text
        assert secret_query not in text

    def test_purged_rows_leave_admin_stats(self, client, session_factory, monkeypatch):
        """Stats are live-computed: once retention (< window) removes rows,
        they disappear from statistics immediately - no aggregation tables."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "retention_days", 7)
        with session_factory() as s:
            _seed(s, query="will vanish from stats", age_days=10)
            _seed(s, query="stays", age_days=2)
        stats_url = "/api/v1/admin/stats?window=30d"
        before = client.get(stats_url, headers=_KEY).json()["searches"]["total"]
        client.post("/api/v1/admin/purge-expired", headers=_KEY)
        after = client.get(stats_url, headers=_KEY).json()["searches"]["total"]
        assert before == 2
        assert after == 1