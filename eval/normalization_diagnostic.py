# ruff: noqa: E501
"""M8 diagnostic: expose C4 component scores for controlled scenarios.

Evaluation-only. Replicates the production arithmetic (app/services/ranking.py
lines 89-96, 162-174 + freshness.py constants) exactly, asserts the replica
reproduces the production ``rank_items`` ordering, then prints component tables
for scenarios A-E to answer: where does min-max bite, how sensitive is
normalized relevance to one document, and can weak-but-fresh outrank strong?

Run: python -m eval.normalization_diagnostic   (writes reports/normalization_diagnostic.md)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.ranking import Rankable, rank_items  # noqa: E402

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=__import__("datetime").UTC)

WEIGHTS = {
    "news": (0.55, 0.30, 0.15),
    "social": (0.55, 0.30, 0.15),
    "reference": (0.65, 0.10, 0.25),
}
QUALITY = {
    ("news", "The Guardian"): 0.90,
    ("reference", "Wikipedia"): 0.80,
    ("social", "r/technology (Reddit)"): 0.50,
    ("news", "Unknown"): 0.50,
}


def freshness(source_type: str, published_hours_ago: float | None) -> float:
    if published_hours_ago is None:
        return 0.25 if source_type in ("news", "social") else 0.5
    if source_type == "reference":
        return 0.5
    half_life = 24.0 if source_type == "news" else 12.0
    floor = 0.05
    import math

    return min(1.0, floor + 0.95 * math.pow(2, -max(0.0, published_hours_ago) / half_life))


def quality(source_type: str, source_name: str) -> float:
    return QUALITY.get((source_type, source_name), 0.50)


def baseline_raw(title_tokens: set[str], desc_tokens: set[str], query_terms: list[str]) -> int:
    return sum((3 if t in title_tokens else 0) + (1 if t in desc_tokens else 0) for t in query_terms)


def analyse(label: str, query: str, docs: list[dict]) -> tuple[list[dict], list[str]]:
    """docs: dicts with id/title/desc/source_type/source_name/pub_hours_ago."""
    import re

    tokens = re.findall(r"[a-z0-9]+", query.lower())
    query_terms = sorted(set(tokens))
    rows = []
    for d in docs:
        tt = set(re.findall(r"[a-z0-9]+", d["title"].lower()))
        dt = set(re.findall(r"[a-z0-9]+", (d.get("desc") or "").lower()))
        raw = baseline_raw(tt, dt, query_terms)
        f = freshness(d["source_type"], d.get("pub_hours_ago"))
        q = quality(d["source_type"], d["source_name"])
        rows.append({**d, "raw": raw, "fresh": round(f, 4), "qual": q})
    max_raw = max((r["raw"] for r in rows), default=0)
    for r in rows:
        rel = r["raw"] / max_raw if max_raw else 0.0
        w = WEIGHTS[r["source_type"]]
        parts = (w[0] * rel, w[1] * r["fresh"], w[2] * r["qual"])
        r.update(norm_rel=round(rel, 4), w_rel=w[0], w_fresh=w[1], w_qual=w[2],
                 part_rel=round(parts[0], 4), part_fresh=round(parts[1], 4),
                 part_qual=round(parts[2], 4), final=round(sum(parts), 4))

    # Production ordering (authoritative)
    order = rank_items(
        [Rankable(id=d["id"], title=d["title"], description=d.get("desc"),
                  source_type=d["source_type"], source_name=d["source_name"],
                  published_at=(NOW - timedelta(hours=d["pub_hours_ago"]))
                  if d.get("pub_hours_ago") is not None else None,
                  url=f"https://example.com/{d['id']}") for d in docs],
        query, now=NOW,
    )
    prod_order = [r.id for r in order]
    replica_order = [r["id"] for r in sorted(rows, key=lambda r: (-r["final"],))]
    match = prod_order == replica_order
    print(f"[{label}] replica matches production order: {match}")
    assert match, (prod_order, replica_order)
    return rows, prod_order


def md_table(rows: list[dict], order: list[str], title: str) -> list[str]:
    by_id = {r["id"]: r for r in rows}
    out = [f"### {title}", "",
           "| rank | id | raw | norm_rel | fresh | qual | w_rel·rel | w_f·f | w_q·q | FINAL |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for pos, rid in enumerate(order, 1):
        r = by_id[rid]
        out.append(
            f"| {pos} | {rid} | {r['raw']} | {r['norm_rel']} | {r['fresh']} | {r['qual']} "
            f"| {r['part_rel']} | {r['part_fresh']} | {r['part_qual']} | **{r['final']}** |"
        )
    return out


SECTIONS: list[str] = ["# M8 — C4 normalization diagnostic", "",
                       f"Fixed now: `{NOW.isoformat()}` · replica verified against production `rank_items`.", ""]


def run_scenario(name: str, query: str, docs: list[dict], notes: list[str]):
    global SECTIONS
    print(f"=== {name} ===")
    rows, order = analyse(name, query, docs)
    SECTIONS += md_table(rows, order, name)
    if notes:
        SECTIONS += [""] + [f"- {n}" for n in notes] + [""]


# --- Scenario A: similar relevance ------------------------------------------
run_scenario("Scenario A — similar relevance", "artificial intelligence", [
    {"id": "a1", "title": "Artificial intelligence explained", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 20},
    {"id": "a2", "title": "History of artificial intelligence", "desc": "overview article",
     "source_type": "news", "source_name": "The Guardian", "pub_hours_ago": 30},
    {"id": "a3", "title": "Artificial intelligence safety", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 40},
    {"id": "a4", "title": "AI overview", "desc": "artificial intelligence summary",
     "source_type": "news", "source_name": "Unknown", "pub_hours_ago": 25},
], notes=["All four contain ≥1 query term; raw spread 4-8; top doc defines scale."])

# --- Scenario B: outlier -----------------------------------------------------
base_docs = [
    {"id": "b1", "title": "AI regulation", "desc": "safety ethics overview",
     "source_type": "news", "source_name": "The Guardian", "pub_hours_ago": 24},
    {"id": "b2", "title": "Ethics of automation", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 30},
]
rows_wo, _ = analyse("B without outlier", "ai regulation safety ethics", base_docs)
with_outlier = base_docs + [
    {"id": "bX", "title": "AI regulation safety ethics report", "desc": "ai regulation",
     "source_type": "news", "source_name": "The Guardian", "pub_hours_ago": 26},
]
rows_w, order_w = analyse("B with outlier", "ai regulation safety ethics", with_outlier)
before = {r["id"]: (r["norm_rel"], r["final"]) for r in rows_wo}
after = {r["id"]: (r["norm_rel"], r["final"]) for r in rows_w}
SECTIONS += ["### Scenario B — single outlier recompresses everyone", ""]
for rid in ("b1", "b2"):
    SECTIONS.append(f"- {rid}: norm_rel {before[rid][0]} → {after[rid][0]}, "
                    f"final {before[rid][1]} → {after[rid][1]}")
SECTIONS += [""]

# --- Scenario C: old-relevant vs fresh-weak ----------------------------------
c_docs = [
    {"id": "strong_old", "title": "AI regulation framework deep dive",
     "desc": "artificial intelligence regulation", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 720},
    {"id": "weak_fresh", "title": "Quick AI note", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 1},
]
rows_c, order_c = analyse("Scenario C", "artificial intelligence regulation", c_docs)
by = {r["id"]: r for r in rows_c}
gap = by["strong_old"]["final"] - by["weak_fresh"]["final"]
SECTIONS += ["### Scenario C — strong-old vs weak-fresh (uncompressed)", "",
             f"- winner: `{order_c[0]}` · final gap: {gap:.4f}", ""]

# --- Scenario D: phrase vs scattered -----------------------------------------
d_docs = [
    {"id": "phrase", "title": "Artificial intelligence regulation passes",
     "source_type": "news", "source_name": "The Guardian", "pub_hours_ago": 10},
    {"id": "scatter", "title": "Regulation of artificial intelligence risk",
     "source_type": "news", "source_name": "The Guardian", "pub_hours_ago": 10},
]
rows_d, order_d = analyse("Scenario D", "artificial intelligence regulation", d_docs)
SECTIONS += ["### Scenario D — exact phrase vs scattered tokens", "",
             f"- identical raw & components → order decided only by tie-break URL: {order_d}",
             "- C4 gives the consecutive phrase zero extra weight (motivates C5 test).", ""]

# --- Scenario E: C5-style +2 perturbation ------------------------------------
e_base = [
    {"id": "top", "title": "Artificial intelligence", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 48},
    {"id": "mid", "title": "AI safety summit", "source_type": "news",
     "source_name": "The Guardian", "pub_hours_ago": 2},
    {"id": "low", "title": "Weekly tech roundup", "desc": "brief ai mention",
     "source_type": "news", "source_name": "The Guardian", "pub_hours_ago": 1},
]
rows_e0, order_e0 = analyse("E baseline", "artificial intelligence safety", e_base)
pert = [dict(d) for d in e_base]
for p in pert:
    if p["id"] == "mid":
        p["title"] = "Artificial intelligence safety summit"  # +phrase-equivalent raw jump
rows_e1, order_e1 = analyse("E after mid gets +2-style raw jump", "artificial intelligence safety", pert)
b0 = {r["id"]: (r["norm_rel"], r["final"]) for r in rows_e0}
b1 = {r["id"]: (r["norm_rel"], r["final"]) for r in rows_e1}
SECTIONS += ["### Scenario E — one doc's raw jumps (+2-class event)", ""]
for rid in ("top", "mid", "low"):
    SECTIONS.append(f"- {rid}: norm_rel {b0[rid][0]} → {b1[rid][0]}, "
                    f"final {b0[rid][1]} → {b1[rid][1]}")
SECTIONS += ["", f"- order before: {order_e0} → after: {order_e1}", ""]


def main() -> int:
    out = Path(__file__).resolve().parent / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "normalization_diagnostic.md").write_text("\n".join(SECTIONS), encoding="utf-8")
    print(f"wrote {out / 'normalization_diagnostic.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())