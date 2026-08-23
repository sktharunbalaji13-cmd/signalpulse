"""M12 tests for the admin observability endpoint.

Covers: empty database, populated data, mixed statuses, source failures,
percentile calculations, dedup metrics, semantic states, zero-result searches,
window parameter validation, and read-only behavior.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db import session as db_session
from app.db.models import Base, Search

_ADMIN_KEY = "test-admin-key"
_ADMIN_HEADERS = {"X-Admin-Key": _ADMIN_KEY}


@pytest.fixture()
def admin_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    return factory


def _seed_search(factory, query="test", status="completed",
                 duration_ms=1000, stats=None):
    with factory() as s:
        search = Search(query=query, normalized_query=query.lower().split(),
                        status=status, duration_ms=duration_ms, stats=stats)
        s.add(search)
        s.commit()
        return search.id


class TestAdminStatsEmptyDB:
    def test_empty_database_returns_zeroed_metrics(self, client):
        resp = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["searches"]["total"] == 0
        assert body["latency_ms"]["p50"] is None
        assert body["sources"] == {}
        assert body["dedup"]["total_groups"] == 0


class TestAdminStatsPopulated:
    def _seed(self, factory, n=5, statuses=None):
        statuses = statuses or ["completed"] * n
        for i in range(n):
            with factory() as s:
                st = statuses[i % len(statuses)]
                search = Search(query=f"q{i}", normalized_query=f"q{i}",
                                status=st, duration_ms=1000 + i * 100)
                s.add(search)
                s.commit()

    def test_total_count(self, client, session_factory):
        self._seed(session_factory, 3)
        body = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        ).json()
        assert body["searches"]["total"] == 3

    def test_by_status_counts(self, client, session_factory):
        self._seed(session_factory, 6, ["completed", "completed", "partial",
                                        "failed", "completed", "partial"])
        body = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        ).json()["searches"]["by_status"]
        assert body["completed"] == 3
        assert body["partial"] == 2
        assert body["failed"] == 1

    def test_latency_percentiles(self, client, session_factory):
        durations = [500, 1000, 1500, 2000, 2500]
        for i, d in enumerate(durations):
            with session_factory() as s:
                s.add(Search(query=f"q{i}", normalized_query=f"q{i}",
                             status="completed", duration_ms=d))
                s.commit()
        body = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        ).json()
        assert body["latency_ms"]["p50"] == 1500
        assert body["latency_ms"]["p95"] >= 2000

    def test_source_events_aggregated(self, client, session_factory):
        with session_factory() as s:
            search = Search(query="x", normalized_query="x", status="completed")
            s.add(search)
            s.commit()
            from app.db.models import SourceEvent

            for name, status, lat, cnt in [
                ("Wikipedia", "success", 300, 10),
                ("The Guardian", "success", 500, 8),
                ("Reddit", "failed", None, None),
            ]:
                s.add(SourceEvent(search_id=search.id, source_name=name,
                                  status=status, result_count=cnt, latency_ms=lat,
                                  created_at=datetime.now(UTC)))
            s.commit()
        body = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        ).json()
        wiki = body["sources"].get("Wikipedia", {})
        assert wiki.get("success") == 1
        assert wiki.get("avg_latency_ms") == 300


class TestSemanticStats:
    def test_disabled_status_reported(self, client, session_factory, monkeypatch):
        monkeypatch.setattr(settings, "semantic_enabled", False)
        client.post("/api/v1/searches", json={"query": "ai"})
        body = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        ).json()
        assert body["semantic"].get("disabled", 0) >= 1


class TestWindowValidation:
    def test_invalid_window_422(self, client):
        resp = client.get(
            "/api/v1/admin/stats?window=5d", headers=_ADMIN_HEADERS,
        )
        assert resp.status_code == 422

    def test_valid_windows_accepted(self, client):
        for w in ("24h", "7d", "30d"):
            resp = client.get(
                f"/api/v1/admin/stats?window={w}", headers=_ADMIN_HEADERS,
            )
            assert resp.status_code == 200


class TestReadOnly:
    def test_stats_endpoint_does_not_write(self, client, session_factory):
        before = client.get("/api/v1/searches").json()["items"]
        client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        )
        after = client.get("/api/v1/searches").json()["items"]
        assert len(before) == len(after)


class TestZeroResults:
    def test_zero_result_search_counted(self, client, session_factory):
        """Seed a search directly with zero results (no pipeline run)."""
        from app.db.models import Search

        with session_factory() as s:
            search = Search(query="empty", normalized_query="empty",
                            status="completed", duration_ms=500)
            s.add(search)
            s.commit()

        body = client.get(
            "/api/v1/admin/stats", headers=_ADMIN_HEADERS,
        ).json()
        assert body["queries"]["empty_result_count"] >= 1