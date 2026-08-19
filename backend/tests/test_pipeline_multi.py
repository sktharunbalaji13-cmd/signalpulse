import asyncio
from time import monotonic

import pytest
import respx

from app.core.config import settings
from app.db.models import Result, Search, SourceEvent
from app.services.search_pipeline import run_search_job
from app.sources.registry import registry
from tests.helpers import (
    mock_guardian_api_key_error,
    mock_guardian_success,
    mock_guardian_timeout,
    mock_reddit_empty,
    mock_reddit_success,
    mock_reddit_timeout,
    mock_wikipedia_success,
    mock_wikipedia_timeout,
)


@pytest.fixture()
def guardian_key(monkeypatch, clean_secrets):
    monkeypatch.setattr(settings, "guardian_api_key", "test-key")


@pytest.fixture()
def reddit_creds(monkeypatch, clean_secrets):
    monkeypatch.setattr(settings, "reddit_client_id", "test-client-id")
    monkeypatch.setattr(settings, "reddit_client_secret", "test-client-secret")


def create_search(client, query="artificial intelligence"):
    return client.post("/api/v1/searches", json={"query": query}).json()["search_id"]


def find_source(sources, name):
    return next(source for source in sources if source["name"] == name)


# --- Combined-source scenarios ------------------------------------------------


@respx.mock
def test_wikipedia_and_guardian_both_succeed(client, guardian_key, reddit_creds):
    mock_wikipedia_success()
    mock_guardian_success()
    mock_reddit_empty()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "completed"
    assert body["result_count"] == 4
    wikipedia_source = find_source(body["sources"], "Wikipedia")
    guardian_source = find_source(body["sources"], "The Guardian")
    reddit_source = find_source(body["sources"], "Reddit")
    assert wikipedia_source["status"] == "success"
    assert wikipedia_source["result_count"] == 2
    assert guardian_source["status"] == "success"
    assert guardian_source["result_count"] == 2
    assert reddit_source["status"] == "success"
    assert reddit_source["result_count"] == 0

    results = client.get(f"/api/v1/searches/{search_id}/results?per_page=100").json()
    names = {item["source_name"] for item in results["items"]}
    assert names == {"Wikipedia", "The Guardian"}
    guardian_items = [i for i in results["items"] if i["source_name"] == "The Guardian"]
    assert all(i["source_type"] == "news" for i in guardian_items)
    assert all(i["url"].startswith("https://www.theguardian.com/") for i in guardian_items)
    assert all(i["published_at"] is not None for i in guardian_items)
    assert all(i["retrieved_at"] is not None for i in guardian_items)


@respx.mock
def test_wikipedia_succeeds_guardian_fails_partial(client, guardian_key):
    mock_wikipedia_success()
    mock_guardian_api_key_error()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "partial"
    assert body["result_count"] == 2
    wikipedia_source = find_source(body["sources"], "Wikipedia")
    guardian_source = find_source(body["sources"], "The Guardian")
    assert wikipedia_source["status"] == "success"
    assert wikipedia_source["result_count"] == 2
    assert guardian_source["status"] == "failed"
    assert guardian_source["error_type"] == "failed"
    assert "API key" in guardian_source["error"]

    results = client.get(f"/api/v1/searches/{search_id}/results").json()
    assert results["total"] == 2
    assert {item["source_name"] for item in results["items"]} == {"Wikipedia"}


@respx.mock
def test_guardian_succeeds_wikipedia_fails_partial(client, guardian_key):
    mock_wikipedia_timeout()
    mock_guardian_success()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "partial"
    assert body["result_count"] == 2
    wikipedia_source = find_source(body["sources"], "Wikipedia")
    guardian_source = find_source(body["sources"], "The Guardian")
    assert wikipedia_source["status"] == "timeout"
    assert wikipedia_source["error_type"] == "timeout"
    assert guardian_source["status"] == "success"
    assert guardian_source["result_count"] == 2

    results = client.get(f"/api/v1/searches/{search_id}/results").json()
    assert results["total"] == 2
    assert {item["source_name"] for item in results["items"]} == {"The Guardian"}


