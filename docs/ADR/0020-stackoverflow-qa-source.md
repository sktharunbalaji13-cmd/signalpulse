# ADR 0020: Stack Overflow as a Q&A evidence source — new `qa` source type

- **Status:** Accepted
- **Date:** 2026-08-24
- **Milestone:** M22.3
- **Related:** [ADR 0018](0018-arxiv-research-source.md), [ADR 0019](0019-github-code-source.md) (type-gate pattern & ambient-var lesson), M22.3 feasibility audit

## Context

M22.3's audit classified Stack Overflow **CONDITIONAL GO**: free Stack
Exchange API, but the keyless quota (300 req/day *per shared IP*) is unusable
on Render's shared egress — a free Stack Apps key lifts it to 10,000/day.
The audit measured p50 0.41 s latency and canonical, community-scored
questions with near-zero URL overlap against HN/GitHub.

**Scope decision — questions only.** The question (with its accepted-answer
ecosystem behind the link) is the atomic artifact. Answer/comment bodies
require heavy HTML filters; deferred unless lexical relevance proves
insufficient (`description` stays `None` in v1).

**Type decision — new `qa` class.** Curated problem→solution knowledge is
distinct from discussion (HN), artifacts (GitHub), and papers (arXiv):

| Constant | Value | Rationale |
|---|---|---|
| quality | `Stack Overflow = 0.75` | moderated + score-voted curation; per-item variance keeps it below Wikipedia |
| weights | `(0.60, 0.20, 0.20)` | relevance dominates; answers rot through framework drift |
| freshness | **180-day** half-life on `creation_date` | slower than code, faster than papers; classic answers keep a long tail via the 0.05 floor |
| priority | 5 (after code) | |

Score/answer_count/is_answered are provenance only — **not ranking inputs**
(same discipline as GitHub stars). `published_at = creation_date`;
`last_activity_date` rejected (trivial edits would fake freshness).
Titles/author display names are HTML-entity-decoded. Field names avoid the
GitHub Actions ambient namespace (`GITHUB_TOKEN`/`GITHUB_API_URL` lesson,
ADR 0019 follow-up).

## Evaluation (live gate, 2026-08-24, pre-registration)

Ten developer queries through the real adapter:

| Metric | Result |
|---|---|
| Success rate | **10/10** |
| Yield | 10.0 results/query |
| Latency | p50 **0.98 s**, p95 **2.21 s**, max 2.21 s |
| Over 4.5 s budget | **0/10** |
| Result character | canonical high-score questions (rebase-vs-merge 2552, useEffect cleanup 594); creation-year spreads 2009–2025 confirming the long-shelf-life freshness model |

Corpus rankings bit-identical by construction (no `qa` rows; explicit dict
keys leave existing fallbacks untouched), pinned by the full suite run.

## Consequences

- Six enabled sources once `STACKEXCHANGE_API_KEY` is configured (+ Reddit
  dormant); without it the source reports neutral `disabled`.
- Developer how-to queries gain curated problem/solution coverage distinct
  from every existing class.
- Backoff compliance is structural: stateless one-request-per-search with no
  automatic retries; throttle responses map to `rate_limited`.
