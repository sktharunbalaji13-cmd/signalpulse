# M3 — Retrieval Intelligence: Design

**Status:** Approved baseline (2026-08-20). Authoritative M3 design; supersedes the prose in `PROJECT_SPEC.md` §17–§20 where they conflict (they do not — this document adds precision).
**Scope:** M3-A (dedup), M3-B (relevance), M3-C (freshness), M3-D (ranking), M3-E (filters), plus the M3-A0 evaluation harness.
**Contract:** Must not violate `PROJECT_SPEC.md` v0.3 §6A (public reliability & performance). Priority order is locked: Reliability → Speed → Source quality → Provenance → Intelligence → AI.

---

## 1. M3 architecture

```
Sources (concurrent fan-out — unchanged)
   → SourceResult (canonical model — unchanged)
   → persist (unchanged; dedupe_key / rank_score stay NULL here)
   → POST-PASS (new, at the end of run_search_job after asyncio.gather):
        load all results for search_id (one local query)
        → sort by stable key (source_name, url)        [determinism guard]
        → dedupe   (M3-A)  → duplicate_groups + canonical set
        → rank     (M3-B + C + D) → rank_score + rank_components
        → persist updates (one transaction)
        → search.stats gains a dedupe/rank summary
   → status completed / partial / failed (unchanged)
```

Invariants:
- **One new local pass.** Zero network, zero LLM, zero new external calls. Time-to-first-results is unchanged (first results render when the first source completes; the post-pass adds ~tens of ms).
- **Determinism is a hard requirement.** Concurrent fan-out makes arrival order vary run-to-run. Every algorithm consumes results sorted by `(source_name, url)` first, and all tie-breaks are total and documented. Same search → same output, always.
- **Provenance invariant.** Dedup/rank only *annotate* rows. Nothing is deleted; every member, URL, timestamp, and `raw` payload survives.
- **Bounded workload.** ≤ ~30 results/search at `limit=10`/source. Hard guard: truncate to 500 before dedup (with a log line).

## 2. M3-A — Deduplication

### Algorithm comparison (evaluated, not assumed)

| Approach | Catches | Problems | Verdict |
|---|---|---|---|
| URL-only exact | exact dupes | misses cross-outlet wire stories, mobile/AMP variants | ❌ alone |
| Canonical URL + title equality | + cross-outlet same headline | misses paraphrased titles | ❌ alone |
| Fuzzy title (RapidFuzz `token_set_ratio`) | + rephrased titles | false merges on generic titles; threshold tuning | ✅ core |
| SimHash / MinHash | near-dup at scale | opaque, needs corpus stats, overkill at ~30 docs | ❌ M3 (V2 option) |
| Embedding similarity | semantic dupes | violates "no AI"; opaque, non-deterministic, infra | ❌ |
| **URL-canonical → title-exact → title-fuzzy, layered + guards** | all required cases | none fatal (guards below) | ✅ |

### Pipeline (three stages, each explainable)

**Stage 0 — Canonical URL** (`services/canonicalize.py`): lowercase scheme+host; strip fragment, default ports, tracking params (`utm_*`, `fbclid`, `gclid`, `ref`, `source`, `spm`, `mtm_*`), empty params, trailing slash on path (host-specific exceptions). Host-specific rules: YouTube keep only `v`; Reddit keep `t3_` post-id shape; Guardian strip `?page=all`. Output `canonical_url`; `dedupe_key = sha256(canonical_url)` (the schema already expects exactly this).

**Stage 1 — Normalized title equality**: lowercase, NFKC, strip punctuation, collapse whitespace, strip trailing publisher boilerplate (` - The Guardian`, ` | BBC`, `— Publisher`). Equal normalized titles **and same `source_type`** (or the Level-C link rule) → merge.

**Stage 2 — Fuzzy title similarity** (only on items not merged in stages 0–1): settle the metric on the eval corpus — compare `token_set_ratio` vs `token_sort_ratio` vs `partial_ratio` vs char-trigram Jaccard — choose best dedup F1 on gold pairs. Expectation: `token_set_ratio ≥ 0.90`; threshold fixed in config after calibration (documented, never silently re-tuned).

### Merge levels (the anti-false-merge guard)

| Level | Rule | Result |
|---|---|---|
| **A — same page** | canonical URL equal | merge, any types |
| **B — same story** | title equality/fuzzy + same `source_type` | merge (wire story; repost) |
| **C — linked discussion** | news item + social **link post** whose target URL canonicalizes to the news URL | merge; social member keeps its own permalink |
| **D — unlinked discussion** | social title contains news title but no link, or cross-type without link | **NOT merged in M3**; note recorded for V2 story-linking |

