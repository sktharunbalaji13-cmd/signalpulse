# ADR 0018: arXiv as the first research source — new "research" source type

- **Status:** Accepted
- **Date:** 2026-08-24
- **Milestone:** M22.1
- **Related:** [ADR 0005](0005-gdelt-gate.md) (gate method), [ADR 0014](0014-hacker-news-source.md) (adapter pattern), M22.0 source-expansion audit

## Context

SignalPulse covered news (Guardian), reference (Wikipedia), and tech discussion
(Hacker News), but had no research-literature coverage. The M22.0 feasibility
audit classified arXiv **GO**: keyless public Atom export API (~1 request/3 s
courtesy budget; SignalPulse issues one request per search), rich metadata,
genuine publication timestamps.

Unlike Hacker News (ADR 0014), which reused the existing `"news"` type with
zero ranking-table changes, arXiv introduces a **new source type**
(`"research"`). Freshness explicitly rejects unknown types (`ValueError`) so a
new type cannot silently inherit another curve — every constant below is a
deliberate design decision.

## Decision

1. **Adapter** (`app/sources/arxiv.py`): keyless Atom export API,
   `search_query=all:{query}`, `sortBy=relevance`, `max_results` from the
   shared limit contract; requested time windows are pushed server-side via
   the `submittedDate` range operator (HN parity). XML parsed with the
   standard library; unmapped entry fields are serialized into `raw`
   (provenance rule). Errors map to the shared vocabulary
   (`timeout` / `rate_limited` / `failed`).
2. **Ranking constants** (design decisions, not corpus-fitted):
   - quality: `arXiv = 0.75` — moderated preprint repository: above anonymous
     social signals (0.50), below peer-reviewed/editorial sources;
   - weights: `research = (0.60, 0.20, 0.20)` — between news/social and
     reference: relevance dominates, freshness carries real weight (papers
     carry genuine dates; recency matters in fast-moving fields);
   - freshness half-life: **30 days** — literature decays far slower than news
     but is not timeless; fast-moving preprint fields are triaged monthly.
     Not corpus-validatable (the frozen corpus holds no research judgments);
     affects research rows only and is revisable by future experiments.
3. **Filters**: `"research"` added to the API allow-list and frontend filter
   bar; time-view semantics treat research rows like other dated types.
4. **Gate order preserved**: adapter offline-tested → ranking-corpus regression
   proven → live measurement → only then registered for production fan-out.

## Evaluation (live, 2026-08-24)

Six research-oriented queries through the real API:

| Metric | Result |
|---|---|
| Success rate | 6/6 |
| Latency | p50 **0.95 s**, max 1.89 s (budget 4.5 s per source) |
| Relevance | Strongly on-topic for domain queries (graph neural networks, RL robotics, diffusion surveys, LLM surveys); **weak for exact-title lookup** ("attention is all you need" returned tangential papers — a known `all:` field-search limitation) |
| Cross-source duplication | Exactly one title collision vs Wikipedia/HN across all queries ("Quantum Error Correction" ≡ Wikipedia article, similarity 1.00) — handled by the existing annotate-don't-delete title-normalization path |

**Ranking-regression gate:** the frozen corpus contains no research rows, and
all C4 table additions use explicit keys with unchanged fallbacks for existing
types; the full corpus-pinned suites pass bit-for-bit after the change
(backend 401 passed / eval 98 passed).

## Consequences

- Searches fan out to four enabled sources (+ Reddit dormant); wall-clock
  remains bounded by the per-source timeout.
- Research-oriented queries gain coverage no existing source provides; exact
  title lookup quality on arXiv is a documented weakness, not a defect to tune
  away silently.
- The `research` type is now available to future academic sources (Semantic
  Scholar, M22.5) without further freshness/ranking plumbing.
- GitHub Actions CI gates all suites on every push; production activation
  follows the standard deploy-and-verify protocol.
