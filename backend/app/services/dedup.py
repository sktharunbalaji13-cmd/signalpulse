"""Duplicate detection: exact (M3-A2) and fuzzy (M3-A3).

Exact duplicates are detected when two candidates share a canonical URL
(Level A) or a normalized title AND the same source type (Level B). Fuzzy
duplicates add a conservative, multi-signal rule (M3-A3): near-identical titles
alone are **not** enough — the detector also requires the same source type,
a sufficiently informative (non-generic) title, and publication-time proximity
when both timestamps are known.

Each :class:`DuplicateGroup` records the ``methods`` that produced it
(``canonical_url`` / ``normalized_title`` / ``fuzzy_title``) so every merge is
explainable. Groups are connected components over the union of all edge kinds.

:func:`detect_duplicates` is the production entry point (exact + fuzzy in one
pass); :func:`select_canonical` picks the deterministic representative. No
persistence (M3-A4), no pipeline wiring, no ranking here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations

from rapidfuzz import fuzz

from app.services.canonicalize import canonicalize_url, normalize_title

URL_METHOD = "canonical_url"
TITLE_METHOD = "normalized_title"
FUZZY_METHOD = "fuzzy_title"

# Fuzzy matching applies only within these source types and requires the two
# candidates to share one. Reference results are excluded (they describe
# topics, not events; the design merges them only on exact URL).
_FUZZY_SOURCE_TYPES = {"news", "social"}

# Generic titles ("Update", "Statement", ...) must never be fuzzy-merged.
_MIN_TITLE_TOKENS = 3

# Canonical selection prefers news > social > reference when timestamps and
# description length do not already decide.
_SOURCE_TYPE_PRIORITY = {"news": 0, "social": 1, "reference": 2}


@dataclass(frozen=True)
class Candidate:
    """A minimal dedup input: the fields the detector needs, nothing more."""

    id: str
    url: str
    title: str
    source_type: str
    published_at: datetime | None = None
    description: str | None = None


@dataclass(frozen=True)
class DuplicateGroup:
    """A set of candidates that describe the same underlying page/story."""

    members: tuple[str, ...]
    methods: frozenset[str]


def _connected_components(n: int, pairs: Iterable[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for a, b in pairs:
        union(a, b)

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)
    return list(components.values())


def _build_groups(
    candidates: list[Candidate],
    components: list[list[int]],
    pair_sets: dict[str, set[frozenset[int]]],
) -> list[DuplicateGroup]:
    groups: list[DuplicateGroup] = []
    for indices in components:
        if len(indices) < 2:
            continue
        member_ids = tuple(sorted(candidates[i].id for i in indices))
        methods: set[str] = set()
        for a, b in combinations(indices, 2):
            for method, pairs in pair_sets.items():
                if frozenset((a, b)) in pairs:
                    methods.add(method)
        groups.append(DuplicateGroup(members=member_ids, methods=frozenset(methods)))
    groups.sort(key=lambda group: group.members)
    return groups


def _exact_pair_sets(candidates: list[Candidate]) -> tuple[set, set]:
    canon = [canonicalize_url(c.url) for c in candidates]
    norm_title = [normalize_title(c.title) for c in candidates]

    url_pairs: set[frozenset[int]] = set()
    title_pairs: set[frozenset[int]] = set()

    by_url: dict[str, list[int]] = {}
    for i, key in enumerate(canon):
        by_url.setdefault(key, []).append(i)
    for indices in by_url.values():
        for a, b in combinations(indices, 2):
            url_pairs.add(frozenset((a, b)))

    by_title: dict[tuple[str, str], list[int]] = {}
    for i in range(len(candidates)):
        if not norm_title[i]:
            continue
        key = (norm_title[i], candidates[i].source_type)
        by_title.setdefault(key, []).append(i)
    for indices in by_title.values():
        for a, b in combinations(indices, 2):
            title_pairs.add(frozenset((a, b)))

    return url_pairs, title_pairs


def _fuzzy_pair_sets(
    candidates: list[Candidate],
    threshold: float,
    max_age_gap: timedelta,
) -> set[frozenset[int]]:
    norm_title = [normalize_title(c.title) for c in candidates]
    fuzzy_pairs: set[frozenset[int]] = set()

    for i in range(len(candidates)):
        if candidates[i].source_type not in _FUZZY_SOURCE_TYPES:
            continue
        if len(norm_title[i].split()) < _MIN_TITLE_TOKENS:
            continue
        for j in range(i + 1, len(candidates)):
            if candidates[j].source_type != candidates[i].source_type:
                continue
            if len(norm_title[j].split()) < _MIN_TITLE_TOKENS:
                continue
            if fuzz.token_set_ratio(norm_title[i], norm_title[j]) < threshold * 100:
                continue
            if not _within_time_window(candidates[i], candidates[j], max_age_gap):
                continue
            fuzzy_pairs.add(frozenset((i, j)))

    return fuzzy_pairs


def _within_time_window(a: Candidate, b: Candidate, max_age_gap: timedelta) -> bool:
    """Return True when publication times are compatible (or unknown)."""
    published_a, published_b = a.published_at, b.published_at
    if published_a is None or published_b is None:
        return True
    return abs(published_a - published_b) <= max_age_gap


def detect_exact_duplicates(candidates: list[Candidate]) -> list[DuplicateGroup]:
    """Detect exact duplicates: canonical URL equality or normalized-title equality."""
    n = len(candidates)
    if n < 2:
        return []
    url_pairs, title_pairs = _exact_pair_sets(candidates)
    components = _connected_components(n, url_pairs | title_pairs)
    return _build_groups(
        candidates,
        components,
        {URL_METHOD: url_pairs, TITLE_METHOD: title_pairs},
    )


def detect_fuzzy_duplicates(
    candidates: list[Candidate],
    threshold: float = 0.90,
    max_age_gap_days: int = 7,
) -> list[DuplicateGroup]:
    """Detect fuzzy duplicates conservatively (M3-A3).

    Two candidates are fuzzy duplicates only when ALL hold:

    * both are ``news`` or both are ``social`` (never reference, never mixed),
    * their normalized titles have at least ``_MIN_TITLE_TOKENS`` tokens,
    * ``token_set_ratio >= threshold`` (0.90 by default — a starting point),
    * publication times are within ``max_age_gap_days`` (only enforced when
      both timestamps are known; missing timestamps carry no time evidence).

    ``threshold`` is a documented starting point, not a sacred number; tune it
    against the eval corpus, not by hand.
    """
    n = len(candidates)
    if n < 2:
        return []
    fuzzy_pairs = _fuzzy_pair_sets(candidates, threshold, timedelta(days=max_age_gap_days))
    components = _connected_components(n, fuzzy_pairs)
    return _build_groups(candidates, components, {FUZZY_METHOD: fuzzy_pairs})


def detect_duplicates(
    candidates: list[Candidate],
    *,
    fuzzy_threshold: float = 0.90,
    max_age_gap_days: int = 7,
) -> list[DuplicateGroup]:
    """Detect exact + fuzzy duplicates in a single pass (production entry point).

    Groups are connected components over the union of URL, title, and fuzzy
    edges, with ``methods`` recording every signal that contributed.
    """
    n = len(candidates)
    if n < 2:
        return []
    url_pairs, title_pairs = _exact_pair_sets(candidates)
    fuzzy_pairs = _fuzzy_pair_sets(
        candidates, fuzzy_threshold, timedelta(days=max_age_gap_days)
    )
    components = _connected_components(n, url_pairs | title_pairs | fuzzy_pairs)
    return _build_groups(
        candidates,
        components,
        {URL_METHOD: url_pairs, TITLE_METHOD: title_pairs, FUZZY_METHOD: fuzzy_pairs},
    )


def select_canonical(members: list[Candidate]) -> str:
    """Return the deterministic representative of a duplicate group.

    Preference order (total, deterministic): known ``published_at`` > source
    type (news > social > reference) > longer description > URL > id.
    """

    def key(candidate: Candidate) -> tuple:
        return (
            0 if candidate.published_at is not None else 1,
            _SOURCE_TYPE_PRIORITY.get(candidate.source_type, 9),
            -len(candidate.description or ""),
            candidate.url,
            candidate.id,
        )

    return min(members, key=key).id
