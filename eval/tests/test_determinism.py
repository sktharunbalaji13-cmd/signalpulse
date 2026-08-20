"""Determinism tests: the harness must produce identical output every run."""

import json

from eval.runner import _run_report


def test_report_is_deterministic():
    first = _run_report()
    second = _run_report()
    assert first == second


def test_main_writes_identical_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("eval.runner.REPORT_PATH", tmp_path / "latest.json")

    from eval.runner import main

    assert main() == 0
    first_bytes = (tmp_path / "latest.json").read_bytes()

    assert main() == 0
    second_bytes = (tmp_path / "latest.json").read_bytes()

    assert first_bytes == second_bytes


def test_report_json_is_valid_and_sorted():
    report = _run_report()
    raw = json.dumps(report, indent=2, sort_keys=True)
    assert json.loads(raw) == report
    assert report["schema"] == "signalpulse-eval-report"


def test_report_declares_pending_stages():
    report = _run_report()
    assert report["deduplication"]["status"] == "pending_m3_a"
    assert report["freshness"]["status"] == "pending_m3_c"


def test_report_targets_are_present_but_not_claimed():
    report = _run_report()
    targets = report["targets"]
    assert targets["dedup_precision"] == 0.90
    assert targets["dedup_recall"] == 0.90
    assert targets["ndcg_at_10"] == 0.75
    # Baseline ranking metrics are reported as measured, not as target achievement.
    assert "means" in report["baseline_ranking"]
