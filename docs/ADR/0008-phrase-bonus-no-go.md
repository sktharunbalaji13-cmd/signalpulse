# ADR 0008 — Exact-phrase relevance bonus: NO-GO

**Status:** Accepted (2026-08-23)
**Context:** M7 search-quality milestone. Production ranking is the frozen M3-D C4 model
(relevance = bag-of-words term presence ×3 title / ×1 description, min-max normalised per
search; freshness curve; source-quality constants; ±0.05 diversity band; duplicate-score
inheritance; deterministic total order). ADR 0007 already rejected BM25 as the relevance core.

## Pre-registered experiment (defined before evaluation)

**C5 = C4 + conservative exact-phrase title bonus**

- One-time **+2 raw** relevance points when ≥2 query tokens appear **consecutively, in order**
  inside the title token sequence (same `[a-z0-9]+` tokenizer; case/punctuation-insensitive).
- Single-token queries get no bonus. No description-phrase bonus, no partial credit,
  no other parameter changes. Evaluation-only; production untouched.
- **Adoption gate:** all 9 behavioural probes pass AND nDCG@10 improves ≥ +0.005 with no
  P@10 regression vs C4.

## Measured result (frozen corpus v2, 16 queries)

| Metric | C4 | C5 | Δ |
|---|---|---|---|
| nDCG@10 | **0.7850** | 0.7757 | −0.0093 |
| P@10 | **0.8688** | 0.8625 | −0.0063 |
| rel-0 in top-10 | **1.3125** | 1.375 | worse |
| fresh-junk in top-10 | **0.0625** | 0.125 | 2× worse |

Behavioural probes: 9/9 pass for both candidates — but the metric gate failed decisively.

## Decision

**NO-GO.** C4 remains the production ranking model unchanged. Rationale: boosting
consecutive-phrase titles under per-search min-max normalisation compresses every other
document's relevance component, letting freshness/quality carry weak matches upward —
fresh-junk in the top 10 doubled. Consistent with ADR 0007: richer lexical scoring does not
beat the naive baseline on this corpus.

## Notes

- Definition was fixed before evaluation; no parameter tuning occurred post-hoc.
- Experiment code lived only in `eval/ranking_eval.py` (evaluation harness) and has been
  reverted; the harness returns to the C4-only baseline. Numbers are preserved here.
