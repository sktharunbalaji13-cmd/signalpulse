"""M4 stale PostgreSQL connection resilience (session.py pool config).

The production engine must ping on checkout (``pool_pre_ping``) and recycle
connections before Neon's server-side idle close (``pool_recycle=300``). These
tests pin that configuration and, when ``POSTGRES_TEST_URL`` is set, prove a
server-side-killed pooled connection self-heals with ``pre_ping`` enabled (and
reproduces the ``OperationalError`` without it). No sleep-based timing; no
dependency on a specific Postgres provider.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db import session as db_session


def test_production_engine_has_pre_ping():
    assert db_session.engine.pool._pre_ping is True


def test_production_engine_recycle_is_300():
    assert db_session.engine.pool._recycle == 300


def test_sqlite_connect_args_logic_preserved():
    if settings.database_url.startswith("sqlite"):
        assert db_session.connect_args.get("check_same_thread") is False
    else:
        assert db_session.connect_args == {}


def _kill_backend(url: str, pid: int) -> None:
    with create_engine(url).connect() as killer:
        killer.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})


@pytest.mark.skipif(
    os.environ.get("POSTGRES_TEST_URL") is None,
    reason="POSTGRES_TEST_URL not set (set it to run the live stale-connection check)",
)
@pytest.mark.parametrize("pre_ping,expect_recovered", [(False, False), (True, True)])
def test_stale_connection_recovery(pre_ping, expect_recovered):
    """A connection returned healthy and then killed server-side while idle in
    the pool must fail on checkout without ``pre_ping`` and self-heal with it."""
    url = os.environ["POSTGRES_TEST_URL"]
    engine = create_engine(url, pool_pre_ping=pre_ping, pool_recycle=-1, pool_size=1)
    try:
        with engine.connect() as conn:
            pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()
        _kill_backend(url, pid)
        recovered = False
        try:
            with engine.connect() as conn2:
                conn2.execute(text("SELECT 1"))
            recovered = True
        except OperationalError:
            recovered = False
        assert recovered is expect_recovered, f"pre_ping={pre_ping} recovered={recovered}"
    finally:
        engine.dispose()