Additional guards: reference (`Wikipedia`) never merges with news/social except Level A; fuzzy merge requires `token_set_ratio ≥ 0.90` **and** (when both timestamps known) publication gap ≤ 7 days (evergreen re-publication tolerated; the gap is evidence, not a veto). Exact-title merges ignore time.

**Canonical member selection**: prefer `published_at` known > source-type priority (news > social > reference) > longer description > lexicographic URL. Deterministic.

**Explainability**: `duplicate_groups.duplicate_evidence` JSON: `{method, score, matched_pairs, time_gap_days}`.

## 3. M3-B — Relevance

| Approach | Pros | Cons |
|---|---|---|
| Weighted lexical (hand weights) | transparent | no IDF, no saturation, no length normalization |
| TF-IDF | dampens common words | needs a corpus; per-search IDF over ~30 docs is unstable |
| **BM25** | principled: TF saturation (k1), length normalization (b), IDF; deterministic; explainable | per-search IDF noise at n≈30 (mitigated by smoothing) |

**Recommendation: BM25 as the text core, with hand-set exact-match bonuses.**
- Implement BM25 ourselves (~50 lines, `services/ranker.py`): k1 = 1.5, b = 0.75, smoothed IDF `ln(1 + (N−n+0.5)/(n+0.5))`, collection = the search's own result set. Deterministic; avoids a new dependency; stronger portfolio signal than `pip install rank-bm25`.
- Field weighting: `bm25_score = 2·bm25_title + 1·bm25_description`.
- Exact-match bonuses (stored in `rank_components`): exact phrase in title +1.0; whole query substring in title +0.75, in description +0.35; all query terms in title +0.5.
- Normalize to [0,1]: `relevance = min(1.0, score / score(query-as-document))` (self-match is the ceiling).
- Stopwords: minimal list only. No LLM, no embeddings.

> **Superseded (M3-B, ADR 0007):** measured against the unchanged v2 corpus,
> BM25 as the text core was a NO-GO. Per-search IDF at n≈23 topic-dense
> candidates down-weights the central query terms and promotes rare-term
> decoys: core nDCG@10 0.5674 vs baseline 0.6909; best variant (title-only)
> 0.6263. The BM25 implementation survives as an experimental research
> artifact only, explicitly not production ranking. The transparent lexical
> baseline becomes the production relevance core, evolved carefully with each
> improvement measured on the same corpus.

## 4. M3-C — Freshness (per source type, honest timestamps)

Rules (non-negotiable):
1. Never fabricate: freshness is computed only from `published_at` when the source provided it. Index-time fields (`seendate`, first-seen) are provenance, never freshness. GDELT stays `published_at=None`.
2. `retrieved_at` is **not** a freshness signal.
3. `published_at > now` → clamp age = 0.

| Case | Freshness component |
|---|---|
| News with `published_at` | `0.05 + 0.95·2^(−age_hours/24)` (24 h half-life, 0.05 floor) |
| Social with `published_at` | same curve, **12 h** half-life |
| Reference (Wikipedia) | **constant 0.5** |
| News/social missing `published_at` | **0.25** (poor, not zero; UI shows "no timestamp") |

### 4.1 M3-C experiment — candidate functions, design + independent measurement only

The production freshness scorer is **not implemented yet**. Before choosing a
function, candidates are measured independently in `eval/freshness_eval.py` —
no clock, no randomness, fixed "now" = corpus `RETRIEVED`; nothing combined
with relevance; nothing wired:

- **Admissibility gate:** every candidate must pass `metrics.check_freshness`
  (missing handled, `retrieved_at` never substitutes for `published_at`,
  monotonic with age, future timestamps clamped).
- **Corpus behaviour:** per-source-type score distributions on the unchanged v2
  corpus, effective separation between freshest and oldest items, and the two
  tensions: very-recent-but-weakly-relevant items (rel-0 "Update" decoys, which
  are the freshest items) and older-but-relevant items.
- **Controlled probes at fixed timestamps:** decay curves over 0 h … 2 y,
  future clamp, old authoritative reference material (2-year-old timestamp
  still constant), missing timestamps, `retrieved_at` invariance. The corpus
  timestamps span only ~6 days, so long-age behaviour is measured by probes,
  not by corpus items — **no corpus change**.
- **Interaction with relevance (analysis only, no combination):** Spearman
  correlation between candidate freshness and gold relevance, overall and per
  source type. Freshness must not encode relevance; where tension exists
  (e.g. the decoys), M3-D combination will have to handle it explicitly.
- **Candidates** (full list in `eval/freshness_eval.py`): the §4 curve itself,
  a no-freshness control, decay shape (exponential / linear-30d / step),
  half-life choices (6 h / 12 h / 24 h / 48 h / 7 d), floor choices
  (0.0 / 0.05 / 0.25), reference level (0.5 / 0.9), missing-timestamp levels
  (0.0 / 0.25 / 0.5), and social half-life alternatives (12 h / 24 h).

