# ADR 0012 — Semantic relevance production architecture

**Status:** Accepted (2026-08-23) — architecture decision; implementation not yet approved
**Context:** M10 (ADR 0011) proved SEM1 (semantic blend into C4's relevance
axis) improves ranking quality (nDCG@10 +0.0234, MRR +0.0125, zero regressions,
probes 9/9, 63/63 lexical-collapsed groups separated). Open question: how to
obtain embeddings in production without breaking SignalPulse's latency, memory,
reliability, cost, or privacy characteristics on the Render free tier.

## 1. Production constraints (fixed)

- Render free web service: **512 MB RAM / shared 0.1-0.5 CPU**
- Search budget (M3.5): completed ≤ 5 s; background job already performs
  fan-out + dedup + ranking in-process
- PyTorch + MiniLM: model ~90 MB, runtime RAM ~300-500 MB → **does not fit**
- Failure rule: any semantic problem must degrade to plain C4, never fail a
  search (same discipline as M3.5 source timeouts)

## 2. Architecture options

### Option A — ONNX int8 local inference — MEASURED ✅

`all-MiniLM-L6-v2` exported to ONNX, dynamic-int8 quantized
(`Xenova/all-MiniLM-L6-v2::onnx/model_quantized.onnx`, Apache-2.0). Runtime:
`onnxruntime` CPU, **no PyTorch dependency**. Tokenizer: `tokenizers` JSON
(~0.7 MB). Mean pooling + L2 norm replicated exactly (matches M10 reference).

Measured on dev hardware, single-threaded (Render allocates ≤1 core):

| Metric | Value |
|---|---|
| Model size | **21.9 MB** |
| Cold session load | **0.16 s** |
| Session RSS delta | **34 MB** |
| Warm single-query encode | **2 ms** median |
| Realistic search (~23 docs batched) | **97 ms** median |
| Full-corpus encode (350 docs + 16 q) | 2.27 s |
| Cosine agreement vs PyTorch fp32 | avg 0.9904, min 0.9797 (365 texts) |

Quality through the full frozen-corpus gate with **int8 vectors driving SEM1**:

| Metric | C4 | SEM1-on-int8 |
|---|---|---|
| nDCG@10 | 0.7850 | **0.8065** |
| P@10 | 0.8688 | **0.8750** |
| MRR | 0.8750 | **0.9062** |
| Probes | 9/9 | **ALL PASS** |

Fallback: `semantics=None` ⇒ byte-identical C4 ordering (**MEASURED True**).
Determinism: fixed weights + CPU EP ⇒ deterministic across runs ✓.

### Option B — external embedding API — ANALYSIS ONLY (UNKNOWN where marked)

No provider credentials exist in this environment; nothing was called.
Architecture: POST query+doc texts to an embeddings endpoint per search
(batched), receive vectors. Natural candidate: Gemini `text-embedding-004`
(PROJECT_SPEC already names Gemini for V3; free tier exists).

| Aspect | Assessment |
|---|---|
| Backend footprint | Minimal (HTTP client only) |
| Latency | **UNKNOWN without measurement** — adds network RTT to every search job |
| Cost | **ESTIMATED $0** at current scale (free tiers); rate limits apply |
| Privacy | Queries + result titles/descriptions transmitted to third party |
| Reliability | New external failure mode inside the search job; needs timeout+fallback |
| Vendor lock-in | Embedding space changes per model/version → cache invalidation |
| Determinism | Not guaranteed across provider model updates |

Verdict: viable but strictly worse than Option A on privacy/latency/
determinism for this workload; justified only if local RAM proves insufficient
(it does not — see §4).

### Option C — hybrid/optional semantic — SELECTED ARCHITECTURE

C4 remains authoritative. Semantic scoring becomes an **optional stage that can
fail independently**, exactly matching how M3.5 treats sources:

```
sources → dedup → [semantic stage: try embed(canonical texts)+query;
                   on ANY failure → sem=None] →
C4 score (rel' = blend when sem present else pure lexical)
       → rank_position → persistence
```

- Semantic unavailability degrades to today's C4 — **MEASURED identical
  output** (benchmark § Fallback).