@respx.mock
def test_both_sources_fail_marks_search_failed(client, guardian_key):
    mock_wikipedia_timeout()
    mock_guardian_timeout()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "failed"
    assert body["result_count"] == 0
    assert find_source(body["sources"], "Wikipedia")["status"] == "timeout"
    assert find_source(body["sources"], "The Guardian")["status"] == "timeout"


@respx.mock
def test_source_events_record_guardian_outcomes(client, session_factory, guardian_key):
    mock_wikipedia_success()
    mock_guardian_api_key_error()
    search_id = create_search(client)

    with session_factory() as session:
        events = {
            e.source_name: e
            for e in session.query(SourceEvent).filter_by(search_id=search_id).all()
        }
        assert set(events) == {"Wikipedia", "The Guardian", "Reddit"}
        wikipedia_event = events["Wikipedia"]
        assert wikipedia_event.status == "success"
        assert wikipedia_event.result_count == 2
        assert wikipedia_event.latency_ms is not None
        guardian_event = events["The Guardian"]
        assert guardian_event.status == "failed"
        assert guardian_event.result_count is None
        assert guardian_event.error_type == "failed"
        assert guardian_event.error_message is not None
        assert guardian_event.latency_ms is not None
        reddit_event = events["Reddit"]
        assert reddit_event.status == "failed"
        assert reddit_event.error_type == "failed"
        assert reddit_event.error_message is not None


# --- Reddit pipeline integration (M2-B) ---------------------------------------


@respx.mock
def test_all_three_sources_succeed_completed(client, guardian_key, reddit_creds):
    mock_wikipedia_success()
    mock_guardian_success()
    mock_reddit_success()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "completed"
    assert body["result_count"] == 6
    assert find_source(body["sources"], "Wikipedia")["status"] == "success"
    assert find_source(body["sources"], "The Guardian")["status"] == "success"
    assert find_source(body["sources"], "Reddit")["status"] == "success"

    results = client.get(f"/api/v1/searches/{search_id}/results?per_page=100").json()
    assert {item["source_name"] for item in results["items"]} == {
        "Wikipedia",
        "The Guardian",
        "Reddit",
    }
    reddit_items = [i for i in results["items"] if i["source_name"] == "Reddit"]
    assert len(reddit_items) == 2
    assert all(i["source_type"] == "social" for i in reddit_items)
    assert all(i["url"].startswith("https://www.reddit.com/") for i in reddit_items)
    assert all(i["published_at"] is not None for i in reddit_items)
    assert all(i["retrieved_at"] is not None for i in reddit_items)
    assert all(i["author"] is not None for i in reddit_items) is False
    assert {i["author"] for i in reddit_items} == {"ml_enthusiast", None}


@respx.mock
def test_reddit_fails_others_succeed_partial(client, guardian_key, reddit_creds):
    mock_wikipedia_success()
    mock_guardian_success()
    mock_reddit_timeout()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "partial"
    assert find_source(body["sources"], "Wikipedia")["status"] == "success"
    assert find_source(body["sources"], "The Guardian")["status"] == "success"
    assert find_source(body["sources"], "Reddit")["status"] == "timeout"


@respx.mock
def test_reddit_succeeds_another_fails_partial(client, guardian_key, reddit_creds):
    mock_wikipedia_timeout()
    mock_guardian_api_key_error()
    mock_reddit_success()
    search_id = create_search(client)

    body = client.get(f"/api/v1/searches/{search_id}").json()
    assert body["status"] == "partial"
    assert find_source(body["sources"], "Wikipedia")["status"] == "timeout"
    assert find_source(body["sources"], "The Guardian")["status"] == "failed"
    assert find_source(body["sources"], "Reddit")["status"] == "success"


