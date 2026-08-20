"""Tests for exact duplicate detection (M3-A2). Deterministic and offline."""

from app.services.dedup import (
    TITLE_METHOD,
    URL_METHOD,
    Candidate,
    detect_exact_duplicates,
)


def _c(cid: str, url: str, title: str, source_type: str = "news") -> Candidate:
    return Candidate(id=cid, url=url, title=title, source_type=source_type)


def _members(groups) -> list[frozenset[str]]:
    return [frozenset(g.members) for g in groups]


def test_empty_and_single_candidates_produce_no_groups():
    assert detect_exact_duplicates([]) == []
    assert detect_exact_duplicates([_c("a", "https://n.example/x", "T", "news")]) == []


def test_canonical_url_equality_merges_any_source_type():
    candidates = [
        _c("a", "https://news.example/story", "News headline", "news"),
        _c("b", "https://news.example/story", "Completely different title", "social"),
    ]
    groups = detect_exact_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b"})]
    assert groups[0].methods == frozenset({URL_METHOD})


def test_url_variant_merges_via_canonical_url():
    candidates = [
        _c("a", "https://news.example/story", "Headline", "news"),
        _c("b", "https://news.example/story?utm_source=push&utm_medium=email", "Headline", "news"),
        _c("c", "https://news.example/story#comments", "Headline", "news"),
    ]
    groups = detect_exact_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b", "c"})]
    assert URL_METHOD in groups[0].methods


def test_normalized_title_equality_same_type_merges():
    candidates = [
        _c("a", "https://one.example/a", "Some Headline — The Guardian", "news"),
        _c("b", "https://two.example/b", "Some Headline", "news"),
    ]
    groups = detect_exact_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b"})]
    assert groups[0].methods == frozenset({TITLE_METHOD})


def test_same_title_different_source_type_does_not_merge():
    candidates = [
        _c("a", "https://news.example/a", "OpenAI", "news"),
        _c("b", "https://en.wikipedia.example/wiki/OpenAI", "OpenAI", "reference"),
    ]
    assert detect_exact_duplicates(candidates) == []


def test_unrelated_candidates_produce_no_groups():
    candidates = [
        _c("a", "https://n.example/1", "First story", "news"),
        _c("b", "https://n.example/2", "Second story", "news"),
        _c("c", "https://n.example/3", "Third story", "news"),
    ]
    assert detect_exact_duplicates(candidates) == []


def test_empty_title_is_never_matched():
    candidates = [
        _c("a", "https://n.example/1", "", "news"),
        _c("b", "https://n.example/2", "", "news"),
    ]
    assert detect_exact_duplicates(candidates) == []


def test_mixed_url_and_title_edges_form_one_component():
    candidates = [
        _c("a", "https://news.example/story", "Headline X", "news"),
        # b shares canonical URL with a, title with c
        _c("b", "https://news.example/story?ref=home", "Headline X", "news"),
        # c shares title with a/b
        _c("c", "https://other.example/c", "Headline X", "news"),
    ]
    groups = detect_exact_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b", "c"})]
    assert groups[0].methods == frozenset({URL_METHOD, TITLE_METHOD})


def test_duplicate_detection_is_order_independent():
    candidates = [
        _c("a", "https://news.example/story", "Headline", "news"),
        _c("b", "https://news.example/story?utm_source=push", "Headline", "news"),
        _c("c", "https://other.example/c", "Headline", "news"),
        _c("d", "https://unrelated.example/d", "Not a duplicate", "news"),
    ]
    expected = detect_exact_duplicates(candidates)
    reversed_candidates = list(reversed(candidates))
    assert detect_exact_duplicates(reversed_candidates) == expected


def test_members_and_groups_are_sorted_deterministically():
    candidates = [
        _c("b", "https://news.example/story", "Headline", "news"),
        _c("a", "https://news.example/story?utm_source=push", "Headline", "news"),
    ]
    groups = detect_exact_duplicates(candidates)
    assert groups[0].members == ("a", "b")


def test_two_distinct_groups_are_returned_separately():
    candidates = [
        _c("a", "https://news.example/story1", "Story one", "news"),
        _c("b", "https://news.example/story1?ref=x", "Story one", "news"),
        _c("c", "https://news.example/story2", "Story two", "news"),
        _c("d", "https://news.example/story2?ref=y", "Story two", "news"),
    ]
    groups = detect_exact_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b"}), frozenset({"c", "d"})]
