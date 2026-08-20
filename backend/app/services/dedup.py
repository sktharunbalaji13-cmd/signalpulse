"""Exact duplicate detection (M3-A2).

Consumes the M3-A1 canonicalization primitives. Two candidates are exact
duplicates when:

* they share a **canonical URL** (Level A: same page, any source type), or
* they share a **normalized title AND the same source type** (Level B: same
  story; cross-type title equality alone is not trusted).

The two signals stay distinguishable in the result: each :class:`DuplicateGroup`
records the ``methods`` that produced it, so a caller always knows *why* two
results were considered duplicates.

Groups are connected components over the union of URL-equality and
title-equality edges, so a single underlying story that is both a URL duplicate
and a cross-outlet title duplicate collapses into one group.

No fuzzy matching (M3-A3), no persistence (M3-A4), no ranking here.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from app.services.canonicalize import canonicalize_url, normalize_title

URL_METHOD = "canonical_url"
TITLE_METHOD = "normalized_title"


@dataclass(frozen=True)
class Candidate:
    """A minimal dedup input: the fields the detector needs, nothing more."""

    id: str
    url: str
    title: str
    source_type: str


@dataclass(frozen=True)
class DuplicateGroup:
    """A set of candidates that describe the same underlying page/story."""

    members: tuple[str, ...]
    methods: frozenset[str]


def detect_exact_duplicates(candidates: list[Candidate]) -> list[DuplicateGroup]:
    """Return duplicate groups, sorted deterministically by their member ids.

    Deterministic and order-independent: the group *membership* is a connected
    component (independent of input order), and both ``members`` and the group
    list are sorted.
    """
    n = len(candidates)
    if n < 2:
        return []

    canon = [canonicalize_url(c.url) for c in candidates]
    norm_title = [normalize_title(c.title) for c in candidates]

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

    url_pairs: set[frozenset[int]] = set()
    title_pairs: set[frozenset[int]] = set()

    # Level A: canonical URL equality (any source type).
    by_url: dict[str, list[int]] = {}
    for i, key in enumerate(canon):
        by_url.setdefault(key, []).append(i)
    for indices in by_url.values():
        for a, b in combinations(indices, 2):
            union(a, b)
            url_pairs.add(frozenset((a, b)))

    # Level B: normalized-title equality, same source type, non-empty title.
    by_title: dict[tuple[str, str], list[int]] = {}
    for i in range(n):
        if not norm_title[i]:
            continue
        key = (norm_title[i], candidates[i].source_type)
        by_title.setdefault(key, []).append(i)
    for indices in by_title.values():
        for a, b in combinations(indices, 2):
            union(a, b)
            title_pairs.add(frozenset((a, b)))

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    groups: list[DuplicateGroup] = []
    for indices in components.values():
        if len(indices) < 2:
            continue
        member_ids = tuple(sorted(candidates[i].id for i in indices))
        methods: set[str] = set()
        for a, b in combinations(indices, 2):
            if frozenset((a, b)) in url_pairs:
                methods.add(URL_METHOD)
            if frozenset((a, b)) in title_pairs:
                methods.add(TITLE_METHOD)
        groups.append(
            DuplicateGroup(
                members=member_ids,
                methods=frozenset(methods),
            )
        )

    groups.sort(key=lambda group: group.members)
    return groups
