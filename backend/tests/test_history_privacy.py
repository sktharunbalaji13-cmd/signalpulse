"""M19.1 privacy regression tests (ADR 0015).

Proves the listing endpoint no longer exposes query text in any form while
ID-addressed endpoints keep their existing behavior.
"""

import pytest

from app.db.models import Search
from app.sources.wikipedia import WIKIPEDIA_API_URL


@pytest.fixture()
def seeded(session_factory):
    marker = "super-secret-user-query-xyz"
    with session_factory() as s:
        s.add(
            Search(
                query=marker,
                normalized_query=marker,
                status="completed",
                duration_ms=100,
            )
        )
        s.commit()
    return marker


def test_history_list_does_not_expose_raw_query(client, seeded):
    body = client.get("/api/v1/searches").json()
    assert body["items"], "expected at least one history item"
    for item in body["items"]:
        assert "query" not in item
    assert seeded not in str(body)


def test_history_list_does_not_expose_normalized_query(client, seeded):
    raw = client.get("/api/v1/searches").text
    assert "normalized_query" not in raw
    assert seeded not in raw


def test_history_item_fields_are_operational_only(client, seeded):
    item = client.get("/api/v1/searches").json()["items"][0]
    assert set(item) == {
        "search_id",
        "status",
        "created_at",
        "completed_at",
        "duration_ms",
        "result_count",
    }


def test_search_status_endpoint_retains_query(client, session_factory, seeded):
    with session_factory() as s:
        search = s.query(Search).first()
        search_id = search.id
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["query"] == seeded


def test_results_endpoint_retains_existing_behavior(client, seeded):
    import httpx
    import respx

    from tests.helpers import HACKER_NEWS_API_URL

    with respx.mock:
        respx.get(WIKIPEDIA_API_URL).mock(
            return_value=httpx.Response(200, json={"query": {"pages": {}}})
        )
        respx.get(HACKER_NEWS_API_URL).mock(
            return_value=httpx.Response(200, json={"hits": []})
        )
        search_id = client.post("/api/v1/searches", json={"query": seeded}).json()[
            "search_id"
        ]
    body = client.get(f"/api/v1/searches/{search_id}/results").json()
    assert body["total"] == 0
    assert set(body) == {"total", "page", "per_page", "items"}