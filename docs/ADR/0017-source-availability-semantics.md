# ADR 0017: source availability semantics — "disabled" is a source state, not a search failure

- **Status:** Accepted
- **Date:** 2026-08-24
- **Milestone:** M21.3
- **Related:** [ADR 0004](0004-reddit-integration.md) (Reddit), M21.2 audit, M15/M19 privacy boundary

## Context

Reddit is implemented but unconfigured in production (external API approval
blocked). Because an unconfigured adapter raised a normal `failed` source
error, every production search reported `partial` (133/133 measured) even
though Wikipedia, Guardian and Hacker News were functioning. M21.2 audited
this and concluded that `partial` had lost its meaning: a warning shown on
100% of searches is alarm fatigue, and the model conflated two different
facts — *a source broke* (operational) versus *a source was never enabled*
(deployment state).

## Decision

**"Disabled" is a source-level state, not a search-level outcome.**

1. `BaseSourceAdapter.is_configured() -> bool` (default `True`). Adapters with
   credential gates override it: Reddit (`client_id`/`client_secret`) and
   Guardian (`api_key`). The mechanism is generic — not a Reddit special case.
2. The search pipeline partitions registered sources into **enabled** and
   **disabled** before fan-out. Disabled sources:
   - are **not invoked**;
   - receive a `SourceEvent(status="disabled", error_type="disabled")`
     ("source is not configured");
   - are **excluded from search status computation**.
3. Search status is computed over enabled sources only: `completed` (all
   enabled ok) / `partial` (≥1 enabled failed) / `failed` (all enabled
   failed). Disabled sources never count toward any of these.
4. If **no** sources are enabled, `POST /searches` is rejected with 503
   instead of fabricating an empty search.
5. Frontend renders a disabled source neutrally (`○`, muted, `disabled`),
   and the partial-coverage banner only appears for genuine enabled-source
   failures.
6. Admin stats continue to show each source, now with a `disabled` count so
   operators keep visibility of the blocked source.

## Consequences

- A healthy three-source search now reads `completed`; Reddit reads
  `disabled`. `partial` regains real meaning.
- **Historical data is preserved exactly.** Existing `partial` searches are
  historical records; only new searches use the corrected semantics.
- **Transition is automatic:** the moment Reddit credentials appear,
  `is_configured()` flips, Reddit re-enters the enabled set, and searches
  become four-source again — proven by the credential-transition test
  (disabled → enabled → completed four-source search). No special-casing.
- API additions are additive: a new `SourceEventStatus.DISABLED` value and an
  optional `disabled` count in admin stats. Search-level vocabulary unchanged.
- No ranking, dedup, retention, authentication, adapter behavior, or data
  schema changed; no migration required.

## Non-goals

No Reddit/Devvit API changes, no frontend redesign, no new dependencies, no
changes to how *genuinely failing* enabled sources are surfaced (`partial` +
banner remain the honest signal for those).