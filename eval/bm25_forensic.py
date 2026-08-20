"""Forensic analysis: why BM25 regresses on the M3-B corpus (no tuning).

**EXPERIMENTAL RESEARCH ARTIFACT — NOT PRODUCTION RANKING (ADR 0007).**

Preserved as evidence of the BM25 NO-GO: per-search IDF at n≈23 topic-dense
candidates down-weights central query terms and promotes rare-term decoys.
The production ranker (``backend/app/services/ranker.py``) is NOT modified,
nothing is wired, and nothing is committed. This module:

1. Walks q13/q10/q12/q02/q01 item-by-item: naive vs BM25 top-10, gold
   relevance, scores, the specific harmful inversions, and the reason
   (IDF / length normalization / field weighting / query / corpus).
2. Measures documented BM25 variants as SEPARATE experiments (title-only,
   different IDF smoothing, ``b`` alternatives, description-weight
   alternatives) without substituting any of them into production.

Run with::

    python -m eval.bm25_forensic

Full detail (full titles, all per-query tables) is written to
``eval/reports/bm25_forensic.md``.
"""

from __future__ import annotations

import math
import statistics
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path

from eval import baseline, corpus, metrics
from eval.schema import EvalCorpus, validate_corpus

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
_REPORTS = Path(__file__).resolve().parent / "reports"
_REPORT_PATH = _REPORTS / "bm25_forensic.md"

FOCUS_QUERIES = [
    "q13_ar_workplace",
    "q10_vaccine_logistics",
    "q12_ocean_plastic",
    "q02_quantum_computing",
    "q01_ev_battery_recycling",
]

SOURCE_TYPE_PRIORITY = {"news": 0, "social": 1, "reference": 2, "video": 3}
MEAN_KEYS = ("precision_at_5", "precision_at_10", "reciprocal_rank", "ndcg_at_10")


def _load_backend() -> None:
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _candidates_for(items):
    _load_backend()
    from app.services.ranker import RankCandidate  # noqa: PLC0415

    return [
        RankCandidate(
            id=item.id,
            title=item.title,
            description=item.description,
            source_type=item.source_type,
            published_at=_parse_ts(item.published_at),
            url=item.url,
        )
        for item in items
    ]


def _trim(text: str, width: int = 46) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 3] + "..."


def _naive_ranking(items, query: str) -> tuple[list[str], dict[str, int]]:
    """Return ordered ids and a score map for the naive baseline."""
    query_terms = sorted(baseline._tokenize(query))
    scored = [
        (
            -baseline.baseline_score(item, query_terms),
            SOURCE_TYPE_PRIORITY.get(item.source_type, 9),
            item.title,
            item.id,
        )
        for item in items
    ]
    scored.sort()
    ordered = [entry[3] for entry in scored]
    scores = {item.id: baseline.baseline_score(item, query_terms) for item in items}
    return ordered, scores


def _bm25_ranking(items, query: str, include_bonuses: bool):
    _load_backend()
    from app.services.ranker import rank, score_candidates  # noqa: PLC0415

    candidates = _candidates_for(items)
    ordered = rank(candidates, query, include_bonuses=include_bonuses)
    scored = score_candidates(candidates, query, include_bonuses=include_bonuses)
    return ordered, scored


def _query_term_idf(items, query: str):
    _load_backend()
    from app.services.ranker import BM25Field, tokenize  # noqa: PLC0415

    title_field = BM25Field([c.title for c in _candidates_for(items)])
    desc_field = BM25Field([(c.description or "") for c in _candidates_for(items)])
    terms = tokenize(query)
    return [(term, title_field.idf(term), desc_field.idf(term)) for term in terms]