- No new external dependency; no credentials; deterministic.
- Stage wrapped in its own try/except + timeout (mirrors `_run_source`
  pattern); a `semantic` block in `search.stats` records
  `{status: ok|unavailable|failed, ms}` for observability.

## 3. Placement (options 1-4)

| Placement | Verdict |
|---|---|
| 1. During source collection | Rejected: interleaves CPU inference with network I/O, embeds pre-dedup duplicates, spreads failure handling across adapters |
| **2. Post-collection, pre-ranking (inside existing background post-pass)** | **SELECTED**: dedup has collapsed duplicates (embed canonical texts once), all texts known, one batched call, direct feed into C4 relevance, isolated try/except, matches M10 evaluation exactly |
| 3. After C4 ranking | Rejected: reordering after rank_position assignment would need a second sort/persist pass; no benefit over 2 |
| 4. Separate optional ranking stage | Equivalent to 2 implemented as its own function; adopted as design framing |

## 4. Caching

- **Query embeddings**: in-process LRU keyed by normalized query string
  (`functools.lru_cache` on the encode wrapper), bounded (e.g., 256 entries).
  Repeat/near-repeat queries are common (history feature) — cheap win, no
  invalidation needed (deterministic model).
- **Document embeddings**: computed fresh per search from just-fetched content;
  content-hash cross-search caching rejected for now (adds storage/state for
  low hit-rate at current scale). Revisit if M11 telemetry shows repeat docs.

## 5. Integration formula

Exact validated SEM1 composition — no retuning:

```
rel'_i = 0.70 * rel_lexical_i + 0.30 * sem_minmax_i
score_i = w_type · rel'_i + w_fresh · freshness_i + w_qual · quality_i
```

`rel_lexical` remains min-max scaled per search (unchanged); `sem_minmax` is
cosine min-max scaled across the same candidate set; duplicate members inherit
the canonical member's blended relevance (unchanged inheritance rule).

## 6. Resource fit (Render free tier)

FastAPI baseline ~120 MB + onnxruntime session ~35 MB + transient batch buffers
~10 MB ≈ **165-200 MB peak** < 512 MB ✓. CPU: +97 ms single-thread per search
job (background task; user-perceived latency unchanged — job is async).
Cold start: session loads in 0.16 s at startup — negligible next to Render's
own cold-start behavior.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Inference hangs | Stage-level `asyncio.wait_for` timeout (pattern proven in M3.5) |
| Model file missing/corrupt at deploy | Startup guard: load once at lifespan; on failure set flag → permanent C4-only mode + stats marker |
| Quantization drift on future model swap | Pin model artifact version; regression harness reruns frozen-corpus gate |
| Concurrent searches | ORT sessions are thread-safe; batches serialize on GIL-free native code; measured 97 ms/batch leaves headroom |

## 8. Decision summary

| Criterion (1-10) | Option A | Option B | Option C-as-shape |
|---|---|---|---|
| Preserves C4 fallback | ✅ (measured) | ✅ by design | ✅ by design |
| Search reliability preserved | ✅ | ⚠ new external dependency | ✅ |
| Acceptable latency | ✅ +97 ms/job | ⚠ network RTT (UNKNOWN) | ✅ |
| Fits free tier | ✅ 34 MB session | ✅ | ✅ |
| Predictable cost | ✅ $0 | ⚠ ESTIMATED $0 free tier; UNKNOWN beyond | ✅ $0 |
| Quality preserved | ✅ MEASURED (nDCG +0.0215 w/ int8) | ✅ expected (=fp32) | depends on A/B |
| Cold start | ✅ 0.16 s | n/a | ✅ |
| Failure isolation | ✅ try/except+timeout | ⚠ needs same wrapping | ✅ |
| Testable | ✅ deterministic | ⚠ mock-required | ✅ |
| Maintainable | ✅ one small module | ⚠ vendor surface | ✅ |
| Privacy | ✅ data stays local | ❌ third-party transmission | ✅ |

**Selected: Option A runtime inside Option C hybrid shape.**

Production integration is **recommended** as the next implementation checkpoint
(M11.1): isolated semantic stage, exact SEM1 composition, graceful C4 fallback,
stats observability — gated by the same frozen-corpus quality suite plus new
failure-mode tests. This ADR approves the architecture; implementation still
requires explicit approval.
