# ADR 0019: GitHub as a code-evidence source — new `code` source type

- **Status:** Accepted
- **Date:** 2026-08-24
- **Milestone:** M22.2
- **Related:** [ADR 0018](0018-arxiv-research-source.md) (type-gate pattern), [ADR 0006](0006-dedupe-key-non-unique.md) (annotate-only dedup), M21.3 (disabled semantics), M22.0 audit

## Context

The M22.0 audit classified GitHub GO: free REST search API, backend-held
fine-grained PAT (public read is implicit in every token — zero extra
scopes), search budget of 30 req/min authenticated against a one-request-
per-search workload.

**Scope decision — repositories only.** A repository is the atomic unit of
engineering evidence: maintained, described, dated, canonical URL. Issue
search was considered and deferred: issue text is noisy for topical queries
and collides with the developer-Q&A domain planned for Stack Overflow
(M22.3). Revisit as its own experiment if a concrete need appears.

**Type decision — new `code` type, not reuse.** Forcing repos into `news`
would attach a 24-hour freshness half-life to `pushed_at` and news weights to
library metadata — semantically wrong on every axis. Freshness deliberately
rejects unknown types (`ValueError`), so the constants below are explicit,
documented design decisions:

| Constant | Value | Rationale |
|---|---|---|
| quality | `GitHub = 0.70` | hosts everything from abandoned toys to critical infrastructure; above anonymous social (0.50), below curated reference (0.80) |
| weights | `(0.60, 0.15, 0.25)` | fit dominates; maintenance recency is a weak signal |
| freshness half-life | **90 days** on `pushed_at` | quarterly horizon; active projects push within weeks, abandonment fades slowly |
| priority | 4 (after research) | |

Stars/forks are **not** ranking inputs — they live in `raw` provenance only.
Adding popularity would be a ranking-model change requiring its own
pre-registered experiment.

**Timestamp policy:** `published_at = pushed_at` (last engineering activity).
`created_at` would bury maintained classics. `language = None`: the repo's
programming language is not a human language.

## Evaluation (live gate, 2026-08-24, pre-registration)

Ten research/engineering queries through the real API:

| Metric | Result |
|---|---|
| Success rate | **10/10** |
| Yield | 10.0 results/query |
| Latency | p50 **0.58 s**, p95 **1.63 s**, max 1.63 s |
| Over 4.5 s source budget | **0/10** |
| HN stories linking github.com | mean **28%** of story URLs per query |
| Would-be duplicate groups (exact URL match vs HN) | mean **0.80**/query, max 3 |

Result quality was consistently canonical artifacts (scrapy, stable-
diffusion, milvus, pytorch_geometric). The HN↔GitHub overlap is a *feature*:
the same repository surfaced as community discussion and code artifact merges
into one annotated duplicate group via the exact-URL dedupe key (ADR 0006),
so it cannot double-count. Corpus rankings remain bit-identical by
construction (no `code` rows in the frozen corpus; explicit dict keys leave
existing fallbacks untouched) — pinned by the full suite run.

A feasibility-stage probe had measured one 6.35 s outlier out of six queries;
it did not recur across the ten-query gate. The per-source timeout remains
the bound: an outlier becomes an isolated `timeout` event and a `partial`
search, never a hung search.

## Consequences

- Five enabled sources once `GITHUB_API_TOKEN` is configured (+ Reddit dormant);
  without the token GitHub reports neutral `disabled` and searches stay
  `completed` (M21.3 semantics).
- Engineering queries gain an evidence class no other source provides.
- Future popularity-aware ranking (stars) or issue search each require their
  own gated experiment before touching production behavior.
