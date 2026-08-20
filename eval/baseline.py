"""Naive baseline ordering for the evaluation harness.

This is NOT the production ranking algorithm. It exists purely as a fixed
reference that M3-B/M3-D can be measured against: a simple lexical term-count
score with a deterministic, total tie-break.
"""

from __future__ import annotations

import re

from eval.schema import EvalItem

_SOURCE_TYPE_ORDER = {"news": 0, "social": 1, "reference": 2, "video": 3}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def baseline_score(item: EvalItem, query_terms: list[str]) -> int:
    """Term-overlap count: query terms in title weigh 3, in description weigh 1."""
    title_terms = _tokenize(item.title)
    desc_terms = _tokenize(item.description)
    score = 0
    for term in query_terms:
        if term in title_terms:
            score += 3
        if term in desc_terms:
            score += 1
    return score


def rank(items: list[EvalItem], query: str) -> list[str]:
    """Return item ids ordered by descending baseline score, deterministically."""
    query_terms = sorted(_tokenize(query))
    scored = [
        (
            -baseline_score(item, query_terms),
            _SOURCE_TYPE_ORDER.get(item.source_type, 9),
            item.title,
            item.id,
        )
        for item in items
    ]
    scored.sort()
    return [entry[3] for entry in scored]
