# M3 — Retrieval Intelligence: Design

**Status:** Approved baseline (2026-08-20). Authoritative M3 design; supersedes the prose in `PROJECT_SPEC.md` §17–§20 where they conflict (they do not — this document adds precision).
**Implementation note (M16.1):** M3 shipped in full. Statements below that components are "not implemented yet" were true at design time and describe the pre-M3 baseline only — the freshness scorer, combined ranker, and filter layer are production today.
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

## 6. M3-E — Filters & result controls (query-time views, no pipeline change)

### 6.0 Core principle: filters are a VIEW over the frozen ranked set

The M3-D C4 total order (persisted `rank_position` at search completion) is the
single source of truth. Every M3-E filter is a **query-time predicate over
stored rows** — it selects a subset of that total order and serves it with the
same ordering keys. Nothing is re-ranked, re-normalised, or re-diversified at
request time; no row is written. This guarantees by construction:

- filtered results remain correctly ranked (a subset of a total order is a
  total order; scores and `rank_components` are bit-identical to the frozen
  model);
- ranking semantics never change silently (no per-filter re-normalisation of
  relevance, no re-run of the diversity pass);
- provenance is never mutated (filters are read-only SELECTs);
- determinism (same search + same params → same rows, same order, forever);
- no filter can cause an indefinite search (no retrieval is ever triggered);
- partial/failed searches degrade identically (the view reads whatever rows
  exist; `search.status` is untouched);
- one indexed query, cheap enough for a public browser client.

### 6.1 API surface (zero schema change)

On `GET /api/v1/searches/{id}/results` (query params only):

| Param | Values | Semantics |
|---|---|---|
| `page` | int ≥ 1 (default 1) | 1-indexed page over the **filtered** view |
| `per_page` | int 1..100 (default 20) | page size; capped, never unbounded |
| `source_type` | `news` / `social` / `reference`, repeatable (OR) | vertical filter; default all |
| `time` | `24h` / `7d` / `30d` / `all` (default `all`) | hard age window on `published_at` |
| `duplicates` | `all` / `canonical` (default `all`) | `canonical` hides `is_duplicate` members |
| `language` | `[a-z]{2,3}` code (default none) | exact match on the stored `language` column |

Ordering is unchanged (M3-D): `rank_position` asc NULLS LAST, then the
fallback tie-break (type priority → `published_at` desc NULLS LAST → URL).
`total` = filtered row count; a page beyond the range returns an empty
`items` list with HTTP 200 (not an error).

Semantic rules:

