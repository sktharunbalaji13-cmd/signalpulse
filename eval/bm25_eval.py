"""Evaluate the M3-B BM25 ranker against the gold corpus (offline).

**EXPERIMENTAL RESEARCH ARTIFACT — NOT PRODUCTION RANKING (ADR 0007).**

BM25 was REJECTED as the relevance core; this bridge is preserved as evidence.
Its measurement on the unchanged v2 corpus: baseline nDCG@10 0.6909, BM25 core
0.5674, best variant (title-only) 0.6263. See ``docs/ADR/0007-bm25-relevance-evaluation.md``.

Run with::

    python -m eval.bm25_eval
"""

from __future__ import annotations

import statistics
import sys
from datetime import datetime
from pathlib import Path

from eval import baseline, corpus, metrics
from eval.schema import EvalCorpus, validate_corpus

_BACKEND = Path(__file__).resolve().parents[1] / "backend"

_MEAN_KEYS = ("precision_at_5", "precision_at_10", "reciprocal_rank", "ndcg_at_10")


def _load_ranker():
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    from app.services.ranker import (  # noqa: PLC0415 - import after path setup
        RankCandidate,
        rank,
    )

    return RankCandidate, rank


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _candidates_for(items):
    RankCandidate, _ = _load_ranker()
    return [
        RankCandidate(
            id=item.id,
            title=item.title,
            description=item.description,
            source_type=item.source_type,
            published_at=_parse_ts(item.published_at),
            url=item.url,
        )
        for item in items
    ]


def _run_variant(data: EvalCorpus, include_bonuses: bool) -> dict:
    _, rank_fn = _load_ranker()
    per_query: list[dict] = []
    for query in data.queries:
        relevance = {item.id: item.relevance for item in query.items}
        ranked_ids = rank_fn(
            _candidates_for(query.items), query.query, include_bonuses=include_bonuses
        )
        per_query.append(
            {"query_id": query.id, **metrics.ranking_metrics(ranked_ids, relevance)}
        )
    means = {
        key: statistics.mean(q[key] for q in per_query) for key in _MEAN_KEYS
    }
    return {"means": means, "per_query": per_query}


def _run_baseline(data: EvalCorpus) -> dict:
    per_query: list[dict] = []
    for query in data.queries:
        relevance = {item.id: item.relevance for item in query.items}
        ranked_ids = baseline.rank(query.items, query.query)
        per_query.append(
            {"query_id": query.id, **metrics.ranking_metrics(ranked_ids, relevance)}
        )
    means = {key: statistics.mean(q[key] for q in per_query) for key in _MEAN_KEYS}
    return {"means": means, "per_query": per_query}


def evaluate() -> dict:
    """Measure BM25 core/full vs the naive baseline on the current corpus."""
    data = validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )
    baseline_report = _run_baseline(data)
    core = _run_variant(data, include_bonuses=False)
    full = _run_variant(data, include_bonuses=True)

    deltas = {}
    for key in _MEAN_KEYS:
        deltas[key] = {
            "core": round(core["means"][key] - baseline_report["means"][key], 4),
            "full": round(full["means"][key] - baseline_report["means"][key], 4),
        }

    return {
        "corpus_revision": data.revision,
        "query_count": len(data.queries),
        "baseline": baseline_report,
        "bm25_core": core,
        "bm25_full": full,
        "delta_vs_baseline": deltas,
    }


def _human_summary(report: dict) -> str:
    rows = [
        ("naive baseline", report["baseline"]["means"]),
        ("BM25 core     ", report["bm25_core"]["means"]),
        ("BM25 full     ", report["bm25_full"]["means"]),
    ]
    lines = [
        "SignalPulse ranking evaluation (M3-B) — BM25 vs naive baseline "
        f"(corpus revision {report['corpus_revision']})",
        "",
        "                   P@5      P@10     MRR      nDCG@10",
    ]
    for name, means in rows:
        lines.append(
            f"  {name}   {means['precision_at_5']:.4f}   "
            f"{means['precision_at_10']:.4f}   {means['reciprocal_rank']:.4f}   "
            f"{means['ndcg_at_10']:.4f}"
        )
    lines.append("")
    lines.append("  nDCG@10 delta vs baseline:")
    lines.append(
        f"    BM25 core: {report['delta_vs_baseline']['ndcg_at_10']['core']:+.4f}"
    )
    lines.append(
        f"    BM25 full: {report['delta_vs_baseline']['ndcg_at_10']['full']:+.4f}"
    )
    lines.append("")
    lines.append("  per-query nDCG@10 (baseline / core / full):")
    for index, query in enumerate(report["baseline"]["per_query"]):
        qid = query["query_id"]
        core = report["bm25_core"]["per_query"][index]
        full = report["bm25_full"]["per_query"][index]
        lines.append(
            f"    {qid}: {query['ndcg_at_10']:.4f} / {core['ndcg_at_10']:.4f} / "
            f"{full['ndcg_at_10']:.4f}"
        )
    return "\n".join(lines)


def main() -> int:
    print(_human_summary(evaluate()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
