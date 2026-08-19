import httpx
import respx

from app.db.models import Result, Search, SourceEvent
from app.sources.wikipedia import WIKIPEDIA_API_URL
from tests.helpers import (
    mock_wikipedia_malformed,
    mock_wikipedia_rate_limited,
    mock_wikipedia_success,
    mock_wikipedia_timeout,
)


def create_search(client, query="artificial intelligence", window_hours=None):
    body = {"query": query}
    if window_hours is not None:
        body["window_hours"] = window_hours
    return client.post("/api/v1/searches", json=body).json()["search_id"]


# --- POST /searches ----------------------------------------------------------


@respx.mock
def test_post_searches_valid_query_returns_202(client):
    mock_wikipedia_success()
    response = client.post(
        "/api/v1/searches", json={"query": "artificial intelligence", "window_hours": 24}
    )
    assert response.status_code == 202


@respx.mock
def test_post_searches_returns_search_id(client):
    mock_wikipedia_success()
    response = client.post("/api/v1/searches", json={"query": "artificial intelligence"})
    assert len(response.json()["search_id"]) == 36


@respx.mock
def test_post_searches_status_starts_running(client):
    mock_wikipedia_success()
    response = client.post("/api/v1/searches", json={"query": "artificial intelligence"})
    assert response.json()["status"] == "running"


def test_post_searches_empty_query_rejected(client):
    response = client.post("/api/v1/searches", json={"query": "   "})
    assert response.status_code == 422


def test_post_searches_long_query_rejected(client):
    response = client.post("/api/v1/searches", json={"query": "x" * 201})
    assert response.status_code == 422


def test_post_searches_negative_window_rejected(client):
    response = client.post("/api/v1/searches", json={"query": "ai", "window_hours": -1})
    assert response.status_code == 422


# --- Background execution ----------------------------------------------------


@respx.mock
def test_background_success_becomes_completed(client):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "completed"


@respx.mock
def test_results_persisted(client, session_factory):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}/results").json()
    assert body["total"] == 2
    titles = {item["title"] for item in body["items"]}
    assert "Artificial intelligence" in titles
    with session_factory() as session:
        rows = session.query(Result).filter_by(search_id=search_id).all()
        assert len(rows) == 2
        assert all(row.raw for row in rows)
        assert all(row.is_duplicate is False for row in rows)
        search = session.get(Search, search_id)
        assert search.normalized_query == "artificial intelligence"


@respx.mock
def test_source_events_persisted(client, session_factory):
    mock_wikipedia_success()
    search_id = create_search(client)
    with session_factory() as session:
        events = session.query(SourceEvent).filter_by(search_id=search_id).all()
        assert len(events) == 1
        assert events[0].source_name == "Wikipedia"
        assert events[0].status == "success"
        assert events[0].result_count == 2
        assert events[0].latency_ms is not None
        assert events[0].error_message is None


@respx.mock
def test_completed_at_populated(client):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["completed_at"] is not None


@respx.mock
def test_duration_ms_populated(client):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["duration_ms"] is not None
    assert body["duration_ms"] >= 0


# --- Failure handling --------------------------------------------------------


@respx.mock
def test_timeout_marks_search_failed(client):
    mock_wikipedia_timeout()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "failed"
    assert body["sources"][0]["status"] == "timeout"
    assert "timed out" in body["sources"][0]["error"]


@respx.mock
def test_rate_limited_marks_search_failed(client):
    mock_wikipedia_rate_limited()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "failed"
    assert body["sources"][0]["status"] == "rate_limited"


@respx.mock
def test_malformed_response_marks_search_failed(client):
    mock_wikipedia_malformed()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "failed"
    assert body["sources"][0]["status"] == "failed"


# --- GET /searches/{id} -------------------------------------------------------


@respx.mock
def test_get_existing_search(client):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["search_id"] == search_id
    assert body["query"] == "artificial intelligence"
    assert body["status"] == "completed"
    assert body["sources"][0]["name"] == "Wikipedia"
    assert body["sources"][0]["result_count"] == 2


def test_get_nonexistent_search_404(client):
    response = client.get("/api/v1/searches/does-not-exist")
    assert response.status_code == 404


@respx.mock
def test_completed_search_reports_result_count(client):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["result_count"] == 2


# --- GET /searches/{id}/results -----------------------------------------------


@respx.mock
def test_results_returned_correctly(client):
    mock_wikipedia_success()
    search_id = create_search(client)
    body = client.get(f"/api/v1/searches/{search_id}/results").json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["per_page"] == 20
    item = body["items"][0]
    assert item["source_name"] == "Wikipedia"
    assert item["source_type"] == "reference"
    assert item["url"].startswith("https://en.wikipedia.org/wiki/")
    assert item["published_at"] is None
    assert item["retrieved_at"] is not None
    assert "raw" not in item
    assert "dedupe_key" not in item


@respx.mock
def test_results_pagination_works(client):
    pages = {
        "query": {
            "pages": {
                str(i): {
                    "pageid": i,
                    "ns": 0,
                    "title": f"Page {i}",
                    "index": i,
                    "extract": f"Extract {i}",
                }
                for i in range(1, 11)
            }
        }
    }
    respx.get(WIKIPEDIA_API_URL).mock(return_value=httpx.Response(200, json=pages))
    search_id = create_search(client, query="pages")
    page1 = client.get(f"/api/v1/searches/{search_id}/results?page=1&per_page=5").json()
    page2 = client.get(f"/api/v1/searches/{search_id}/results?page=2&per_page=5").json()
    assert page1["total"] == 10
    assert len(page1["items"]) == 5
    assert len(page2["items"]) == 5
    assert page1["items"][0]["title"] != page2["items"][0]["title"]


def test_results_nonexistent_search_404(client):
    response = client.get("/api/v1/searches/does-not-exist/results")
    assert response.status_code == 404


# --- History ------------------------------------------------------------------


@respx.mock
def test_history_newest_first(client):
    mock_wikipedia_success()
    first = create_search(client, query="first query")
    second = create_search(client, query="second query")
    third = create_search(client, query="third query")
    body = client.get("/api/v1/searches?limit=20").json()
    ids = [item["search_id"] for item in body["items"]]
    assert ids == [third, second, first]
    assert body["items"][0]["query"] == "third query"
    assert body["items"][0]["result_count"] == 2