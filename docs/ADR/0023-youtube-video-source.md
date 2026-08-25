# ADR 0023: YouTube as a video-evidence source — new `video` source type

- **Status:** Accepted
- **Date:** 2026-08-25
- **Milestone:** M22.7
- **Related:** [ADR 0018](0018-arxiv-research-source.md), [ADR 0019](0019-github-code-source.md), [ADR 0020](0020-stackoverflow-qa-source.md), [ADR 0021](0021-bluesky-social-source.md) (type-gate pattern), M22.7 keyed gate report

## Context

M22.7's keyed live gate (10 queries, real `search.list`) passed decisively:
10/10 success, p50 0.40 s / p95 0.68 s, 100/100 on-topic results, zero
Shorts/spam signals, and a strong authoritative-channel mix (MIT
OpenCourseWare, Andrej Karpathy, IPCC, The Lancet, freeCodeCamp, 3Blue1Brown).
The dominant constraint is quota: `search.list` draws from a **separate
100-calls/day bucket**; at ~50 searches/day that is ~50% utilization with a
hard ceiling and midnight-PT reset.

**Type decision — new `video` evidence class.** Multimedia content is a
distinct consumption mode: official-channel explainers, course content, and
event coverage that no text source replicates. No existing type fits (news'
24 h half-life too fast for persistent tutorials; reference's timelessness
wrong for event coverage):

| Constant | Value | Rationale |
|---|---|---|
| quality | `YouTube = 0.60` | spans junk-to-official-channels; engagement signals are NOT ranking inputs |
| weights | `(0.55, 0.25, 0.20)` | relevance dominates; video relevance decays slower than news |
| freshness | **72-hour** half-life on `publishedAt` | design constant; tutorials persist longer, event coverage decays fast |
| priority | 6 (after qa) | |

## Decision

1. **Adapter** (`app/sources/youtube.py`): one `search.list` call per search,
   `part=snippet, type=video, relevanceLanguage=en`, relevance order. No
   `videos.list` enrichment in v1 (would break single-call discipline; view
   counts never enter raw or ranking).
2. **Quota-exhaustion semantics are the defining design point**: exhaustion
   arrives as **HTTP 403 `quotaExceeded`** — deterministic-until-midnight-PT
   temporary unavailability, mapped to **`rate_limited`** (distinct from a
   genuine failure). Other 403s (missing key, restrictions) map to `failed`.
   The adapter inspects the error body's `reason` to distinguish them.
3. **Credential model**: backend-held Google Cloud key (`YOUTUBE_API_KEY`),
   sent as the `key` query parameter. Absent → source reports `disabled`
   (M21.3 semantics). No quota workarounds (multi-project multiplication is
   ToS-violating; quota increases are a weeks-long discretionary audit).

## Evaluation (post-implementation live gate, 2026-08-25)

Eight queries through the real adapter: **8/8 success · yield 10.0 · p50 1.12 s
· p95/max 1.28 s · 0/10 over budget · 8 `search.list` calls burned**.

## Consequences

- Eight enabled sources once `YOUTUBE_API_KEY` is configured (+ Reddit
  dormant). Video joins reference/news/tech-discussion/research/code/Q&A/
  social.
- The `video` filter/chip enters the UI (`chip--video` CSS pre-existed).
- Quota is a monitored operational constraint: partial searches during
  exhaustion are attributable (`rate_limited`), auto-recover at PT midnight,
  and are reported in admin telemetry.
- Corpus rankings bit-identical by construction (no `video` rows; explicit
  dict keys) — pinned by the full suite run.