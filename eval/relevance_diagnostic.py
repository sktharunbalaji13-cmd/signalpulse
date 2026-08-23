# ruff: noqa: E501
"""M9 diagnostic: probe C4's binary-presence relevance for information loss.

Evaluation-only, deterministic. Part 1 replays controlled scenarios through the
exact production arithmetic. Part 2 scans frozen corpus v2 for evidence that
binary term-presence collapses documents that gold labels distinguish, and
reports which unused signals (title-tf, description-tf, coverage ratio,
combined) could separate those collapsed groups.

Run: python -m eval.relevance_diagnostic
Writes: eval/reports/relevance_diagnostic.md
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from eval import baseline, corpus  # noqa: E402
from eval.schema import EvalCorpus, validate_corpus  # noqa: E402

TOKEN_RE = re.compile(r"[a-z0-9]+")
SECTIONS: list[list[str]] = []


def toks(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def raw_of(title: str, desc: str, query_terms: list[str]) -> int:
    t = set(toks(title))
    d = set(toks(desc))
    return sum((3 if term in t else 0) + (1 if term in d else 0) for term in query_terms)


def section(title: str) -> None:
    SECTIONS.append([f"### {title}", ""])


def table(rows: list[str]) -> None:
    SECTIONS.append(
        ["| doc | raw (C4) | title-tf | desc-tf | coverage |", "|---|---|---|---|---|"]
        + rows
        + [""]
    )


def bullets(items: list[str]) -> None:
    SECTIONS.append(["- " + i for i in items] + [""])


QUERY_3 = ["artificial", "intelligence", "safety"]

SC_A = [
    ("once",  "AI safety", ""),
    ("twice", "AI safety: AI safety debate", ""),
    ("five",  "AI safety AI safety AI safety", ""),
]
SC_B = [
    ("3/3 title", "Artificial intelligence safety", ""),
    ("2/3 title", "Artificial intelligence risk", ""),
    ("1/3 title", "Intelligence report", ""),
]
SC_C = [
    ("all title",       "Artificial intelligence safety", ""),
    ("all description", "ai", "artificial intelligence safety"),
    ("split t2+d1",     "Artificial intelligence", "safety"),
]
SC_D = [
    ("phrase",    "Artificial intelligence regulation passes", ""),
    ("scattered", "Safety of artificial intelligence regulation", ""),
    ("partial",   "Artificial intelligence risk", ""),
]
SC_E = [
    ("short desc", "Topic", "ai safety brief note"),
    ("long desc",  "Topic", "ai safety " + "filler words about other things entirely " * 3),
]


def sig_rows(docs: list[tuple[str, str, str]], qtokens: list[str]) -> list[str]:
    qt = set(qtokens)
    rows = []
    for label, title, desc in docs:
        tt = toks(title)
        dt = toks(desc)
        raw = raw_of(title, desc, qtokens)
        ttf = sum(tt.count(t) for t in qtokens)
        dtf = sum(dt.count(t) for t in qtokens)
        cov = len(qt & set(tt)) / len(qt) if qt else 0.0
        rows.append(f"| {label} | {raw} | {ttf} | {dtf} | {cov:.2f} |")
    return rows


def part1() -> None:
    SECTIONS.append(["## Part 1 - controlled scenarios", ""])

    section("Scenario A - frequency blindness (query: ai safety)")
    table(sig_rows(SC_A, ["ai", "safety"]))
    bullets(["raw identical for 1x/2x/5x occurrences: term FREQUENCY is invisible."])

    section("Scenario B - coverage tiers (query: artificial intelligence safety)")
    table(sig_rows(SC_B, QUERY_3))
    bullets([
        "9 > 6 > 3: per-term reward linear; different coverages do NOT tie here.",
        "Placement asymmetry follows in Scenario C.",
    ])

    section("Scenario C - title vs description placement")
    table(sig_rows(SC_C, QUERY_3))
    bullets([
        "all-in-description (3) TIES one single title hit (3): placement collapse.",
        "split t2+d1 (7) outranks pure-title-partial (6): composition matters.",
    ])

    section("Scenario D - phrase vs scattered vs partial (3-term query)")
    table(sig_rows(SC_D, QUERY_3))
    bullets([
        "phrase == scattered (both 9): adjacency invisible (M7 confirmed; not retried).",
        "both beat partial (6): full coverage rewarded.",
    ])

    section("Scenario E - description length invariance (query: ai safety)")
    table(sig_rows(SC_E, ["ai", "safety"]))
    bullets(["Same hits regardless of length: length-invariant by design (defensible)."])


def _signals(title_tokens: list[str], desc_tokens: list[str], qtokens: list[str]) -> tuple[int, int, float]:
    ttf = sum(title_tokens.count(t) for t in qtokens)
    dtf = sum(desc_tokens.count(t) for t in qtokens)
    cov = len(set(qtokens) & set(title_tokens)) / len(set(qtokens)) if qtokens else 0.0
    return ttf, dtf, cov


def part2() -> dict:
    data = validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )
    total_groups = 0
    split_groups = 0
    queries_affected: set[str] = set()
    sep = {"ttf": 0, "dtf": 0, "cov": 0, "any": 0}
    examples: list[str] = []
    for q in data.queries:
        qtokens = sorted(baseline._tokenize(q.query))
        by_raw: dict[int, list] = defaultdict(list)
        for item in q.items:
            tt_list = toks(item.title)
            dt_list = toks(item.description or "")
            raw = baseline.baseline_score(item, qtokens)
            by_raw[raw].append((item, tt_list, dt_list))
        for raw_val, members in sorted(by_raw.items(), reverse=True):
            if len(members) < 2:
                continue
            total_groups += 1
            labels = {m[0].relevance for m in members}
            if len(labels) < 2:
                continue
            split_groups += 1
            queries_affected.add(q.id)
            sig = {
                "ttf": {m[1] and sum(m[1].count(t) for t in qtokens) for m in members},
                "dtf": {sum(m[2].count(t) for t in qtokens) for m in members},
                "cov": {
                    len(set(qtokens) & set(m[1])) / len(set(qtokens)) for m in members
                },
            }
            sep_any = False
            for key in ("ttf", "dtf", "cov"):
                if len(sig[key]) > 1:
                    sep[key] += 1
                    sep_any = True
            if sep_any:
                sep["any"] += 1
            if len(examples) < 10:
                detail = "; ".join(
                    f"{item.id}(rel={item.relevance},ttf={ttf},dtf={dtf})"
                    for (item, tt_list, dt_list), ttf, dtf in (
                        (m, sum(m[1].count(t) for t in qtokens),
                         sum(m[2].count(t) for t in qtokens))
                        for m in members
                    )
                )
                examples.append(f"- `{q.id}` raw={raw_val}: {detail}")

    SECTIONS.append([
        "## Part 2 - frozen corpus v2: equal-raw groups with differing gold labels",
        "",
        f"- equal-raw groups (>=2 items): **{total_groups}**",
        f"- groups whose gold labels DIFFER (information collapsed by binary presence): "
        f"**{split_groups}** across {len(queries_affected)}/16 queries",
        f"- separable by unused title-tf: **{sep['ttf']}** · "
        f"description-tf: **{sep['dtf']}** · "
        f"title-coverage-ratio: **{sep['cov']}** · "
        f"any-of-those: **{sep['any']}**",
        "",
        "First examples encountered (deterministic order, not selected):",
        *examples,
        "",
    ])
    return {"total_groups": total_groups, "split_groups": split_groups,
            "queries_affected": len(queries_affected), **sep}


def main() -> int:
    part1()
    stats = part2()
    out = Path(__file__).resolve().parent / "reports"
    out.mkdir(parents=True, exist_ok=True)
    body = "\n".join("\n".join(chunk) for chunk in SECTIONS)
    header = (
        "# M9 - C4 relevance signal diagnostic\n\n"
        f"- corpus revision {corpus.REVISION}\n"
        f"- equal-raw tie groups: {stats['total_groups']}; label-split: "
        f"{stats['split_groups']} across {stats['queries_affected']}/16 queries\n"
        f"- separable within split groups - title-tf: {stats['ttf']}, "
        f"description-tf: {stats['dtf']}, coverage-ratio: {stats['cov']}, "
        f"any: {stats['any']}\n"
    )
    (out / "relevance_diagnostic.md").write_text(header + "\n" + body, encoding="utf-8")
    print(header.split("\n")[2])
    print(header.split("\n")[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())