The report (`eval/reports/freshness_eval.md`) is the input to the M3-C
accept/reject decision on which function, if any, behaves sensibly by itself.

## 5. M3-D — Final ranking

```
final = w_rel·relevance + w_fresh·freshness + w_qual·source_quality   [+ diversity pass]
```

| Type | w_rel | w_fresh | w_qual |
|---|---|---|---|
| news | 0.55 | 0.30 | 0.15 |
| social | 0.55 | 0.30 | 0.15 |
| reference | 0.65 | 0.10 | 0.25 |

- Source quality = fixed, documented constants: Guardian 0.90, Wikipedia 0.80, Reddit 0.50. Merged groups inherit the canonical member's quality.
- Dedup runs **before** ranking; only canonical members are scored; members inherit the group's score.
- Diversity: within a score band of ±0.05, alternate source types; deterministic, toggleable, measured on the eval set.
- Total tie-break (arrival-order-proof): score desc → source-type priority → `published_at` desc (else `retrieved_at` desc) → URL lexicographic.
- All weights in config; every component stored in `rank_components`.

### 5.1 M3-D experiment — combination formula, behavioural acceptance tests first

The combined ranker is **not implemented yet**. Components are fixed and
validated: lexical relevance (the production core after ADR 0007, min-max
normalised per search to [0, 1]), the M3-C freshness scorer (bit-identical to
the accepted model), fixed source-quality constants, and the diversity pass.
**No BM25, no tuning against the corpus until the acceptance tests are
defined and met** — `eval/ranking_eval.py` measures candidates on controlled
probes first, then reports corpus metrics as secondary evidence.

Behavioural acceptance tests (defined BEFORE any corpus measurement):

| # | Behaviour | Controlled probe |
|---|---|---|
| P1 | Fresh irrelevant must not outrank older relevant (the "Update 4 h ago vs highly relevant yesterday" case) | A: relevant, 24 h old · B: "Update", 4 h old → A first |
| P2 | Relevance dominates even at the freshness floor | A: relevant, 30 d old · B: "Update", 4 h old → A first |
| P3 | Higher source quality wins at equal relevance + freshness | Guardian vs Reddit, same age/score → Guardian first |
| P4 | Reference timelessness: authoritative reference beats fresh partial news; reference never dominates on weight alone | A: reference, rel-1.0, no ts · B: news rel-0.5, 4 h → A first; weak reference < relevant news |
| P5 | Missing timestamp is neutral, not lethal | A: relevant, no ts · B: "Update", 4 h → A first |
| P6 | Deterministic total order: identical scores → type priority → `published_at` desc (None last) → URL | exact tie cases; order identical across runs |
| P7 | Duplicates: members inherit the canonical score; no double-counting | identical pair: equal scores, unchanged neighbours |
| P8 | Diversity: within ±0.05 band source types alternate; toggleable | same-band news+social: alternation differs from plain order |
| P9 | Freshness advantage: fresher relevant beats older relevant at equal relevance/quality | A: relevant 4 h · B: relevant 30 d → A first |

Candidates (principled, documented — not fitted to the corpus): **C0**
relevance only (control); **C1** the §5 weights (news/social 0.55/0.30/0.15,
reference 0.65/0.10/0.25); **C2** balanced (0.50/0.30/0.20); **C3**
relevance-heavy (0.70/0.20/0.10); **C4** = C1 + diversity pass.

Source quality for the eval corpus: Guardian 0.90, Wikipedia 0.80, Reddit
0.50 (design §5); the fictional "Global Wire" outlet gets a documented 0.85
placeholder pending a real second news source; unknown sources default to
0.50. Weights are not changed during the experiment; the report
(`eval/reports/ranking_eval.md`) decides whether a candidate is good enough
to implement.

## 6. M3-E — Filters (API only, no UI yet)

On `GET /api/v1/searches/{id}/results` (query params, repo layer, zero schema change):
- `source_type=news|social|reference` (repeatable)
- `source=guardian|reddit|wikipedia`
- `time=24h|7d|30d|all` — hard filter on `published_at`, applied to **news/social only**; reference always included (timeless context). Items lacking `published_at` are excluded from `time` filters except `all`.
- Defaults: all types, all sources, all time.

## 7. Provenance rules

- Every result retains original source, source URL, source timestamps, `retrieved_at`, and `raw` payload (§16).
- Dedup/rank never destroy attribution; contributing sources are preserved in `duplicate_groups` (canonical member + member URLs), rendered as "Also reported by: X, Y, Z".

## 8. Performance constraints

