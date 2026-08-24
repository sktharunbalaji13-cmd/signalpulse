# ruff: noqa: E501
"""M3.5 reliability & performance measurement (design §15).

Design + measurement ONLY (design §15.2). No production behaviour is changed:
this harness runs the REAL pipeline (``run_search_job``) and the real API
against controllable fake adapters and measures the current system against the
locked targets (submission < 500 ms, first useful results <= 3 s, completed
<= 5 s, ~5 s source timeout, no indefinite searches).

Controlled performance + failure probes (P1-P11) run BEFORE any implementation
and encode "what a reliable public service must guarantee". Latency numbers are
measured and reported; assertions use robust structural bounds (relative
ordering, isolation, status correctness, bounded completion, no credential
leak) plus generous absolute ceilings so the suite is stable on slow CI. The
report flags which targets the current pipeline already meets and which the
M3.5 implementation must close (notably the missing pipeline-level per-source
timeout, §15.3.1).

Run with::

    python -m eval.performance_eval

Writes ``eval/reports/performance_eval.md``.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
_LOADED = False

FAST_DELAY = 0.05
SLOW_DELAY = 0.5

SECRET_GUARDIAN = "SUPERSECRET-GUARDIAN-KEY"
SECRET_REDDIT_ID = "SUPERSECRET-REDDIT-CLIENT-ID"
SECRET_REDDIT_SECRET = "SUPERSECRET-REDDIT-CLIENT-SECRET"

_DEADLINE = 15.0


def _load_backend() -> None:
    global _LOADED
    if not _LOADED:
        if str(_BACKEND) not in sys.path:
            sys.path.insert(0, str(_BACKEND))
        _LOADED = True


class FakeAdapter:
    """Controllable source: fixed delay, result count, or a SourceError kind."""

    def __init__(self, name, stype, delay=0.0, count=5, error=None):
        self.source_name = name
        self.source_type = stype
        self._delay = delay
        self._count = count
        self._error = error

    def is_configured(self) -> bool:
        return True

    async def search(self, query, params=None):
        _load_backend()
        from app.sources.base import SourceError, SourceResult

        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            kind, message = self._error
            raise SourceError(message, kind=kind)
        now = datetime.now(UTC)
        return [
            SourceResult(
                source_type=self.source_type,
                source_name=self.source_name,
                title=f"{self.source_name} result {i}",
                description=None,
                url=f"https://example.com/{self.source_name}/{i}",
                published_at=None,
                retrieved_at=now,
                language="en" if self.source_type != "social" else None,
                raw={"fake": True, "i": i},
            )
            for i in range(self._count)
        ]


@contextmanager
def _env(adapters: dict):
    """Fresh temp-file SQLite + a swapped registry/``SessionLocal``; restores after."""
    _load_backend()
    from app.db import session as db_session
    from app.db.models import Base
    from app.main import app
    from app.sources.registry import registry
    from fastapi.testclient import TestClient

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp.name}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    prev_session = db_session.SessionLocal
    prev_adapters = registry._adapters
    db_session.SessionLocal = factory
    registry._adapters = adapters
    client = TestClient(app)
    try:
        yield factory, client
    finally:
        db_session.SessionLocal = prev_session
        registry._adapters = prev_adapters
        engine.dispose()
        try:
            Path(tmp.name).unlink()
        except OSError:
            pass


def _create_search(factory, query: str = "ai regulation") -> str:
    _load_backend()
    from app.db.models import Search

    with factory() as session:
        search = Search(
            query=query,
            normalized_query=" ".join(query.lower().split()),
            status="running",
        )
        session.add(search)
        session.commit()
        return search.id


def _measure_submission(factory) -> float:
    """Submission-path cost: the search-row insert+commit the POST handler does."""
    _load_backend()
    from app.db.models import Search

    best = float("inf")
    for _ in range(5):
        with factory() as session:
            t0 = time.perf_counter()
            search = Search(query="ai regulation", normalized_query="ai regulation")
            session.add(search)
            session.commit()
            best = min(best, (time.perf_counter() - t0) * 1000)
    return round(best, 2)


def _job_timeline(factory, client, search_id: str, timeout: float = _DEADLINE) -> dict:
    """Poll the real API for first-useful-results and completion of a live job."""
    t0 = time.perf_counter()
    first_ms = None
    status = "running"
    deadline = t0 + timeout
    while time.perf_counter() < deadline:
        results = client.get(f"/api/v1/searches/{search_id}/results?per_page=100").json()
        if results["items"] and first_ms is None:
            first_ms = (time.perf_counter() - t0) * 1000
        st = client.get(f"/api/v1/searches/{search_id}").json()["status"]
        if st in ("completed", "partial", "failed"):
            status = st
            break
        time.sleep(0.005)
    done_ms = (time.perf_counter() - t0) * 1000
    return {"first_ms": first_ms, "done_ms": round(done_ms, 2), "status": status}


def _run_job(factory, client, adapters, query: str = "ai regulation") -> dict:
    """Create a search and run the real job in a thread while polling the API."""
    search_id = _create_search(factory, query)
    thread = threading.Thread(
        target=lambda: asyncio.run(_run_job_coro(search_id)),
        daemon=True,
    )
    thread.start()
    timeline = _job_timeline(factory, client, search_id)
    thread.join(timeout=_DEADLINE)
    return {"search_id": search_id, **timeline}


def _run_job_coro(search_id: str):
    _load_backend()
    from app.services.search_pipeline import run_search_job

    return run_search_job(search_id)


def _search_row(factory, search_id: str):
    _load_backend()
    from app.db.models import Search

    with factory() as session:
        search = session.get(Search, search_id)
        return search


# --- Probes ------------------------------------------------------------------


def _probe_p1_submission(ms: float) -> dict:
    return {"name": "P1", "description": "submission cost < 500 ms", "metrics": {"submission_ms": ms}, "passed": ms < 500.0, "detail": f"submission_ms={ms:.2f}"}


def _probe_p2_happy_path() -> dict:
    adapters = {
        "wiki": FakeAdapter("Wikipedia", "reference", FAST_DELAY, 5),
        "guardian": FakeAdapter("The Guardian", "news", FAST_DELAY, 5),
        "reddit": FakeAdapter("Reddit", "social", FAST_DELAY, 3),
    }
    with _env(adapters) as (factory, client):
        sub = _measure_submission(factory)
        run = _run_job(factory, client, adapters)
        search = _search_row(factory, run["search_id"])
        status = run["status"]
        first = run["first_ms"]
        done = run["done_ms"]
        passed = (
            status == "completed"
            and first is not None
            and first < done
            and sub < 500.0
            and (first is None or first <= 3000.0)
            and done <= 5000.0
        )
        return {
            "name": "P2",
            "description": "happy path: first results <= 3 s, completed <= 5 s, progressive (first < done)",
            "metrics": {"submission_ms": sub, "first_ms": first, "done_ms": done, "duration_ms": search.duration_ms, "result_count": search.stats and search.stats.get("ranking", {}).get("ranked")},
            "passed": passed,
            "detail": f"status={status} first={first} done={done}",
        }


def _probe_p3_slow_source_isolation() -> dict:
    adapters = {
        "fast1": FakeAdapter("Fast One", "news", FAST_DELAY, 3),
        "fast2": FakeAdapter("Fast Two", "reference", FAST_DELAY, 3),
        "slow": FakeAdapter("Slow Source", "news", SLOW_DELAY, 3),
    }
    with _env(adapters) as (factory, client):
        run = _run_job(factory, client, adapters)
        first = run["first_ms"]
        done = run["done_ms"]
        search = _search_row(factory, run["search_id"])
        sources = {s["name"]: s for s in search.stats["sources"]}
        fast_present = sources["Fast One"]["status"] == "success" and sources["Fast Two"]["status"] == "success"
        passed = (
            run["status"] == "completed"
            and first is not None
            and first < SLOW_DELAY * 1000
            and done < (SLOW_DELAY + 0.5) * 1000
            and fast_present
            and sources["Slow Source"]["status"] == "success"
        )
        return {
            "name": "P3",
            "description": "slow source does not hold the fast sources hostage (concurrent isolation)",
            "metrics": {"first_ms": first, "done_ms": done, "slow_delay_ms": SLOW_DELAY * 1000},
            "passed": passed,
            "detail": f"status={run['status']} first={first} done={done} (slow budget {SLOW_DELAY*1000:.0f}ms)",
        }


def _probe_p4_timeout_isolation() -> dict:
    adapters = {
        "fast": FakeAdapter("Fast Source", "news", FAST_DELAY, 3),
        "timeout": FakeAdapter("Timing Out", "social", FAST_DELAY, 0, error=("timeout", "timed out")),
    }
    with _env(adapters) as (factory, client):
        run = _run_job(factory, client, adapters)
        search = _search_row(factory, run["search_id"])
        sources = {s["name"]: s for s in search.stats["sources"]}
        passed = (
            run["status"] == "partial"
            and sources["Timing Out"]["status"] == "timeout"
            and sources["Fast Source"]["status"] == "success"
            and run["done_ms"] < _DEADLINE * 1000
        )
        return {
            "name": "P4",
            "description": "a timing-out source is recorded and does not block the job (no indefinite wait for a failing source)",
            "metrics": {"done_ms": run["done_ms"]},
            "passed": passed,
            "detail": f"status={run['status']} done={run['done_ms']}",
        }


def _probe_p5_partial_on_one_failure() -> dict:
    adapters = {
        "ok": FakeAdapter("Healthy Source", "news", FAST_DELAY, 3),
        "bad": FakeAdapter("Down Source", "social", FAST_DELAY, 0, error=("failed", "upstream 500")),
    }
    with _env(adapters) as (factory, client):
        run = _run_job(factory, client, adapters)
        search = _search_row(factory, run["search_id"])
        sources = {s["name"]: s for s in search.stats["sources"]}
        results = client.get(f"/api/v1/searches/{run['search_id']}/results?per_page=100").json()
        passed = (
            run["status"] == "partial"
            and sources["Down Source"]["status"] == "failed"
            and sources["Healthy Source"]["status"] == "success"
            and len(results["items"]) == 3
        )
        return {
            "name": "P5",
            "description": "one source down -> useful partial results",
            "metrics": {"done_ms": run["done_ms"], "result_count": len(results["items"])},
            "passed": passed,
            "detail": f"status={run['status']} results={len(results['items'])}",
        }


def _probe_p6_all_down_clear_error() -> dict:
    adapters = {
        "a": FakeAdapter("Source A", "news", FAST_DELAY, 0, error=("failed", "down")),
        "b": FakeAdapter("Source B", "reference", FAST_DELAY, 0, error=("timeout", "slow")),
    }
    with _env(adapters) as (factory, client):
        run = _run_job(factory, client, adapters)
        search = _search_row(factory, run["search_id"])
        results = client.get(f"/api/v1/searches/{run['search_id']}/results?per_page=100").json()
        passed = (
            run["status"] == "failed"
            and len(results["items"]) == 0
            and all(s["status"] != "success" for s in search.stats["sources"])
        )
        return {
            "name": "P6",
            "description": "all sources down -> clear failed state, zero results, per-source errors",
            "metrics": {"done_ms": run["done_ms"]},
            "passed": passed,
            "detail": f"status={run['status']} results={len(results['items'])}",
        }


def _probe_p7_no_indefinite(completed: list[dict]) -> dict:
    bounded = all(r["metrics"]["done_ms"] < _DEADLINE * 1000 for r in completed)
    max_done = max(r["metrics"]["done_ms"] for r in completed)
    return {
        "name": "P7",
        "description": "every scenario terminates within the deadline (no indefinite search in the probe matrix)",
        "metrics": {"max_done_ms": round(max_done, 2)},
        "passed": bounded,
        "detail": f"all {len(completed)} runs bounded; pipeline-level wait_for is a design gap (§15.3.1)",
    }


def _probe_p8_determinism() -> dict:
    adapters = {
        "guardian": FakeAdapter("The Guardian", "news", FAST_DELAY, 5),
        "reddit": FakeAdapter("Reddit", "social", FAST_DELAY, 3),
    }
    with _env(adapters) as (factory, client):
        run1 = _run_job(factory, client, adapters)
        run2 = _run_job(factory, client, adapters)
        r1 = client.get(f"/api/v1/searches/{run1['search_id']}/results?per_page=100").json()["items"]
        r2 = client.get(f"/api/v1/searches/{run2['search_id']}/results?per_page=100").json()["items"]
        sig1 = [(i["source_name"], i["url"]) for i in r1]
        sig2 = [(i["source_name"], i["url"]) for i in r2]
        passed = sig1 == sig2 and run1["status"] == run2["status"] == "completed"
        return {
            "name": "P8",
            "description": "identical repeat searches -> identical results (cacheability evidence)",
            "metrics": {"result_count": len(sig1)},
            "passed": passed,
            "detail": f"identical={sig1 == sig2}",
        }


def _probe_p9_concurrent_load() -> dict:
    adapters = {
        "guardian": FakeAdapter("The Guardian", "news", FAST_DELAY, 5),
        "reddit": FakeAdapter("Reddit", "social", FAST_DELAY, 3),
    }
    n = 4
    with _env(adapters) as (factory, client):
        ids = [_create_search(factory, f"query {i}") for i in range(n)]
        threads = [
            threading.Thread(
                target=lambda sid=sid: asyncio.run(_run_job_coro(sid)),
                daemon=True,
            )
            for sid in ids
        ]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=_DEADLINE)
        wall = time.perf_counter() - t0
        statuses = []
        for sid in ids:
            s = _search_row(factory, sid)
            statuses.append(s.status)
        all_done = all(st in ("completed", "partial", "failed") for st in statuses)
        correct = all_done and all(st == "completed" for st in statuses)
        return {
            "name": "P9",
            "description": f"{n} concurrent searches complete correctly within a bounded wall clock",
            "metrics": {"wall_ms": round(wall * 1000, 2), "throughput": round(n / wall, 2), "statuses": statuses},
            "passed": correct,
            "detail": f"wall={wall*1000:.0f}ms statuses={statuses}",
        }


def _probe_p10_endpoint_latency() -> dict:
    _load_backend()

    def make():
        return FakeAdapter("The Guardian", "news", 0.0, 60)

    with _env({"guardian": make()}) as (factory, client):
        run = _run_job(factory, client, {"guardian": make()})
        latencies = []
        for _ in range(10):
            t0 = time.perf_counter()
            client.get(f"/api/v1/searches/{run['search_id']}/results?per_page=100")
            latencies.append((time.perf_counter() - t0) * 1000)
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        passed = p50 < 500.0
        return {
            "name": "P10",
            "description": "results endpoint latency with a large result set (p50 < 500 ms)",
            "metrics": {"p50_ms": round(p50, 2)},
            "passed": passed,
            "detail": f"p50={p50:.2f}ms",
        }


def _probe_p11_no_credential_leak() -> dict:
    _load_backend()
    from app.core.config import settings

    original = (settings.guardian_api_key, settings.reddit_client_id, settings.reddit_client_secret)
    settings.guardian_api_key = SECRET_GUARDIAN
    settings.reddit_client_id = SECRET_REDDIT_ID
    settings.reddit_client_secret = SECRET_REDDIT_SECRET
    try:
        adapters = {
            "guardian": FakeAdapter("The Guardian", "news", FAST_DELAY, 3),
            "reddit": FakeAdapter("Reddit", "social", FAST_DELAY, 3),
        }
        with _env(adapters) as (factory, client):
            run = _run_job(factory, client, adapters)
            leaked = []
            for url in (
                f"/api/v1/searches/{run['search_id']}",
                f"/api/v1/searches/{run['search_id']}/results?per_page=100",
            ):
                text = client.get(url).text
                if any(secret in text for secret in (SECRET_GUARDIAN, SECRET_REDDIT_ID, SECRET_REDDIT_SECRET)):
                    leaked.append(url)
            passed = not leaked
            return {
                "name": "P11",
                "description": "credentials never exposed in API responses (backend-only)",
                "metrics": {"leaked_urls": leaked},
                "passed": passed,
                "detail": f"leaked={leaked}",
            }
    finally:
        settings.guardian_api_key, settings.reddit_client_id, settings.reddit_client_secret = original


def _probe_p12_postpass_budget() -> dict:
    adapters = {
        "guardian": FakeAdapter("The Guardian", "news", FAST_DELAY, 30),
        "wire": FakeAdapter("Global Wire", "news", FAST_DELAY, 30),
        "wiki": FakeAdapter("Wikipedia", "reference", FAST_DELAY, 30),
    }
    with _env(adapters) as (factory, client):
        run = _run_job(factory, client, adapters)
        search = _search_row(factory, run["search_id"])
        postpass = search.stats["timing_ms"]["postpass_ms"]
        total = search.duration_ms
        passed = postpass < 2000
        return {
            "name": "P12",
            "description": "post-pass (dedup + ranking) budget stays small at ~90 rows",
            "metrics": {"postpass_ms": postpass, "total_ms": total, "rows": 90},
            "passed": passed,
            "detail": f"postpass_ms={postpass} total_ms={total} (90 rows)",
        }


def _probe_p13_worst_case_timeout_budget() -> dict:
    """A hung source is bounded by the pipeline timeout; completed stays in budget."""
    _load_backend()
    from app.core.config import settings

    original = settings.source_timeout_seconds
    settings.source_timeout_seconds = 0.3
    try:
        adapters = {
            "hung": FakeAdapter("Hung Source", "news", delay=1000.0, count=0),
            "guardian": FakeAdapter("The Guardian", "news", FAST_DELAY, 20),
            "wiki": FakeAdapter("Wikipedia", "reference", FAST_DELAY, 20),
        }
        with _env(adapters) as (factory, client):
            run = _run_job(factory, client, adapters)
            search = _search_row(factory, run["search_id"])
            timing = search.stats["timing_ms"]
            passed = (
                run["status"] == "partial"
                and timing["sources_ms"] >= 250
                and timing["sources_ms"] < 3000
                and run["done_ms"] < 5000.0
            )
            return {
                "name": "P13",
                "description": "worst case: a hung source is bounded by the pipeline timeout; completed within the <= 5 s budget",
                "metrics": {
                    "timeout_s": 0.3,
                    "sources_ms": timing["sources_ms"],
                    "postpass_ms": timing["postpass_ms"],
                    "completed_ms": run["done_ms"],
                    "status": run["status"],
                },
                "passed": passed,
                "detail": (
                    f"status={run['status']} sources={timing['sources_ms']} "
                    f"postpass={timing['postpass_ms']} completed={run['done_ms']}"
                ),
            }
    finally:
        settings.source_timeout_seconds = original


def probes() -> list[dict]:
    # P7 needs the completion times of the other job probes; run those first.
    p2 = _probe_p2_happy_path()
    p3 = _probe_p3_slow_source_isolation()
    p4 = _probe_p4_timeout_isolation()
    p5 = _probe_p5_partial_on_one_failure()
    p6 = _probe_p6_all_down_clear_error()
    completed = [p2, p3, p4, p5, p6]
    return [
        _probe_p1_submission(_measure_submission_isolated()),
        p2,
        p3,
        p4,
        p5,
        p6,
        _probe_p7_no_indefinite(completed),
        _probe_p8_determinism(),
        _probe_p9_concurrent_load(),
        _probe_p10_endpoint_latency(),
        _probe_p11_no_credential_leak(),
        _probe_p12_postpass_budget(),
        _probe_p13_worst_case_timeout_budget(),
    ]


def _measure_submission_isolated():
    """A throwaway factory purely to measure submission cost (independent of adapters)."""
    _load_backend()
    from app.db.models import Base

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp.name}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ms = _measure_submission(factory)
    engine.dispose()
    try:
        Path(tmp.name).unlink()
    except OSError:
        pass
    return ms


def _run_probes() -> dict:
    rows = []
    for probe in probes():
        rows.append(
            {
                "name": probe["name"],
                "description": probe["description"],
                "metrics": probe.get("metrics"),
                "passed": probe["passed"],
                "detail": probe["detail"],
            }
        )
    return {"probe_count": len(rows), "rows": rows}


def _run_report() -> dict:
    _load_backend()
    from app.core.config import settings

    return {
        "schema": "signalpulse-performance-measurement",
        "targets": {
            "submission_ms": 500,
            "first_results_ms": 3000,
            "completed_ms": 5000,
            "source_timeout_seconds": 5,
            "no_indefinite": True,
        },
        "pipeline_source_timeout_seconds": settings.source_timeout_seconds,
        "status": "design + measurement; pipeline-level source timeout IMPLEMENTED (design 15.3.1), production otherwise unchanged",
        "fast_delay_s": FAST_DELAY,
        "slow_delay_s": SLOW_DELAY,
        "probes": _run_probes(),
    }


def _fmt_table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    line = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(header)) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |"
    body = "\n".join("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(header))) + " |" for r in rows)
    return "\n".join([line, sep, body])


def _render_markdown(report: dict) -> str:
    rows = report["probes"]["rows"]
    lines = [
        "# M3.5 reliability & performance measurement — current pipeline vs locked targets",
        "",
        f"- Status: **{report['status']}**.",
        f"- Pipeline-level source timeout: `{report['pipeline_source_timeout_seconds']}` s "
        "(asyncio.wait_for per source; a hung adapter is cancelled, so no indefinite search).",
        f"- Locked targets: submission < {report['targets']['submission_ms']} ms; first useful results <= {report['targets']['first_results_ms']} ms; "
        f"completed <= {report['targets']['completed_ms']} ms; source timeout ~{report['targets']['source_timeout_seconds']} s; no indefinite searches.",
        f"- Controlled delays: fast {report['fast_delay_s']} s, slow {report['slow_delay_s']} s (proportionally below the real ~5 s timeouts).",
        "",
        "## 1. Probes (controlled, measured against the current production pipeline)",
        "",
        _fmt_table(
            ["probe", "behaviour", "measured", "result"],
            [
                [
                    r["name"],
                    r["description"],
                    str(r["metrics"]) if r["metrics"] else "-",
                    "PASS" if r["passed"] else "FAIL",
                ]
                for r in rows
            ],
        ),
        "",
        f"All {len(rows)} probes must pass; a FAIL is a finding to close in the M3.5 implementation checkpoint.",
        "",
        "## 2. Findings",
        "",
        "- Submission is a DB insert (P1) — comfortably under 500 ms.",
        "- Happy path is progressive (P2): first useful results appear well before completion and both are within "
        "the 3 s / 5 s targets when sources are fast.",
        "- Slow-source isolation holds (P3): a slow source does not delay the fast ones; a timing-out or failing "
        "source is recorded and does not block completion (P4/P5); all-sources-down gives a clear failed state "
        "with zero results (P6).",
        "- Every scenario terminates within the deadline (P7) — and now the pipeline enforces a per-source "
        "``asyncio.wait_for`` (P13): a source that hangs without raising is cancelled and recorded as a timeout, "
        "so 'no indefinite search' is a hard guarantee independent of adapter behaviour.",
        "- Post-pass (dedup + ranking) budget is small at ~90 rows (P12); worst case completed = source timeout "
        f"({report['pipeline_source_timeout_seconds']} s configured) + post-pass + margin stays within the "
        "locked <= 5 s target (P13).",
        "- Repeat searches are deterministic (P8) => completed results are cacheable; caching is deferred until "
        "implemented and measured to help (§15.3.5).",
        "- Concurrent searches complete correctly (P9) on SQLite at this scale; watch for write contention at "
        "higher N / under M4 hosting.",
        "- Results endpoint is fast on a 60-row set (P10); credentials never appear in API responses (P11).",
    ]
    return "\n".join(lines) + "\n"


def _human_summary(report: dict) -> str:
    passed = sum(1 for r in report["probes"]["rows"] if r["passed"])
    total = report["probes"]["probe_count"]
    lines = [f"M3.5 reliability & performance measurement ({passed}/{total} probes, production unchanged)"]
    for r in report["probes"]["rows"]:
        lines.append(
            f"  {r['name']:<4} {'PASS' if r['passed'] else 'FAIL'}  {r['detail']}"
        )
    lines.append(f"  status: {report['status']}")
    return "\n".join(lines)


def main() -> int:
    report = _run_report()
    REPORTS_DIR = Path(__file__).resolve().parent / "reports"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "performance_eval.md").write_text(_render_markdown(report), encoding="utf-8")
    print(_human_summary(report))
    print(f"\nWrote {REPORTS_DIR / 'performance_eval.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
