"""Schema and corpus validation tests (offline, deterministic)."""

import pytest
from pydantic import ValidationError

from eval import corpus
from eval.runner import _build_corpus
from eval.schema import DuplicateGroup, EvalCorpus, EvalItem, validate_corpus

RETRIEVED = "2026-08-19T12:00:00Z"


def _item(iid: str, **overrides) -> dict:
    base = {
        "id": iid,
        "title": f"title {iid}",
        "description": "",
        "url": f"https://news.example/{iid}",
        "source_type": "news",
        "source_name": "The Guardian",
        "retrieved_at": RETRIEVED,
        "relevance": 0,
    }
    base.update(overrides)
    return base


def _group(gid: str, members: list[str], label: str = "story") -> dict:
    return {"id": gid, "label": label, "members": members}


def test_corpus_loads_and_validates():
    data = _build_corpus()
    assert len(data.queries) == 16
    assert all(len(q.items) >= 20 for q in data.queries)
    total = sum(len(q.items) for q in data.queries)
    assert total >= 360
    assert len(data.duplicate_groups) >= 16
    assert len(data.ambiguous_pairs) >= 1
    assert data.revision == 2


def test_relevance_labels_are_valid_in_corpus():
    data = _build_corpus()
    for query in data.queries:
        for item in query.items:
            assert item.relevance in {0, 1, 2}


def test_relevance_label_rejects_invalid():
    with pytest.raises(ValidationError):
        EvalItem(**_item("x", relevance=3))
    with pytest.raises(ValidationError):
        EvalItem(**_item("x", relevance=-1))


def test_source_type_rejects_invalid():
    with pytest.raises(ValidationError):
        EvalItem(**_item("x", source_type="blog"))


def test_url_must_be_absolute_http():
    with pytest.raises(ValidationError):
        EvalItem(**_item("x", url="example.com/not-http"))


def test_duplicate_group_label_required():
    with pytest.raises(ValidationError):
        DuplicateGroup(id="g", label="", members=["a", "b"])


def test_duplicate_group_unknown_member_rejected():
    c = EvalCorpus(
        queries=[{"id": "q", "query": "test", "items": [_item("q_1")]}],
        duplicate_groups=[_group("g", ["q_1", "q_2"])],
    )
    with pytest.raises(ValueError, match="unknown item"):
        validate_corpus(c)


def test_duplicate_group_repeated_members_rejected():
    c = EvalCorpus(
        queries=[{"id": "q", "query": "test", "items": [_item("q_1")]}],
        duplicate_groups=[_group("g", ["q_1", "q_1"])],
    )
    with pytest.raises(ValueError, match="repeated members"):
        validate_corpus(c)


def test_duplicate_group_cannot_span_queries():
    c = EvalCorpus(
        queries=[
            {"id": "q1", "query": "a", "items": [_item("q1_1")]},
            {"id": "q2", "query": "b", "items": [_item("q2_1")]},
        ],
        duplicate_groups=[_group("g", ["q1_1", "q2_1"])],
    )
    with pytest.raises(ValueError, match="spans multiple queries"):
        validate_corpus(c)


def test_item_cannot_belong_to_multiple_groups():
    c = EvalCorpus(
        queries=[{"id": "q", "query": "a", "items": [_item("q_1"), _item("q_2")]}],
        duplicate_groups=[
            _group("g1", ["q_1", "q_2"]),
            _group("g2", ["q_1", "q_2"], label="second"),
        ],
    )
    with pytest.raises(ValueError, match="multiple duplicate groups"):
        validate_corpus(c)


def test_ambiguous_pair_unknown_member_rejected():
    c = EvalCorpus(
        queries=[{"id": "q", "query": "a", "items": [_item("q_1")]}],
        duplicate_groups=[],
        ambiguous_pairs=[["q_1", "q_9"]],
    )
    with pytest.raises(ValueError, match="unknown item"):
        validate_corpus(c)


def test_ambiguous_pair_must_be_two_distinct_ids():
    c = EvalCorpus(
        queries=[{"id": "q", "query": "a", "items": [_item("q_1"), _item("q_2")]}],
        duplicate_groups=[],
        ambiguous_pairs=[["q_1", "q_1"]],
    )
    with pytest.raises(ValueError, match="two distinct"):
        validate_corpus(c)


def test_ambiguous_pair_cannot_span_queries():
    c = EvalCorpus(
        queries=[
            {"id": "q1", "query": "a", "items": [_item("q1_1")]},
            {"id": "q2", "query": "b", "items": [_item("q2_1")]},
        ],
        duplicate_groups=[],
        ambiguous_pairs=[["q1_1", "q2_1"]],
    )
    with pytest.raises(ValueError, match="spans multiple queries"):
        validate_corpus(c)


def test_gold_groups_reference_items_in_same_query():
    data = _build_corpus()
    items_by_query = {q.id: {i.id for i in q.items} for q in data.queries}
    for group in data.duplicate_groups:
        owners = {qid for qid, ids in items_by_query.items() if set(group.members) & ids}
        assert len(owners) == 1


def test_corpus_contains_required_relationship_categories():
    data = _build_corpus()
    items = {i.id: i for q in data.queries for i in q.items}

    group_member_sets = [set(g.members) for g in data.duplicate_groups]

    # exact URL duplicate
    assert any(
        items[m1].url == items[m2].url
        for members in group_member_sets
        for m1 in members
        for m2 in members
        if m1 < m2
    ), "exact URL duplicate missing"

    # cross-outlet (two source names in one cluster)
    assert any(
        len({items[m].source_name for m in members}) >= 2 for members in group_member_sets
    ), "cross-outlet duplicate missing"

    # mobile/AMP subdomain variant
    assert any(
        (".amp." in items[m].url or items[m].url.startswith("https://m."))
        for members in group_member_sets
        for m in members
    ), "mobile/AMP variant missing"

    # boilerplate suffix title in a cluster
    boilerplate = [
        i.id
        for q in data.queries
        for i in q.items
        if "— The Guardian" in i.title
    ]
    assert boilerplate, "boilerplate-suffix title missing from corpus"
    assert any(m in set().union(*group_member_sets) for m in boilerplate), (
        "boilerplate-suffix title not in a duplicate cluster"
    )


def test_ambiguous_pairs_are_cross_type():
    data = _build_corpus()
    items = {i.id: i for q in data.queries for i in q.items}
    for pair in data.ambiguous_pairs:
        types = {items[pid].source_type for pid in pair}
        assert types == {"news", "social"}


def test_decoys_are_never_merged():
    data = _build_corpus()
    group_members = {m for g in data.duplicate_groups for m in g.members}
    decoys = [i.id for q in data.queries for i in q.items if i.title.lower() == "update"]
    assert decoys, "corpus must contain generic-title 'Update' decoys"
    assert not (set(decoys) & group_members), "decoys must never be in a group"


def test_each_query_has_relevance_spread():
    data = _build_corpus()
    for query in data.queries:
        labels = {i.relevance for i in query.items}
        assert 2 in labels and 0 in labels, f"{query.id} lacks relevance spread"


def test_corpus_has_missing_and_present_timestamps():
    data = _build_corpus()
    has_missing = any(i.published_at is None for q in data.queries for i in q.items)
    has_present = any(i.published_at is not None for q in data.queries for i in q.items)
    assert has_missing and has_present


def test_corpus_source_types_covered():
    data = _build_corpus()
    types = {i.source_type for q in data.queries for i in q.items}
    assert {"news", "social", "reference"} <= types


def test_corpus_is_marked_synthetic():
    data = _build_corpus()
    assert data.synthetic is True
    assert corpus.QUERIES