def _harmful_inversions(naive_ids, bm25_ids, items, naive_scores, bm25_scored):
    """Pairs where BM25 puts a lower-relevance item above a higher-relevance one.

    Restricted to the naive top-10 x bm25 top-10 region. Returns a list of
    dicts sorted by relevance gap, largest first.
    """
    relevance = {item.id: item.relevance for item in items}
    titles = {item.id: item.title for item in items}
    na_pos = {iid: i for i, iid in enumerate(naive_ids[:10])}
    bm_pos = {iid: i for i, iid in enumerate(bm25_ids[:10])}
    inversions: list[dict] = []
    for a, b in combinations(set(na_pos) & set(bm_pos), 2):
        na_order = na_pos[a] < na_pos[b]
        bm_order = bm_pos[a] < bm_pos[b]
        if na_order == bm_order:
            continue
        higher, lower = (a, b) if relevance[a] > relevance[b] else (b, a)
        if relevance[higher] <= relevance[lower]:
            continue  # BM25's swap is neutral or helpful
        inversions.append(
            {
                "worse": lower,
                "better": higher,
                "rel_worse": relevance[lower],
                "rel_better": relevance[higher],
                "na_worse": na_pos[lower],
                "na_better": na_pos[higher],
                "bm_worse": bm_pos[lower],
                "bm_better": bm_pos[higher],
                "na_worse_score": naive_scores[lower],
                "na_better_score": naive_scores[higher],
                "bm_worse_score": bm25_scored[lower]["relevance"],
                "bm_better_score": bm25_scored[higher]["relevance"],
                "titles": (_trim(titles[lower]), _trim(titles[higher])),
            }
        )
    inversions.sort(key=lambda d: -(d["rel_better"] - d["rel_worse"]))
    return inversions


# ---------------------------------------------------------------------------
# Variant measurement (each experiment is independent; nothing is substituted)
# ---------------------------------------------------------------------------

def _make_idf(field, mode: str):
    """Return an idf callable for a given smoothing formulation."""
    n_docs = field._doc_count

    def idf(term: str) -> float:
        n = field._df.get(term, 0)
        if mode == "smooth1":  # current: ln(1 + (N-n+0.5)/(n+0.5))
            return math.log(1 + (n_docs - n + 0.5) / (n + 0.5))
        if mode == "smooth2":  # milder smoothing
            return math.log(1 + (n_docs - n) / (n + 1))
        if mode == "classic":  # standard BM25, clamped at 0
            return max(0.0, math.log((n_docs - n + 0.5) / (n + 0.5)))
        raise ValueError(mode)

    return idf


def _measure_variant(items, query: str, *, wt, wd, b, idf_mode: str):
    """Order items by a parametrized BM25 variant. Returns ordered ids."""
    _load_backend()
    from app.services.ranker import BM25Field, tokenize  # noqa: PLC0415

    candidates = _candidates_for(items)
    title_field = BM25Field([c.title for c in candidates], b=b)
    desc_field = BM25Field([c.description or "" for c in candidates], b=b)
    if idf_mode != "smooth1":
        title_field.idf = _make_idf(title_field, idf_mode)
        desc_field.idf = _make_idf(desc_field, idf_mode)
    terms = tokenize(query)
    ceiling = (
        wt * title_field.score_text(query, terms) + wd * desc_field.score_text(query, terms)
    )
    scores = {}
    for index, candidate in enumerate(candidates):
        base = wt * title_field.score(index, terms) + wd * desc_field.score(index, terms)
        scores[candidate.id] = (base / ceiling) if ceiling > 0 else 0.0

    def key(candidate) -> tuple:
        published = candidate.published_at.timestamp() if candidate.published_at else -1.0
        return (
            -scores[candidate.id],
            SOURCE_TYPE_PRIORITY.get(candidate.source_type, 9),
            -published,
            candidate.url,
            candidate.id,
        )

    return [c.id for c in sorted(candidates, key=key)]


def _variant_means(data: EvalCorpus, *, wt, wd, b, idf_mode: str) -> dict:
    per_query = []
    for query in data.queries:
        relevance = {item.id: item.relevance for item in query.items}
        ranked_ids = _measure_variant(
            query.items, query.query, wt=wt, wd=wd, b=b, idf_mode=idf_mode
        )
        per_query.append(metrics.ranking_metrics(ranked_ids, relevance))
    return {key: statistics.mean(q[key] for q in per_query) for key in MEAN_KEYS}


