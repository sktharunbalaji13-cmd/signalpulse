# ADR 0009 — C4 normalization investigation: NO-GO, retain min-max

**Status:** Accepted (2026-08-23)
**Context:** M7.2 showed that adding a relevance bonus (+2 phrase) made ranking worse
(ADR 0008). Hypothesis to investigate: is C4's relevance normalization the cause?

## 1. How C4 scoring actually works (audited)

Per search (`app/services/ranking.py`):

```
raw_i        = Σ over query terms (3·title_hit + 1·desc_hit)        # int, ≥0
norm_rel_i   = raw_i / max(raw)          if max>0 else 0            # ← L174 (max-scaling)
freshness_i  = news/social: 0.05+0.95·2^(−age/half_life); reference 0.5; missing 0.25
quality_i    = constants (Guardian .90 / Wikipedia .80 / Reddit .50 / unknown .50)
weights      = news,social (.55,.30,.15) · reference (.65,.10,.25)
score_i      = w_rel·rel + w_fresh·fresh + w_qual·quality
order        = score desc → type priority → published desc (None last) → URL
             → diversity pass reorders inside ±0.05 bands (type round-robin)
```

Duplicate members inherit the canonical member's components but keep their own
tie-break keys. Ranking runs before filters; filters are SQL views over
`rank_position`.

### Answers to the audit questions

1–3. Normalization happens at `ranking.py:174`, applies **only to the relevance
term-count score**, and is **per query / per search** — one global divisor across
all sources and types. Min is implicitly 0 (raw scores cannot be negative).
4. All-identical nonzero scores → every document gets rel = 1.0; all-zero
(`max_raw = 0`, no term matches anything) → guard sets rel = 0.0 for everyone and
ordering falls entirely to freshness/quality/tie-breaks.
5–6. One document defines the divisor. Adding/removing/changing the top-raw
document rescales **every other document simultaneously** (measured: Scenario B,
one outlier halved all other norm_rels; Scenario E, one +raw event moved the
previous leader from 1.0 → 0.667 without touching its content).
7. News weights make full-range relevance worth ±0.55, full-range freshness
±0.285, quality ≤ ±0.06. After an outlier halves relevance gaps (~0.14),
freshness differences dominate.
8. Yes. Uncompressed, strong-old beat weak-fresh by 0.273 (Scenario C). Apply
the Scenario-B-style halving and the same gap shrinks below typical
freshness advantages — the flip is reachable naturally whenever any source
returns one strongly-matching document.
9. Naturally, yes — it does not require the C5 perturbation; any query where one
source returns a high term-count match triggers global rescaling.
10. **The decisive finding:** normalization choice is not just about min-max —
*any* change to the relevance scale re-balances relevance against the fixed
freshness/quality axes. Even a purely affine divisor change altered metrics
(C4T below). The problem is the **relative weighting between normalized
components**, which every normalization strategy implicitly adjusts.

## 2. Diagnostic experiment

`eval/normalization_diagnostic.py` replicates the production arithmetic,
asserts its ordering matches production `rank_items` in every scenario, and
prints full component tables:

- **A** similar-relevance field: top-doc-defined scale visible (raw 6,6,6,2).
- **B** outlier enters: b1 rel 1.0→0.571, final 0.843→0.607 — whole-field
  recompression from one document.
- **C** strong-old vs weak-fresh uncompressed: strong wins by 0.273.
- **D** exact phrase vs scattered tokens with equal presence: identical
  components — C4 gives phrase adjacency zero weight (why C5 was tested).
- **E** one mid-document's raw jumps: previous leader demoted (final
  0.771→0.588) while its own raw was untouched; jumper overtakes (the exact
  C5 mechanism).

## 3. Normalization candidates (pre-registered shapes, no tuning)

Affine variants were initially predicted to be ranking-neutral; measurement
falsified that (see §1.10) — they rebalance relevance against the fixed axes.

| Candidate | Shape | nDCG@10 | P@10 | Fresh-junk | Probes | Verdict |
|---|---|---|---|---|---|---|
| **C4 (incumbent)** | max-scale | **0.7850** | **0.8688** | **0.0625** | 9/9 | baseline |
| M8_C4T_affine_theoretical | raw ÷ (4·terms) | 0.7862 (+0.0012) | 0.8625 (−0.0063) ✗ | 0.3125 (5×) ✗ | 9/9 | REJECT |
| M8_N1_rank_norm | uniform rank spacing | 0.7926 (+0.0076) ✓ | 0.8375 (−0.0313) ✗ | 0.0000 ✓ | 9/9 | REJECT |
| M8_N2_sigmoid_norm | σ(x)=1/(1+e^(−10(x−0.5))) | 0.7307 (✗) | 0.8313 (✗) | 0.1875 ✗ | **8/9 (P7 fail)** | REJECT |

MRR moved within noise (±0.01) and did not affect any verdict.

## 4. Decision

**NO-GO — retain C4 min-max unchanged.**

- Every candidate violates the adoption gate: C4T regresses P@10 and quintuples
  fresh-junk; N1 trades its nDCG gain for a large P@10 regression; N2 fails the
  P7 duplicate-inheritance probe outright and regresses everything else.
- Mechanism (now measured, not assumed): relevance normalization sets the size
  of the relevance axis relative to freshness/quality. Any reshaping moves
  failures around rather than removing them — C4's current balance is the
  best-measured point among the shapes tested.

## 5. Rejected alternatives / follow-ups

- Sigmoid steepness/midpoint tuning: rejected as benchmark tuning (§ no metric
  gaming).
- Per-source-type normalization: would fragment the shared relevance axis and
  break cross-type comparability the diversity band depends on; not tested.
- Re-testing after corpus growth: legitimate future work; corpus v2 remains
  frozen for this milestone.

## 6. Artifacts

- Diagnostic tool (kept): `eval/normalization_diagnostic.py` +
  `eval/reports/normalization_diagnostic.md` (deterministic, evaluation-only).
- Evaluation harness restored to the pristine C4 candidate set after the
  experiment (same policy as ADR 0008).
