# ADR 0024: Disable anonymous Bluesky — M22.13 Option C (hybrid disposition)

- **Status:** Accepted
- **Date:** 2026-08-25
- **Milestone:** M22.13
- **Related:** [ADR 0021](0021-bluesky-social-source.md) (introduction), [ADR 0017](0017-source-availability-semantics.md) (disabled ≠ failed), [ADR 0014](0014-hacker-news-source.md) (type-gate pattern)

## Context

Anonymous Bluesky (`app.bsky.feed.searchPosts` on `api.bsky.app`, single-page)
shipped at M22.4 as the activation of the dormant `social` evidence class.
Production telemetry since deploy:

| Finding | Source |
|---|---|
| 13 attempts: 1 success / 12 failures; 12/12 failures HTTP 403 | M22.10 (measured) |
| 0 recoveries across restarts, idles, deploys, and volume levels | M22.10 (measured) |
| 9 of 27 searches became `partial` solely because Bluesky failed | M22.10 (measured) |
| Only successful search: positions 12–21, 0 top-10, 9/10 deduped into one group | M22.10 (measured) |
| Controlled diagnostic: `403`, `EDGE_RULE_HTML`, `server=openresty`, `content-type=text/html`, no `retry-after`/`ratelimit-*`, no structured auth error, body fingerprint `9221cfedfc5e` | M22.12 (measured, single request) |

The M22.12 diagnostic establishes an **administrative edge block** on anonymous
search from the production egress path — not rate limiting (no rate-limit
headers/JSON), not a structured authentication challenge. It does **not**
establish whether authentication bypasses the restriction (residential-IP
comparison and authenticated requests were explicitly excluded).

## Decision (M22.13, Option C — hybrid)

1. **Anonymous Bluesky is disabled by default.** `BlueskyAdapter.is_configured()`
   returns `settings.bluesky_anonymous_enabled` (default `False`). Under
   ADR 0017 semantics the source is excluded from fan-out and status math,
   renders neutrally, and reports `disabled` in admin telemetry. Re-enabling
   anonymous access is a config flip only and is discouraged without new
   evidence.
2. **403 → failed semantics unchanged.** The edge block is a failure/restriction,
   not throttling; reclassification to `rate_limited` is rejected (M22.12 body
   has no rate-limit semantics).
3. **No authentication implemented.** An authenticated path is preserved only as
   a **separately gated future feasibility milestone** with the pre-registered
   gate below.
4. **Ranking/dedup/freshness/contract unchanged.** The `social` type, quality
   constant `SOURCE_QUALITY["Bluesky"]=0.45`, weights, and half-life remain
   dormant-but-intact; disabling does not touch them.

### Future gate — Authenticated Bluesky feasibility milestone (only if separately approved)

- Dedicated service account + app password, backend-held env credentials
  (`BLUESKY_IDENTIFIER`/`BLUESKY_APP_PASSWORD`), never committed/logged/exposed.
- Live keyed gate, pre-registered: ≥20 distinct queries; pass = ≥90% success,
  **zero** `EDGE_RULE_HTML`-class 403s on first-page requests (fingerprint
  family `9221cfedfc5e`), p50 ≤ 2.0 s, all within the 4.5 s budget, ≤1 login
  per gate run.
- Failure semantics before gate: invalid-credential 401/403 → `disabled`;
  429 → `rate_limited`; timeout → `timeout`.
- Unique-yield/relevance: ≥60% of queries yield ≥1 canonical post-dedup result;
  operator spot-check on ≥10 queries.
- Production confirmation: ≥30 organic attempts over ≥48 h before KEEP is
  permanent (the M22.10 sample-size lesson).
- **Kill criteria:** any authenticated `EDGE_RULE_HTML` block → authenticated
  path NO-GO permanently → full closure (Option A); repeated credential
  failures after verified setup; unique-yield below threshold; unresolved
  ToS/provenance objection; two failed gates.

## Consequences

- Seven enabled production sources (+ Reddit and Bluesky dormant/disabled).
- Healthy searches return `completed` again; the false `partial` degradation
  attributable to Bluesky is eliminated.
- Bluesky renders as a neutral `disabled` chip; admin telemetry records a
  `disabled` count; zero anonymous Bluesky network calls occur.
- Historic failed/success Bluesky telemetry is preserved untouched.
- Reopening social coverage requires the gated authenticated milestone above.

## Production verification (post-deploy, 2026-08-25)

One real search: status `completed`, all 7 enabled sources `success`, Bluesky
and Reddit `disabled`, 40 results. Admin telemetry: `Bluesky: success=1
failed=12 disabled=1` (historical rows unchanged; `disabled=1` from the
verification search). Zero new Bluesky events → zero anonymous network calls.
`/health` 200; CI green; working tree clean.