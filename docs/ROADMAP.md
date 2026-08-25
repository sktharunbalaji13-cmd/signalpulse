# SignalPulse Roadmap

Status: **post-M22.7**. Everything below marked ✅ is shipped and deployed;
items under *Next* / *Deferred* are **planned, not implemented**.

## Completed milestones

| Milestone | Scope | Outcome |
|---|---|---|
| M0–M4 | Scaffold, Wikipedia vertical slice, Guardian integration, dedup design, PostgreSQL/Neon deployment | Multi-source foundation live on Render + Neon |
| M5–M6.5 | Frontend workspace, result filters (query-time views), UX polish, footer/branding | Professional workspace UI |
| M7 | Query normalization investigation + phrase-bonus candidate | **NO-GO** ([ADR 0008](ADR/0008-phrase-bonus-no-go.md)) |
| M8 | C4 score-normalization variants | **NO-GO** ([ADR 0009](ADR/0009-c4-normalization-no-go.md)) |
| M9 | Alternative relevance-signal candidate | **NO-GO** ([ADR 0010](ADR/0010-c4-relevance-signal-no-go.md)) |
| M10 | Semantic relevance candidate (SEM1) | **Experimental GO** — nDCG@10 0.8084 vs 0.7850 ([ADR 0011](ADR/0011-semantic-relevance-decision.md)) |
| M11 | Production semantic architecture decision (ONNX-int8 local) | Architecture selected ([ADR 0012](ADR/0012-semantic-production-architecture.md)) |
| M11.1–M11.3 | SEM1 implemented dormant → activated → measured ~3.5 s/search on free tier → disabled rollout | Dormant, config-gated |
| M12 | `/api/v1/admin/stats` production observability | Live |
| M13 | Read-only production audit (deployment, stats, privacy findings) | Findings F1..F10 logged |
| M14 | Admin authentication: fail-closed `X-Admin-Key`, constant-time compare | Live, production-verified |
| M15 | 30-day retention (`RETENTION_DAYS`), batched FK-safe cleanup, admin purge endpoints, `created_at` index | Live; first run deleted 0 records as predicted ([ADR 0013](ADR/0013-data-retention-policy.md)) |
| M16 | Consolidated gap analysis; documentation & repository consolidation | This document set |
| M17 | Reddit activation readiness | Adapter audited production-ready; **blocked externally** on API approval |
| M17.5 | Hacker News source evaluation & implementation | Keyless Algolia adapter live — 4th source; zero core-pipeline changes ([ADR 0014](ADR/0014-hacker-news-source.md)) |
| M18 | Multi-source production quality audit (Wikipedia + Guardian + HN) | 3 active sources at 100% success; battery p50≈1.1 s, p95 1.59 s (24 h); zero empty searches; ~0.3% dup rate; no HIGH/CRITICAL findings; Wikipedia top-5 share measured as by-design behavior |
| M19.1 | Search history privacy boundary + sources-proxy hardening | Query text removed from `GET /searches`; frontend local-first (localStorage) history; proxy on shared per-IP rate-limit budget ([ADR 0015](ADR/0015-search-history-privacy-boundary.md)) |
| M20.1 | Admin observability dashboard + HttpOnly session boundary | Protected `#/admin` dashboard over existing `/admin/stats`; admin key never enters the browser; CSS-only visuals, manual refresh only ([ADR 0016](ADR/0016-admin-observability-dashboard.md)) |
| M21.1 | Presentation & portfolio credibility | Live-demo CTA, real production screenshots, measured-metrics bullet, GitHub homepage + topics |
| M21.3 | Source availability semantics — "disabled" is not a failure | Unconfigured sources render neutrally and are excluded from status; searches read `completed` over enabled sources; credential transition auto-re-enables ([ADR 0017](ADR/0017-source-availability-semantics.md)) |
| M22.0 | Source-expansion feasibility audit | 9 candidates classified GO / CONDITIONAL / NO-GO / externally blocked with verified API economics; ranking-gate rule adopted: new source type → corpus evidence → production |
| M22.1 | arXiv research source + new `research` type | Live gate: 6/6 success, p50 0.95 s; one cross-source title collision handled by dedup; corpus rankings bit-identical; quality 0.75, weights (0.60/0.20/0.20), 30-day freshness half-life ([ADR 0018](ADR/0018-arxiv-research-source.md)) |
| M22.2 | GitHub code source + new `code` type | Repositories only, backend-held PAT, disabled without token; live gate: 10/10 success, p50 0.58 s / max 1.63 s, 0 over budget; HN↔GitHub exact-URL dup rate mean 0.8/query absorbed annotate-only; quality 0.70, weights (0.60/0.15/0.25), 90-day half-life ([ADR 0019](ADR/0019-github-code-source.md)) |
| M22.3 | Stack Overflow Q&A source + new qa type | Questions only, key-required (10k/day), disabled without it; live gate: 10/10 success, p50 0.98 s / p95 2.21 s, 0 over budget; minimal dedup overlap vs HN/GitHub; quality 0.75, weights (0.60/0.20/0.20), 180-day half-life ([ADR 0020](ADR/0020-stackoverflow-qa-source.md)) |
| M22.4 | Bluesky social source - activates dormant social type | Anonymous single-page searchPosts (25/post max, no cursor - 403-blocked); live gate: 10/10 success, p50 1.75 s / max 2.24 s, 0 over budget; near-zero dedup overlap; only ranking change is SOURCE_QUALITY[Bluesky]=0.45 ([ADR 0021](ADR/0021-bluesky-social-source.md)) |
| M22.6 | Third-party Reddit providers (FetchLayer et al.) | NO-GO on authorization/provenance grounds — technical fit was strong but no documented Reddit authorization exists for acquisition or downstream redistribution; official API remains the preferred path ([ADR 0022](ADR/0022-third-party-reddit-providers-no-go.md)) |
| M22.7 | YouTube video source + new ideo type | Keyed gate passed (10/10, p50 0.40 s, zero spam); quota-exhaustion (403 quotaExceeded) maps to rate_limited; quality 0.60, weights (0.55/0.25/0.20), 72h half-life ([ADR 0023](ADR/0023-youtube-video-source.md)) |

