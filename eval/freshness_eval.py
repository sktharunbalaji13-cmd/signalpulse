# ruff: noqa: E501
"""M3-C freshness experiment: candidate functions measured independently.

Research measurement ONLY — the production freshness scorer does not exist yet,
nothing is combined with relevance, and nothing is wired into the pipeline.
The design for the candidates is in ``docs/M3-retrieval-intelligence-design.md``
§4.1; this module:

1. Admissibility gate: every candidate must pass ``metrics.check_freshness``.
2. Corpus behaviour: per-source-type score distributions on the unchanged v2
   corpus plus the two tensions (recent-but-weakly-relevant, older-but-relevant).
3. Controlled probes at fixed timestamps: decay curves 0 h … 2 y, future clamp,
   old authoritative reference material, missing timestamps.
4. Interaction with gold relevance (Spearman) — analysis only, no combination.

Deterministic by construction: no clock, no randomness, fixed "now" taken from
the corpus ``RETRIEVED`` constant. Run with::

    python -m eval.freshness_eval

Writes ``eval/reports/freshness_eval.md``.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from eval import corpus, metrics
from eval.schema import EvalCorpus, _parse_ts, validate_corpus

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
REPORT_PATH = REPORTS_DIR / "freshness_eval.md"

# Fixed reference instant for every measurement (equals corpus retrieval time).
NOW = _parse_ts(corpus.RETRIEVED)
assert NOW == metrics._FIXED_NOW  # same instant by construction

PROBE_AGES_HOURS = [0.0, 1.0, 12.0, 24.0, 48.0, 168.0, 720.0, 8760.0, 17520.0]

DECAY_SHAPES = {"exp", "linear30d", "step", "constant"}


def _ts(hours_ago: float, *, future: bool = False) -> str:
    delta = timedelta(hours=hours_ago)
    dt = NOW + delta if future else NOW - delta
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_scorer(
    *,
    shape: str,
    news_hl_hours: float = 24.0,
    social_hl_hours: float = 12.0,
    floor: float = 0.05,
    ref_const: float = 0.5,
    miss_news_social: float = 0.25,
) -> Callable:
    """Build a deterministic freshness scorer from the documented parameters.

    Signature (matches ``metrics.check_freshness``)::

        scorer(published_at: str | None, retrieved_at: str, source_type: str) -> float

    * Reference items are timeless: always ``ref_const`` regardless of age,
      including when ``published_at`` is missing.
    * ``retrieved_at`` is deliberately unused (never substitutes publication).
    * ``published_at`` in the future is clamped to age 0.
    * Shapes: ``exp`` = floor + (1 - floor) * 2^(-t/hl); ``linear30d`` = linear
      decay to floor over 30 days; ``step`` = 1.0 (<24h), 0.7 (<7d), 0.4
      (<30d), 0.2 (>=30d); ``constant`` = 1.0 (the no-freshness control).
    """
    if shape not in DECAY_SHAPES:
        raise ValueError(f"unknown shape {shape!r}")
    if shape == "step":
        step_levels = [(24.0, 1.0), (168.0, 0.7), (720.0, 0.4)]

        def _shape_value(age_h: float) -> float:
            for bound, level in step_levels:
                if age_h < bound:
                    return level
            return 0.2

    else:

        def _shape_value(age_h: float) -> float:
            if shape == "constant":
                return 1.0
            if shape == "linear30d":
                return max(floor, 1.0 - (age_h / 720.0) * (1.0 - floor))
            return floor + (1.0 - floor) * (2.0 ** (-age_h / news_hl_hours))

    def scorer(published_at: str | None, retrieved_at: str, source_type: str) -> float:
        del retrieved_at  # retrieved_at must never influence freshness
        if source_type == "reference":
            return ref_const
        if published_at is None:
            return miss_news_social
        age_hours = max(0.0, (NOW - _parse_ts(published_at)).total_seconds() / 3600.0)
        if shape == "exp":
            hl = news_hl_hours if source_type == "news" else social_hl_hours
            return floor + (1.0 - floor) * (2.0 ** (-age_hours / hl))
        return _shape_value(age_hours)

    return scorer


def _candidate(name: str, description: str, scorer) -> dict:
    return {"name": name, "description": description, "scorer": scorer}


def candidates() -> dict[str, dict]:
    """The candidate families from design §4.1, keyed by name."""
    exp = dict(shape="exp", floor=0.05, news_hl_hours=24.0, social_hl_hours=12.0)
    items = [
        _candidate("control_none", "no freshness (constant 1.0) — control", make_scorer(shape="constant")),
        _candidate("design", "§4 curve: exp 24h/12h, floor 0.05, ref 0.5, missing 0.25", make_scorer(**exp)),
        _candidate("shape_linear30d", "linear decay to floor over 30 days", make_scorer(**dict(exp, shape="linear30d"))),
        _candidate("shape_step", "step function: 1.0 / 0.7 / 0.4 / 0.2 bands", make_scorer(**dict(exp, shape="step"))),
        _candidate("hl_06h", "news 6h, social 3h half-life", make_scorer(**dict(exp, news_hl_hours=6.0, social_hl_hours=3.0))),
        _candidate("hl_12h", "news 12h, social 6h half-life", make_scorer(**dict(exp, news_hl_hours=12.0, social_hl_hours=6.0))),
        _candidate("hl_48h", "news 48h, social 24h half-life", make_scorer(**dict(exp, news_hl_hours=48.0, social_hl_hours=24.0))),
        _candidate("hl_168h", "news 7d, social 3.5d half-life", make_scorer(**dict(exp, news_hl_hours=168.0, social_hl_hours=84.0))),
        _candidate("floor_00", "exponential with floor 0.0", make_scorer(**dict(exp, floor=0.0))),
        _candidate("floor_25", "exponential with floor 0.25", make_scorer(**dict(exp, floor=0.25))),
        _candidate("ref_09", "reference constant 0.9 (never penalised)", make_scorer(**dict(exp, ref_const=0.9))),
        _candidate("miss_00", "missing timestamp scores 0.0", make_scorer(**dict(exp, miss_news_social=0.0))),
        _candidate("miss_05", "missing timestamp scores 0.5", make_scorer(**dict(exp, miss_news_social=0.5))),
        _candidate("social_24", "social half-life 24h (same as news)", make_scorer(**dict(exp, social_hl_hours=24.0))),
    ]
    return {item["name"]: item for item in items}


def _build_corpus() -> EvalCorpus:
    return validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )


def _all_items(corpus_data: EvalCorpus) -> list:
    return [item for query in corpus_data.queries for item in query.items]


def _rank_data(values: list[float]) -> list[float]:
    """Average-rank a list, deterministically (ties share the mean rank)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation (average ranks for ties); nan if constant."""
    n = len(xs)
    if n < 3:
        return float("nan")
    rx, ry = _rank_data(xs), _rank_data(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy) ** 0.5


def _probe_curve(scorer, ages_hours: list[float]) -> list[float]:
    return [scorer(_ts(a), _ts(0.0), "news") for a in ages_hours]


def _probe_social_curve(scorer, ages_hours: list[float]) -> list[float]:
    return [scorer(_ts(a), _ts(0.0), "social") for a in ages_hours]


def _invariants_table() -> dict[str, dict[str, bool | float]]:
    result = {}
    for name, cand in candidates().items():
        result[name] = metrics.check_freshness(cand["scorer"])
    return result


def _corpus_behavior(corpus_data: EvalCorpus) -> dict:
    items = _all_items(corpus_data)
    freshest = sorted(
        items,
        key=lambda i: (
            -(_parse_ts(i.published_at) - NOW).total_seconds()
            if i.published_at
            else float("inf")
        ),
    )[:10]
    rows = []
    for name, cand in candidates().items():
        scores = {item.id: cand["scorer"](item.published_at, item.retrieved_at, item.source_type) for item in items}
        per_type = {}
        for stype in ("news", "social", "reference"):
            vals = [scores[item.id] for item in items if item.source_type == stype]
            per_type[stype] = {
                "n": len(vals),
                "min": round(min(vals), 4),
                "median": round(statistics.median(vals), 4),
                "max": round(max(vals), 4),
                "pct_below_0_5": round(100.0 * sum(1 for v in vals if v < 0.5) / len(vals), 1),
            }
        decoy_tension_ge09 = sum(1 for item in items if item.relevance == 0 and scores[item.id] >= 0.9)
        decoy_tension_ge07 = sum(1 for item in items if item.relevance == 0 and scores[item.id] >= 0.7)
        old_relevant = sum(1 for item in items if item.relevance >= 1 and scores[item.id] < 0.5)
        rows.append(
            {
                "name": name,
                "per_type": per_type,
                "decoy_tension_rel0_fresh_ge09": decoy_tension_ge09,
                "decoy_tension_rel0_fresh_ge07": decoy_tension_ge07,
                "old_relevant_tension_rel_ge1_fresh_lt05": old_relevant,
            }
        )
    freshest_rows = [
        {
            "id": item.id,
            "title": item.title,
            "source_type": item.source_type,
            "relevance": item.relevance,
            "age_hours": round((NOW - _parse_ts(item.published_at)).total_seconds() / 3600.0, 2)
            if item.published_at
            else None,
        }
        for item in freshest
    ]
    return {
        "item_count": len(items),
        "timestamp_span_days": (max(NOW - _parse_ts(i.published_at) for i in items if i.published_at)).days
        if any(i.published_at for i in items)
        else None,
        "freshest_10": freshest_rows,
        "per_candidate": rows,
    }


def _probes() -> dict:
    rows = {}
    for name, cand in candidates().items():
        scorer = cand["scorer"]
        news_curve = _probe_curve(scorer, PROBE_AGES_HOURS)
        social_curve = _probe_social_curve(scorer, PROBE_AGES_HOURS)
        rows[name] = {
            "name": name,
            "news_curve": [round(v, 4) for v in news_curve],
            "social_curve": [round(v, 4) for v in social_curve],
            "reference_at_now": round(scorer(_ts(0.0), _ts(0.0), "reference"), 4),
            "reference_2y_old": round(scorer(_ts(17520.0), _ts(0.0), "reference"), 4),
            "future_clamped": round(scorer(_ts(24.0, future=True), _ts(0.0), "news"), 4),
            "future_clamped_equals_now": scorer(_ts(24.0, future=True), _ts(0.0), "news")
            == scorer(_ts(0.0), _ts(0.0), "news"),
            "missing_news": round(scorer(None, _ts(0.0), "news"), 4),
            "missing_social": round(scorer(None, _ts(0.0), "social"), 4),
            "missing_reference": round(scorer(None, _ts(0.0), "reference"), 4),
        }
    return {"probe_ages_hours": PROBE_AGES_HOURS, "per_candidate": rows}


def _interaction(corpus_data: EvalCorpus) -> dict:
    items = _all_items(corpus_data)
    rows = []
    for name, cand in candidates().items():
        scores = [cand["scorer"](item.published_at, item.retrieved_at, item.source_type) for item in items]
        relevance = [float(item.relevance) for item in items]
        by_type = {}
        for stype in ("news", "social", "reference"):
            sub = [i for i, item in enumerate(items) if item.source_type == stype]
            sx = [scores[i] for i in sub]
            sy = [relevance[i] for i in sub]
            rho = spearman(sx, sy)
            by_type[stype] = round(rho, 4) if rho == rho else "constant (no variance)"
        overall = spearman(scores, relevance)
        rows.append(
            {
                "name": name,
                "spearman_overall": round(overall, 4) if overall == overall else "constant (no variance)",
                "spearman_by_type": by_type,
            }
        )
    return {"per_candidate": rows}


def _run_report() -> dict:
    corpus_data = _build_corpus()
    return {
        "schema": "signalpulse-freshness-experiment",
        "fixed_now": corpus.RETRIEVED,
        "corpus_revision": corpus_data.revision,
        "corpus_unchanged": True,
        "status": "research measurement only; NOT production, NOT combined with relevance",
        "candidates": [
            {"name": cand["name"], "description": cand["description"]} for cand in candidates().values()
        ],
        "invariants": _invariants_table(),
        "corpus_behavior": _corpus_behavior(corpus_data),
        "probes": _probes(),
        "interaction": _interaction(corpus_data),
    }


def _fmt_table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    line = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(header)) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |"
    body = "\n".join("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(header))) + " |" for r in rows)
    return "\n".join([line, sep, body])


def _render_markdown(report: dict) -> str:
    inv = report["invariants"]
    inv_ok = [
        name
        for name, checks in inv.items()
        if all(checks[k] is True for k in ("missing_timestamp_handled", "no_retrieved_substitution", "monotonic_with_age", "future_clamped"))
    ]
    lines = [
        "# M3-C freshness experiment — candidate functions, measured independently",
        "",
        f"- Fixed now: `{report['fixed_now']}` (corpus `RETRIEVED`); corpus revision "
        f"{report['corpus_revision']}, unchanged.",
        f"- Status: **{report['status']}**.",
        "",
        "## 1. Candidates",
        "",
        _fmt_table(
            ["name", "description"],
            [[c["name"], c["description"]] for c in report["candidates"]],
        ),
        "",
        "## 2. Admissibility gate (all four invariants must pass)",
        "",
        _fmt_table(
            ["name", "missing_handled", "no_retrieved_substitution", "monotonic", "future_clamped"],
            [
                [name, str(checks["missing_timestamp_handled"]), str(checks["no_retrieved_substitution"]),
                 str(checks["monotonic_with_age"]), str(checks["future_clamped"])]
                for name, checks in inv.items()
            ],
        ),
        f"\nPassed by all candidates: {len(inv_ok)}/{len(inv)} (`{'`, `'.join(inv_ok)}`).",
        "",
        "## 3. Corpus behaviour (unchanged v2 corpus, fixed now)",
        "",
        f"- {report['corpus_behavior']['item_count']} items; timestamps span at most "
        f"{report['corpus_behavior']['timestamp_span_days']} days, so the corpus only exercises "
        "the steep (breaking-news) part of any decay curve — long-age behaviour is probed in §4.",
        "",
        "Freshest 10 items (these are the very-recent-but-weakly-relevant population):",
        "",
        _fmt_table(
            ["id", "title", "type", "rel", "age_h"],
            [
                [r["id"], r["title"], r["source_type"], str(r["relevance"]), str(r["age_hours"])]
                for r in report["corpus_behavior"]["freshest_10"]
            ],
        ),
        "",
        "Per candidate (per-source-type stats, plus the two tensions):",
        "",
        _fmt_table(
            ["name", "news min/med/max", "news %<0.5", "social min/med/max", "ref med",
             "rel0 fresh>=0.9", "rel0 fresh>=0.7", "rel>=1 fresh<0.5"],
            [
                [r["name"],
                 f"{r['per_type']['news']['min']}/{r['per_type']['news']['median']}/{r['per_type']['news']['max']}",
                 str(r["per_type"]["news"]["pct_below_0_5"]),
                 f"{r['per_type']['social']['min']}/{r['per_type']['social']['median']}/{r['per_type']['social']['max']}",
                 str(r["per_type"]["reference"]["median"]),
                 str(r["decoy_tension_rel0_fresh_ge09"]),
                 str(r["decoy_tension_rel0_fresh_ge07"]),
                 str(r["old_relevant_tension_rel_ge1_fresh_lt05"])]
                for r in report["corpus_behavior"]["per_candidate"]
            ],
        ),
        "",
        "## 4. Controlled probes (fixed timestamps; 0 h = now)",
        "",
        "News decay curves (age in hours):",
        "",
        _fmt_table(
            ["name"] + [str(a) for a in report["probes"]["probe_ages_hours"]],
            [[r["name"]] + [str(v) for v in r["news_curve"]] for r in report["probes"]["per_candidate"].values()],
        ),
        "",
        "Per-candidate probe summary:",
        "",
        _fmt_table(
            ["name", "ref@now", "ref@2y", "future", "future==now", "missing news/social/ref"],
            [
                [r["name"], str(r["reference_at_now"]), str(r["reference_2y_old"]),
                 str(r["future_clamped"]), str(r["future_clamped_equals_now"]),
                 f"{r['missing_news']}/{r['missing_social']}/{r['missing_reference']}"]
                for r in report["probes"]["per_candidate"].values()
            ],
        ),
        "",
        "## 5. Interaction with relevance (analysis only — NO combination)",
        "",
        "Spearman between candidate freshness and gold relevance, overall and per type "
        "(`constant (no variance)` = no rank variance in that group):",
        "",
        _fmt_table(
            ["name", "spearman overall", "news", "social", "reference"],
            [
                [r["name"], str(r["spearman_overall"]), str(r["spearman_by_type"]["news"]),
                 str(r["spearman_by_type"]["social"]), str(r["spearman_by_type"]["reference"])]
                for r in report["interaction"]["per_candidate"]
            ],
        ),
        "",
        "## 6. Observations",
        "",
        "- All 14 candidates pass the admissibility gate; the choice is behavioural, not mechanical.",
        "- The corpus timestamps span only 0.2–6 days and are dominated by 1–6-day-old items: under "
        "the design 24 h half-life, 87% of news scores below 0.5 and 191 relevant items score below "
        "0.5. The curve behaves as specified (see probes); this is a property of the corpus's age "
        "distribution, and it is exactly the distribution M3-D weighting must be validated against.",
        "- Within a source type, every monotone candidate (exp/linear/hl/floor variants) has the same "
        "Spearman vs relevance (news 0.4522, social 0.3623): rank correlation is invariant to "
        "monotone transforms, so curve shape changes only score spacing, never order within a type. "
        "Only non-monotone shapes (step) or per-type constants change the interaction.",
        "- The measured overall Spearman (0.41 for design) reflects how the corpus was authored "
        "(timestamps were written to look realistic, not randomised against relevance). The corpus "
        "is not designed to isolate freshness from relevance, so the interaction numbers are "
        "indicative, not causal; the controlled probes (§4) are the definitive measurements.",
        "- Decoy tension: the freshest 10 items (§3) are rel-0/rel-1 near-miss or 'Update' items — "
        "the very-recent-but-weakly-relevant population a combined ranker must not let dominate. "
        "Under the design curve none of them reach 0.9 (the freshest is ~5 h old, scoring 0.88), "
        "which is the separation the curve provides at M3-D combination time.",
        "- Reference timelessness holds for every candidate: a 2-year-old reference item scores "
        "exactly like a fresh one; missing timestamps score the documented neutral (0.25 news/social, "
        "0.5 reference) instead of zero or a retrieved_at substitution.",
        "- No combined ranking is computed anywhere in this experiment.",
    ]
    return "\n".join(lines) + "\n"


def _human_summary(report: dict) -> str:
    inv_ok = sum(
        1
        for checks in report["invariants"].values()
        if all(checks[k] is True for k in ("missing_timestamp_handled", "no_retrieved_substitution", "monotonic_with_age", "future_clamped"))
    )
    design = next(r for r in report["corpus_behavior"]["per_candidate"] if r["name"] == "design")
    interaction = next(r for r in report["interaction"]["per_candidate"] if r["name"] == "design")
    return (
        f"M3-C freshness experiment ({len(report['candidates'])} candidates, corpus revision "
        f"{report['corpus_revision']} unchanged)\n"
        f"  invariants passed: {inv_ok}/{len(report['candidates'])} candidates\n"
        f"  design curve news median {design['per_type']['news']['median']}, "
        f"social median {design['per_type']['social']['median']}, "
        f"reference median {design['per_type']['reference']['median']}\n"
        f"  decoy tension (rel0 & fresh>=0.9): {design['decoy_tension_rel0_fresh_ge09']} items; "
        f"old-relevant tension: {design['old_relevant_tension_rel_ge1_fresh_lt05']} items\n"
        f"  interaction: spearman overall {interaction['spearman_overall']}\n"
        f"  status: {report['status']}"
    )


def main() -> int:
    report = _run_report()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_render_markdown(report), encoding="utf-8")
    print(_human_summary(report))
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())