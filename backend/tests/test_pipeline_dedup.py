"""Integration tests for duplicate-group persistence and pipeline wiring (M3-A4)."""

import asyncio
from datetime import UTC, datetime

from app.db.models import DuplicateGroup, Result, Search
from app.services.search_pipeline import _annotate_duplicates, run_search_job
from app.sources.registry import registry

_RETRIEVED = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
_T0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=UTC)


def _add_search(session, query="q"):
    search = Search(query=query, normalized_query=query, status="running")
    session.add(search)
    session.flush()
    return search.id


def _add_result(
    session,
    search_id,
    *,
    title,
    url,
    source_type="news",
    source_name="The Guardian",
    published_at=_T0,
    description=None,
):
    result = Result(
        search_id=search_id,
        source_type=source_type,
        source_name=source_name,
        title=title,
        description=description,
        url=url,
        published_at=published_at,
        retrieved_at=_RETRIEVED,
        raw={},
    )
    session.add(result)
    session.flush()
    return result.id


def test_annotate_creates_group_without_deleting_results(session_factory):
    with session_factory() as session:
        search_id = _add_search(session)
        a = _add_result(session, search_id, title="Same story", url="https://n.example/story")
        b = _add_result(
            session, search_id, title="Same story", url="https://n.example/story?utm_source=push"
        )
        session.commit()

        stats = _annotate_duplicates(session, search_id)
        session.commit()

        assert stats == {"groups": 1, "duplicates": 1}

        results = session.query(Result).filter_by(search_id=search_id).all()
        assert len(results) == 2  # nothing deleted

        groups = session.query(DuplicateGroup).filter_by(search_id=search_id).all()
        assert len(groups) == 1
        group = groups[0]
        assert group.member_count == 2
        assert group.canonical_result_id in {a, b}
        assert group.duplicate_evidence == {"methods": ["canonical_url", "normalized_title"]}

        by_id = {r.id: r for r in results}
        canonical_id = group.canonical_result_id
        assert by_id[canonical_id].is_duplicate is False
        duplicate_id = a if canonical_id == b else b
        assert by_id[duplicate_id].is_duplicate is True
        assert all(r.duplicate_group_id == group.id for r in results)
        assert all(r.dedupe_key is not None for r in results)


def test_annotate_does_not_merge_news_and_social(session_factory):
    with session_factory() as session:
        search_id = _add_search(session)
        _add_result(
            session,
            search_id,
            title="Big story about the framework",
            url="https://n.example/a",
            source_type="news",
        )
        _add_result(
            session,
            search_id,
            title="Big story about the framework",
            url="https://r.example/b",
            source_type="social",
        )
        session.commit()

        stats = _annotate_duplicates(session, search_id)
        session.commit()

        assert stats == {"groups": 0, "duplicates": 0}
        assert session.query(DuplicateGroup).filter_by(search_id=search_id).count() == 0
        results = session.query(Result).filter_by(search_id=search_id).all()
        assert all(r.is_duplicate is False for r in results)
        assert all(r.duplicate_group_id is None for r in results)


def test_annotate_records_fuzzy_evidence(session_factory):
    with session_factory() as session:
        search_id = _add_search(session)
        _add_result(
            session,
            search_id,
            title="Researchers report quantum error correction milestone",
            url="https://n.example/a",
        )
        _add_result(
            session,
            search_id,
            title="Quantum error correction milestone reached, researchers report",
            url="https://n.example/b",
        )
        session.commit()

        _annotate_duplicates(session, search_id)
        session.commit()

        groups = session.query(DuplicateGroup).filter_by(search_id=search_id).all()
        assert len(groups) == 1
        assert groups[0].duplicate_evidence == {"methods": ["fuzzy_title"]}


def test_annotate_is_deterministic_across_identical_searches(session_factory):
    def build_and_annotate(query: str) -> tuple:
        with session_factory() as session:
            search_id = _add_search(session, query=query)
            _add_result(
                session,
                search_id,
                title="Same story",
                url="https://n.example/story",
                source_name="The Guardian",
            )
            _add_result(
                session,
                search_id,
                title="Same story",
                url="https://n.example/story?ref=home",
                source_name="The Guardian",
            )
            _add_result(
                session,
                search_id,
                title="Unrelated different story",
                url="https://n.example/other",
                source_name="The Guardian",
            )
            session.commit()
            _annotate_duplicates(session, search_id)
            session.commit()

            groups = session.query(DuplicateGroup).filter_by(search_id=search_id).all()
            results = session.query(Result).filter_by(search_id=search_id).all()
            result_by_id = {r.id: r for r in results}
            signature = tuple(
                sorted(
                    (
                        result_by_id[g.canonical_result_id].url,
                        frozenset(
                            result_by_id[r.id].url
                            for r in results
                            if r.duplicate_group_id == g.id
                        ),
                        tuple(sorted(g.duplicate_evidence["methods"])),
                    )
                    for g in groups
                )
            )
            return signature

    assert build_and_annotate("q1") == build_and_annotate("q2")


def test_full_pipeline_persists_duplicate_groups(session_factory, monkeypatch):
    class DupAdapter:
        source_type = "news"
        source_name = "DupNews"

        async def search(self, query: str, params=None) -> list:
            from app.sources.base import SourceResult

            return [
                SourceResult(
                    source_type="news",
                    source_name="DupNews",
                    title="Same story",
                    url="https://n.example/story",
                    retrieved_at=_RETRIEVED,
                    raw={},
                ),
                SourceResult(
                    source_type="news",
                    source_name="DupNews",
                    title="Same story",
                    url="https://n.example/story?ref=home",
                    retrieved_at=_RETRIEVED,
                    raw={},
                ),
            ]

    monkeypatch.setattr(registry, "_adapters", {"dup": DupAdapter()})

    with session_factory() as session:
        search_id = _add_search(session)
        session.commit()

    asyncio.run(run_search_job(search_id))

    with session_factory() as session:
        search = session.get(Search, search_id)
        assert search.status == "completed"
        assert search.stats["dedup"] == {"groups": 1, "duplicates": 1}
        groups = session.query(DuplicateGroup).filter_by(search_id=search_id).all()
        assert len(groups) == 1
        results = session.query(Result).filter_by(search_id=search_id).all()
        assert len(results) == 2
        assert sum(1 for r in results if r.is_duplicate) == 1
