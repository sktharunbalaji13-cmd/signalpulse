"""Regression tests for the M3-E filter experiment (offline, deterministic).

The behavioural acceptance probes (P1-P11) are the admissibility bar for the
designed view semantics: every probe must pass. Corpus metrics are secondary
evidence and are pinned here to detect regressions, not to tune anything.

The filter layer is design + measurement only (design §6.1): nothing is
implemented in production yet.
"""

import hashlib

from eval import filter_eval as fe
from eval import ranking_eval as re

ALL_PROBES = [f"P{i}" for i in range(1, 12)]


def test_every_probe_passes():
    rows = fe._run_probes()["rows"]
    assert {r["name"] for r in rows} == set(ALL_PROBES)
    for row in rows:
        assert row["passed"] is True, (row["name"], row["detail"])


def test_report_is_deterministic():
    first = hashlib.sha256(repr(fe._run_report()).encode("utf-8")).hexdigest()
    second = hashlib.sha256(repr(fe._run_report()).encode("utf-8")).hexdigest()
    assert first == second


def test_filter_never_mutates_input_rows():
    rows = [
        fe._frow("a", "news", pub=re._ts(4.0), gid="G", is_duplicate=True),
        fe._frow("b", "reference", pub=None),
    ]
    before = [dict(r) for r in rows]
    fe.apply_filters(rows, source_types=["news"], time_window="24h", duplicates="canonical")
    assert rows == before


def test_time_all_is_the_no_filter_view():
    rows = [
        fe._frow("n", "news", pub=re._ts(4.0)),
        fe._frow("old", "news", pub=re._ts(720.0)),
        fe._frow("r", "reference", pub=None),
    ]
    assert fe.apply_filters(rows, time_window="all") == rows
    assert fe.apply_filters(rows) == rows


def test_canonical_view_is_total_order_preserving():
    rows = [
        fe._frow("c", "news", gid="G"),
        fe._frow("m", "news", gid="G", is_duplicate=True),
        fe._frow("l", "social"),
    ]
    view = fe.apply_filters(rows, duplicates="canonical")
    assert [r["id"] for r in view] == [r["id"] for r in rows if not r["is_duplicate"]]


def test_corpus_measurement_pins():
    m = fe._corpus_measurement()["means"]
    assert m["F0_default"]["ndcg_at_10"] == 0.7850
    assert m["F0_default"]["precision_at_10"] == 0.8688
    assert m["F0_default"]["rel2_coverage"] == 1.0
    assert m["F1_news_only"]["rel2_coverage"] < 0.9
    assert m["F4_time_24h"]["kept"] < m["F0_default"]["kept"]


def test_language_coverage_is_reported_honestly():
    cov = fe._corpus_measurement()["language_coverage"]
    assert cov["rows_total"] == 365
    assert 0.85 < cov["coverage"] < 0.95
    social = next(
        b for source, b in cov["by_source"].items() if source.startswith("r/")
    )
    assert social["en"] == 0, "social rows carry no language metadata today"


def test_filter_over_production_ranker_matches_c4_projection():
    """The designed view over the PRODUCTION C4 ranker == the view over the
    accepted experiment ranker, per corpus query (subset order bit-for-bit)."""
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.services import ranking  # noqa: PLC0415

    from eval.schema import _parse_ts  # noqa: PLC0415

    corpus_data = fe._build_corpus()
    annotations = fe._duplicate_annotations(corpus_data)
    fixed_now = _parse_ts(fe.NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    for query in corpus_data.queries:
        expected = fe._corpus_rows(query, annotations[query.id])
        production = ranking.rank_items(
            [
                ranking.Rankable(
                    id=item.id,
                    title=item.title,
                    description=item.description,
                    source_type=item.source_type,
                    source_name=item.source_name,
                    published_at=_parse_ts(item.published_at) if item.published_at else None,
                    url=item.url,
                )
                for item in query.items
            ],
            query.query,
            now=fixed_now,
        )
        prod_order = [row.id for row in production]
        expected_ids = [r["id"] for r in expected]
        assert prod_order == expected_ids, query.id
        news_view = [r["id"] for r in fe.apply_filters(expected, source_types=["news"])]
        news_proj = [
            i for i in prod_order if _by_id(expected, i)["source_type"] == "news"
        ]
        assert news_view == news_proj, query.id


def _by_id(rows, item_id):
    return next(r for r in rows if r["id"] == item_id)