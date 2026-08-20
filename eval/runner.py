"""Evaluation runner: loads the corpus, validates it, and produces a report.

Deterministic by construction: no clock, no randomness, fixed timestamps, and
sorted JSON output. Run with ``python -m eval`` from the repository root.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from eval import baseline, corpus, metrics
from eval.schema import EvalCorpus, validate_corpus

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
REPORT_PATH = REPORTS_DIR / "latest.json"


def _build_corpus() -> EvalCorpus:
    return validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
        )
    )


def _run_ranking_baseline(corpus_data: EvalCorpus) -> dict:
    per_query: list[dict] = []
    for query in corpus_data.queries:
        relevance = {item.id: item.relevance for item in query.items}
        ranked_ids = baseline.rank(query.items, query.query)
        per_query.append(
            {"query_id": query.id, **metrics.ranking_metrics(ranked_ids, relevance)}
        )
    means = {
        "precision_at_5": statistics.mean(q["precision_at_5"] for q in per_query),
        "precision_at_10": statistics.mean(q["precision_at_10"] for q in per_query),
        "reciprocal_rank": statistics.mean(q["reciprocal_rank"] for q in per_query),
        "ndcg_at_10": statistics.mean(q["ndcg_at_10"] for q in per_query),
    }
    return {"means": means, "per_query": per_query}


def _run_report() -> dict:
    corpus_data = _build_corpus()

    total_items = sum(len(q.items) for q in corpus_data.queries)
    gold_groups = [g.model_dump() for g in corpus_data.duplicate_groups]
    ambiguous_pairs = [list(p) for p in corpus_data.ambiguous_pairs]

    baseline_ranking = _run_ranking_baseline(corpus_data)

    return {
        "schema": "signalpulse-eval-report",
        "corpus": {
            "synthetic": True,
            "query_count": len(corpus_data.queries),
            "item_count": total_items,
            "duplicate_group_count": len(gold_groups),
            "ambiguous_pair_count": len(ambiguous_pairs),
        },
        "baseline_ranking": baseline_ranking,
        "deduplication": {
            "status": "pending_m3_a",
            "note": "No dedup implementation exists yet in M3-A0; dedup_metrics() is "
            "unit-tested and will accept predictions from M3-A.",
            "gold_group_count": len(gold_groups),
            "ambiguous_pair_count": len(ambiguous_pairs),
        },
        "freshness": {
            "status": "pending_m3_c",
            "invariants": metrics.FRESHNESS_INVARIANTS,
            "note": "Production freshness scorer not implemented yet; check_freshness() "
            "is unit-tested and will validate the M3-C scorer.",
        },
        "targets": {
            "dedup_precision": 0.90,
            "dedup_recall": 0.90,
            "ndcg_at_10": 0.75,
            "note": "These are targets, not guaranteed results; reported only when measured.",
        },
    }


def _human_summary(report: dict) -> str:
    lines = [
        "SignalPulse evaluation report (M3-A0)",
        f"  corpus: {report['corpus']['query_count']} queries, "
        f"{report['corpus']['item_count']} items, "
        f"{report['corpus']['duplicate_group_count']} duplicate groups, "
        f"{report['corpus']['ambiguous_pair_count']} ambiguous pairs",
        "",
        "  baseline ranking (naive lexical term-count, NOT production):",
    ]
    means = report["baseline_ranking"]["means"]
    lines.append(f"    Precision@5  = {means['precision_at_5']:.4f}")
    lines.append(f"    Precision@10 = {means['precision_at_10']:.4f}")
    lines.append(f"    MRR          = {means['reciprocal_rank']:.4f}")
    lines.append(f"    nDCG@10      = {means['ndcg_at_10']:.4f}")
    lines.append("")
    lines.append(f"  deduplication: {report['deduplication']['status']}")
    lines.append(f"  freshness:     {report['freshness']['status']}")
    lines.append(
        "  targets: dedup P/R >= 0.90, nDCG@10 >= 0.75 (targets, not guarantees)"
    )
    return "\n".join(lines)


def main() -> int:
    report = _run_report()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(_human_summary(report))
    print(f"\nWrote {REPORT_PATH}")
    return 0
