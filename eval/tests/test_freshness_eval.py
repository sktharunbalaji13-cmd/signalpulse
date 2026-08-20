"""Regression tests for the M3-C freshness experiment (offline, deterministic).

These pin the measured behaviour of the candidate freshness functions — the
numbers are the honest first measurement on the unchanged v2 corpus, NOT a
passing target. If they change, that is a regression (or an intentional,
documented retune). The production freshness scorer does not exist yet;
nothing here is combined with relevance.
"""

import math

from eval import freshness_eval as fe

INVARIANTS = (
    "missing_timestamp_handled",
    "no_retrieved_substitution",
    "monotonic_with_age",
    "future_clamped",
)


def _scorer(name: str):
    return fe.candidates()[name]["scorer"]


def _news(name: str, hours_ago: float) -> float:
    return _scorer(name)(fe._ts(hours_ago), fe._ts(0.0), "news")


def test_all_candidates_pass_the_admissibility_gate():
    inv = fe._invariants_table()
    assert set(inv) == set(fe.candidates())
    for checks in inv.values():
        for key in INVARIANTS:
            assert checks[key] is True, (checks, key)


def test_report_is_deterministic():
    first = fe._run_report()
    second = fe._run_report()
    assert first == second


def test_main_writes_identical_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("eval.freshness_eval.REPORT_PATH", tmp_path / "freshness_eval.md")
    assert fe.main() == 0
    first = (tmp_path / "freshness_eval.md").read_bytes()
    assert fe.main() == 0
    assert first == (tmp_path / "freshness_eval.md").read_bytes()


def test_report_has_no_combination_section():
    report = fe._run_report()
    assert set(report) == {
        "schema", "fixed_now", "corpus_revision", "corpus_unchanged", "status",
        "candidates", "invariants", "corpus_behavior", "probes", "interaction",
    }
    assert report["status"].startswith("research measurement only")


def test_design_curve_pins():
    design = _scorer("design")
    assert math.isclose(design(fe._ts(0.0), fe._ts(0.0), "news"), 1.0)
    assert round(_news("design", 1.0), 4) == 0.973
    assert round(_news("design", 24.0), 4) == 0.525
    assert round(_news("design", 168.0), 4) == 0.0574
    assert math.isclose(_news("design", 720.0), 0.05, abs_tol=1e-6)


def test_half_life_ordering():
    names = ("hl_06h", "hl_12h", "design", "hl_48h", "hl_168h")
    at_24h = {name: _news(name, 24.0) for name in names}
    assert at_24h["hl_06h"] < at_24h["hl_12h"]
    assert at_24h["hl_12h"] < at_24h["design"]
    assert at_24h["design"] < at_24h["hl_48h"]
    assert at_24h["hl_48h"] < at_24h["hl_168h"]


def test_floor_ordering():
    at_30d = {name: _news(name, 720.0) for name in ("floor_00", "design", "floor_25")}
    assert at_30d["floor_00"] < at_30d["design"] < at_30d["floor_25"]
    assert at_30d["floor_00"] < 1e-6
    assert math.isclose(at_30d["floor_25"], 0.25, abs_tol=1e-6)


def test_shape_ordering_at_48h():
    at_48h = {name: _news(name, 48.0) for name in ("shape_linear30d", "shape_step", "design")}
    assert at_48h["shape_linear30d"] > at_48h["shape_step"] > at_48h["design"]


def test_social_decays_faster_than_news_under_design():
    scorer = _scorer("design")
    news = scorer(fe._ts(24.0), fe._ts(0.0), "news")
    social = scorer(fe._ts(24.0), fe._ts(0.0), "social")
    assert round(news, 4) == 0.525
    assert round(social, 4) == 0.2875
    assert social < news


def test_reference_is_timeless_for_every_candidate():
    for name in fe.candidates():
        scorer = _scorer(name)
        at_now = scorer(fe._ts(0.0), fe._ts(0.0), "reference")
        two_years = scorer(fe._ts(17520.0), fe._ts(0.0), "reference")
        assert at_now == two_years, name


def test_future_timestamps_clamped_for_every_candidate():
    for name in fe.candidates():
        scorer = _scorer(name)
        now = scorer(fe._ts(0.0), fe._ts(0.0), "news")
        future = scorer(fe._ts(24.0, future=True), fe._ts(0.0), "news")
        assert future == now, name


def test_missing_timestamp_levels():
    for name, expected in (
        ("design", 0.25),
        ("miss_00", 0.0),
        ("miss_05", 0.5),
    ):
        assert _scorer(name)(None, fe._ts(0.0), "news") == expected
        assert _scorer(name)(None, fe._ts(0.0), "reference") == 0.5


def test_retrieved_at_never_influences_freshness():
    for name in fe.candidates():
        scorer = _scorer(name)
        a = scorer(None, "2026-08-19T12:00:00Z", "news")
        b = scorer(None, "2026-07-01T12:00:00Z", "news")
        assert a == b, name


def test_decoy_tension_reported_for_design():
    report = fe._run_report()
    design = next(r for r in report["corpus_behavior"]["per_candidate"] if r["name"] == "design")
    assert design["decoy_tension_rel0_fresh_ge09"] == 0
    assert design["decoy_tension_rel0_fresh_ge07"] == 10
    assert design["old_relevant_tension_rel_ge1_fresh_lt05"] == 191


def test_freshest_items_are_the_recent_weak_relevance_population():
    report = fe._run_report()
    freshest = report["corpus_behavior"]["freshest_10"]
    assert freshest[0]["id"] == "q01_14"
    assert freshest[0]["title"] == "Update"
    assert freshest[0]["relevance"] == 0
    assert freshest[0]["age_hours"] < 12.0


def test_interaction_pins_for_design():
    report = fe._run_report()
    design = next(r for r in report["interaction"]["per_candidate"] if r["name"] == "design")
    assert design["spearman_overall"] == 0.407
    assert design["spearman_by_type"]["news"] == 0.4522
    assert design["spearman_by_type"]["social"] == 0.3623
    assert design["spearman_by_type"]["reference"] == "constant (no variance)"


def test_spearman_helper():
    assert fe.spearman([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    assert fe.spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0
    assert fe.spearman([1.0, 1.0, 2.0], [1.0, 1.0, 2.0]) == 1.0


def test_spearman_constant_is_nan():
    import math

    assert math.isnan(fe.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]))


def test_monotone_candidates_share_within_type_interaction():
    report = fe._run_report()
    rows = {r["name"]: r for r in report["interaction"]["per_candidate"]}
    monotone = (
        "design", "shape_linear30d", "hl_12h", "hl_48h",
        "floor_00", "floor_25", "ref_09", "social_24",
    )
    news_rhos = {name: rows[name]["spearman_by_type"]["news"] for name in monotone}
    assert len(set(news_rhos.values())) == 1
    assert news_rhos["design"] == 0.4522