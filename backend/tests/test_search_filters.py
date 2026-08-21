"""Production API acceptance tests for the M3-E filter view (design §6).

The 11 behavioural acceptance probes from the M3-E experiment are replayed
through the actual production endpoint (``GET /api/v1/searches/{id}/results``)
against seeded rows. Filters must be a read-only projection over the frozen
``rank_position`` order: no re-ranking, no writes, no retrieval, deterministic
pagination, explicit 422 on invalid values.
"""

from datetime import UTC, datetime, timedelta

from app.db.models import Result, Search

NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


def _ts(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def _seed(client, session_factory, items, *, status="completed"):
    """Create a completed search with rows in rank_position order.

    ``items`` are dicts: source_type, url, rank_position, and optionally
    published_at / language / is_duplicate / duplicate_group_id / source_name.
    """
    with session_factory() as session:
        search = Search(
            query="ai regulation",
            normalized_query="ai regulation",
            status=status,
            created_at=_ts(48.0),
            completed_at=_ts(0.0),
        )
        session.add(search)
        session.commit()
        search_id = search.id
        for item in items:
            session.add(
                Result(
                    search_id=search_id,
                    source_type=item["source_type"],
                    source_name=item.get("source_name", "The Guardian"),
                    title=item.get("title", "AI regulation"),
                    url=item["url"],
                    published_at=item.get("published_at"),
                    retrieved_at=NOW,
                    language=item.get("language"),
                    is_duplicate=item.get("is_duplicate", False),
                    duplicate_group_id=item.get("duplicate_group_id"),
                    rank_position=item["rank_position"],
                    rank_score=1.0 - item["rank_position"],
                    rank_components={"relevance": 0.0, "freshness": 0.0, "quality": 0.0},
                    raw={},
                )
            )
        session.commit()
    return search_id


def _item_ids(payload) -> list[str]:
    return [i["url"].rsplit("/", 1)[-1] for i in payload["items"]]


def _row(sid, url, pos, **kw):
    return {
        "source_type": "news",
        "url": f"https://example.probe/{sid}",
        "rank_position": pos,
        **kw,
    }


def _probe_urls(search_id, **params) -> str:
    parts = [
        f"{k}={v}"
        for k, vs in params.items()
        for v in (vs if isinstance(vs, list) else [vs])
    ]
    qs = "&".join(parts)
    base = f"/api/v1/searches/{search_id}/results"
    return f"{base}?{qs}" if qs else base


# --- P1: filtered subset stays correctly ranked (projection of the C4 order) -


def test_p1_filtered_subset_keeps_rank_order(client, session_factory):
    rows = [
        _row("a", "a", 0, published_at=_ts(4.0)),
        _row("b", "b", 1, published_at=_ts(8.0)),
        _row("c", "c", 2, source_type="social", published_at=_ts(2.0)),
        _row("d", "d", 3, source_type="reference"),
    ]
    sid = _seed(client, session_factory, rows)
    payload = client.get(_probe_urls(sid, source_type="news", per_page=100)).json()
    assert _item_ids(payload) == ["a", "b"]
    assert payload["total"] == 2
    # no re-ranking: subset order == the rank_position projection of the full set
    full = client.get(_probe_urls(sid, per_page=100)).json()
    assert _item_ids(payload) == [
        i for i in _item_ids(full) if i in {"a", "b"}
    ]


# --- P2: source_type membership, OR for repeats, empty view -------------------


def test_p2_source_type_filter_and_or_and_empty(client, session_factory):
    rows = [
        _row("n", "n", 0),
        _row("r", "r", 1, source_type="reference"),
    ]
    sid = _seed(client, session_factory, rows)
    assert _item_ids(client.get(_probe_urls(sid, source_type="news")).json()) == ["n"]
    assert _item_ids(client.get(_probe_urls(sid, source_type=["news", "social"])).json()) == ["n"]
    empty = client.get(_probe_urls(sid, source_type="social")).json()
    assert empty["items"] == []
    assert empty["total"] == 0


# --- P3: time window semantics ------------------------------------------------


def test_p3_time_window_type_scoping_and_null(client, session_factory):
    rows = [
        _row("fresh", "fresh", 0, published_at=_ts(4.0)),
        _row("old", "old", 1, published_at=_ts(168.0)),
        _row("nopub", "nopub", 2),
        _row("ref", "ref", 3, source_type="reference"),
        _row("sfresh", "sfresh", 4, source_type="social", published_at=_ts(2.0)),
    ]
    sid = _seed(client, session_factory, rows)
    day = client.get(_probe_urls(sid, time="24h")).json()
    assert _item_ids(day) == ["fresh", "ref", "sfresh"]
    week = client.get(_probe_urls(sid, time="7d")).json()
    assert "old" in _item_ids(week)
    assert set(_item_ids(client.get(_probe_urls(sid, time="all")).json())) == {
        "fresh",
        "old",
        "nopub",
        "ref",
        "sfresh",
    }
    assert _item_ids(client.get(_probe_urls(sid)).json()) == _item_ids(
        client.get(_probe_urls(sid, time="all")).json()
    )


# --- P4: time never reorders within the kept set ------------------------------


def test_p4_time_preserves_kept_order(client, session_factory):
    rows = [
        _row("fresh", "fresh", 0, published_at=_ts(4.0)),
        _row("old", "old", 1, published_at=_ts(168.0)),
        _row("ref", "ref", 2, source_type="reference"),
    ]
    sid = _seed(client, session_factory, rows)
    day = client.get(_probe_urls(sid, time="24h")).json()
    assert _item_ids(day) == ["fresh", "ref"]


# --- P5: duplicates=canonical hides members, group ids intact -----------------


def test_p5_duplicates_canonical_hides_members(client, session_factory):
    rows = [
        _row("canon", "canon", 0, duplicate_group_id="G"),
        _row("member", "member", 1, duplicate_group_id="G", is_duplicate=True),
        _row("lone", "lone", 2, source_type="reference"),
    ]
    sid = _seed(client, session_factory, rows)
    view = client.get(_probe_urls(sid, duplicates="canonical")).json()
    assert _item_ids(view) == ["canon", "lone"]
    assert view["total"] == 2
    all_rows = client.get(_probe_urls(sid, duplicates="all")).json()
    assert all_rows["total"] == 3
    assert view["items"][0]["duplicate_group_id"] == "G"


# --- P6: filtered-out canonical keeps remaining members -----------------------


def test_p6_canonical_filtered_out_keeps_member(client, session_factory):
    rows = [
        _row("canon", "canon", 0, duplicate_group_id="G"),
        _row(
            "member",
            "member",
            1,
            source_type="social",
            duplicate_group_id="G",
            is_duplicate=True,
        ),
    ]
    sid = _seed(client, session_factory, rows)
    social = client.get(_probe_urls(sid, source_type="social")).json()
    assert _item_ids(social) == ["member"]
    assert social["items"][0]["duplicate_group_id"] == "G"


# --- P7: invalid values -> explicit 422 ---------------------------------------


def test_p7_invalid_values_are_rejected_422(client, session_factory):
    sid = _seed(client, session_factory, [_row("n", "n", 0)])
    base = f"/api/v1/searches/{sid}/results"
    for url in (
        f"{base}?source_type=blog",
        f"{base}?time=3d",
        f"{base}?duplicates=hide",
        f"{base}?language=english",
        f"{base}?language=EN",
        f"{base}?page=0",
        f"{base}?per_page=101",
        f"{base}?source_type=news&time=banana",
    ):
        assert client.get(url).status_code == 422, url


# --- P8: determinism + deterministic pagination over the filtered view --------


def test_p8_deterministic_pagination_over_filtered_view(client, session_factory):
    rows = [
        _row("a", "a", i, published_at=_ts(float(1 + i)))
        for i in range(5)
    ] + [_row("ref", "ref", 5, source_type="reference")]
    sid = _seed(client, session_factory, rows)
    first = client.get(_probe_urls(sid, time="24h", per_page=100)).json()
    second = client.get(_probe_urls(sid, time="24h", per_page=100)).json()
    assert first == second
    # 5 news within the window + 1 reference (always included) = 6
    assert first["total"] == 6
    p1 = _item_ids(client.get(_probe_urls(sid, time="24h", page=1, per_page=2)).json())
    p2 = _item_ids(client.get(_probe_urls(sid, time="24h", page=2, per_page=2)).json())
    p3 = _item_ids(client.get(_probe_urls(sid, time="24h", page=3, per_page=2)).json())
    assert p1 + p2 + p3 == _item_ids(first)
    beyond = client.get(_probe_urls(sid, time="24h", page=99, per_page=2)).json()
    assert beyond["items"] == []
    assert beyond["total"] == 6


# --- P9: partial/failed sources degrade gracefully ----------------------------


def test_p9_partial_search_filters_behave_identically(client, session_factory):
    rows = [
        _row("a", "a", 0, published_at=_ts(4.0)),
        _row("b", "b", 1, published_at=_ts(8.0)),
    ]
    sid = _seed(client, session_factory, rows, status="partial")
    body = client.get(f"/api/v1/searches/{sid}").json()
    assert body["status"] == "partial"
    news = client.get(_probe_urls(sid, source_type="news", time="7d")).json()
    assert news["total"] == 2
    assert _item_ids(news) == ["a", "b"]


# --- P10: provenance invariant (filters never write) --------------------------


def test_p10_filters_never_mutate_stored_rows(client, session_factory):
    rows = [
        _row("a", "a", 0, published_at=_ts(4.0), duplicate_group_id="G"),
        _row("b", "b", 1, duplicate_group_id="G", is_duplicate=True),
        _row("c", "c", 2, source_type="reference"),
    ]
    sid = _seed(client, session_factory, rows)
    before = _snapshot(session_factory, sid)
    for url in (
        _probe_urls(sid, source_type="news"),
        _probe_urls(sid, time="24h"),
        _probe_urls(sid, duplicates="canonical"),
        _probe_urls(sid, language="en"),
    ):
        client.get(url)
    assert _snapshot(session_factory, sid) == before


def _snapshot(session_factory, search_id):
    with session_factory() as session:
        rows = session.query(Result).filter_by(search_id=search_id).all()
        return {
            (r.url,): (
                r.source_type,
                r.published_at,
                r.language,
                r.is_duplicate,
                r.duplicate_group_id,
                r.rank_position,
                r.rank_score,
                r.raw,
            )
            for r in rows
        }


# --- P11: language exact match, NULL excluded, invalid rejected ---------------


def test_p11_language_filter(client, session_factory):
    rows = [
        _row("en", "en", 0, language="en"),
        _row("null", "null", 1),
        _row("fr", "fr", 2, source_type="reference", language="fr"),
    ]
    sid = _seed(client, session_factory, rows)
    en_view = client.get(_probe_urls(sid, language="en")).json()
    assert _item_ids(en_view) == ["en"]
    assert client.get(_probe_urls(sid, language="EN")).status_code == 422