- **`source_type`** — simple membership predicate. Filters that remove every
  canonical member of a group do not cascade: remaining members are still
  valid rows (they carry the group's inherited score) and keep their
  `duplicate_group_id`.
- **`time`** — hard cut on `published_at` age measured from the **search
  completion instant** (`search.completed_at`; falls back to `created_at`
  while running), so a given search + params is deterministic forever
  (shareable URLs, stable pagination). Applied to **news/social only**;
  reference rows are always included (timeless context, M3-C design). Rows
  with NULL `published_at` are excluded by any `time` filter except `all`.
  There is deliberately **no hard freshness-score filter**: freshness is a
  soft weighted ranking signal (M3-C); a hard score filter would fight the
  frozen weights. The time window is the user's control.
- **`duplicates=canonical`** — the view skips `is_duplicate` members.
  `duplicate_group_id` stays exposed; group metadata (`member_count`,
  `duplicate_evidence`) describes the full group and is **not** reduced by
  the view.
- **`language`** — exact match on the stored `language` column. Rows with
  NULL `language` are excluded while a language filter is active (a hard
  filter is honest: we cannot prove they match). Coverage is measured
  (§6.3) because current source metadata only carries language for
  Guardian/Wikipedia/GDELT — a `language=en` filter excludes the social
  vertical entirely today.
- **Invalid values are rejected with HTTP 422** (enum/pattern validation) —
  never silently ignored, never partially applied. `page=0`, `per_page>100`,
  unknown `source_type`, unknown `time`, unknown `duplicates`, malformed
  `language` all fail explicitly.
- **Interaction with ranking**: filters never recompute scores. The earlier
  §6 sketch's `source=` (per-outlet) param is dropped from scope: verticals
  are the user-facing controls, and a per-outlet filter is a trivial
  extension of the same predicate family (deferred).

### 6.2 M3-E experiment — filter semantics, behavioural acceptance tests first

The filter layer is **not implemented yet**. `eval/filter_eval.py` defines
behavioural acceptance probes BEFORE any corpus measurement (same discipline
as §5.1), runs them against the designed view semantics, then measures the
filter configs on the frozen corpus ranked by the accepted C4 model. The
probes encode "what correct filtering means":

| # | Behaviour | Controlled probe |
|---|---|---|
| P1 | Filtered subset stays correctly ranked: order == projection of the full C4 order, scores unchanged | filter over C4-ranked synthetic items → same relative order + identical scores |
| P2 | `source_type` restricts to the requested verticals (OR for repeats); empty result → empty list, not error | news-only view excludes social/reference; news+social OR |
| P3 | `time` window: news/social only, reference always included, NULL `published_at` excluded except `all` | 24h view: news at 4h in, news at 7d out, reference without ts in, news without ts out |
| P4 | `time` never reorders within the kept set | kept ids identical before/after window filter |
| P5 | `duplicates=canonical` hides members, keeps canonicals, total order intact, group ids intact | pair + lone item → view shows canonical + lone, member hidden |
| P6 | Type filter removing a canonical keeps remaining members (no dangling rows); group info preserved | canonical=news filtered out by social-only → social member still present with group id |
| P7 | Invalid filters fail explicitly (422-class): every invalid value rejected, nothing silently ignored | each invalid param value → rejection |
| P8 | Deterministic + deterministic pagination: repeated calls identical; total = filtered count; pages non-overlapping; beyond-range page → empty | two applications equal; page math over a filtered view |
| P9 | Partial/failed sources degrade gracefully: filters work identically over partial results; no retrieval is ever triggered | view over a subset of rows behaves identically; filter function performs no I/O |
| P10 | Provenance invariant: any filter leaves stored rows bit-identical (rank/dedup/raw columns untouched) | input rows deep-compared before/after every filter application |
| P11 | `language` matches exactly; NULL-language rows excluded when active; invalid code rejected | en filter keeps only `language == "en"` rows; NULL excluded |

Candidates measured (configs of the designed view, not fitted): **F0**
default (no filters, control = C4 order); **F1** news-only; **F2**
social-only; **F3** reference-only; **F4** `time=24h`; **F5** `time=7d`;
**F6** `time=30d`; **F7** `duplicates=canonical`; **F8** news + `time=7d`;
**F9** news+social + `time=24h` (the "today" view); **F10** `language=en`
(coverage-only: the corpus has no language field, so coverage is mapped from
real source metadata — Guardian/Wikipedia `en`, Reddit NULL — and reported
honestly as metadata coverage, not relevance quality).

Report (`eval/reports/filter_eval.md`) decides which filter set is
admissible for implementation. Decision gate: all 11 probes must pass, the
report must be byte-deterministic, and corpus measurement must be read with
the coverage numbers (nDCG@10 on a filtered view is computed against the
full-query ideal, so narrow filters score low even when every kept item is
relevant — coverage explains the gap).

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
- **M3-D** (CLOSED): C4 accepted as the production model; `app/services/ranking.py` implements it unchanged (validated weights, diversity pass, deterministic total order, duplicate awareness); pipeline persists `rank_score`/`rank_components`/`rank_position` at completion; results endpoint serves rank order; all 9 behavioural probes pass through the production ranker and the production ranker reproduces C4's corpus behaviour bit-for-bit. BM25 is NOT used (ADR 0007).
- **M3-E** (CLOSED): query-time filter view on `GET /searches/{id}/results` — `source_type` (repeatable), `time=24h|7d|30d|all`, `duplicates=all|canonical`, `language` (exact match, `[a-z]{2,3}`), over the frozen `rank_position` order with `page`/`per_page` on the filtered view. Time cutoff anchored to `search.completed_at` (permanent view); reference always included in time views; news/social with NULL `published_at` excluded except `all`; invalid values → explicit 422; read-only projection (no re-ranking, no writes, no retrieval). All 11 behavioural probes pass as production API acceptance tests (`tests/test_search_filters.py`).
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

## 15. M3.5 — Public reliability & performance (measurement first)

### 15.0 Product requirement and locked priorities

A normal person opens the website, searches, and gets useful information without
unnecessary delay. Priority is locked: **Reliability → Speed → Source quality →
Provenance → Intelligence → AI** (PROJECT_SPEC §6A). M0–M3 is frozen and
complete: M3.5 changes **no** retrieval / dedup / freshness / C4 ranking / M3-E
filter semantics — it adds reliability + performance infrastructure only.

### 15.1 Locked targets (the measurement bar)

| Metric | Target |
|---|---|
| Search submission (POST accepted) | < 500 ms |
| First useful results | ≤ 3 s |
| Completed search | ≤ 5 s |
| Upstream source timeout | ~5 s |
| Indefinite searches | never (every search terminates) |

### 15.2 Current baseline (measured, no behavior change)

`eval/performance_eval.py` measures the **current** pipeline against the bar
without touching production behavior. Structural findings:

1. **Submission is cheap** (DB insert + 202) — well under 500 ms (P1).
2. **Happy path has huge headroom**: concurrent fan-out persists each source's
   results as it completes, so first useful results appear well before
   completion (P2).
3. **Slow-source isolation works today** (per-source sessions + `asyncio.gather`
   with `return_exceptions`): one slow/failing source does not delay the
   others beyond its own budget; partial results are served (P3/P5).
4. **Timeout path exists per adapter** (httpx `timeout=...` → `SourceError(timeout)`
   recorded) but is enforced **inside each adapter only**. The pipeline has
   **no `asyncio.wait_for` per source**: a source that hangs without raising
   would block the whole job — the "no indefinite search" guarantee currently
   rests entirely on every adapter obeying its httpx timeout (P7 shows the
   gap; the probes can only prove sources that *raise* are isolated).
5. **Worst-case completion is tight**: with all sources at the ~5 s timeout,
   `completed_at ≈ slowest source (5 s) + post-pass` (dedup O(n²) + ranking) —
   right at the ≤5 s boundary. The post-pass budget must be measured and kept
   small (P-post).
6. **No rate limiting, no caching, no per-request latency metrics** (only
   structured logs + `search.duration_ms`).
7. **Progressive delivery is structurally possible**: rows persist incrementally
   and the results endpoint serves whatever exists regardless of status
   (fallback ordering while unranked). No UI yet.
8. **Credentials are backend-only** (verified, P11); CORS is origin-restricted.
9. **SQLite is single-writer** — concurrent search writes may contend (P9).

### 15.3 Design decisions (M3.5 implementation checkpoint)

Status: **1, 2, 6 IMPLEMENTED; 4, 5 DEFERRED to M4 (evidence-driven); 3 structural
(UI deferred); 7 measured.**

1. **Pipeline-level per-source timeout** — **IMPLEMENTED** (`search_pipeline._run_source_with_timeout`):
   each source unit (fetch + persist) is wrapped in `asyncio.wait_for(task,
   settings.source_timeout_seconds)` (default 4.5 s) as defense in depth on top of
   per-adapter httpx timeouts. A hung adapter is cancelled and recorded as a
   `timeout` `SourceEvent`; isolation and partial-result behaviour are preserved.
   This makes **no indefinite search** a hard guarantee regardless of adapter
   behaviour (regression tests `tests/test_source_timeout.py`).
2. **Timeout budget alignment** — **IMPLEMENTED + MEASURED**: per-stage timings
   (`sources_ms`, `postpass_ms`, `total_ms`) are recorded in `search.stats`
   (design §15.3.6). Measured on ~90 rows the post-pass is ~50 ms and worst-case
   `completed ≈ source_timeout + post-pass + margin` (P12/P13), so the 4.5 s
   pipeline timeout keeps worst-case well within the locked ≤ 5 s target.
3. **Progressive delivery** — structurally available today (rows persist per
   source; the results endpoint serves them regardless of status, fallback order
   while unranked). Surfacing a `status`/`done` marker and the browser UX are
   deferred to the UI / M4.
4. **Rate limiting / abuse protection** — **DEFERRED to M4**. No public traffic
   yet to justify limits or calibrate burst values; the endpoint already validates
   query/page bounds and keeps credentials backend-only. Revisit at M4 with real
   traffic (token bucket on `POST /searches` + global in-flight cap → 429).
5. **Caching strategy** — **DEFERRED to M4 (evidence-driven)**. Determinism
   (P8) proves identical repeat queries are cacheable, but with no public load
   there is no evidence caching materially improves UX or protects upstream
   APIs; the complexity (TTL, provenance-preserving invalidation) is not yet
   justified. When introduced (M4), cache only completed results keyed by
   `normalized_query + window_hours + M3-E filter params`, never partial/in-progress.
6. **Observability / latency metrics** — **IMPLEMENTED**: per-stage timings in
   `search.stats.timing_ms` plus the existing structured `log_event` source
   events; exposes the budget data and feeds the M4 monitoring story.
7. **Load behaviour** — measured (P9: 4 concurrent searches correct and bounded on
   SQLite). If M4 hosting shows write contention, serialize writes / queue (design only).

### 15.4 M3.5 acceptance criteria (the bar the implementation must meet)

Status: **A–E, H, I, J MET**; **F, G deferred to M4**.

| # | Criterion | Status |
|---|---|---|
| A | Every search terminates (pipeline-level timeout present and tested); no indefinite search. | ✅ MET (`test_source_timeout.py`) |
| B | Submission < 500 ms. | ✅ MET (P1: ~6 ms) |
| C | Happy-path first useful results ≤ 3 s and completed ≤ 5 s. | ✅ MET (P2) |
| D | Slow-source isolation: one slow/failing source does not delay others beyond its own budget; partial results served. | ✅ MET (P3/P4/P5) |
| E | All-sources-down → clear failed state, zero results, no broken page. | ✅ MET (P6) |
| F | Rate limiting present and tested (burst → 429). | ⏸ DEFERRED to M4 |
| G | Caching (if implemented) correct: only completed results, provenance-preserving, TTL-bound. | ⏸ DEFERRED to M4 |
| H | Concurrent load: N simultaneous searches correct, bounded duration, no DB errors. | ✅ MET (P9) |
| I | Credentials never exposed to the browser. | ✅ MET (P11) |
| J | M0–M3 semantics unchanged: retrieval/dedup/ranking/filter bit-identical (existing suites stay green). | ✅ MET |
