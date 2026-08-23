# ADR 0015: search history privacy boundary & local-first history

- **Status:** Accepted
- **Date:** 2026-08-23
- **Milestone:** M19.1
- **Related:** M13/M16 findings (F3/F4); [ADR 0013](0013-data-retention-policy.md) (retention); M4 design (rate limiting)

## Context

`GET /api/v1/searches` published the most recent searches **including raw
query text** to any anonymous caller. The original spec
(`PROJECT_SPEC.md` §"search history page") intended *a visitor seeing their
own recent searches*, but the implementation was a global window: every
visitor's queries were visible to everyone. Retention (ADR 0013) bounds how
long data lives — it says nothing about who can read it. The M13/M16/M18
audits repeatedly flagged this as the last open medium privacy finding.

Search IDs are UUIDv4 (`models.py:23–24`, 122 random bits) so ID-addressed
access (`/searches/{id}`, shareable `?s=` links) is already effectively
capability-based; enumeration was ruled out by probe (all guessable IDs → 404).

## Decision

**Option C — local-first history.**

1. `GET /api/v1/searches` becomes operational metadata only
   (`search_id, status, created_at, completed_at, duration_ms,
   result_count`). Raw and normalized query text are no longer part of the
   listing response. ID-addressed endpoints are unchanged.
2. The frontend records each search it initiates in `localStorage`
   (`signalpulse:history`, capped at 20 entries): id, query label,
   created-at; status/count are finalized locally when the pipeline
   completes. History now means exactly *"searches previously initiated from
   this browser"* — honest semantics with no server-side exposure. Corrupt or
   missing storage degrades to an empty list.
3. Share links keep working unchanged: a recipient with the ID can still open
   that one search through existing endpoints.
4. The `/sources/{name}/search` proxy joins the same per-IP sliding-window
   limiter instance used by search creation (one mechanism, one budget per
   IP; no in-flight check since the proxy runs no pipeline job). It also
   gains its first test coverage.

## Alternatives considered

| Option | Verdict |
|---|---|
| Redact list but keep global listing | Breaks the Recent Queries labels without removing the global-metadata surface |
| History tokens issued at creation | Real boundary, but adds server state/tokens — a step toward sessions the project does not need |
| User accounts | Explicitly over-engineering for an anonymous service ([ROADMAP](ROADMAP.md) non-goal) |

localStorage trade-offs: history is device-local (clearing browser data
removes it; other devices don't see it) and readable by anything running in
the page's origin — acceptable for non-sensitive query labels, and strictly
narrower than the previous global API exposure.

## Relationship to retention

Unchanged and complementary: retention bounds *how long* rows live (30 days,
ADR 0013); this decision bounds *who can list* them. Purged searches simply
disappear from both the (now metadata-only) listing and ID-addressed access.

## Consequences

- No raw/normalized query text is served by any unauthenticated listing.
  Verified by regression tests asserting the exact item field set.
- The frontend no longer calls `GET /searches`; the endpoint remains for
  operational/admin use with the reduced contract.
- Non-goals (explicit): accounts, authentication, sessions/history tokens on
  the client, changes to ranking/dedup/adapters/retention.
