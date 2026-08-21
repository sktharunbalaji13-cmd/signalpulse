"""Pre-deployment PostgreSQL compatibility + TZ-001 verification (M4 design).

Compiles the schema DDL and the key production queries against the PostgreSQL
dialect WITHOUT a live database. This is the deploy-time guarantee that:

* SQLite -> PostgreSQL is a config change, not a rewrite (no SQLite-only
  constructs anywhere in the schema or queries);
* the M4 migration closes TZ-001: ``DateTime(timezone=True)`` columns become
  ``TIMESTAMP WITH TIME ZONE`` (TIMESTAMPTZ), which round-trips timezone-aware
  datetimes correctly (SQLite dropped tzinfo on round-trip, shifting browser
  display by the UTC offset).

These assertions are dialect-compilation checks; a live Neon connectivity +
round-trip check is a documented pre-deployment checklist step (M4 §13).
"""

from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.models import Base, DuplicateGroup, Result, Search, SourceEvent
from app.services.filters import filter_conditions

_PG = postgresql.dialect()


def _compile_ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=_PG))


def test_datetime_columns_become_timestamptz_on_postgres():
    search_ddl = _compile_ddl(Search)
    result_ddl = _compile_ddl(Result)
    assert "TIMESTAMP WITH TIME ZONE" in search_ddl, search_ddl  # created/completed
    assert "TIMESTAMP WITH TIME ZONE" in result_ddl, result_ddl  # published/retrieved


def test_json_columns_are_json_on_postgres():
    for model in (Search, Result, DuplicateGroup):
        assert "JSON" in _compile_ddl(model)


def test_no_sqlite_only_constructs_in_schema():
    for model in (Search, Result, DuplicateGroup, SourceEvent):
        assert "sqlite" not in _compile_ddl(model).lower()


def test_filter_query_compiles_for_postgres():
    now = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    conditions = filter_conditions(
        source_types=["news", "social"],
        time_window="7d",
        duplicates="canonical",
        language="en",
        completed_at=now,
        created_at=now,
    )
    stmt = select(Result).where(*conditions)
    sql = str(stmt.compile(dialect=_PG))
    assert "IN" in sql.upper()
    assert "is_duplicate" in sql  # canonical filter is included
    assert ">=" in sql


def test_results_ordering_compiles_for_postgres():
    stmt = (
        select(Result)
        .order_by(
            Result.rank_position.asc().nullslast(),
            case(
                (Result.source_type == "news", 0),
                (Result.source_type == "social", 1),
                (Result.source_type == "reference", 2),
                else_=9,
            ),
            Result.published_at.desc().nullslast(),
            Result.url,
        )
    )
    sql = str(stmt.compile(dialect=_PG))
    assert "NULLS LAST" in sql.upper()


def test_metadata_compiles_without_error_for_postgres():
    for table in Base.metadata.sorted_tables:
        _compile_ddl(type("_M", (), {"__table__": table})())
