"""End-to-end dedup evaluation through the actual production pipeline (M3-A final).

The offline bridge (``eval/dedup_eval.py``) calls the detector directly on
corpus candidates. This module proves the wired system does the same thing:
each corpus query is run through the real job (``run_search_job``), results are
persisted to a fresh SQLite database, ``_annotate_duplicates`` creates
``DuplicateGroup`` rows, the API endpoint serializes them, and the persisted
groups are scored against the gold corpus.

Run with::

    python -m eval.e2e_dedup_eval

Expected numbers match the bridge: precision 1.0, recall ~0.6425, F1 ~0.7823,
zero false positives, zero ambiguous pairs merged. If the pipeline result
differs, stop and investigate — do not tune the algorithm to fit.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eval import corpus, dedup_eval, metrics
from eval.schema import EvalCorpus, validate_corpus

_BACKEND = Path(__file__).resolve().parents[1] / "backend"


def _load_backend() -> None:
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CorpusAdapter:
    """Fake source that replays one corpus query's items as SourceResults."""

    source_type = "news"
    source_name = "Corpus"

    def __init__(self, items) -> None:
        self._items = items

    def is_configured(self) -> bool:
        return True

    async def search(self, query: str, params=None) -> list:
        _load_backend()
        from app.sources.base import SourceResult  # noqa: PLC0415

        return [
            SourceResult(
                source_type=item.source_type,
                source_name=item.source_name,
                title=item.title,
                description=item.description or None,
                url=item.url,
                author=item.author,
                published_at=_parse_ts(item.published_at),
                retrieved_at=_parse_ts(item.retrieved_at),
                language=None,
                raw={"corpus_item_id": item.id},
            )
            for item in self._items
        ]


def _install_environment(query_items):
    """Point the pipeline at a fresh in-memory DB and a corpus-only registry.

    Returns a session factory; the caller is responsible for restoring
    ``registry._adapters`` (previous mapping returned alongside).
    """
    _load_backend()
    from app.db import session as db_session  # noqa: PLC0415
    from app.db.models import Base  # noqa: PLC0415
    from app.sources.registry import registry  # noqa: PLC0415

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    previous = registry._adapters
    registry._adapters = {"corpus": CorpusAdapter(query_items)}
    db_session.SessionLocal = factory
    return factory, previous


def _run_query(factory, query_text: str) -> tuple:
    """Create a search row and run the production job end to end."""
    _load_backend()
    from app.db.models import Search, SearchStatus  # noqa: PLC0415
    from app.services.search_pipeline import run_search_job  # noqa: PLC0415

    with factory() as session:
        search = Search(
            query=query_text,
            normalized_query=" ".join(query_text.lower().split()),
            window_hours=None,
            status=SearchStatus.RUNNING.value,
        )
        session.add(search)
        session.commit()
        search_id = search.id

    asyncio.run(run_search_job(search_id))

    from app.db.models import DuplicateGroup, Result  # noqa: PLC0415

    with factory() as session:
        search = session.get(Search, search_id)
        results = (
            session.query(Result)
            .filter(Result.search_id == search_id)
            .order_by(Result.id)
            .all()
        )
        groups = (
            session.query(DuplicateGroup)
            .filter(DuplicateGroup.search_id == search_id)
            .order_by(DuplicateGroup.id)
            .all()
        )
    return search, results, groups


