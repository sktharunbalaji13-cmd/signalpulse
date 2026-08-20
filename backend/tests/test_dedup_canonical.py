"""Tests for combined detection and canonical selection (M3-A4 primitives)."""

from datetime import UTC, datetime

from app.services.dedup import (
    FUZZY_METHOD,
    TITLE_METHOD,
    URL_METHOD,
    Candidate,
    detect_duplicates,
    select_canonical,
)

_T0 = datetime(2026, 8, 18, 10, 0, 0, tzinfo=UTC)


def _c(
    cid: str,
    title: str,
    source_type: str = "news",
    url: str | None = None,
    published_at: datetime | None = None,
    description: str | None = None,
) -> Candidate:
    return Candidate(
        id=cid,
        url=url or f"https://n.example/{cid}",
        title=title,
        source_type=source_type,
        published_at=published_at,
        description=description,
    )


def test_select_canonical_prefers_timestamp_then_news_then_description():
    members = [
        _c("ref", "Same", "reference", url="https://n.example/x", description="x"),
        _c("social", "Same", "social", url="https://n.example/x", published_at=_T0),
        _c("news", "Same", "news", url="https://n.example/x", published_at=_T0),
    ]
    assert select_canonical(members) == "news"


def test_select_canonical_prefers_known_timestamp_over_none():
    members = [
        _c("no_ts", "Same", "news", url="https://n.example/x"),
        _c("with_ts", "Same", "news", url="https://n.example/x", published_at=_T0),
    ]
    assert select_canonical(members) == "with_ts"


def test_select_canonical_is_deterministic_and_order_independent():
    members = [
        _c("a", "Same", "news", url="https://n.example/x", published_at=_T0, description="short"),
        _c(
            "b",
            "Same",
            "news",
            url="https://n.example/x",
            published_at=_T0,
            description="a longer description",
        ),
    ]
    assert select_canonical(members) == "b"
    assert select_canonical(list(reversed(members))) == "b"


def test_detect_duplicates_combines_exact_and_fuzzy_with_methods():
    candidates = [
        # URL duplicate pair (same title)
        _c(
            "a",
            "Researchers report quantum error correction milestone",
            "news",
            url="https://n.example/story",
            published_at=_T0,
        ),
        _c(
            "b",
            "Researchers report quantum error correction milestone",
            "news",
            url="https://n.example/story?ref=x",
            published_at=_T0,
        ),
        # fuzzy duplicate of a/b (word reorder)
        _c(
            "c",
            "Quantum error correction milestone reached, researchers report",
            "news",
            url="https://o.example/c",
            published_at=_T0,
        ),
        # unrelated
        _c(
            "d",
            "Totally different subject here",
            "news",
            url="https://n.example/d",
            published_at=_T0,
        ),
    ]
    groups = detect_duplicates(candidates)
    assert len(groups) == 1
    group = groups[0]
    assert frozenset(group.members) == {"a", "b", "c"}
    assert group.methods == frozenset({URL_METHOD, TITLE_METHOD, FUZZY_METHOD})


def test_detect_duplicates_does_not_merge_news_and_social():
    candidates = [
        _c("a", "Big story about the framework", "news", published_at=_T0),
        _c("b", "Big story about the framework", "social", published_at=_T0),
    ]
    assert detect_duplicates(candidates) == []
