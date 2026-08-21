"""Regression tests for the M3.5 pipeline-level per-source timeout (design §15.3.1).

The pipeline bounds every source unit with ``asyncio.wait_for`` so a source
that hangs without raising can never block the whole search. These tests prove:
adapter timeouts are recorded; a hung source is bounded and does not cause an
indefinite search; one/multiple hung sources coexist with healthy ones
(partial results persist); total duration is bounded; the terminal status is
deterministic; credentials never leak into API responses.
"""

import asyncio
from datetime import UTC, datetime
from time import monotonic

import pytest

from app.core.config import settings
from app.db.models import Result, Search, SourceEvent
from app.services.search_pipeline import run_search_job
from app.sources.base import SourceError, SourceResult
from app.sources.registry import registry


class FakeAdapter:
    """Controllable source: healthy / delayed / error / hangs-forever."""

    def __init__(self, name, stype, *, delay=0.0, count=3, hang=False, error=None, kind="failed"):
        self.source_name = name
        self.source_type = stype
        self._delay = delay
        self._count = count
        self._hang = hang
        self._error = error
        self._kind = kind

    async def search(self, query, params=None):
        if self._hang:
            await asyncio.sleep(1000)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise SourceError(self._error, kind=self._kind)
        now = datetime.now(UTC)
        return [
            SourceResult(
                source_type=self.source_type,
                source_name=self.source_name,
                title=f"{self.source_name} result {i}",
                url=f"https://example.com/{self.source_name}/{i}",
                retrieved_at=now,
                raw={"fake": True},
            )
            for i in range(self._count)
        ]


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch):
    monkeypatch.setattr(settings, "source_timeout_seconds", 0.2)


def _run(session_factory, monkeypatch, adapters) -> tuple:
    monkeypatch.setattr(registry, "_adapters", adapters)
    with session_factory() as session:
        search = Search(query="ai regulation", normalized_query="ai regulation", status="running")
        session.add(search)
        session.commit()
        search_id = search.id
    started = monotonic()
    asyncio.run(run_search_job(search_id))
    elapsed_ms = (monotonic() - started) * 1000
    with session_factory() as session:
        search = session.get(Search, search_id)
        results = session.query(Result).filter_by(search_id=search_id).all()
        events = {
            e.source_name: e
            for e in session.query(SourceEvent).filter_by(search_id=search_id).all()
        }
    return search, results, events, elapsed_ms


def test_adapter_timeout_is_recorded_and_isolated(session_factory, monkeypatch):
    search, results, events, _ = _run(
        session_factory,
        monkeypatch,
        {
            "healthy": FakeAdapter("Healthy", "news", count=3),
            "timing": FakeAdapter("Timing Out", "social", error="slow", kind="timeout"),
        },
    )
    assert search.status == "partial"
    assert events["Timing Out"].status == "timeout"
    assert events["Timing Out"].error_type == "timeout"
    assert events["Healthy"].status == "success"
    assert len(results) == 3
    assert {r.source_name for r in results} == {"Healthy"}


def test_hung_source_is_bounded_and_recorded(session_factory, monkeypatch):
    search, results, events, elapsed_ms = _run(
        session_factory,
        monkeypatch,
        {
            "hung": FakeAdapter("Hung", "news", hang=True),
            "healthy": FakeAdapter("Healthy", "news", count=3),
        },
    )
    assert search.status == "partial"
    assert events["Hung"].status == "timeout"
    assert events["Hung"].error_type == "timeout"
    assert "timeout" in (events["Hung"].error_message or "")
    assert events["Healthy"].status == "success"
    assert len(results) == 3
    # bounded: nowhere near the hung source's 1000 s sleep
    assert elapsed_ms < 5000
    assert search.duration_ms is not None and search.duration_ms < 5000


def test_one_hung_source_plus_healthy_keeps_healthy_results(session_factory, monkeypatch):
    search, results, events, _ = _run(
        session_factory,
        monkeypatch,
        {
            "hung": FakeAdapter("Hung", "social", hang=True),
            "a": FakeAdapter("A", "news", count=2),
            "b": FakeAdapter("B", "reference", count=4),
        },
    )
    assert search.status == "partial"
    assert events["Hung"].status == "timeout"
    assert events["A"].status == "success" and events["B"].status == "success"
    assert len(results) == 6
    assert {r.source_name for r in results} == {"A", "B"}


def test_multiple_hung_sources(session_factory, monkeypatch):
    search, results, events, _ = _run(
        session_factory,
        monkeypatch,
        {
            "hung1": FakeAdapter("Hung One", "news", hang=True),
            "hung2": FakeAdapter("Hung Two", "social", hang=True),
            "healthy": FakeAdapter("Healthy", "reference", count=2),
        },
    )
    assert search.status == "partial"
    assert events["Hung One"].status == "timeout"
    assert events["Hung Two"].status == "timeout"
    assert events["Healthy"].status == "success"
    assert len(results) == 2


def test_all_hung_sources_fail_deterministically(session_factory, monkeypatch):
    search, results, events, _ = _run(
        session_factory,
        monkeypatch,
        {
            "hung1": FakeAdapter("Hung One", "news", hang=True),
            "hung2": FakeAdapter("Hung Two", "social", hang=True),
        },
    )
    assert search.status == "failed"
    assert len(results) == 0
    assert events["Hung One"].status == "timeout"
    assert events["Hung Two"].status == "timeout"


def test_partial_results_persist_and_are_served(client, session_factory, monkeypatch):
    search, results, events, _ = _run(
        session_factory,
        monkeypatch,
        {
            "hung": FakeAdapter("Hung", "news", hang=True),
            "healthy": FakeAdapter("Healthy", "news", count=3),
        },
    )
    assert len(results) == 3
    payload = client.get(
        f"/api/v1/searches/{search.id}/results?per_page=100"
    ).json()
    assert payload["total"] == 3
    assert {i["source_name"] for i in payload["items"]} == {"Healthy"}


def test_bounded_total_duration_and_sources_timing(session_factory, monkeypatch):
    search, *_ = _run(
        session_factory,
        monkeypatch,
        {
            "hung": FakeAdapter("Hung", "news", hang=True),
            "healthy": FakeAdapter("Healthy", "news", count=3),
        },
    )
    timing = search.stats["timing_ms"]
    # sources phase is bounded by the pipeline timeout (0.2 s), not the hang
    assert timing["sources_ms"] < 2000
    assert timing["total_ms"] < 5000
    assert timing["postpass_ms"] >= 0


def test_no_credential_leakage(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "guardian_api_key", "SUPERSECRET-GUARDIAN")
    monkeypatch.setattr(settings, "reddit_client_id", "SUPERSECRET-REDDIT-ID")
    monkeypatch.setattr(settings, "reddit_client_secret", "SUPERSECRET-REDDIT-SECRET")
    search, results, events, _ = _run(
        session_factory,
        monkeypatch,
        {"healthy": FakeAdapter("Healthy", "news", count=3)},
    )
    for url in (
        f"/api/v1/searches/{search.id}",
        f"/api/v1/searches/{search.id}/results?per_page=100",
    ):
        text = client.get(url).text
        assert "SUPERSECRET" not in text, url