def _gold_pairs_for_query(groups, item_ids: set[str]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for group in groups:
        members = [m for m in group.members if m in item_ids]
        if len(members) < 2:
            continue
        for a, b in combinations(members, 2):
            pairs.add(frozenset((a, b)))
    return pairs


def _pairs_from_group_members(member_ids: list[str]) -> set[frozenset[str]]:
    return {frozenset((a, b)) for a, b in combinations(member_ids, 2)}


def evaluate() -> dict:
    """Run every corpus query through the production pipeline and score dedup."""
    _load_backend()
    from app.db import session as db_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415
    from app.services.dedup import Candidate, select_canonical  # noqa: PLC0415
    from app.sources.registry import registry  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    data = validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )

    all_gold: set[frozenset[str]] = set()
    all_predicted: set[frozenset[str]] = set()
    groups_created = 0
    ambiguous_merged = 0
    canonical_correct = 0
    canonical_total = 0
    rows_preserved = True
    api_verified = True
    per_query: list[dict] = []

    original_factory = db_session.SessionLocal
    previous_adapters = registry._adapters
    try:
        with TestClient(app) as client:
            for query in data.queries:
                factory, _ = _install_environment(query.items)
                search, results, groups = _run_query(factory, query.query)
                if search.status != "completed":
                    raise AssertionError(
                        f"{query.id}: search status {search.status!r}, expected 'completed'"
                    )
                if len(results) != len(query.items):
                    raise AssertionError(
                        f"{query.id}: {len(results)} rows persisted for {len(query.items)} items"
                    )
                expected_stats = {
                    "groups": len(groups),
                    "duplicates": sum(g.member_count - 1 for g in groups),
                }
                if (search.stats or {}).get("dedup") != expected_stats:
                    raise AssertionError(f"{query.id}: search.stats.dedup mismatch")

                item_id_of = {r.id: r.raw["corpus_item_id"] for r in results}
                predicted: set[frozenset[str]] = set()
                for group in groups:
                    members = [r for r in results if r.duplicate_group_id == group.id]
                    if len(members) != group.member_count:
                        raise AssertionError(f"{query.id}: member_count mismatch")
                    member_ids = [item_id_of[r.id] for r in members]
                    predicted |= _pairs_from_group_members(member_ids)

                    candidates = [
                        Candidate(
                            id=row.id,
                            url=row.url,
                            title=row.title,
                            source_type=row.source_type,
                            published_at=row.published_at,
                            description=row.description,
                        )
                        for row in members
                    ]
                    canonical_correct += int(
                        select_canonical(candidates) == group.canonical_result_id
                    )
                    canonical_total += 1

                for member_ids in (
                    frozenset(item_id_of[r.id] for r in results if r.duplicate_group_id == g.id)
                    for g in groups
                ):
                    for pair in data.ambiguous_pairs:
                        if frozenset(pair) <= member_ids:
                            ambiguous_merged += 1
                groups_created += len(groups)

                response = client.get(f"/api/v1/searches/{search.id}/results?per_page=100")
                assert response.status_code == 200, response.text
                payload = response.json()
                api_items = payload["items"]
                api_verified = api_verified and len(api_items) == len(results)
                # order-independent: the API now returns results in rank order
                # and some duplicate groups share a URL (URL-only exact dupes)
                api_sig = sorted(
                    (i["is_duplicate"], i["duplicate_group_id"] or "") for i in api_items
                )
                row_sig = sorted((r.is_duplicate, r.duplicate_group_id or "") for r in results)
                api_verified = api_verified and api_sig == row_sig

                item_ids = {item.id for item in query.items}
                gold = _gold_pairs_for_query(data.duplicate_groups, item_ids)
                all_gold |= gold
                all_predicted |= predicted
                per_query.append(
                    {
                        "query_id": query.id,
                        "gold_pairs": len(gold),
                        "predicted_pairs": len(predicted),
                        "caught_pairs": len(gold & predicted),
                        "false_pairs": len(predicted - gold),
                        "groups": len(groups),
                    }
                )
    finally:
        registry._adapters = previous_adapters
        db_session.SessionLocal = original_factory

    ambiguous = [tuple(p) for p in data.ambiguous_pairs]
    result = metrics.dedup_metrics(
        [tuple(sorted(p)) for p in all_gold],
        [tuple(sorted(p)) for p in all_predicted],
        ambiguous,
    )

    bridge = dedup_eval.evaluate()
    bridge_by_query = {q["query_id"]: q for q in bridge["per_query"]}
    _DETECTION_KEYS = ("gold_pairs", "predicted_pairs", "caught_pairs", "false_pairs")
    pipeline_matches_bridge = all(
        {k: q[k] for k in _DETECTION_KEYS}
        == {k: bridge_by_query[q["query_id"]][k] for k in _DETECTION_KEYS}
        for q in per_query
    )

    return {
        "corpus_revision": data.revision,
        "gold_cluster_count": len(data.duplicate_groups),
        "gold_pair_count": len(all_gold),
        "ambiguous_pair_count": len(ambiguous),
        "predicted_pair_count": len(all_predicted),
        "duplicate_groups_created": groups_created,
        "ambiguous_pairs_incorrectly_merged": ambiguous_merged,
        "canonical_selection_correct": canonical_correct,
        "canonical_selection_total": canonical_total,
        "rows_preserved": rows_preserved,
        "api_serialization_verified": api_verified,
        "metrics": result,
        "per_query": per_query,
        "pipeline_matches_bridge": pipeline_matches_bridge,
    }


def _human_summary(report: dict) -> str:
    m = report["metrics"]
    lines = [
        "SignalPulse dedup evaluation (M3-A E2E) — production pipeline vs gold corpus",
        f"  corpus revision {report['corpus_revision']}: "
        f"{report['gold_cluster_count']} gold clusters, "
        f"{report['gold_pair_count']} gold pairs, "
        f"{report['ambiguous_pair_count']} ambiguous pairs (excluded)",
        "",
        f"  precision  = {m['precision']:.4f}",
        f"  recall     = {m['recall']:.4f}",
        f"  F1         = {m['f1']:.4f}",
        f"  (TP={m['true_positive']}, FP={m['false_positive']}, FN={m['false_negative']})",
        "",
        f"  duplicate groups created in DB: {report['duplicate_groups_created']}",
        f"  canonical selection correct: "
        f"{report['canonical_selection_correct']}/{report['canonical_selection_total']}",
        f"  ambiguous pairs incorrectly merged: {report['ambiguous_pairs_incorrectly_merged']}",
        f"  no result rows deleted: {report['rows_preserved']}",
        f"  API serialization verified: {report['api_serialization_verified']}",
        f"  pipeline matches bridge per-query detections: {report['pipeline_matches_bridge']}",
        "",
        "  per-query gold/predicted/caught/false/groups:",
    ]
    for q in report["per_query"]:
        lines.append(
            f"    {q['query_id']}: gold={q['gold_pairs']} predicted={q['predicted_pairs']} "
            f"caught={q['caught_pairs']} false={q['false_pairs']} groups={q['groups']}"
        )
    return "\n".join(lines)


def main() -> int:
    first = evaluate()
    second = evaluate()
    deterministic = first == second
    print(_human_summary(first))
    print(f"\n  deterministic across two full pipeline runs: {deterministic}")
    if not deterministic:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
