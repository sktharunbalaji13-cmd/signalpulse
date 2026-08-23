# ADR 0010 — C4 relevance signal investigation: NO-GO, retain binary presence

**Status:** Accepted (2026-08-23)
**Context:** M9. M8 (ADR 0009) established that normalization reshuffling moves
failures rather than fixing them; M7 (ADR 0008) established that additive bonuses
trigger the same rebalancing failure. This investigation therefore stayed **inside
the relevance signal itself**: is C4's binary term-presence score leaving
measurable information on the table?

## 1. Baseline behavior (audited)

`_baseline_score` (production `app/services/ranking.py:89-96`): for each query
term, +3 if present in the title token set, +1 if present in the description
token set. Tokenizer `[a-z0-9]+`, no stopwords, sets ⇒ per-term presence only.

Answers to the audit questions:

1. Term frequency: **not measured at all** (sets collapse repeats).
2–3. "AI AI AI" vs "AI": **identical score**.
4. Coverage is rewarded linearly per term, BUT different partial coverages tie:
   query {A,B,C} → title{A,C}=6 == title{B,C}=6, and all-3-in-description=3 ==
   one-term-in-title=3 (placement collapse).
5. Phrase adjacency: zero weight (ADR 0008 confirmed empirically).
6–7. Scattered multi-term docs outscore single-term docs by design; the full-
   coverage premium exists but placement ties remain unresolved.
8. Description length: invariant by design (presence-only) — defensible.
9. Binary presence makes C4 blind to within-equal-score differences.
10. **Yes — visible in the frozen corpus** (Part 2 below).

## 2. Diagnostic evidence

Controlled scenarios (`eval/reports/relevance_diagnostic.md`) confirmed each
behavior through exact production arithmetic.

Frozen-corpus scan (v2, 16 queries, 365 items):

- **85 equal-raw tie groups** (≥2 items sharing a C4 raw score).
- **63 of 85 contain documents with differing gold relevance labels** — binary
  presence genuinely collapses label-distinguishable documents, in **all 16
  queries**.
- Separability of those 63 groups by unused text signals:
  - title term-frequency total: **2**
  - description term-frequency total: **2**
  - title coverage ratio: **2**
  - any of the above: **2**
- Striking example: `q01` raw=0 group contains three rel=2 documents whose
  titles/descriptions share no query token — C4 cannot see them at all; they
  rank purely on freshness/quality.

## 3. Why this differs from ADR 0007 (BM25)

ADR 0007's BM25 replaced the entire relevance core with **per-search IDF** over
~23 topic-dense candidates; central topic terms were down-weighted and
peripheral distractor terms promoted. The M9 candidate family deliberately
avoids IDF entirely (no per-search statistics), so it is not a constants-level
retry of ADR 0007 — but see §5 for why it was still excluded.

## 4. Candidate tested (pre-registered before running)

**R1 — pure coverage tie-break:** ordering key inserts title-coverage ratio
(|title∩query| / |query|) immediately after the final score, acting **only among
equal-final-score documents**. No score, weight, normalization, freshness,
quality, or diversity changes. This is the maximum-safety shape possible: it can
refine genuinely ambiguous groups without touching any non-tied pair.

Gate (same as M8): probes 9/9, no nDCG@10/P@10/MRR regression, fresh-junk not
materially worse.

## 5. Measured result

| Metric | C4 | R1 |
|---|---|---|
| nDCG@10 | 0.7850 | 0.7850 |
| P@10 | 0.8688 | 0.8688 |
| Fresh-junk | 0.0625 | 0.0625 |
| Probes | 9/9 | 9/9 |

**Identical.** Exactly as the separability statistic predicted: with only 2/63
collapsed groups recoverable by any available signal, a pure tie-break cannot
move aggregate metrics.

## 6. Decision

**NO-GO — retain C4 binary-presence relevance unchanged.**

- The weakness is real but its recoverable portion is tiny: only 2/63 collapsed
  groups are separable by ANY available text signal, violating adoption-gate
  criterion 6 ("improvement must not be limited to one or two queries").
- Additive/scale-changing variants are pre-excluded by M7/M8 evidence (rebalance
  failure mode).
- Recovering the remaining collapsed information (e.g., `raw=0 rel=2` documents)
  would require semantic matching beyond term statistics — out of scope for the
  current no-AI architecture and deferred indefinitely.

## 7. Relationship to prior decisions

- **ADR 0007:** BM25 rejected as core replacement (per-search IDF failure).
  M9 confirms that even IDF-free frequency signals add nothing measurable here.
- **ADR 0008:** normalization alternatives rejected. M9 stays entirely inside
  the relevance signal, per M8's closing recommendation.
- **M7/ADR 0008:** phrase bonus not retried.

## 8. Artifacts

- Diagnostic tool (kept): `eval/relevance_diagnostic.py` +
  `eval/reports/relevance_diagnostic.md` (deterministic; scenarios A–E +
  corpus-wide tie analysis).
- Evaluation harness restored to pristine C4 candidate set after the
  experiment.
