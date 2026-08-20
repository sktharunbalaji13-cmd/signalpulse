"""Tests for fuzzy duplicate detection (M3-A3).

Emphasis on hard negatives: near-identical titles that must NOT merge because
they lack corroborating evidence (same source type, informative title, or
publication-time proximity).
"""

from datetime import UTC, datetime

from app.services.dedup import (
    FUZZY_METHOD,
    Candidate,
    detect_fuzzy_duplicates,
)


def _c(
    cid: str,
    title: str,
    source_type: str = "news",
    url: str | None = None,
    published_at: datetime | None = None,
) -> Candidate:
    return Candidate(
        id=cid,
        url=url or f"https://n.example/{cid}",
        title=title,
        source_type=source_type,
        published_at=published_at,
    )


_T0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=UTC)


def _members(groups) -> list[frozenset[str]]:
    return [frozenset(g.members) for g in groups]


def test_word_reorder_same_type_close_time_merges():
    candidates = [
        _c("a", "Researchers report quantum error correction milestone", published_at=_T0),
        _c("b", "Quantum error correction milestone reached, researchers report", published_at=_T0),
    ]
    groups = detect_fuzzy_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b"})]
    assert groups[0].methods == frozenset({FUZZY_METHOD})


def test_same_title_far_apart_does_not_merge():
    # Recurring event with the same headline, months apart -> different story.
    candidates = [
        _c("a", "Apple reports quarterly earnings", published_at=datetime(2026, 5, 1, tzinfo=UTC)),
        _c("b", "Apple reports quarterly earnings", published_at=datetime(2026, 8, 18, tzinfo=UTC)),
    ]
    assert detect_fuzzy_duplicates(candidates) == []


def test_same_title_cross_source_type_does_not_merge():
    candidates = [
        _c("a", "Big story about regulation", source_type="news", published_at=_T0),
        _c("b", "Big story about regulation", source_type="social", published_at=_T0),
    ]
    assert detect_fuzzy_duplicates(candidates) == []


def test_reference_results_are_never_fuzzily_merged():
    candidates = [
        _c("a", "Quantum computing", source_type="reference"),
        _c("b", "Quantum computing explained", source_type="reference"),
    ]
    assert detect_fuzzy_duplicates(candidates) == []


def test_generic_short_titles_are_not_fuzzily_merged():
    candidates = [
        _c("a", "Update", published_at=_T0),
        _c("b", "Update", published_at=_T0),
    ]
    assert detect_fuzzy_duplicates(candidates) == []


def test_high_overlap_but_distinct_topics_do_not_merge():
    candidates = [
        _c("a", "New iPhone camera review", published_at=_T0),
        _c("b", "New iPhone battery review", published_at=_T0),
    ]
    assert detect_fuzzy_duplicates(candidates) == []


def test_antonym_titles_do_not_merge():
    candidates = [
        _c("a", "Stock market closes higher on tech gains", published_at=_T0),
        _c("b", "Stock market closes lower on tech losses", published_at=_T0),
    ]
    assert detect_fuzzy_duplicates(candidates) == []


def test_missing_timestamps_fall_back_to_title_plus_type():
    # Both timestamps unknown -> no time evidence, title+type still merge.
    candidates = [
        _c("a", "Researchers report quantum error correction milestone"),
        _c("b", "Quantum error correction milestone reached, researchers report"),
    ]
    groups = detect_fuzzy_duplicates(candidates)
    assert _members(groups) == [frozenset({"a", "b"})]


def test_fuzzy_detection_is_order_independent():
    candidates = [
        _c("a", "Researchers report quantum error correction milestone", published_at=_T0),
        _c("b", "Quantum error correction milestone reached, researchers report", published_at=_T0),
        _c("c", "Completely unrelated title here", published_at=_T0),
    ]
    expected = detect_fuzzy_duplicates(candidates)
    assert detect_fuzzy_duplicates(list(reversed(candidates))) == expected
