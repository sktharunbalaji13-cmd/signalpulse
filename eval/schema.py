"""Pydantic schema and validation for the SignalPulse offline evaluation corpus.

The corpus is authored deterministically in :mod:`eval.corpus` (see the note
there on why Python data structures are used instead of hand-authored JSON).
This module defines the shape every item/query/duplicate-group must satisfy and
the cross-record invariants (unique ids, valid references, one-group-per-item).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

RELEVANCE_LABELS: set[int] = {0, 1, 2}
SOURCE_TYPES: set[str] = {"news", "social", "reference", "video"}


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; ``Z`` normalised to UTC offset (naive)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class EvalItem(BaseModel):
    """One fixed result in the corpus with its gold relevance label."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    description: str = ""
    url: str
    source_type: str
    source_name: str = Field(min_length=1)
    author: str | None = None
    published_at: str | None = None
    retrieved_at: str
    relevance: int = 0

    @field_validator("source_type")
    @classmethod
    def _valid_source_type(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError(f"unknown source_type {value!r}")
        return value

    @field_validator("relevance")
    @classmethod
    def _valid_relevance(cls, value: int) -> int:
        if value not in RELEVANCE_LABELS:
            raise ValueError(f"relevance must be 0, 1 or 2, got {value}")
        return value

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        if not value.startswith("http"):
            raise ValueError(f"url must be absolute http(s), got {value!r}")
        return value

    @field_validator("published_at")
    @classmethod
    def _valid_published_at(cls, value: str | None) -> str | None:
        if value is not None:
            _parse_ts(value)
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _valid_retrieved_at(cls, value: str) -> str:
        _parse_ts(value)
        return value


class EvalQuery(BaseModel):
    """One query with its fixed candidate set and gold relevance labels."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    query: str = Field(min_length=1)
    items: list[EvalItem] = Field(min_length=1)


class DuplicateGroup(BaseModel):
    """A gold duplicate cluster: item ids that describe the same underlying page/story.

    ``label`` is a free-text description of the underlying story and the
    relationship kinds it demonstrates (e.g. cross-outlet + URL variant).
    """

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    members: list[str] = Field(min_length=2)


class EvalCorpus(BaseModel):
    """The full validated corpus: queries, gold duplicate clusters, ambiguous pairs.

    ``ambiguous_pairs`` are item-id pairs that genuinely require judgment (e.g.
    a social discussion post vs the news article it discusses). They are neither
    asserted true duplicates nor asserted non-duplicates, and are excluded from
    dedup precision/recall/F1 scoring.
    """

    synthetic: bool = True
    revision: int = 1
    queries: list[EvalQuery]
    duplicate_groups: list[DuplicateGroup]
    ambiguous_pairs: list[list[str]] = []


def validate_corpus(corpus: EvalCorpus) -> EvalCorpus:
    """Run cross-record validation and return the corpus (raising on violations)."""
    items_by_query: dict[str, dict[str, EvalItem]] = {
        q.id: {item.id: item for item in q.items} for q in corpus.queries
    }
    seen_item_ids: set[str] = set()
    for query in corpus.queries:
        for item in query.items:
            if item.id in seen_item_ids:
                raise ValueError(f"duplicate item id {item.id!r} across corpus")
            seen_item_ids.add(item.id)

    item_to_group: dict[str, str] = {}
    for group in corpus.duplicate_groups:
        if len(set(group.members)) != len(group.members):
            raise ValueError(f"duplicate group {group.id!r} has repeated members")
        query_id: str | None = None
        for member_id in group.members:
            owner = next(
                (qid for qid, items in items_by_query.items() if member_id in items),
                None,
            )
            if owner is None:
                raise ValueError(
                    f"duplicate group {group.id!r} references unknown item {member_id!r}"
                )
            if query_id is None:
                query_id = owner
            elif owner != query_id:
                raise ValueError(
                    f"duplicate group {group.id!r} spans multiple queries (dedup is per-search)"
                )
            if member_id in item_to_group:
                raise ValueError(
                    f"item {member_id!r} belongs to multiple duplicate groups "
                    f"({item_to_group[member_id]!r} and {group.id!r})"
                )
            item_to_group[member_id] = group.id

    for pair in corpus.ambiguous_pairs:
        if len(pair) != 2 or len(set(pair)) != 2:
            raise ValueError(f"ambiguous pair {pair!r} must contain two distinct item ids")
        query_id: str | None = None
        for member_id in pair:
            owner = next(
                (qid for qid, items in items_by_query.items() if member_id in items),
                None,
            )
            if owner is None:
                raise ValueError(f"ambiguous pair {pair!r} references unknown item {member_id!r}")
            if query_id is None:
                query_id = owner
            elif owner != query_id:
                raise ValueError(f"ambiguous pair {pair!r} spans multiple queries")
    return corpus
