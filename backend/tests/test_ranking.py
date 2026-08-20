"""Regression tests for the M3-D production ranker (C4, design §5).

The nine behavioural acceptance probes from the M3-D experiment are replayed
through the actual production implementation (``app.services.ranking``); a
candidate ranking is only acceptable if all nine pass (design §5.1). The
corpus-level reproduction of C4's measured behaviour lives in
``eval/tests/test_ranking_eval.py``.
"""

from datetime import UTC, datetime, timedelta

from app.services.ranking import Rankable, RankedRow, rank_items, source_quality

NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


def _ts(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


_UNSET = object()


def _r(
    iid: str,
    title: str,
    stype: str = "news",
    sname: str = "The Guardian",
    pub: datetime | None | object = _UNSET,
    url: str | None = None,
    desc: str = "",
    group: str | None = None,
    dup: bool = False,
) -> Rankable:
    if pub is _UNSET:
        pub = _ts(24.0)
    return Rankable(
        id=iid,
        title=title,
        description=desc,
        source_type=stype,
        source_name=sname,
        published_at=pub,
        url=url or f"https://example.probe/{iid}",
        duplicate_group_id=group,
        is_duplicate=dup,
    )


def _rank(items: list[Rankable], query: str = "ai regulation") -> list[str]:
    return [row.id for row in rank_items(items, query, now=NOW)]


# --- Behavioural acceptance probes (P1-P9, design §5.1) -----------------------


def test_p1_fresh_irrelevant_must_not_outrank_older_relevant():
    items = [
        _r("a", "AI regulation", desc="EU publishes new AI regulation framework"),
        _r("b", "Update", pub=_ts(4.0)),
    ]
    assert _rank(items).index("a") < _rank(items).index("b")


def test_p2_relevance_dominates_even_at_the_freshness_floor():
    items = [
        _r("a", "AI regulation", pub=_ts(720.0), desc="EU publishes new AI regulation framework"),
        _r("b", "Update", pub=_ts(4.0)),
    ]
    assert _rank(items).index("a") < _rank(items).index("b")


def test_p3_guardian_before_reddit_at_equal_relevance_and_freshness():
    items = [
        _r("social", "AI regulation", stype="social", sname="r/technology (Reddit)", pub=_ts(0.0)),
        _r("guardian", "AI regulation", pub=_ts(0.0)),
    ]
    assert _rank(items).index("guardian") < _rank(items).index("social")


def test_p4_reference_timelessness_both_ways():
    items = [
        _r("ref", "AI regulation", stype="reference", sname="Wikipedia", pub=None),
        _r("partial", "AI explained", pub=_ts(4.0)),
        _r("weakref", "Artificial", stype="reference", sname="Wikipedia", pub=None),
        _r("relevant", "AI regulation", pub=_ts(4.0)),
    ]
    ranked = _rank(items)
    assert ranked.index("ref") < ranked.index("partial")
    assert ranked.index("relevant") < ranked.index("weakref")


def test_p5_missing_timestamp_is_neutral_not_lethal():
    items = [
        _r("a", "AI regulation", pub=None, desc="EU publishes new AI regulation framework"),
        _r("b", "Update", pub=_ts(4.0)),
    ]
    assert _rank(items).index("a") < _rank(items).index("b")


def test_p6_tie_break_url_lexicographic_and_deterministic():
    items = [
        _r("aaa", "AI regulation", url="https://example.probe/aaa"),
        _r("bbb", "AI regulation", url="https://example.probe/bbb"),
    ]
    ranked = _rank(items)
    assert ranked.index("aaa") < ranked.index("bbb")
    twice = rank_items(items, "ai regulation", now=NOW)
    assert twice == rank_items(items, "ai regulation", now=NOW)


def test_p7_duplicate_pair_shared_score_without_boost():
    items = [
        _r("a", "AI regulation", group="g1"),
        _r("a2", "AI regulation", group="g1", dup=True),
        _r("b", "Update", pub=_ts(4.0)),
    ]
    rows = rank_items(items, "ai regulation", now=NOW)
    by_id = {row.id: row for row in rows}
    assert by_id["a"].score == by_id["a2"].score
    ids = [row.id for row in rows]
    assert ids.index("b") > ids.index("a")
    assert ids.index("a2") == ids.index("a") + 1


def test_p8_diversity_alternates_source_types_within_the_band():
    items = [
        _r("g1", "AI regulation"),
        _r("g2", "AI regulation"),
        _r("s1", "AI regulation", stype="social", sname="r/technology (Reddit)", pub=_ts(9.75)),
        _r("ref", "AI regulation", stype="reference", sname="Wikipedia", pub=None),
    ]
    ranked = _rank(items)
    assert ranked == ["ref", "g1", "s1", "g2"]
    rows = rank_items(items, "ai regulation", now=NOW)
    by_score = {row.id: row.score for row in rows}
    band = [i for i in ranked if by_score[i] >= by_score["g1"] - 0.05]
    types = {item.id: item.source_type for item in items}
    assert all(types[band[j]] != types[band[j + 1]] for j in range(len(band) - 1))


def test_p9_fresher_relevant_outranks_older_relevant():
    items = [
        _r("fresh", "AI regulation", pub=_ts(4.0)),
        _r("old", "AI regulation", pub=_ts(720.0)),
    ]
    assert _rank(items).index("fresh") < _rank(items).index("old")


# --- Unit behaviour -----------------------------------------------------------


def test_duplicate_member_inherits_canonical_score_and_components():
    canonical = _r("a", "AI regulation", pub=_ts(4.0), group="g1")
    member = _r("a2", "Update", pub=_ts(720.0), group="g1", dup=True)
    rows = rank_items([canonical, member], "ai regulation", now=NOW)
    by_id = {row.id: row for row in rows}
    assert by_id["a2"].score == by_id["a"].score
    assert by_id["a2"].relevance == by_id["a"].relevance
    assert by_id["a2"].freshness == by_id["a"].freshness
    assert by_id["a2"].quality == by_id["a"].quality


def test_relevance_is_minmax_normalised_per_search():
    items = [
        _r("top", "AI regulation"),
        _r("partial", "AI explained"),
        _r("none", "Update"),
    ]
    rows = rank_items(items, "ai regulation", now=NOW)
    by_id = {row.id: row for row in rows}
    assert by_id["top"].relevance == 1.0
    assert 0.0 < by_id["partial"].relevance < 1.0
    assert by_id["none"].relevance == 0.0


def test_reference_freshness_is_constant_regardless_of_timestamp():
    with_ts = _r("a", "AI regulation", stype="reference", sname="Wikipedia", pub=_ts(4.0))
    without_ts = _r("b", "AI regulation", stype="reference", sname="Wikipedia", pub=None)
    rows = rank_items([with_ts, without_ts], "ai regulation", now=NOW)
    assert {row.freshness for row in rows} == {0.5}


def test_source_quality_constants():
    assert source_quality("news", "The Guardian") == 0.90
    assert source_quality("reference", "Wikipedia") == 0.80
    assert source_quality("news", "Global Wire") == 0.85
    assert source_quality("social", "r/technology (Reddit)") == 0.50
    assert source_quality("news", "Some Unknown Outlet") == 0.50


def test_timestamp_desc_with_missing_last():
    items = [
        _r("social", "AI regulation", stype="social", sname="r/technology (Reddit)", pub=_ts(4.0)),
        _r("old", "AI regulation", pub=_ts(720.0)),
        _r("fresh", "AI regulation", pub=_ts(4.0)),
        _r("none", "AI regulation", pub=None),
    ]
    # news 4h (~0.954) > social 4h (~0.866) > missing ts (0.76) > news 30d
    # (~0.70); strictly descending, no diversity band overlap
    assert [row.id for row in rank_items(items, "ai regulation", now=NOW)] == [
        "fresh",
        "social",
        "none",
        "old",
    ]


def test_tie_break_type_priority_then_url_on_exact_ties():
    items = [
        _r("social", "Update", stype="social", sname="Some Unknown Outlet", pub=None),
        _r("newsb", "Update", sname="Some Unknown Outlet", pub=None, url="https://example.probe/b"),
        _r("newsa", "Update", sname="Some Unknown Outlet", pub=None, url="https://example.probe/a"),
    ]
    rows = rank_items(items, "ai regulation", now=NOW)
    assert len({row.score for row in rows}) == 1
    # the exact-tie band is one band, so the diversity pass alternates by
    # type (news, social); URLs decide within a type
    assert [row.id for row in rows] == ["newsa", "social", "newsb"]


def test_ranked_row_fields_are_consistent():
    items = [_r("a", "AI regulation")]
    rows = rank_items(items, "ai regulation", now=NOW)
    row: RankedRow = rows[0]
    expected = 0.55 * row.relevance + 0.30 * row.freshness + 0.15 * row.quality
    assert abs(row.score - expected) < 1e-12