- Retrieval stays concurrent; source failures stay isolated (unchanged pipeline).
- Ranking is local, on already-retrieved results; no new network, no LLM, no external ranking.
- O(n²) dedup on ≤ ~90 items (RapidFuzz C-backed, ms); BM25 on token lists trivial. Hard cap 500 with logged truncation.

## 9. Database changes

- Activate dormant columns: `dedupe_key`, `rank_score`, `rank_components`, `duplicate_group_id`, `is_duplicate`.
- `dedupe_key` is **not** a uniqueness constraint (the original `UNIQUE (search_id, dedupe_key)` was removed, ADR 0006). It identifies a canonicalized URL for deduplication; multiple result rows within the same search may legitimately share a key because duplicates are annotated rather than deleted. Uniqueness of the representative is preserved by the detector: each `DuplicateGroup` has exactly one canonical member.
- New table `duplicate_groups` (justified: it is the provenance container preserving contributing sources; JSON-on-row would be denormalized and have no FK): `id`, `search_id` FK, `canonical_result_id` FK→results, `member_count`, `duplicate_evidence` JSON, `created_at`.
- Index `(search_id, rank_score)` on results. No Alembic until M4; dev schema via `create_all`.

## 10. Evaluation methodology (M3-A0)

- **Offline, deterministic corpus** in `eval/` (~15 queries, ~20 fixed items each, authored in Python and validated against a Pydantic schema). Every item is synthetic and marked so; `.example` domains; no fabricated real-world events.
- **Gold labels**: relevance 0/1/2 per item (0 = irrelevant, 1 = partially relevant, 2 = highly relevant); gold duplicate groups with an `ambiguous` flag (ambiguous pairs are excluded from dedup scoring).
- **Metrics**: ranking — Precision@5, Precision@10, MRR, nDCG@10 (graded gain `2^rel − 1`, log2 discount); dedup — precision/recall/F1 over non-ambiguous gold pairs vs predicted pairs (predictions supplied by future M3-A); freshness — invariant checks (monotonicity, missing-timestamp, no retrieved substitution, future clamp, per-type).
- **Baseline**: a naive lexical term-count ordering (title ×3, description ×1, deterministic tie-break) — a reference to beat, **not** the production ranker.
- **Determinism**: `python -m eval` must produce identical output on repeated runs (no clock, no randomness, fixed timestamps).
- **Targets** (targets, not guarantees): dedup P/R ≥ 0.90, nDCG@10 ≥ 0.75. Reported only when actually measured.

## 11. Risks

| Risk | Mitigation |
|---|---|
| False merges (generic titles, same-headline-different-story) | type/link/time guards, conservative threshold, evidence stored, decoys in corpus |
| Overfitting thresholds to the eval set | fixed documented thresholds; holdout queries; tune once, report honestly |
| Per-search IDF noise at n≈30 | smoothed IDF; exact-match bonuses carry the load |
| Arrival-order nondeterminism | stable sort before every pass; total tie-break |
| Reddit title noise | suffix stripping; possibly higher social-social threshold |
| Wikipedia empty descriptions | field fallback (title-only scoring) |
| Reference items dominating recent queries | per-type weights (w_fresh 0.10) |

## 12. Acceptance criteria

- **M3-A**: `dedupe_key` set on every row; table-driven canonicalization passes; dedup P/R ≥ 0.90 (target, reported honestly) on offline eval; every group has evidence; zero rows deleted; determinism green; `duplicate_groups` table justified and created.
- **M3-B**: nDCG@10 ≥ 0.75 (target) on offline eval; `rank_components` populated and interpretable.
- **M3-C**: per-type curves unit-tested; no fabricated timestamps (property test); GDELT `seendate` remains untrusted.
- **M3-D**: shuffled-arrival determinism green; weights in config + components; diversity pass bounded and toggleable; existing tests green.
- **M3-E**: filter semantics per design on mocked data.
- **Global**: no new network calls, no LLM/RAG/agents/caching/Redis/Celery; ruff clean; CI green.

## 13. Dependency

- **`rapidfuzz`** is the single new runtime dependency, required by M3-A dedup. Added to `backend/pyproject.toml` runtime dependencies in M3-A0 (not yet imported; imported by M3-A). Hand-rolled BM25 (no `rank-bm25` dependency).

## 14. Implementation order

1. **M3-A0**: eval corpus + metrics harness + baseline (this document's harness).
2. **M3-A**: canonicalize → dedup → `duplicate_groups` + evidence.
3. **M3-B**: BM25 + bonuses + components.
4. **M3-C**: freshness per type.
5. **M3-D**: combine + weights + tie-break + diversity.
6. **M3-E**: filters (repo layer only).
7. Milestone report with real eval numbers.
