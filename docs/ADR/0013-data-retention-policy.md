# ADR 0013: 30-day production data retention with admin purge

- **Status:** Accepted
- **Date:** 2026-08-23
- **Milestone:** M15.1
- **Related:** M15.0 audit; ADR 0006 (annotate-don't-delete); M14.1 admin auth

## Context

The M15.0 read-only audit established that SignalPulse stores every search,
result, source event, and duplicate group **indefinitely**: there was no TTL,
no scheduled cleanup, no DELETE path anywhere in the application, and every FK
is `ON DELETE NO ACTION`, so even manual deletion of a search fails while
children exist. Production held 108 searches / 2,104 results (13.55 MB) at
audit time - small, but growing unbounded (~2.4 MB/day at observed usage).

SignalPulse has **no accounts and no user identification**; the only
user-provided data is the query string itself, stored raw (`searches.query`)
and normalized (`searches.normalized_query`). The audit classified indefinite
retention (F1/F2), public raw-query history (F3), and the absence of any
deletion mechanism (F5) as MEDIUM findings.

## Decision

1. **Retention policy: 30 days**, configured via `RETENTION_DAYS` (default 30).
   The clock is `searches.created_at`. Values < 1 are rejected at startup so a
   zero/negative value can never mean "delete everything".
2. **Automatic cleanup** runs as an isolated background task on application
   startup/cold start (`lifespan` -> thread). Render free tier has no
   scheduler, so enforcement is **eventually consistent between restarts**.
   Deletion order respects the real FK graph:
   `duplicate_groups` → `source_events` → `results` → `searches`
   (`duplicate_groups.canonical_result_id` references `results.id`, so groups
   must go first). Batches of 200 searches commit atomically - a failure can
   never leave a search with partially deleted children.
3. **Admin purge API** under the existing `X-Admin-Key` mechanism:
   - `DELETE /api/v1/admin/searches/{search_id}` - purge one search (404 when
     unknown);
   - `POST /api/v1/admin/purge-expired` - purge everything older than the
     cutoff.
   Both return operational counts only (searches/results/source-events/
   duplicate-groups deleted) - never query text or content.
4. **Index:** `ix_searches_created_at` added via Alembic revision
   `c7d2e94a1b58` so cleanup scans do not sequential-scan.
5. **Observability:** cleanup logs only event names, counts, durations, and
   error *types* through the existing structured logger. Admin stats gain a
   `retention` block (days + clock). Stats remain live-computed, so purged
   rows disappear from statistics automatically - no aggregation tables.

## Alternatives considered

- **Ephemeral (no retention):** breaks the shipped history panel and shareable
  `?s=` links almost immediately; disproportionate for a portfolio demo.
- **7 days:** strongest privacy posture but history/links feel broken within a
  week of normal use.
- **90 days:** longest-lived history but retains query text ~3x longer than
  needed for the product's observability purpose, on a service that has no
  accounts to justify it.

30 days keeps recent searches useful (history, share links) while bounding
storage (~1,500 searches ≈ tens of MB) and limiting query-text lifetime.

## Consequences

- Records older than 30 days are permanently deleted, including their `raw`
  source payloads. Provenance beyond 30 days is not preserved (accepted: the
  annotate-don't-delete model remains intact *within* the retention window).
- First production run happens at the next deploy/startup; with production
  data only ~2 days old at implementation time, it deletes nothing.
- No user-facing deletion exists (still out of scope): anonymous visitors have
  no account to hang a deletion right on; the admin purge is the operator's
  escape hatch.

## Out of scope (explicitly)

- User accounts, per-user deletion rights, or consent flows.
- Changes to public `/searches` history semantics (M15.0 finding F3 stands as
  a deliberate product behavior until separately decided).
- Trimming `raw` payloads, aggregation/statistics tables, log-format changes,
  and Render/Neon infrastructure changes.
