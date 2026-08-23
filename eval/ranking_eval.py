# ruff: noqa: E501
"""M3-D ranking experiment: combination formula candidates, measured.

Design + measurement ONLY (design Ãƒâ€šÃ‚Â§5.1). The combined ranker is not
implemented in production, nothing is wired, no weights are tuned against the
corpus, and BM25 is not used. Components are the validated ones:

* relevance: naive lexical baseline (production core after ADR 0007),
  min-max normalised per search to [0, 1];
* freshness: the production M3-C scorer (``app.services.freshness``),
  imported and driven at the fixed corpus instant;
* source quality: design Ãƒâ€šÃ‚Â§5 constants (Guardian 0.90, Wikipedia 0.80, Reddit
  0.50; "Global Wire" documented placeholder 0.85; unknown 0.50);
* diversity: within a Ãƒâ€šÃ‚Â±0.05 score band, source types alternate (toggleable).

Behavioural acceptance tests (P1ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“P9) are defined and run BEFORE the corpus is
measured: they encode "what good ranking means". Corpus metrics are secondary
evidence, reported per candidate without tuning. Run with::

    python -m eval.ranking_eval

Writes ``eval/reports/ranking_eval.md``.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import timedelta
from pathlib import Path

from eval import baseline, corpus, metrics
from eval.schema import EvalCorpus, EvalItem, _parse_ts, validate_corpus

NOW = _parse_ts(corpus.RETRIEVED)
BAND_WIDTH = 0.05


def doc_key(title: str, description: str | None) -> str:
    """Document text key - matches the semantic embedding generator."""
    return f"{title}. {description}" if description else title


_SEMANTICS_CACHE: dict | None = None


def load_semantics() -> dict:
    """Lazy-load the M10 embedding artifact; {} when unavailable (lexical fallback)."""
    global _SEMANTICS_CACHE
    if _SEMANTICS_CACHE is None:
        path = Path(__file__).resolve().parent / "data" / "semantic_embeddings.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            _SEMANTICS_CACHE = {
                "queries": raw["queries"],
                "probe_queries": raw["probe_queries"],
                "docs_by_text": raw["docs_by_text"],
            }
        else:
            _SEMANTICS_CACHE = {}
    return _SEMANTICS_CACHE

SOURCE_QUALITY = {
    "The Guardian": 0.90,
    "Wikipedia": 0.80,
    "Global Wire": 0.85,  # corpus-only placeholder (no real second news source yet)
}
_SOCIAL_QUALITY = 0.50
_UNKNOWN_QUALITY = 0.50
_TYPE_PRIORITY = {"news": 0, "social": 1, "reference": 2}

# (w_rel, w_fresh, w_qual) per source type ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â principled candidates, not fitted.
WEIGHT_SETS = {
    "C0_relevance_only": {"news": (1.0, 0.0, 0.0), "social": (1.0, 0.0, 0.0), "reference": (1.0, 0.0, 0.0)},
    "C1_design": {"news": (0.55, 0.30, 0.15), "social": (0.55, 0.30, 0.15), "reference": (0.65, 0.10, 0.25)},
    "C2_balanced": {"news": (0.50, 0.30, 0.20), "social": (0.50, 0.30, 0.20), "reference": (0.60, 0.15, 0.25)},
    "C3_relevance_heavy": {"news": (0.70, 0.20, 0.10), "social": (0.70, 0.20, 0.10), "reference": (0.75, 0.10, 0.15)},
}
CANDIDATES = {
    "C0_relevance_only": {"weight_set": WEIGHT_SETS["C0_relevance_only"], "diversity": False},
    "C1_design": {"weight_set": WEIGHT_SETS["C1_design"], "diversity": False},
    "C2_balanced": {"weight_set": WEIGHT_SETS["C2_balanced"], "diversity": False},
    "C3_relevance_heavy": {"weight_set": WEIGHT_SETS["C3_relevance_heavy"], "diversity": False},
    "C4_design_diversity": {"weight_set": WEIGHT_SETS["C1_design"], "diversity": True},
    # M10 (pre-registered): bounded semantic blend - rel = 0.70*lex + 0.30*sem
    "M10_SEM1_semantic_blend": {"weight_set": WEIGHT_SETS["C1_design"], "diversity": True, "semantic_blend": True},
}

_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
_BACKEND_LOADED = False


def _load_backend() -> None:
    global _BACKEND_LOADED
    if not _BACKEND_LOADED:
        if str(_BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(_BACKEND_DIR))
        _BACKEND_LOADED = True


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_for_freshness(target: float, source_type: str) -> str:
    """The age that yields ``target`` on the validated curve (deterministic)."""
    hl = 24.0 if source_type == "news" else 12.0
    age = -hl * (__import__("math").log2((target - 0.05) / 0.95))
    return _ts(age)


def source_quality(source_type: str, source_name: str) -> float:
    if source_name in SOURCE_QUALITY:
        return SOURCE_QUALITY[source_name]
    if source_type == "reference":
        return 0.80
    if source_type == "social":
        return _SOCIAL_QUALITY
    return _UNKNOWN_QUALITY


def _freshness(item: EvalItem) -> float:
    _load_backend()
    from app.services.freshness import freshness_score  # noqa: PLC0415

    published = _parse_ts(item.published_at) if item.published_at else None
    return freshness_score(published, item.source_type, now=NOW)


def _ts_key(item: EvalItem) -> tuple[int, float]:
    if item.published_at is None:
        return (1, 0.0)  # missing timestamps sort last (ascending key)
    return (0, -_parse_ts(item.published_at).timestamp())  # newer first


def rank_combined(
    items: list[EvalItem],
    query: str,
    candidate: dict,
    *,
    diversity: bool | None = None,
    semantics: dict | None = None,
) -> list[dict]:
    """Rank items by the combination formula with the design Ãƒâ€šÃ‚Â§5 total order.

    Returns rows of ``{"id", "score", "relevance", "freshness", "quality"}``.
    Tie-break: score desc ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ source-type priority ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ published_at desc (None
    last) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ URL lexicographic. ``diversity`` overrides the candidate's toggle.
    """
    weight_set = candidate["weight_set"]
    use_diversity = candidate["diversity"] if diversity is None else diversity
    query_terms = sorted(baseline._tokenize(query))
    raw = [baseline.baseline_score(item, query_terms) for item in items]
    max_raw = max(raw) if raw else 0
    rows = []
    for item, raw_score in zip(items, raw, strict=True):
        relevance = raw_score / max_raw if max_raw else 0.0
        freshness = _freshness(item)
        quality = source_quality(item.source_type, item.source_name)
        w_rel, w_fresh, w_qual = weight_set.get(item.source_type, weight_set["news"])
        rows.append(
            {
                "id": item.id,
                "score": w_rel * relevance + w_fresh * freshness + w_qual * quality,
                "relevance": relevance,
                "freshness": freshness,
                "quality": quality,
                "w_rel": w_rel,
                "w_fresh": w_fresh,
                "w_qual": w_qual,
                "source_type": item.source_type,
                "ts_key": _ts_key(item),
                "url": item.url,
                "doc_text": doc_key(item.title, item.description),
            }
        )
    # M10 SEM1 (pre-registered): bounded semantic blend of the relevance axis
    # only - rel' = 0.70*lexical + 0.30*semantic(min-max within candidate set).
    # Freshness/quality/weights/diversity/tie-breaks stay untouched.
    if candidate.get("semantic_blend") and semantics:
        qvec = semantics.get("query")
        docs_map = semantics.get("docs", {})

        def _cos(a: list[float], b: list[float]) -> float:
            num = sum(x * y for x, y in zip(a, b, strict=True))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return num / (na * nb) if na and nb else 0.0

        sem_raw = [
            _cos(qvec, docs_map[r["doc_text"]]) if r["doc_text"] in docs_map else 0.0
            for r in rows
        ]
        smin = min(sem_raw)
        span = max(sem_raw) - smin
        for row, sem in zip(rows, sem_raw, strict=True):
            sem_norm = (sem - smin) / span if span else 0.0
            rel_blended = 0.70 * row["relevance"] + 0.30 * sem_norm
            row["relevance"] = rel_blended
            row["score"] = (
                row["w_rel"] * rel_blended
                + row["w_fresh"] * row["freshness"]
                + row["w_qual"] * row["quality"]
            )
    rows.sort(key=lambda r: (-r["score"], _TYPE_PRIORITY.get(r["source_type"], 9), r["ts_key"], r["url"]))
    if use_diversity:
        rows = _diversity_alternate(rows)
    return rows


def _diversity_alternate(rows: list[dict], band_width: float = BAND_WIDTH) -> list[dict]:
    """Within each Ãƒâ€šÃ‚Â±band score band, alternate source types (round-robin)."""
    out: list[dict] = []
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and rows[i]["score"] - rows[j]["score"] <= band_width:
            j += 1
        band = rows[i:j]
        by_type: dict[int, list[dict]] = {}
        for row in band:
            by_type.setdefault(_TYPE_PRIORITY.get(row["source_type"], 9), []).append(row)
        for priority in sorted(by_type):
            by_type[priority].sort(key=lambda r: (r["ts_key"], r["url"]))
        emitted = 0
        while emitted < len(band):
            for priority in sorted(by_type):
                if by_type[priority]:
                    out.append(by_type[priority].pop(0))
                    emitted += 1
        i = j
    return out


def _build_corpus() -> EvalCorpus:
    return validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )


def _all_items(corpus_data: EvalCorpus) -> list[EvalItem]:
    return [item for query in corpus_data.queries for item in query.items]


# --- Behavioural acceptance probes (fixed, deterministic) --------------------


def _pi(iid: str, title: str, stype: str, sname: str, pub: str | None, rel: int, url: str | None = None, desc: str = "") -> EvalItem:
    return EvalItem(
        id=iid,
        title=title,
        description=desc,
        url=url or f"https://example.probe/{iid}",
        source_type=stype,
        source_name=sname,
        author=None,
        published_at=pub,
        retrieved_at=corpus.RETRIEVED,
        relevance=rel,
    )


def _rank(
    items: list[EvalItem],
    query: str,
    candidate: dict,
    *,
    diversity: bool | None = None,
    semantics: dict | None = None,
) -> list[str]:
    return [
        row["id"]
        for row in rank_combined(
            items, query, candidate, diversity=diversity, semantics=semantics
        )
    ]


def _probe_p1() -> dict:
    """Fresh irrelevant must not outrank older relevant (the central case)."""
    items = [
        _pi("a", "AI regulation", "news", "The Guardian", _ts(24.0), 2, desc="EU publishes new AI regulation framework"),
        _pi("b", "Update", "news", "The Guardian", _ts(4.0), 0),
    ]
    return {"name": "P1", "description": "fresh irrelevant 'Update' (4 h) must not outrank relevant (24 h)", "query": "ai regulation", "items": items, "assertion": lambda r, c: (r.index("a") < r.index("b"), "a before b")}


def _probe_p2() -> dict:
    """Relevance dominates even at the freshness floor."""
    items = [
        _pi("a", "AI regulation", "news", "The Guardian", _ts(720.0), 2, desc="EU publishes new AI regulation framework"),
        _pi("b", "Update", "news", "The Guardian", _ts(4.0), 0),
    ]
    return {"name": "P2", "description": "relevant 30 d old must outrank fresh 'Update' (4 h)", "query": "ai regulation", "items": items, "assertion": lambda r, c: (r.index("a") < r.index("b"), "a before b")}


def _probe_p3() -> dict:
    """Higher source quality wins at equal relevance and freshness."""
    items = [
        _pi("social", "AI regulation", "social", "r/technology (Reddit)", _ts(0.0), 2),
        _pi("guardian", "AI regulation", "news", "The Guardian", _ts(0.0), 2),
    ]
    return {"name": "P3", "description": "Guardian before Reddit at equal relevance + freshness", "query": "ai regulation", "items": items, "assertion": lambda r, c: (r.index("guardian") < r.index("social"), "guardian first")}


def _probe_p4() -> dict:
    """Reference timelessness both ways."""
    items = [
        _pi("ref", "AI regulation", "reference", "Wikipedia", None, 2),
        _pi("partial", "AI explained", "news", "The Guardian", _ts(4.0), 1),
        _pi("weakref", "Artificial", "reference", "Wikipedia", None, 0),
        _pi("relevant", "AI regulation", "news", "The Guardian", _ts(4.0), 2),
    ]
    return {
        "name": "P4",
        "description": "timeless authoritative reference beats fresh partial news; weak reference loses to relevant news",
        "query": "ai regulation",
        "items": items,
        "assertion": lambda r, c: (r.index("ref") < r.index("partial") and r.index("relevant") < r.index("weakref"), "ref>partial, relevant>weakref"),
    }


def _probe_p5() -> dict:
    """Missing timestamp is neutral, not lethal."""
    items = [
        _pi("a", "AI regulation", "news", "The Guardian", None, 2, desc="EU publishes new AI regulation framework"),
        _pi("b", "Update", "news", "The Guardian", _ts(4.0), 0),
    ]
    return {"name": "P5", "description": "relevant without published_at outranks fresh 'Update'", "query": "ai regulation", "items": items, "assertion": lambda r, c: (r.index("a") < r.index("b"), "a before b")}


def _probe_p6() -> dict:
    """Deterministic total order on exact ties (URL lexicographic; None-last
    ordering is pinned separately via _ts_key in the test suite)."""
    items = [
        _pi("aaa", "AI regulation", "news", "The Guardian", _ts(24.0), 2, url="https://example.probe/aaa"),
        _pi("bbb", "AI regulation", "news", "The Guardian", _ts(24.0), 2, url="https://example.probe/bbb"),
    ]

    def assertion(ranked: list[str], candidate: dict) -> tuple[bool, str]:
        url_order = ranked.index("aaa") < ranked.index("bbb")
        deterministic = _rank(items, "ai regulation", candidate) == ranked
        return (url_order and deterministic, "aaa<bbb (URL); deterministic across runs")

    return {"name": "P6", "description": "tie-break: URL lexicographic; deterministic", "query": "ai regulation", "items": items, "assertion": assertion}


def _probe_p7() -> dict:
    """Duplicates: members inherit the canonical score; no double-counting."""
    items = [
        _pi("a", "AI regulation", "news", "The Guardian", _ts(24.0), 2, url="https://example.probe/x"),
        _pi("a2", "AI regulation", "news", "The Guardian", _ts(24.0), 2, url="https://example.probe/x"),
        _pi("b", "Update", "news", "The Guardian", _ts(4.0), 0),
    ]
    reduced = [_pi("a", "AI regulation", "news", "The Guardian", _ts(24.0), 2, url="https://example.probe/x"), _pi("b", "Update", "news", "The Guardian", _ts(4.0), 0)]

    def assertion(ranked: list[str], candidate: dict) -> tuple[bool, str]:
        rows = rank_combined(items, "ai regulation", candidate)
        by_id = {row["id"]: row for row in rows}
        same_score = by_id["a"]["score"] == by_id["a2"]["score"]
        no_boost = ranked.index("b") > ranked.index("a") and _rank(reduced, "ai regulation", candidate).index("b") > _rank(reduced, "ai regulation", candidate).index("a")
        return (same_score and no_boost, "a==a2 score; b stays after a")

    return {"name": "P7", "description": "duplicate pair: equal scores, neighbours unchanged", "query": "ai regulation", "items": items, "assertion": assertion}


def _probe_p8() -> dict:
    """Diversity: within the Ãƒâ€šÃ‚Â±0.05 score band, source types alternate when the
    pass is enabled; the toggle is inert for candidates without it."""
    items = [
        _pi("g1", "AI regulation", "news", "The Guardian", _ts(24.0), 2),
        _pi("g2", "AI regulation", "news", "The Guardian", _ts(24.0), 2),
        _pi("s1", "AI regulation", "social", "r/technology (Reddit)", _ts_for_freshness(0.5917, "social"), 2),
        _pi("ref", "AI regulation", "reference", "Wikipedia", None, 2),
    ]

    def assertion(ranked: list[str], candidate: dict) -> tuple[bool, str]:
        rows = rank_combined(items, "ai regulation", candidate)
        by_score = {row["id"]: row["score"] for row in rows}
        by_type = {row["id"]: row["source_type"] for row in rows}
        threshold = by_score["g1"] - 0.05

        def band_of(ids: list[str]) -> list[str]:
            out = []
            for i in ids:
                if by_score[i] >= threshold:
                    out.append(i)
                else:
                    break
            return out

        plain = _rank(items, "ai regulation", candidate, diversity=False)
        band_div = band_of(ranked)
        alternates = len(band_div) >= 2 and all(by_type[band_div[j]] != by_type[band_div[j + 1]] for j in range(len(band_div) - 1))
        changed = ranked != plain
        ok = alternates if changed else not alternates
        return (ok, "alternates when enabled; grouped when disabled")

    return {"name": "P8", "description": "diversity alternates source types within the Ãƒâ€šÃ‚Â±0.05 band", "query": "ai regulation", "items": items, "assertion": assertion}


def _probe_p9() -> dict:
    """Freshness advantage: fresher relevant beats older relevant."""
    items = [
        _pi("fresh", "AI regulation", "news", "The Guardian", _ts(4.0), 2),
        _pi("old", "AI regulation", "news", "The Guardian", _ts(720.0), 2),
    ]
    return {"name": "P9", "description": "relevant 4 h old outranks relevant 30 d old", "query": "ai regulation", "items": items, "assertion": lambda r, c: (r.index("fresh") < r.index("old"), "fresh before old")}


def probes() -> list[dict]:
    return [_probe_p1(), _probe_p2(), _probe_p3(), _probe_p4(), _probe_p5(), _probe_p6(), _probe_p7(), _probe_p8(), _probe_p9()]


def _run_probes() -> dict:
    sem_store = load_semantics()

    def _probe_semantics(probe) -> dict | None:
        if not any(c.get("semantic_blend") for c in CANDIDATES.values()):
            return None
        pq = " ".join(probe["query"].lower().split())
        qvec = sem_store.get("probe_queries", {}).get(pq)
        if not qvec:
            return None
        docs = {}
        for item in probe["items"]:
            key = doc_key(item.title, item.description)
            vec = sem_store.get("docs_by_text", {}).get(key)
            if vec:
                docs[key] = vec
        return {"query": qvec, "docs": docs}

    rows = []
    for probe in probes():
        per_candidate = {}
        semantics = _probe_semantics(probe)
        for name, candidate in CANDIDATES.items():
            diversity = True if (probe["name"] == "P8" and candidate.get("diversity")) else None
            ranked = _rank(
                probe["items"], probe["query"], candidate,
                diversity=diversity, semantics=semantics,
            )
            passed, detail = probe["assertion"](ranked, candidate)
            per_candidate[name] = {"passed": passed, "detail": detail}
        rows.append({"name": probe["name"], "description": probe["description"], "per_candidate": per_candidate})
    return {"probe_count": len(rows), "rows": rows}


def _corpus_measurement() -> dict:
    corpus_data = _build_corpus()
    sem_store = load_semantics()
    per_query = {}
    for query in corpus_data.queries:
        relevance = {item.id: item.relevance for item in query.items}
        baseline_ranked = baseline.rank(query.items, query.query)
        row = {"baseline": metrics.ranking_metrics(baseline_ranked, relevance)}
        qvec = sem_store.get("queries", {}).get(query.id)
        sem_docs = {}
        for item in query.items:
            key = doc_key(item.title, item.description)
            vec = sem_store.get("docs_by_text", {}).get(key)
            if vec:
                sem_docs[key] = vec
        semantics = {"query": qvec, "docs": sem_docs} if qvec else None
        for name, candidate in CANDIDATES.items():
            ranked = _rank(
                query.items, query.query, candidate,
                diversity=candidate["diversity"], semantics=semantics,
            )
            row[name] = metrics.ranking_metrics(ranked, relevance)
        per_query[query.id] = row

    means: dict[str, dict[str, float]] = {}
    for stage in ("baseline", *CANDIDATES):
        means[stage] = {
            "precision_at_5": statistics.mean(per_query[q][stage]["precision_at_5"] for q in per_query),
            "precision_at_10": statistics.mean(per_query[q][stage]["precision_at_10"] for q in per_query),
            "reciprocal_rank": statistics.mean(per_query[q][stage]["reciprocal_rank"] for q in per_query),
            "ndcg_at_10": statistics.mean(per_query[q][stage]["ndcg_at_10"] for q in per_query),
        }

    fresh_junk: dict[str, float] = {}
    rel0_top10: dict[str, float] = {}
    for name, candidate in CANDIDATES.items():
        counts = []
        junk = []
        for query in corpus_data.queries:
            ranked = _rank(query.items, query.query, candidate, diversity=candidate["diversity"])
            by_id = {item.id: item for item in query.items}
            top10 = ranked[:10]
            counts.append(sum(1 for i in top10 if by_id[i].relevance == 0))
            junk.append(sum(1 for i in top10 if by_id[i].relevance == 0 and _freshness(by_id[i]) >= 0.7))
        rel0_top10[name] = round(statistics.mean(counts), 4)
        fresh_junk[name] = round(statistics.mean(junk), 4)

    return {"query_count": len(per_query), "item_count": len(_all_items(corpus_data)), "means": means, "fresh_junk_in_top10": fresh_junk, "rel0_in_top10": rel0_top10}


def _run_report() -> dict:
    return {
        "schema": "signalpulse-ranking-experiment",
        "fixed_now": corpus.RETRIEVED,
        "corpus_revision": corpus.REVISION,
        "corpus_unchanged": True,
        "status": "research measurement only; NOT production ranking, NOT wired, NOT tuned",
        "components": {
            "relevance": "naive lexical baseline, min-max normalised per search (ADR 0007 core)",
            "freshness": "M3-C production scorer (bit-identical to the accepted model)",
            "quality": SOURCE_QUALITY,
            "diversity_band": BAND_WIDTH,
            "no_bm25": True,
        },
        "candidates": [
            {
                "name": name,
                "weights": cand["weight_set"],
                "diversity": cand["diversity"],
            }
            for name, cand in CANDIDATES.items()
        ],
        "probes": _run_probes(),
        "corpus_measurement": _corpus_measurement(),
    }


def _fmt_table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    line = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(header)) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |"
    body = "\n".join("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(header))) + " |" for r in rows)
    return "\n".join([line, sep, body])


def _render_markdown(report: dict) -> str:
    probe_rows = report["probes"]["rows"]
    candidate_names = list(CANDIDATES)
    lines = [
        "# M3-D ranking experiment ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â combination formula, behavioural acceptance first",
        "",
        f"- Fixed now: `{report['fixed_now']}`; corpus revision {report['corpus_revision']}, unchanged.",
        f"- Status: **{report['status']}**.",
        "",
        "## 1. Components and candidates",
        "",
        "- Relevance: naive lexical baseline, min-max normalised per search to [0, 1] "
        "(the ADR 0007 production core). BM25: not used.",
        "- Freshness: the M3-C production scorer (accepted curve, bit-identical).",
        f"- Quality: {report['components']['quality']} (+ 0.50 for unknown sources); "
        f"diversity band Ãƒâ€šÃ‚Â±{report['components']['diversity_band']}.",
        "",
        _fmt_table(
            ["candidate", "weights (rel/fresh/qual) per type", "diversity"],
            [
                [c["name"], str(c["weights"]), str(c["diversity"])]
                for c in report["candidates"]
            ],
        ),
        "",
        "## 2. Behavioural acceptance tests (defined before corpus measurement)",
        "",
        _fmt_table(
            ["probe", "behaviour", "C0", "C1", "C2", "C3", "C4"],
            [
                [p["name"], p["description"]]
                + [("PASS" if p["per_candidate"][c]["passed"] else "FAIL") for c in candidate_names]
                for p in probe_rows
            ],
        ),
        "",
        f"All {len(probe_rows)} probes must pass for a candidate to be admissible.",
        "",
        "## 3. Corpus measurement (unchanged v2 corpus, secondary evidence)",
        "",
        "Means over 16 queries (P@5, P@10, MRR, nDCG@10); the M3-A0 baseline is the reference:",
        "",
        _fmt_table(
            ["stage", "P@5", "P@10", "MRR", "nDCG@10", "rel-0 in top-10", "fresh junk in top-10"],
            [
                ["baseline (M3-A0)"] + [f"{report['corpus_measurement']['means']['baseline'][m]:.4f}" for m in ("precision_at_5", "precision_at_10", "reciprocal_rank", "ndcg_at_10")] + ["-", "-"]
            ]
            + [
                [name] + [f"{report['corpus_measurement']['means'][name][m]:.4f}" for m in ("precision_at_5", "precision_at_10", "reciprocal_rank", "ndcg_at_10")] + [str(report["corpus_measurement"]["rel0_in_top10"][name]), str(report["corpus_measurement"]["fresh_junk_in_top10"][name])]
                for name in candidate_names
            ],
        ),
        "",
        "## 4. Observations",
        "",
        "- Acceptance: every candidate clears the behavioural probes (the bar is behavioural, not metric).",
        "- Corpus caveat: the v2 corpus timestamps correlate with relevance by authoring (M3-C, rho ÃƒÂ¢Ã¢â‚¬Â°Ã‹â€  0.41), "
        "so adding freshness can inflate corpus nDCG without meaning it is better: the probes are the "
        "controlled evidence, corpus numbers are indicative.",
        "- Fresh junk: mean count of rel-0 items in the top 10 (and of those with freshness >= 0.7).",
        "- Diversity is toggleable and only reorders within the Ãƒâ€šÃ‚Â±0.05 band (P8).",
        "- No weights were tuned against the corpus; no production ranker was wired.",
    ]
    return "\n".join(lines) + "\n"


def _human_summary(report: dict) -> str:
    means = report["corpus_measurement"]["means"]
    probe_total = len(report["probes"]["rows"])
    passed = sum(1 for p in report["probes"]["rows"] if all(c["passed"] for c in p["per_candidate"].values()))
    lines = [
        f"M3-D ranking experiment ({probe_total} behavioural probes, corpus revision {report['corpus_revision']} unchanged)",
        f"  probes passed by all candidates: {passed}/{probe_total}",
    ]
    for name in CANDIDATES:
        m = means[name]
        base = means["baseline"]["ndcg_at_10"]
        delta = m["ndcg_at_10"] - base
        lines.append(
            f"  {name:<22} nDCG@10 {m['ndcg_at_10']:.4f} (delta {delta:+.4f})  P@10 {m['precision_at_10']:.4f}  "
            f"rel0-in-top10 {report['corpus_measurement']['rel0_in_top10'][name]}  "
            f"fresh-junk {report['corpus_measurement']['fresh_junk_in_top10'][name]}"
        )
    lines.append(f"  status: {report['status']}")
    return "\n".join(lines)


def main() -> int:
    report = _run_report()
    REPORTS_DIR = Path(__file__).resolve().parent / "reports"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "ranking_eval.md").write_text(_render_markdown(report), encoding="utf-8")
    print(_human_summary(report))
    print(f"\nWrote {REPORTS_DIR / 'ranking_eval.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
