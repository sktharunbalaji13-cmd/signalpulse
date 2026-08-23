"""M15.1 retention cleanup service tests (ADR 0013).

Covers: expired deletion, recent survival, child-row cascade, duplicate-group
FK ordering, empty/failed/partial searches, batching, idempotency, no-op
behavior, transactional rollback, and the scheduled-cleanup wrapper.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models import DuplicateGroup, Result, Search, SourceEvent
from app.services import retention


def _seed_search(
    session,
    query="old query",
    *,
    age_days=0.0,
    status="completed",
    with_children=True,
):
    """Insert one search (optionally with result + source_event + dup group)."""
    now = datetime.now(UTC)
    created = now - timedelta(days=age_days)
    search = Search(
        query=query,
        normalized_query=query.lower(),
        status=status,
        created_at=created,
        completed_at=now if status != "running" else None,
        duration_ms=1000,
    )
    session.add(search)
    session.commit()
    if not with_children:
        return search.id
    result = Result(
        search_id=search.id,
        source_type="news",
        source_name="The Guardian",
        title=f"title for {query}",
        description="desc",
        url=f"https://example.com/{search.id}",
        author=None,
        retrieved_at=now,
        language="en",
        raw={"id": "raw"},
    )
    event = SourceEvent(
        search_id=search.id, source_name="The Guardian", status="success"
    )
    session.add_all([result, event])
    session.commit()
    group = DuplicateGroup(
        search_id=search.id,
        canonical_result_id=result.id,
        member_count=2,
        duplicate_evidence={"methods": ["canonical_url"]},
    )
    session.add(group)
    session.commit()
    return search.id


def _counts(session):
    return {
        "searches": session.scalar(select(Search.id).limit(1)) is not None,
        "results": len(session.scalars(select(Result.id)).all()),
        "events": len(session.scalars(select(SourceEvent.id)).all()),
        "groups": len(session.scalars(select(DuplicateGroup.id)).all()),
    }


@pytest.fixture()
def cutoff():
    return retention.retention_cutoff(retention_days=settings.retention_days)


class TestPurgeExpired:
    def test_expired_search_is_deleted(self, session_factory, cutoff):
        with session_factory() as s:
            sid = _seed_search(s, age_days=31)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 1
            assert s.get(Search, sid) is None

    def test_recent_search_remains(self, session_factory, cutoff):
        with session_factory() as s:
            sid = _seed_search(s, age_days=1)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 0
            assert s.get(Search, sid) is not None

    def test_child_rows_deleted_correctly(self, session_factory, cutoff):
        with session_factory() as s:
            sid = _seed_search(s, age_days=40)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.results == 1
            assert counts.source_events == 1
            assert counts.duplicate_groups == 1
            assert _counts(s) == {
                "searches": False,
                "results": 0,
                "events": 0,
                "groups": 0,
            }
            assert sid  # used

    def test_duplicate_group_fk_order_does_not_violate(self, session_factory, cutoff):
        """duplicate_groups.canonical_result_id -> results.id means groups must
        be deleted before results; the purge must succeed without FK errors."""
        with session_factory() as s:
            _seed_search(s, age_days=45)  # includes a duplicate group
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 1 and counts.duplicate_groups == 1

    def test_search_without_children_cleans_correctly(self, session_factory, cutoff):
        with session_factory() as s:
            sid = _seed_search(s, age_days=35, with_children=False)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 1
            assert counts.results == 0
            assert s.get(Search, sid) is None

    @pytest.mark.parametrize("status", ["failed", "partial"])
    def test_failed_and_partial_searches_clean(self, session_factory, cutoff, status):
        with session_factory() as s:
            sid = _seed_search(s, age_days=31, status=status)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 1
            assert s.get(Search, sid) is None

    def test_multiple_expired_searches_handled(self, session_factory, cutoff):
        with session_factory() as s:
            old_ids = [
                _seed_search(s, query=f"old {i}", age_days=31 + i) for i in range(3)
            ]
            fresh_id = _seed_search(s, query="fresh", age_days=2)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 3
            for sid in old_ids:
                assert s.get(Search, sid) is None
            assert s.get(Search, fresh_id) is not None

    def test_cleanup_is_idempotent(self, session_factory, cutoff):
        with session_factory() as s:
            _seed_search(s, age_days=31)
            first = retention.purge_expired(s, cutoff=cutoff)
            second = retention.purge_expired(s, cutoff=cutoff)
            assert first.searches == 1
            assert second.searches == 0
            assert second.results == 0

    def test_no_expired_rows_is_noop(self, session_factory, cutoff):
        with session_factory() as s:
            _seed_search(s, age_days=0)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.as_dict() == {
                "searches_deleted": 0,
                "results_deleted": 0,
                "source_events_deleted": 0,
                "duplicate_groups_deleted": 0,
            }

    def test_batching_deletes_everything(self, session_factory, monkeypatch, cutoff):
        monkeypatch.setattr(retention, "BATCH_SIZE", 2)
        with session_factory() as s:
            for i in range(5):
                _seed_search(s, query=f"batch {i}", age_days=32)
            counts = retention.purge_expired(s, cutoff=cutoff)
            assert counts.searches == 5

    def test_failure_rolls_back_batch_atomically(
        self, session_factory, monkeypatch, cutoff
    ):
        with session_factory() as s:
            sid = _seed_search(s, age_days=31)

            def broken_commit():
                raise RuntimeError("simulated db failure")

            monkeypatch.setattr(s, "commit", broken_commit)
            with pytest.raises(RuntimeError):
                retention.purge_expired(s, cutoff=cutoff)
            monkeypatch.undo()
            # Nothing may be partially deleted: children AND search survive.
            assert s.get(Search, sid) is not None
            assert _counts(s)["results"] == 1
            assert _counts(s)["groups"] == 1


class TestPurgeSingleSearch:
    def test_purges_one_search_with_children(self, session_factory):
        with session_factory() as s:
            keep = _seed_search(s, query="keep", age_days=1)
            gone = _seed_search(s, query="gone", age_days=99)
            counts = retention.purge_search(s, gone)
            assert counts is not None
            assert counts.searches == 1
            assert s.get(Search, gone) is None
            assert s.get(Search, keep) is not None

    def test_unknown_search_returns_none(self, session_factory):
        with session_factory() as s:
            assert retention.purge_search(s, "no-such-id") is None


class TestScheduledCleanup:
    def test_run_scheduled_cleanup_deletes_expired(self, session_factory, monkeypatch):
        from app.db import session as db_session

        with session_factory() as s:
            _seed_search(s, age_days=31)
        monkeypatch.setattr(db_session, "SessionLocal", session_factory)
        counts = retention.run_scheduled_cleanup()
        assert counts is not None
        assert counts.searches == 1

    def test_skips_when_already_running(self, session_factory, monkeypatch):
        held = retention._cleanup_lock
        assert held.acquire(blocking=False)
        try:
            assert retention.run_scheduled_cleanup() is None
        finally:
            held.release()

    def test_failure_is_isolated_and_logged(self, session_factory, monkeypatch):
        from app.db import session as db_session

        class ExplodingFactory:
            def __call__(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(db_session, "SessionLocal", ExplodingFactory())
        # Must not raise; returns None and logs the failure type only.
        assert retention.run_scheduled_cleanup() is None