def _variant_per_query_nDCG(data: EvalCorpus, *, wt, wd, b, idf_mode: str) -> dict[str, float]:
    out = {}
    for query in data.queries:
        if query.id not in FOCUS_QUERIES:
            continue
        relevance = {item.id: item.relevance for item in query.items}
        ranked_ids = _measure_variant(
            query.items, query.query, wt=wt, wd=wd, b=b, idf_mode=idf_mode
        )
        out[query.id] = metrics.ranking_metrics(ranked_ids, relevance)["ndcg_at_10"]
    return out


VARIANT_DEFS = [
    ("bm25 core  (wt=2:1, b=0.75, smooth1)", dict(wt=2.0, wd=1.0, b=0.75, idf_mode="smooth1")),
    ("title-only (wt=1:0, b=0.75, smooth1)", dict(wt=1.0, wd=0.0, b=0.75, idf_mode="smooth1")),
    ("idf classic(wt=2:1, b=0.75)", dict(wt=2.0, wd=1.0, b=0.75, idf_mode="classic")),
    ("idf smooth2(wt=2:1, b=0.75)", dict(wt=2.0, wd=1.0, b=0.75, idf_mode="smooth2")),
    ("b=0.0      (wt=2:1, smooth1)", dict(wt=2.0, wd=1.0, b=0.0, idf_mode="smooth1")),
    ("b=0.5      (wt=2:1, smooth1)", dict(wt=2.0, wd=1.0, b=0.5, idf_mode="smooth1")),
    ("b=1.0      (wt=2:1, smooth1)", dict(wt=2.0, wd=1.0, b=1.0, idf_mode="smooth1")),
    ("desc-w 0.5 (wt=2:0.5, b=0.75, smooth1)", dict(wt=2.0, wd=0.5, b=0.75, idf_mode="smooth1")),
    ("desc-w 2.0 (wt=2:2, b=0.75, smooth1)", dict(wt=2.0, wd=2.0, b=0.75, idf_mode="smooth1")),
]


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _build_corpus() -> EvalCorpus:
    return validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )


def _query_markdown(data: EvalCorpus, query_id: str) -> str:
    query = next(q for q in data.queries if q.id == query_id)
    items = query.items
    item_by_id = {item.id: item for item in items}
    relevance = {item.id: item.relevance for item in items}

    naive_ids, naive_scores = _naive_ranking(items, query.query)
    bm25_ids, bm25_scored = _bm25_ranking(items, query.query, include_bonuses=False)
    bm25_full_ids, _ = _bm25_ranking(items, query.query, include_bonuses=True)

    rel_dist = {r: sum(1 for item in items if item.relevance == r) for r in (0, 1, 2)}
    idf_rows = _query_term_idf(items, query.query)

    lines = [
        f"## {query_id} — {query.query!r}",
        "",
        f"items={len(items)} relevance 0/1/2 = {rel_dist[0]}/{rel_dist[1]}/{rel_dist[2]}",
        "",
        "query-term IDF (title field / description field):",
    ]
    for term, t_idf, d_idf in idf_rows:
        lines.append(f"  {term:20s} {t_idf:8.4f} {d_idf:8.4f}")

    def table(title, ids, scored_by_id, score_label, ranks, reverse_score=False):
        lines.append("")
        lines.append(f"{title}:")
        lines.append(f"  {'#':>2} {'id':<22} {'rel':>3} {'score':>7}  title")
        for rank, iid in enumerate(ids[:10], start=1):
            item = item_by_id[iid]
            score = scored_by_id[iid]
            lines.append(
                f"  {rank:>2} {iid:<22} {relevance[iid]:>3} {score:>7.4f}  {_trim(item.title)}"
            )

    ranks_naive = {iid: i + 1 for i, iid in enumerate(naive_ids)}
    ranks_bm25 = {iid: i + 1 for i, iid in enumerate(bm25_ids)}
    table("top-10 naive", naive_ids, naive_scores, "naive", ranks_naive)
    bm25_scores = {iid: v["relevance"] for iid, v in bm25_scored.items()}
    table("top-10 BM25 core", bm25_ids, bm25_scores, "bm25", ranks_bm25)
    lines.append("")
    lines.append("rank of relevant items (rel>=1): naive # -> BM25 core #")
    for iid in naive_ids:
        if relevance[iid] >= 1:
            bm_rank = ranks_bm25.get(iid, "-")
            lines.append(
                f"  {iid:<22} rel={relevance[iid]}  "
                f"naive#{ranks_naive[iid]:>2}  bm25#{bm_rank}"
            )

    inversions = _harmful_inversions(naive_ids, bm25_ids, items, naive_scores, bm25_scored)
    lines.append("")
    header = "harmful inversions (BM25 puts worse above better), top by rel gap"
    lines.append(f"{header}: {len(inversions)} total")
    for inv in inversions[:5]:
        lines.append(
            f"  {inv['titles'][1]} (rel {inv['rel_better']}) "
            f"naive#{inv['na_better'] + 1}->bm25#{inv['bm_better'] + 1} "
            f"[bm25 {inv['bm_better_score']:.4f}]"
        )
        lines.append(
            f"    pushed below {inv['titles'][0]} (rel {inv['rel_worse']}) "
            f"naive#{inv['na_worse'] + 1}->bm25#{inv['bm_worse'] + 1} "
            f"[bm25 {inv['bm_worse_score']:.4f}]"
        )

    relevant_in_top10 = {
        "naive": sum(1 for iid in naive_ids[:10] if relevance[iid] >= 1),
        "bm25": sum(1 for iid in bm25_ids[:10] if relevance[iid] >= 1),
    }
    rel_top10 = (
        f"relevant items in top-10: naive={relevant_in_top10['naive']} "
        f"bm25={relevant_in_top10['bm25']}"
    )
    lines.append(rel_top10)
    return "\n".join(lines) + "\n"


