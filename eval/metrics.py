"""Evaluation metrics and freshness-invariant checks for the SignalPulse harness.

All functions are pure and deterministic (no clock, no randomness). Timestamps
are UTC ISO-8601 strings; parsing normalises ``Z`` to a UTC offset.

Ranking metrics use graded relevance labels 0/1/2:
* Precision@k counts items with relevance >= 1 as "relevant".
* nDCG uses gain ``2^rel - 1`` and a log2 discount (TREC convention).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

# Fixed reference instant for freshness checks (matches the corpus retrieval time).
_FIXED_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


def _relevant(rel: int) -> bool:
    return rel >= 1


def _gain(rel: int) -> float:
    return float((2 ** rel) - 1)


def precision_at_k(ranked_ids: list[str], gold_relevance: dict[str, int], k: int) -> float:
    """Fraction of the top-k items that are relevant (rel >= 1)."""
    if k <= 0:
        return 0.0
    top = ranked_ids[:k]
    hits = sum(1 for item_id in top if _relevant(gold_relevance.get(item_id, 0)))
    return hits / k


def reciprocal_rank(ranked_ids: list[str], gold_relevance: dict[str, int]) -> float:
    """Reciprocal of the 1-indexed rank of the first relevant item; 0 if none."""
    for rank, item_id in enumerate(ranked_ids, start=1):
        if _relevant(gold_relevance.get(item_id, 0)):
            return 1.0 / rank
    return 0.0


def dcg_at_k(ranked_ids: list[str], gold_relevance: dict[str, int], k: int) -> float:
    total = 0.0
    for i, item_id in enumerate(ranked_ids[:k], start=1):
        total += _gain(gold_relevance.get(item_id, 0)) / math.log2(i + 1)
    return total


def ndcg_at_k(ranked_ids: list[str], gold_relevance: dict[str, int], k: int) -> float:
    """nDCG@k with graded gain 2^rel - 1; 0.0 when the ideal ordering has no gain."""
    ideal = sorted(gold_relevance.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal, start=1):
        idcg += _gain(rel) / math.log2(i + 1)
    if idcg == 0.0:
        return 0.0
    return dcg_at_k(ranked_ids, gold_relevance, k) / idcg


def ranking_metrics(ranked_ids: list[str], gold_relevance: dict[str, int]) -> dict[str, float]:
    """Compute P@5, P@10, MRR and nDCG@10 for one ranked query result."""
    return {
        "precision_at_5": precision_at_k(ranked_ids, gold_relevance, 5),
        "precision_at_10": precision_at_k(ranked_ids, gold_relevance, 10),
        "reciprocal_rank": reciprocal_rank(ranked_ids, gold_relevance),
        "ndcg_at_10": ndcg_at_k(ranked_ids, gold_relevance, 10),
    }


def _to_pair_set(pairs: list[tuple[str, str]] | list[list[str]]) -> set[frozenset[str]]:
    return {frozenset((a, b)) for a, b in pairs}


def dedup_metrics(
    gold_pairs: list[tuple[str, str]],
    predicted_pairs: list[tuple[str, str]],
    ambiguous_pairs: list[tuple[str, str]] | None = None,
) -> dict[str, float | int]:
    """Precision/recall/F1 over true-duplicate pairs.

    Ambiguous pairs are removed from BOTH the gold and predicted sets before
    scoring, so they neither help nor hurt the numbers.
    """
    ambiguous = _to_pair_set(ambiguous_pairs or [])
    gold = _to_pair_set(gold_pairs) - ambiguous
    predicted = _to_pair_set(predicted_pairs) - ambiguous

    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)

    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
    }


def expand_groups_to_pairs(groups: list[dict]) -> list[tuple[str, str]]:
    """Expand gold duplicate groups (lists of member ids) into unordered pairs."""
    pairs: list[tuple[str, str]] = []
    for group in groups:
        members = group["members"]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.append((members[i], members[j]))
    return pairs


# --- Freshness invariant checks (used by M3-C; defined and tested here) ---
# scorer(published_at: str | None, retrieved_at: str, source_type: str) -> float


def check_freshness(
    scorer: Callable[[str | None, str, str], float],
) -> dict[str, bool | float]:
    """Evaluate a freshness scorer against the invariants M3-C must satisfy.

    Returns a dict of invariant name -> passed (bool), plus a couple of raw
    per-type reference scores for inspection.
    """
    # 1. missing timestamp is handled without error and returns a bounded score.
    try:
        missing_news = scorer(None, "2026-08-19T12:00:00Z", "news")
        missing_handled = isinstance(missing_news, (int, float)) and 0.0 <= missing_news <= 1.0
    except Exception:  # noqa: BLE001 - invariant is "must not raise"
        missing_news = float("nan")
        missing_handled = False

    # 2. retrieved_at must not substitute for published_at.
    score_r1 = scorer(None, "2026-08-19T12:00:00Z", "news")
    score_r2 = scorer(None, "2026-07-01T12:00:00Z", "news")
    no_retrieved_substitution = score_r1 == score_r2

    # 3. monotonic non-increasing with age (older -> no higher score).
    ages = [1.0, 24.0, 48.0, 168.0]
    scores = [scorer(_iso_hours_ago(a), "2026-08-19T12:00:00Z", "news") for a in ages]
    monotonic = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    # 4. future timestamps are clamped (never better than "now").
    now_score = scorer("2026-08-19T12:00:00Z", "2026-08-19T12:00:00Z", "news")
    future_score = scorer("2026-08-20T12:00:00Z", "2026-08-19T12:00:00Z", "news")
    future_clamped = future_score <= now_score + 1e-9

    return {
        "missing_timestamp_handled": missing_handled,
        "no_retrieved_substitution": no_retrieved_substitution,
        "monotonic_with_age": monotonic,
        "future_clamped": future_clamped,
        "reference_missing_ts_score": scorer(None, "2026-08-19T12:00:00Z", "reference"),
        "news_missing_ts_score": missing_news,
    }


def _iso_hours_ago(hours: float) -> str:
    dt = _FIXED_NOW - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


FRESHNESS_INVARIANTS: list[dict[str, str]] = [
    {
        "name": "missing_timestamp_handled",
        "description": (
            "A result with no published_at still receives a bounded score in "
            "[0,1] without error."
        ),
    },
    {
        "name": "no_retrieved_substitution",
        "description": (
            "retrieved_at never influences freshness: two different retrieval "
            "times yield identical scores."
        ),
    },
    {
        "name": "monotonic_with_age",
        "description": (
            "Freshness is non-increasing with age: an older item never scores "
            "higher than a newer one."
        ),
    },
    {
        "name": "future_clamped",
        "description": (
            "Future timestamps are clamped: they never score better than the "
            "present instant."
        ),
    },
]