The M7–M9 NO-GOs are evidence-driven decisions that protected the production
ranker from unproven complexity — not abandoned work. The evaluation corpus
and harness remain the gate for any future ranking change.

## Next

The M22 multi-source expansion program proceeds one gated source at a time
(audit → adapter → corpus evidence → live measurement → production):

### M22.5 — Semantic Scholar *(planned)*
Gated on measuring arXiv↔S2 duplicate overlap once both exist.

### Reddit activation *(blocked externally)*
Enable the implemented Reddit adapter by configuring OAuth credentials.
M21.3 already made it render neutrally as `disabled`; activation is
**blocked solely on Reddit API access approval**.

## Deferred

- **SEM1 activation** — measured quality gain (+0.0234 nDCG@10) does not
  justify ~3.5 s inference latency on free-tier CPU; revisit after
  infrastructure upgrade. Activation itself is configuration-only.
- **Additional ranking experiments** — three consecutive NO-GOs; corpus-scale
  gains exhausted for now.
- **User accounts** — anonymous model is deliberate; accounts would be
  over-engineering for current goals.
- **Alerting / on-call tooling** — no uptime commitments yet.
- **Further sources beyond M22** — the adapter contract makes them cheap to add, but only when a concrete information need appears; every new *source type* additionally passes the ranking-evidence gate.
- **Scaling work** — multi-worker rate limiting/dedup caches, admin-stats SQL
  aggregation — all fine at current volume (~50 searches/day).

## Explicit non-goals

Raw-payload trimming (provenance), aggregation tables for stats (live-computed
by design), any deletion of evaluation artifacts, changes to the frozen
corpus or C4 ranker without new pre-registered evidence.
