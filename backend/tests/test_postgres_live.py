"""Live PostgreSQL integration check (M4). Skipped unless POSTGRES_TEST_URL is set.

Production-equivalent verification against a real PostgreSQL database (Neon
runs the same engine). Run locally with the Docker Postgres container::

    $env:POSTGRES_TEST_URL='postgresql+psycopg://sp:sp_test@127.0.0.1:5433/signalpulse'
    python -m pytest tests/test_postgres_live.py

Verifies the schema, the TIMESTAMPTZ columns, the TZ-001 timezone round-trip,
and that the M3-E filter query executes on real PostgreSQL.
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Result, Search
from app.services.filters import filter_conditions

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_TEST_URL") is None,
    reason="POSTGRES_TEST_URL not set (set it to run the live Postgres check)",
)

URL = os.environ.get("POSTGRES_TEST_URL", "")


@pytest.fixture()
def engine():
    e = create_engine(URL)
    Base.metadata.drop_all(e)
    Base.metadata.create_all(e)
    yield e
    e.dispose()


def test_datetime_columns_are_timestamptz(engine):
    insp = inspect(engine)
    types = {c["name"]: c["type"] for c in insp.get_columns("results")}
    assert types["published_at"].timezone is True
    assert types["retrieved_at"].timezone is True
    search_types = {c["name"]: c["type"] for c in insp.get_columns("searches")}
    assert search_types["created_at"].timezone is True


def test_tz_round_trip_preserves_utc_marker(engine):
    S = sessionmaker(bind=engine, expire_on_commit=False)
    tz = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    with S() as s:
        search = Search(query="x", normalized_query="x", status="running")
        s.add(search)
        s.commit()
        r = Result(
            search_id=search.id,
            source_type="news",
            source_name="The Guardian",
            title="t",
            url="https://t",
            published_at=tz,
            retrieved_at=tz,
            raw={},
        )
        s.add(r)
        s.commit()
        rid = r.id
    with S() as s:
        got = s.get(Result, rid)
        assert got.published_at.tzinfo is not None, "tzinfo must survive the round-trip"
        assert got.published_at == tz
        assert got.published_at.isoformat() == "2026-08-19T12:00:00+00:00"


def test_filter_query_runs_on_postgres(engine):
    S = sessionmaker(bind=engine, expire_on_commit=False)
    with S() as s:
        search = Search(
            query="ai",
            normalized_query="ai",
            status="completed",
            created_at=datetime(2026, 8, 19, 11, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
        )
        s.add(search)
        s.commit()
        sid = search.id
        s.add(
            Result(
                search_id=sid,
                source_type="news",
                source_name="The Guardian",
                title="ai",
                url="https://a",
                published_at=datetime(2026, 8, 19, 10, 0, 0, tzinfo=UTC),
                retrieved_at=datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
                raw={},
                rank_position=0,
            )
        )
        s.commit()
        conditions = filter_conditions(
            source_types=["news"],
            time_window="24h",
            duplicates="all",
            language=None,
            completed_at=search.completed_at,
            created_at=search.created_at,
        )
        rows = s.scalars(select(Result).where(*conditions)).all()
        assert len(rows) == 1
