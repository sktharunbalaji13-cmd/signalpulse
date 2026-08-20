"""BM25 relevance scoring (M3-B), per design §3.

**EXPERIMENTAL RESEARCH ARTIFACT — NOT PRODUCTION RANKING (ADR 0007).**

BM25 was measured against the v2 corpus as the relevance core and REJECTED
(per-search IDF over n≈23 topic-dense candidates down-weights the central terms
and promotes rare-term decoys; nDCG 0.5674 vs baseline 0.6909, best variant
title-only 0.6263). This module is preserved as evidence only: it is not wired
into the pipeline and must not be treated as the production ranker.

The documented formulation: k1 = 1.5, b = 0.75, smoothed IDF
``ln(1 + (N - n + 0.5) / (n + 0.5))``, score = 2·bm25(title) + 1·bm25(description),
self-match normalization, optional exact-match bonuses, deterministic total
order. Freshness and the weighted final ranking are NOT here (M3-C/M3-D).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

# Minimal stopword list only (design §3: "no LLM, no embeddings").
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "to", "was", "with",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_SOURCE_TYPE_PRIORITY = {"news": 0, "social": 1, "reference": 2, "video": 3}

K1 = 1.5
B = 0.75
TITLE_WEIGHT = 2.0
DESCRIPTION_WEIGHT = 1.0


@dataclass(frozen=True)
class RankCandidate:
    """Minimal ranker input: the fields relevance scoring needs, nothing more."""

    id: str
    title: str
    description: str | None = None
    source_type: str = "news"
    published_at: datetime | None = None
    url: str = ""


def tokenize(text: str) -> list[str]:
    """Lowercase ``[a-z0-9]`` tokens with the minimal stopword list removed."""
    return [tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS]


def _bm25(
    freqs: Counter[str, int],
    length: int,
    avgdl: float,
    terms: Iterable[str],
    idf_of: callable,
    k1: float,
    b: float,
) -> float:
    """The BM25 term-saturation formula for one document."""
    denom = 1.0
    if avgdl > 0:
        denom = 1 - b + b * (length / avgdl)
    total = 0.0
    for term in terms:
        tf = freqs.get(term, 0)
        if tf == 0:
            continue
        total += idf_of(term) * (tf * (k1 + 1)) / (tf + k1 * denom)
    return total


class BM25Field:
    """BM25 over one text field (title or description) of the result set."""

    def __init__(self, documents: Sequence[str], k1: float = K1, b: float = B) -> None:
        self.k1 = k1
        self.b = b
        self._freqs: list[Counter[str, int]] = []
        self._lengths: list[int] = []
        self._df: Counter[str, int] = Counter()
        for text in documents:
            freqs = Counter(tokenize(text))
            self._freqs.append(freqs)
            self._lengths.append(sum(freqs.values()))
            self._df.update(freqs.keys())
        self._doc_count = len(documents)
        self._avgdl = sum(self._lengths) / self._doc_count if self._doc_count else 0.0

    def idf(self, term: str) -> float:
        """Smoothed IDF: never blows up when the term is in every document."""
        n = self._df.get(term, 0)
        return math.log(1 + (self._doc_count - n + 0.5) / (n + 0.5))

    def score(self, doc_index: int, terms: Iterable[str]) -> float:
        return _bm25(
            self._freqs[doc_index],
            self._lengths[doc_index],
            self._avgdl,
            terms,
            self.idf,
            self.k1,
            self.b,
        )

    def score_text(self, text: str, terms: Iterable[str]) -> float:
        """Score a hypothetical document (the query-as-document ceiling)."""
        freqs = Counter(tokenize(text))
        return _bm25(freqs, sum(freqs.values()), self._avgdl, terms, self.idf, self.k1, self.b)


def _bonuses(query: str, candidate: RankCandidate) -> dict[str, float]:
    """Exact-match bonuses (design §3). Returns a name -> bonus map."""
    bonuses: dict[str, float] = {}
    title = candidate.title.lower()
    description = (candidate.description or "").lower()
    query_lower = query.lower().strip()

    title_tokens = [t for t in tokenize(candidate.title)]
    query_tokens = [t for t in tokenize(query)]
    if query_tokens and any(
        title_tokens[i : i + len(query_tokens)] == query_tokens
        for i in range(len(title_tokens) - len(query_tokens) + 1)
    ):
        bonuses["exact_phrase_title"] = 1.0
    if query_lower and query_lower in title:
        bonuses["query_substring_title"] = 0.75
    if query_lower and query_lower in description:
        bonuses["query_substring_description"] = 0.35
    if query_tokens and all(token in title_tokens for token in query_tokens):
        bonuses["all_terms_title"] = 0.5
    return bonuses


def score_candidates(
    candidates: Sequence[RankCandidate],
    query: str,
    *,
    include_bonuses: bool = True,
) -> dict[str, dict[str, float]]:
    """Return ``{candidate_id: {"relevance": float, "components": {...}}}``.

    ``components`` always carries ``bm25_title`` / ``bm25_description`` /
    ``base_relevance``; with ``include_bonuses`` it additionally carries each
    exact-match bonus that fired. Deterministic.
    """
    titles = [c.title for c in candidates]
    descriptions = [c.description or "" for c in candidates]
    title_field = BM25Field(titles)
    description_field = BM25Field(descriptions)
    terms = tokenize(query)

    query_doc = query
    ceiling = (
        TITLE_WEIGHT * title_field.score_text(query_doc, terms)
        + DESCRIPTION_WEIGHT * description_field.score_text(query_doc, terms)
    )

    result: dict[str, dict[str, float]] = {}
    for index, candidate in enumerate(candidates):
        bm25_title = title_field.score(index, terms)
        bm25_description = description_field.score(index, terms)
        base = TITLE_WEIGHT * bm25_title + DESCRIPTION_WEIGHT * bm25_description
        base_rel = (base / ceiling) if ceiling > 0 else 0.0
        components: dict[str, float] = {
            "bm25_title": bm25_title,
            "bm25_description": bm25_description,
            "base_relevance": base_rel,
        }
        bonus_total = 0.0
        if include_bonuses:
            for name, value in _bonuses(query, candidate).items():
                components[name] = value
                bonus_total += value
        result[candidate.id] = {
            "relevance": min(1.0, base_rel + bonus_total),
            "components": components,
        }
    return result


def rank(
    candidates: Sequence[RankCandidate],
    query: str,
    *,
    include_bonuses: bool = True,
) -> list[str]:
    """Return candidate ids ordered by descending relevance, deterministically.

    Tie-break (arrival-order-proof): source-type priority → ``published_at``
    desc (unknown last) → URL lexicographic → id.
    """
    scored = score_candidates(candidates, query, include_bonuses=include_bonuses)

    def key(candidate: RankCandidate) -> tuple:
        published_key = candidate.published_at.timestamp() if candidate.published_at else -1
        return (
            -scored[candidate.id]["relevance"],
            _SOURCE_TYPE_PRIORITY.get(candidate.source_type, 9),
            -published_key,
            candidate.url,
            candidate.id,
        )

    ordered = sorted(candidates, key=key)
    return [candidate.id for candidate in ordered]
