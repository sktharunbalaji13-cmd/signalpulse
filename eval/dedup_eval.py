"""Evaluate the M3-A dedup detector against the gold corpus (offline).

Bridges the production detector in ``backend/app/services/dedup.py`` with the
offline gold duplicate clusters in ``eval/corpus.py``. Run with::

    python -m eval.dedup_eval

Precision is the headline metric at this stage: a public site that wrongly
merges two different stories is worse than one that occasionally fails to
merge duplicates. Recall is reported honestly and is expected to trail
precision, because the corpus's cross-outlet and paraphrased pairs are
deliberately out of reach for conservative exact+fuzzy matching.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from eval import corpus, metrics
from eval.schema import EvalCorpus, validate_corpus

_BACKEND = Path(__file__).resolve().parents[1] / "backend"


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_detector():
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    from app.services.dedup import (  # noqa: PLC0415 - import after path setup
        Candidate,
        detect_exact_duplicates,
        detect_fuzzy_duplicates,
    )

    return Candidate, detect_exact_duplicates, detect_fuzzy_duplicates


def _pairs_from_groups(groups) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for group in groups:
        members = list(group.members)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.add(frozenset((members[i], members[j])))
    return pairs


def _gold_pairs_for_query(groups, item_ids: set[str]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for group in groups:
        members = [m for m in group.members if m in item_ids]
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.add(frozenset((members[i], members[j])))
    return pairs


def evaluate() -> dict:
    """Run exact+fuzzy detection on every query and score against gold clusters."""
    Candidate, detect_exact, detect_fuzzy = _load_detector()
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
    per_query: list[dict] = []

    for query in data.queries:
        item_ids = {item.id for item in query.items}
        candidates = [
            Candidate(
                id=item.id,
                url=item.url,
                title=item.title,
                source_type=item.source_type,
                published_at=_parse_ts(item.published_at),
            )
            for item in query.items
        ]
        exact = detect_exact(candidates)
        fuzzy = detect_fuzzy(candidates)
        predicted = _pairs_from_groups(exact) | _pairs_from_groups(fuzzy)
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
            }
        )

    ambiguous = [tuple(p) for p in data.ambiguous_pairs]
    gold_list = [tuple(sorted(p)) for p in all_gold]
    predicted_list = [tuple(sorted(p)) for p in all_predicted]
    result = metrics.dedup_metrics(gold_list, predicted_list, ambiguous)

    return {
        "corpus_revision": data.revision,
        "gold_cluster_count": len(data.duplicate_groups),
        "gold_pair_count": len(all_gold),
        "ambiguous_pair_count": len(ambiguous),
        "predicted_pair_count": len(all_predicted),
        "metrics": result,
        "per_query": per_query,
    }


def _human_summary(report: dict) -> str:
    m = report["metrics"]
    lines = [
        "SignalPulse dedup evaluation (M3-A3) — exact + fuzzy vs gold corpus",
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
        "  per-query gold/predicted/caught/false:",
    ]
    for q in report["per_query"]:
        lines.append(
            f"    {q['query_id']}: gold={q['gold_pairs']} predicted={q['predicted_pairs']} "
            f"caught={q['caught_pairs']} false={q['false_pairs']}"
        )
    return "\n".join(lines)


def main() -> int:
    print(_human_summary(evaluate()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
