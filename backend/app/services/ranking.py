"""M3-D production ranking: the C4 combined model (design Â§5, experiment-validated).

Combined formula, accepted as the M3-D production ranking model and NOT to be
tuned (the experiment is the reference, preserved in ``eval/ranking_eval.py``
and reproduced bit-for-bit by the eval tests):

    score = w_rel * relevance + w_fresh * freshness + w_qual * quality

* relevance: the naive lexical baseline (M3-A0, ADR 0007 core) - query terms
  in the title weigh 3, in the description weigh 1, min-max normalised per
  search;
* freshness: the M3-C production scorer (``app.services.freshness``);
* quality: design Â§5 constants (Guardian 0.90, Wikipedia 0.80, Reddit 0.50,
  arXiv 0.75, GitHub 0.70, "Global Wire" 0.85 documented placeholder,
  unknown 0.50);
* weights: news/social (0.55, 0.30, 0.15), reference (0.65, 0.10, 0.25),
  research (0.60, 0.20, 0.20), code (0.60, 0.15, 0.25), qa (0.60, 0.20, 0.20);
* diversity: within a Â±0.05 score band, source types alternate round-robin;
* total order: score desc, source-type priority (news < social < reference <
  research < code < qa), published_at desc (None last), URL lexicographic;
* duplicate awareness: members of a duplicate group inherit the canonical
  member's score (canonical = the member with ``is_duplicate`` False); the
  canonical's fields drive the group score, members keep their own
  tie-break keys.

BM25 is not used (ADR 0007). ``rank_items`` is pure and deterministic for a
fixed ``now``; the pipeline persists ``rank_score`` / ``rank_components`` at
search completion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.freshness import freshness_score

BAND_WIDTH = 0.05

SOURCE_QUALITY = {
    "The Guardian": 0.90,
    "Wikipedia": 0.80,
    "arXiv": 0.75,  # M22.1: moderated preprint repository (not peer-reviewed)
    "GitHub": 0.70,  # M22.2: hosts everything from toys to critical infra (stars NOT a signal)
    "Stack Overflow": 0.75,  # M22.3: moderated + score-voted Q&A (per-item variance, NOT a signal)
    "Global Wire": 0.85,  # corpus-only placeholder (no real second news source yet)
}
SOCIAL_QUALITY = 0.50
REFERENCE_QUALITY = 0.80
RESEARCH_QUALITY = 0.75
CODE_QUALITY = 0.70
QA_QUALITY = 0.75
UNKNOWN_QUALITY = 0.50

TYPE_PRIORITY = {"news": 0, "social": 1, "reference": 2, "research": 3, "code": 4, "qa": 5}

WEIGHTS = {
    "news": (0.55, 0.30, 0.15),
    "social": (0.55, 0.30, 0.15),
    "reference": (0.65, 0.10, 0.25),
    # M22.1 (ADR 0018): between news and reference - relevance dominates,
    # freshness carries real weight (papers have genuine dates and recency
    # matters in fast-moving fields), quality moderate.
    "research": (0.60, 0.20, 0.20),
    # M22.2 (ADR 0019): maintenance recency is a weak signal; fit dominates.
    "code": (0.60, 0.15, 0.25),
    # M22.3 (ADR 0020): knowledge artifacts with moderate version drift.
    "qa": (0.60, 0.20, 0.20),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Rankable:
    """A rankable result (maps 1:1 from a ``Result`` row)."""

    id: str
    title: str
    description: str | None = None
    source_type: str = "news"
    source_name: str = ""
    published_at: datetime | None = None
    url: str = ""
    duplicate_group_id: str | None = None
    is_duplicate: bool = False


@dataclass(frozen=True)
class RankedRow:
    """One ranked result: final score plus the three components."""

    id: str
    score: float
    relevance: float
    freshness: float
    quality: float


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _baseline_score(title: str, description: str | None, query_terms: list[str]) -> int:
    title_terms = _tokenize(title)
    desc_terms = _tokenize(description or "")
    score = 0
    for term in query_terms:
        if term in title_terms:
            score += 3
        if term in desc_terms:
            score += 1
    return score


def source_quality(source_type: str, source_name: str) -> float:
    if source_name in SOURCE_QUALITY:
        return SOURCE_QUALITY[source_name]
    if source_type == "reference":
        return REFERENCE_QUALITY
    if source_type == "social":
        return SOCIAL_QUALITY
    if source_type == "research":
        return RESEARCH_QUALITY
    if source_type == "code":
        return CODE_QUALITY
    if source_type == "qa":
        return QA_QUALITY
    return UNKNOWN_QUALITY


def doc_key(title: str, description: str | None) -> str:
    """Canonical document text key (matches the M10 embedding generator)."""
    return f"{title}. {description}" if description else title

def _ts_key(published_at: datetime | None) -> tuple[int, float]:
    if published_at is None:
        return (1, 0.0)  # missing timestamps sort last (ascending key)
    ts = published_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)  # naive datetimes are assumed UTC
    return (0, -ts.timestamp())  # newer first


def _diversity_alternate(rows: list[dict], band_width: float = BAND_WIDTH) -> list[dict]:
    """Within each Â±band score band, alternate source types (round-robin)."""
    out: list[dict] = []
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and rows[i]["score"] - rows[j]["score"] <= band_width:
            j += 1
        band = rows[i:j]
        by_type: dict[int, list[dict]] = {}
        for row in band:
            by_type.setdefault(TYPE_PRIORITY.get(row["source_type"], 9), []).append(row)
        for priority in sorted(by_type):
            by_type[priority].sort(key=lambda r: (r["ts_key"], r["url"]))
        emitted = 0
        while emitted < len(band):
            for priority in sorted(by_type):
                if by_type[priority]:
                    out.append(by_type[priority].pop(0))
                    emitted += 1
        i = j
    return out


def rank_items(
    items: list[Rankable],
    query: str,
    *,
    now: datetime | None = None,
    semantic_scores: dict[str, float] | None = None,
) -> list[RankedRow]:
    """Rank items by the validated C4 model, returning rows in final order.

    ``now`` is forwarded to the freshness scorer (``None`` = real clock), so
    the order is fully deterministic for a fixed instant. Duplicate group
    members inherit the canonical member's score; the canonical's fields
    drive relevance, freshness and quality for the whole group.

    M11.1 (ADR 0012): when ``semantic_scores`` (item id -> cosine) is provided,
    relevance becomes the pre-registered SEM1 blend
    ``0.70 * lexical + 0.30 * semantic(min-max)``. Freshness/quality weights,
    diversity, tie-breaks and dedup inheritance are unchanged; omitting the
    parameter reproduces pure C4 exactly.
    """
    canonical_by_group: dict[str, Rankable] = {}
    for item in items:
        if item.duplicate_group_id is not None and not item.is_duplicate:
            canonical_by_group.setdefault(item.duplicate_group_id, item)

    query_terms = sorted(_tokenize(query))
    raw = [_baseline_score(item.title, item.description, query_terms) for item in items]
    max_raw = max(raw) if raw else 0
    raw_by_id = {item.id: raw_score for item, raw_score in zip(items, raw, strict=True)}

    sem_vals = semantic_scores or {}
    sem_span = None
    if sem_vals:
        smin = min(sem_vals.values())
        smax = max(sem_vals.values())
        sem_span = smax - smin

    def _sem_norm(item_id: str) -> float:
        value = sem_vals.get(item_id)
        if value is None or not sem_span:
            return 0.0
        return (value - smin) / sem_span

    rows: list[dict] = []
    for item in items:
        effective = (
            canonical_by_group.get(item.duplicate_group_id, item)
            if item.duplicate_group_id
            else item
        )
        lexical_relevance = raw_by_id[effective.id] / max_raw if max_raw else 0.0
        relevance = (
            0.70 * lexical_relevance + 0.30 * _sem_norm(item.id)
            if semantic_scores is not None
            else lexical_relevance
        )
        freshness = freshness_score(effective.published_at, effective.source_type, now=now)
        quality = source_quality(effective.source_type, effective.source_name)
        w_rel, w_fresh, w_qual = WEIGHTS.get(effective.source_type, WEIGHTS["news"])
        rows.append(
            {
                "id": item.id,
                "score": w_rel * relevance + w_fresh * freshness + w_qual * quality,
                "relevance": relevance,
                "freshness": freshness,
                "quality": quality,
                "source_type": item.source_type,
                "ts_key": _ts_key(item.published_at),
                "url": item.url,
            }
        )

    rows.sort(
        key=lambda r: (
            -r["score"],
            TYPE_PRIORITY.get(r["source_type"], 9),
            r["ts_key"],
            r["url"],
        )
    )
    rows = _diversity_alternate(rows)
    return [
        RankedRow(
            id=r["id"],
            score=r["score"],
            relevance=r["relevance"],
            freshness=r["freshness"],
            quality=r["quality"],
        )
        for r in rows
    ]