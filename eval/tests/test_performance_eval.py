"""Regression tests for the M3.5 reliability & performance measurement (design §15).

The controlled performance + failure probes (P1-P11) run the real production
pipeline against controllable fake adapters and assert the structural
invariants a public service must guarantee (submission cost, happy-path
progressive delivery, slow-source isolation, graceful partial/failed states,
bounded termination, determinism, concurrent load, endpoint latency, no
credential leak). Latency targets are reported in
``eval/reports/performance_eval.md``; the assertions here use robust bounds so
the suite is stable on slow CI.

Measurement only: no production behaviour is changed.
"""

from eval import performance_eval as pe


def test_every_probe_passes():
    rows = pe._run_probes()["rows"]
    assert {r["name"] for r in rows} == {f"P{i}" for i in range(1, 12)}
    for row in rows:
        assert row["passed"] is True, (row["name"], row["detail"])


def test_probe_outcomes_are_structural_and_stable():
    """PASS/FAIL outcomes and definitions are deterministic across runs.

    (Raw latencies vary run-to-run — they are measured, not computed — so the
    report is intentionally NOT byte-deterministic; the structural outcomes are.)
    """
    first = pe._run_probes()["rows"]
    second = pe._run_probes()["rows"]
    sig = lambda rows: [(r["name"], r["description"], r["passed"]) for r in rows]  # noqa: E731
    assert sig(first) == sig(second)


def test_probe_matrix_covers_the_locked_targets():
    targets = pe._run_report()["targets"]
    assert targets["submission_ms"] == 500
    assert targets["first_results_ms"] == 3000
    assert targets["completed_ms"] == 5000
    assert targets["source_timeout_seconds"] == 5
    assert targets["no_indefinite"] is True


def test_credentials_sentinels_are_distinct():
    assert pe.SECRET_GUARDIAN != pe.SECRET_REDDIT_ID != pe.SECRET_REDDIT_SECRET
    assert "SUPERSECRET" in pe.SECRET_GUARDIAN
