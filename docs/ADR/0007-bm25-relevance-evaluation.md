# ADR 0007: BM25 relevance evaluation — NO-GO as production relevance core

- **Status:** Accepted (NO-GO)
- **Date:** 2026-08-20
- **Milestone:** M3-B
- **Related:** ADR 0006; docs/M3-retrieval-intelligence-design.md §3; PROJECT_SPEC.md §17

## Context

The M3 design (§3) recommended BM25 as the text core of relevance ranking:
"BM25 as the text core, with hand-set exact-match bonuses", implemented in
`services/ranker.py` (k1 = 1.5, b = 0.75, smoothed IDF
`ln(1 + (N − n + 0.5) / (n + 0.5))`, `score = 2·bm25(title) + 1·bm25(description)`,
self-match normalization to [0, 1], optional exact-match bonuses).

M3-B was run as an isolated experiment first — BM25 alone, no freshness, no
weighted final ranking — measured against the **unchanged v2 evaluation corpus**
(revision 2, 16 queries, 365 items, near-miss + ambiguous-entity distractors).
No parameter tuning was performed during the evaluation; the production ranker
was never wired into the pipeline.

## Evaluation (offline, deterministic corpus revision 2)

| Variant | P@5 | P@10 | MRR | nDCG@10 |
|---|---|---|---|---|
| Naive baseline (3:1 title/description term-count) | 0.7875 | 0.8250 | 0.8958 | **0.6909** |
| BM25 core (2:1, b=0.75, smoothed IDF, no bonuses) | 0.6750 | 0.7438 | 0.8750 | **0.5674** |
| BM25 full (core + exact-match bonuses) | 0.7250 | 0.7562 | 0.8750 | **0.5834** |
| Title-only BM25 (1:0) | 0.7375 | 0.7875 | 0.9062 | **0.6263** |
| IDF classic (standard BM25 IDF) | 0.6000 | 0.6687 | 0.8542 | 0.4750 |
| IDF smooth2 (milder smoothing) | 0.6750 | 0.7438 | 0.8750 | 0.5735 |
| b = 0.0 / 0.5 / 1.0 | 0.6750–0.6875 | 0.7438–0.7562 | 0.8646–0.9062 | 0.5701–0.5740 |
| Description weight 0.5 / 2.0 | 0.6500–0.7000 | 0.6813–0.7875 | 0.8750–0.8958 | 0.5188–0.6004 |

## Forensic findings (q13, q10, q12, q02, q01 walked item-by-item)

All five focus queries show the **same inversion mechanism** — a per-search IDF
failure mode over the small, topic-dense candidate set (n ≈ 23):

```
Central query term            Peripheral term
   appears in many candidates     rare in candidate set
   → low IDF                      → high IDF
   → BM25 downweights it          → BM25 promotes it
```

Examples: "quantum" IDF 0.44 vs "breakthrough" 2.77 (q02); "battery" 0.58 /
"recycling" 0.74 vs "electric"/"vehicle" 1.93 (q01); "plastic" 0.58 vs
"technology" 2.26 (q12); "vaccine"/"cold"/"chain" ≈ 0.7–0.9 vs "logistics" 1.93
(q10, where the one-word title "Logistics" ranked #2); "training" 0.83 vs
"workplace" 2.77 (q13).

A result can contain the important concept and still lose because the important
word happens to be common within that search's candidate set. The v2 corpus's
near-miss distractors (which share the central terms) amplify exactly this.

Variant isolation:

- Changing `b` does not solve it (0.5701–0.5740 across b = 0/0.5/1.0).
- Changing the IDF formulation does not solve it (classic is worse: 0.4750).
- Increasing description weight makes it worse (desc-w 2.0 → 0.5188).
- Removing descriptions entirely helps (title-only → 0.6263) but still stays
  6.46 percentage points below the naive baseline on nDCG@10.

## Decision

**NO-GO.** BM25 is rejected as the primary relevance-ranking core for
SignalPulse M3-B under the current retrieval architecture. Per-search IDF over
the ~23-item candidate set is the disqualifier; no tested configuration reaches
the naive baseline, so further tuning to "make the metric pass" would be tuning
to the corpus, not fixing the model. BM25 is **not wired into the production
pipeline**.

## Evidence preserved (explicitly experimental research artifacts)

- `backend/app/services/ranker.py` — the BM25 implementation (unit-tested,
  12 tests), header-marked as NOT production ranking.
- `backend/tests/test_ranker.py` — pins the experimental implementation.
- `eval/bm25_eval.py` + `eval/tests/test_bm25_eval.py` — measurement bridge
  and pinned metrics.
- `eval/bm25_forensic.py` + `eval/reports/bm25_forensic.md` — full item-by-item
  forensic analysis (top-10 naive/BM25 tables, gold relevance, scores, harmful
  inversions, per-query IDF tables, all variant measurements).

None of these are imported by the application or the evaluation runner; the
production relevance core remains the transparent lexical baseline, to be
evolved carefully rather than replaced blindly.

## Consequences

- M3-B pivots from "find the fanciest ranking algorithm" to "build a
  transparent relevance baseline that matches the product's actual retrieval
  behavior": query-term matching with stronger title weighting, phrase match,
  description signals, deterministic scoring — each improvement measured
  against the unchanged v2 corpus.
- The naive baseline (nDCG@10 0.6909) remains the reference to beat.
- **Future possibility:** BM25 (or IDF-style signal) may be revisited as one
  feature within the combined M3-D model, or with a global/corpus-level IDF at
  larger N — but only with new evidence, never per-search IDF at n ≈ 23.
- M3-C (freshness) is the next experiment, measured independently before any
  combination with relevance.
- The v2 corpus is unchanged and remains the single source of truth for all
  subsequent ranking experiments.