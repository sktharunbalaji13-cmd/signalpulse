# SignalPulse Roadmap

Status: **post-M19.1**. Everything below marked ✅ is shipped and deployed;
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

The M7–M9 NO-GOs are evidence-driven decisions that protected the production
ranker from unproven complexity — not abandoned work. The evaluation corpus
and harness remain the gate for any future ranking change.

## Next

### M17 — Reddit Activation & Multi-Source Completeness *(planned — blocked externally)*
Enable the implemented Reddit adapter by configuring OAuth credentials.
Restores the social source class and removes today's misleading
`partial` status on every search. M17.0 audited the adapter production-ready
(no code changes required); activation is **blocked solely on Reddit API
access approval**. Verification protocol is ready to run the moment
credentials land.

## Deferred

- **SEM1 activation** — measured quality gain (+0.0234 nDCG@10) does not
  justify ~3.5 s inference latency on free-tier CPU; revisit after
  infrastructure upgrade. Activation itself is configuration-only.
- **Additional ranking experiments** — three consecutive NO-GOs; corpus-scale
  gains exhausted for now.
- **User accounts** — anonymous model is deliberate; accounts would be
  over-engineering for current goals.
- **Alerting / on-call tooling** — no uptime commitments yet.
- **Additional sources** — adapter contract makes them cheap to add, but only
  when a concrete information need appears.
- **Scaling work** — multi-worker rate limiting/dedup caches, admin-stats SQL
  aggregation — all fine at current volume (~50 searches/day).

## Explicit non-goals

Raw-payload trimming (provenance), aggregation tables for stats (live-computed
by design), any deletion of evaluation artifacts, changes to the frozen
corpus or C4 ranker without new pre-registered evidence.
