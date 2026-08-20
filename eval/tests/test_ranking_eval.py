"""Regression tests for the M3-D combined-ranking experiment (offline, deterministic).

The behavioural acceptance probes (P1-P9) are the admissibility bar: every
candidate must pass all of them. Corpus metrics are secondary evidence only
(the v2 corpus cannot isolate freshness from relevance, M3-C rho ~ 0.41) and
are pinned here to detect regressions, not to tune weights.
"""

import hashlib

from eval import ranking_eval as re

ALL_PROBES = [
    "P1",
    "P2",
    "P3",
    "P4",
    "P5",
    "P6",
    "P7",
    "P8",
    "P9",
]


def test_every_candidate_passes_every_probe():
    rows = re._run_probes()["rows"]
    assert {r["name"] for r in rows} == set(ALL_PROBES)
    for row in rows:
        for candidate, result in row["per_candidate"].items():
            assert result["passed"] is True, (row["name"], candidate, result["detail"])


def test_report_is_deterministic():
    first = hashlib.sha256(repr(re._run_report()).encode("utf-8")).hexdigest()
    second = hashlib.sha256(repr(re._run_report()).encode("utf-8")).hexdigest()
    assert first == second


def test_ts_key_orders_newest_first_and_none_last():
    from eval.schema import EvalItem

    def item(pub) -> EvalItem:
        return re._pi("x", "AI regulation", "news", "The Guardian", pub, 2)

    newer = re._ts_key(item(re._ts(4.0)))
    older = re._ts_key(item(re._ts(720.0)))
    missing = re._ts_key(item(None))
    assert newer < older, "newer published_at sorts before older"
    assert newer[0] == 0 and older[0] == 0
    assert missing[0] == 1, "missing published_at sorts last"


def test_tie_break_url_lexicographic():
    p6 = re._probe_p6()
    ranked = re._rank(p6["items"], p6["query"], re.CANDIDATES["C1_design"])
    assert ranked.index("aaa") < ranked.index("bbb")
    assert "https://example.probe/aaa" < "https://example.probe/bbb"


def test_duplicate_members_inherit_score_without_boost():
    p7 = re._probe_p7()
    ranked = re._rank(p7["items"], p7["query"], re.CANDIDATES["C1_design"])
    rows = re.rank_combined(p7["items"], p7["query"], re.CANDIDATES["C1_design"])
    by_id = {row["id"]: row for row in rows}
    assert by_id["a"]["score"] == by_id["a2"]["score"]
    assert ranked.index("b") > ranked.index("a")


def test_diversity_toggle_only_reorders_inside_the_band():
    p8 = re._probe_p8()
    items, query = p8["items"], p8["query"]
    div = re._rank(items, query, re.CANDIDATES["C4_design_diversity"], diversity=True)
    plain = re._rank(items, query, re.CANDIDATES["C4_design_diversity"], diversity=False)
    assert div != plain
    rows = re.rank_combined(items, query, re.CANDIDATES["C4_design_diversity"])
    by_score = {row["id"]: row["score"] for row in rows}
    band = [i for i in div if by_score[i] >= by_score["g1"] - 0.05]
    assert len(band) >= 2
    types = {row["id"]: row["source_type"] for row in rows}
    assert all(types[band[j]] != types[band[j + 1]] for j in range(len(band) - 1))

    inert = re._rank(items, query, re.CANDIDATES["C1_design"])
    inert_plain = re._rank(items, query, re.CANDIDATES["C1_design"], diversity=False)
    assert inert == inert_plain, "diversity toggle is inert for candidates without the pass"


def test_combined_score_formula_c1():
    item = re._pi("x", "AI regulation", "news", "The Guardian", re._ts(24.0), 2)
    rows = re.rank_combined([item], "ai regulation", re.CANDIDATES["C1_design"])
    row = rows[0]
    freshness = re._freshness(item)
    assert row["relevance"] == 1.0
    assert row["freshness"] == freshness
    expected = 0.55 * 1.0 + 0.30 * freshness + 0.15 * 0.90
    assert abs(row["score"] - expected) < 1e-12


def test_reference_freshness_is_constant():
    with_ts = re._pi("a", "AI regulation", "reference", "Wikipedia", re._ts(4.0), 2)
    without_ts = re._pi("b", "AI regulation", "reference", "Wikipedia", None, 2)
    assert re._freshness(with_ts) == re._freshness(without_ts) == 0.5


def test_every_candidate_has_valid_weights():
    for name, candidate in re.CANDIDATES.items():
        for source_type in ("news", "social", "reference"):
            weights = candidate["weight_set"][source_type]
            assert len(weights) == 3
            assert abs(sum(weights) - 1.0) < 1e-12, (name, source_type, weights)


def test_corpus_metrics_are_pinned_within_tolerance():
    means = re._corpus_measurement()["means"]
    c1 = means["C1_design"]
    assert abs(c1["ndcg_at_10"] - 0.7768) < 1e-4
    assert abs(c1["precision_at_10"] - 0.8625) < 1e-4
    c0 = means["C0_relevance_only"]
    assert abs(c0["ndcg_at_10"] - 0.6916) < 1e-4


def test_all_candidates_rank_are_total_orders():
    items = [
        re._pi("a", "AI regulation", "news", "The Guardian", re._ts(24.0), 2),
        re._pi("b", "Update", "news", "The Guardian", re._ts(4.0), 0),
        re._pi("c", "AI regulation", "social", "r/technology (Reddit)", re._ts(1.0), 2),
        re._pi("d", "AI regulation", "reference", "Wikipedia", None, 2),
    ]
    for candidate in re.CANDIDATES.values():
        ranked = re._rank(items, "ai regulation", candidate)
        assert len(ranked) == 4
        assert set(ranked) == {"a", "b", "c", "d"}
        assert len(set(ranked)) == 4