def _variants_markdown(data: EvalCorpus) -> str:
    lines = [
        "## Variant experiments (each measured independently; none substituted)",
        "",
        "Variant (all with normalization & deterministic tie-break):",
        f"  {'variant':<34} {'P@5':>7} {'P@10':>7} {'MRR':>7} {'nDCG@10':>8}",
    ]

    def row(name, means):
        lines.append(
            f"  {name:<34} {means['precision_at_5']:7.4f} {means['precision_at_10']:7.4f} "
            f"{means['reciprocal_rank']:7.4f} {means['ndcg_at_10']:8.4f}"
        )

    baseline_means = {
        key: statistics.mean(
            metrics.ranking_metrics(
                baseline.rank(q.items, q.query), {i.id: i.relevance for i in q.items}
            )[key]
            for q in data.queries
        )
        for key in MEAN_KEYS
    }
    row("naive baseline", baseline_means)

    for name, kwargs in VARIANT_DEFS:
        row(name, _variant_means(data, **kwargs))

    lines.append("")
    lines.append("per-focus-query nDCG@10 by variant (core=wt2:1 b.75 smooth1):")
    lines.append(f"  {'variant':<34} " + " ".join(f"{q.split('_')[0]:>6}" for q in FOCUS_QUERIES))
    for name, kwargs in VARIANT_DEFS:
        per_query = _variant_per_query_nDCG(data, **kwargs)
        lines.append(
            f"  {name:<34} " + " ".join(f"{per_query[q]:>6.4f}" for q in FOCUS_QUERIES)
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    data = _build_corpus()
    sections = [
        "# BM25 forensic analysis (M3-B, no tuning)",
        "",
        f"corpus revision {data.revision}; focus queries: {', '.join(FOCUS_QUERIES)}",
        "",
        "Method: naive = 3:1 title/description term-count (baseline.py). BM25 core = "
        "production ranker (k1=1.5, b=0.75, smoothed IDF, 2:1 field weighting, "
        "self-match normalization, no bonuses). Every variant below is measured as a "
        "separate experiment; none changes the production ranker.",
        "",
    ]
    for query_id in FOCUS_QUERIES:
        sections.append(_query_markdown(data, query_id))
    sections.append(_variants_markdown(data))

    report = "\n".join(sections)
    _REPORTS.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())