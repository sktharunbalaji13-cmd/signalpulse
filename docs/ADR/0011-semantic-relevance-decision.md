# ADR 0011 — Semantic relevance: EXPERIMENTAL GO (not production)

**Status:** Accepted (2026-08-23)
**Context:** M10. After three documented lexical NO-GOs (ADR 0008 phrase bonus,
ADR 0009 normalization variants, ADR 0010 relevance-signal/tie-break), M9
established the remaining limitation precisely: 63/85 equal-raw tie groups
contain documents with differing gold labels, and available lexical signals
separate only 2/63 (~3%) of them. The open question: does semantic similarity
provide genuinely new ranking information C4 cannot obtain, at an operational
cost SignalPulse can support?

## 1. Architecture audit (M10.0)

| Question | Finding |
|---|---|
| Generation point | Evaluation-only now; production would embed at ingestion (docs) + search time (query) |
| Text sufficiency | title + description suffice (corpus items carry both; Guardian desc ≤500 chars) |
| Results per search | ~20-30 typical (3 sources × 10, cap 500) |
| Embedding workload | 1 query + N docs per search ≈ one batched inference call |
| Latency (measured, CPU) | model load 37 s cold incl. download / ~2-5 s warm-cache load; encode 3 texts 0.10 s → batch of ~23 ≈ 0.2-0.5 s |
| Memory (measured class) | torch + MiniLM ≈ 300-500 MB RAM — exceeds Render free tier (512 MB total) comfort |
| Render free viability | Local transformer: **no** (RAM). External API: viable (adds credential/privacy/latency). ONNX int8 quantized MiniLM (~30 MB, <100 MB RAM): plausible middle path, untested here |
| Determinism | Local fixed weights = deterministic ✓ (verified across runs) |

**Decision:** evaluate locally with `all-MiniLM-L6-v2` via sentence-transformers
in an isolated throwaway environment; cache embeddings as a versioned JSON
artifact so the ranking harness needs no ML dependency at runtime. Rejected:
vector DB / RAG / training / new ML platform (unnecessary for 16×23 candidates);
external API for the experiment (credential handling without evaluation need);
production wiring (out of scope).

## 2. Pre-registration (fixed before evaluation)

- Model: `sentence-transformers/all-MiniLM-L6-v2`, 384-dim, mean pooling,
  normalized embeddings.
- Query repr: normalized query string (`lower()` + whitespace collapsed).
- Document repr: `"{title}. {description}"`.
- Similarity: cosine.
- Score normalization: per-candidate-set min-max of cosine → [0, 1].
- Candidate **SEM1**: `rel' = 0.70·rel_lexical(min-max) + 0.30·sem_minmax`;
  freshness/quality weights, diversity pass, dedup, tie-break chain unchanged.
- Gate: probes 9/9 · nDCG@10 ≥ C4 · P@10 ≥ C4 · MRR ≥ C4−0.01 · fresh-junk
  ≤ C4+0.03 · improvement on more than one query.

No parameter was tuned after seeing results.

## 3. Measured result (frozen corpus v2, 16 queries)

| Metric | C4 | SEM1 | Δ |
|---|---|---|---|
| nDCG@10 | 0.7850 | **0.8084** | **+0.0234** |
| P@10 | 0.8688 | 0.8688 | 0 |
| MRR | 0.8750 | **0.8875** | +0.0125 |
| rel-0 top-10 | 1.3125 | 1.3125 | 0 |
| fresh-junk | 0.0625 | 0.0625 | 0 |
| Probes | 9/9 | 9/9 | — |

## 4. Collapsed-group semantic value test

The 63 label-split groups that M9 proved unrecoverable lexically:

- Semantically separable (distinct cosine within group): **63/63 (100%)**
- vs lexical best (2/63): semantic recovers information binary presence cannot.
- Pairwise ordering quality inside those groups: **274 correct / 90 incorrect**
  (75.3% pairwise precision against gold labels).

## 5. Decision

**EXPERIMENTAL GO.** Semantic similarity demonstrably carries new ranking
information: it separates 100% of the collapsed groups lexical signals could
not (vs ~3%), improves nDCG@10 by +0.0234 with zero regressions on P@10,
fresh-junk, or probes, and the mechanism is explainable (cosine similarity to
the query distinguishes topical relevance where term presence cannot).

**NOT approved for production yet.** Production adoption requires a separate
decision covering: embedding source (ONNX-quantized local vs external API),
RAM/latency budget on Render free tier, credential handling if external,
embedding staleness policy, and cost. Those belong to an M11 integration
checkpoint with its own gate.

## 6. Operational notes (for the future integration decision)

- Model size ~90 MB; runtime RAM ~300-500 MB (torch) — exceeds Render free tier
- ONNX int8 quantization ≈ 30 MB / <100 MB RAM — untested but plausible
- External API (e.g., Gemini text-embedding): free tier exists; adds network
  latency (~50-150 ms/batch) and credential requirements
- Per-search compute: single batched encode of query + ~20-30 cached doc
  vectors ≈ sub-second CPU

## 7. Relationship to prior decisions

- **ADR 0007:** BM25-with-IDF rejected; M10 uses no IDF and no per-search term
  statistics — different signal family, different failure surface.
- **ADR 0008:** phrase bonus rejected because additive bonuses rebalance axes;
  SEM1 also rebalances the relevance axis — but with *new* information rather
  than a reweighted old signal, which is why it passes where C5 failed.
- **ADR 0009:** normalization-only changes rejected; SEM1 keeps max-scaling and
  changes the signal content instead.