@respx.mock
def test_reddit_failure_keeps_other_results(client, session_factory, guardian_key, reddit_creds):
    mock_wikipedia_success()
    mock_guardian_success()
    mock_reddit_timeout()
    search_id = create_search(client)

    results = client.get(f"/api/v1/searches/{search_id}/results?per_page=100").json()
    assert results["total"] == 4
    assert {item["source_name"] for item in results["items"]} == {"Wikipedia", "The Guardian"}


@respx.mock
def test_reddit_source_event_recorded(client, session_factory, guardian_key, reddit_creds):
    mock_wikipedia_success()
    mock_guardian_success()
    mock_reddit_timeout()
    search_id = create_search(client)

    with session_factory() as session:
        reddit_events = (
            session.query(SourceEvent)
            .filter_by(search_id=search_id, source_name="Reddit")
            .all()
        )
        assert len(reddit_events) == 1
        event = reddit_events[0]
        assert event.status == "timeout"
        assert event.error_type == "timeout"
        assert event.latency_ms is not None
        assert event.result_count is None


@respx.mock
def test_reddit_results_persisted_as_canonical_source_result(
    client, session_factory, guardian_key, reddit_creds
):
    mock_wikipedia_success()
    mock_guardian_success()
    mock_reddit_success()
    search_id = create_search(client)

    with session_factory() as session:
        reddit_rows = (
            session.query(Result).filter_by(search_id=search_id, source_name="Reddit").all()
        )
        assert len(reddit_rows) == 2
        first = reddit_rows[0]
        assert first.source_type == "social"
        assert first.title == "Why transformers changed machine learning"
        assert first.url == (
            "https://www.reddit.com/r/artificial/comments/1abcd/"
            "why_transformers_changed_machine_learning/"
        )
        assert first.author == "ml_enthusiast"
        assert first.published_at is not None
        assert first.retrieved_at is not None
        assert first.raw["id"] == "1abcd"
        assert first.raw["score"] == 1234


# --- Concurrent fan-out -------------------------------------------------------


class FakeAdapter:
    """Duck-typed adapter that sleeps before returning a fixed result list."""

    def __init__(self, source_name: str, delay_seconds: float, result_count: int) -> None:
        self.source_type = "reference"
        self.source_name = source_name
        self._delay = delay_seconds
        self._result_count = result_count

    async def search(self, query: str, params=None) -> list:
        from datetime import UTC, datetime

        from app.sources.base import SourceResult

        await asyncio.sleep(self._delay)
        return [
            SourceResult(
                source_type=self.source_type,
                source_name=self.source_name,
                title=f"{self.source_name} result {i}",
                url=f"https://example.com/{self.source_name}/{i}",
                retrieved_at=datetime.now(UTC),
                raw={"fake": True},
            )
            for i in range(self._result_count)
        ]


def test_sources_run_concurrently(session_factory, monkeypatch):
    delay = 0.4
    adapters = {
        "alpha": FakeAdapter("Alpha", delay, 1),
        "beta": FakeAdapter("Beta", delay, 1),
    }
    monkeypatch.setattr(registry, "_adapters", adapters)

    with session_factory() as session:
        search = Search(query="concurrent", normalized_query="concurrent")
        session.add(search)
        session.commit()
        search_id = search.id

    started = monotonic()
    asyncio.run(run_search_job(search_id))
    elapsed = monotonic() - started

    # Sequential would take >= 0.8s; concurrent fan-out must be well under.
    assert elapsed < delay * 2 - 0.05
    assert elapsed >= delay - 0.05

    with session_factory() as session:
        search = session.get(Search, search_id)
        assert search.status == "completed"
        events = session.query(SourceEvent).filter_by(search_id=search_id).all()
        assert {e.source_name for e in events} == {"Alpha", "Beta"}
        assert all(e.status == "success" for e in events)
        assert all(e.result_count == 1 for e in events)