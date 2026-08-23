# SignalPulse — Technical Privacy Documentation

This document describes **what the system stores, for how long, who can see
it, and how it is deleted**. It is engineering documentation, not a legal
privacy policy or compliance claim.

## Data model of a search

SignalPulse is an **anonymous service**: there are no accounts, no logins,
no cookies or sessions, and no IP addresses, device identifiers, or user
agents stored anywhere. A search cannot be linked back to a person by data
the system keeps.

For each search the following is stored:

| Data | Where | Why |
|---|---|---|
| The query text (as typed) | `searches.query` | Display in history/results views |
| Normalized query (case/whitespace-collapsed) | `searches.normalized_query` | Sent to sources; aggregated admin stats |
| Search status, timing, pipeline stats | `searches` columns | Observability |
| Result titles, descriptions, URLs, authors, dates, language | `results` | The product output |
| Full raw source API payload per result | `results.raw` | Provenance/auditability of every field shown |
| Per-source outcome events | `source_events` | Reliability observability |
| Duplicate-cluster annotations | `duplicate_groups` | Explainable deduplication |

Result content is public material from third-party sources (Wikipedia, The
Guardian; Reddit when enabled). Reddit-derived rows additionally have
credential-shaped keys stripped from raw payloads before storage.

## Retention

- Everything above persists for **30 days** from `searches.created_at`
  (configurable via `RETENTION_DAYS`; minimum 1).
- After that, searches **and all dependent rows** (results, source events,
  duplicate groups) are deleted automatically in transactional batches.
- Deletion runs at application startup/cold start and can be triggered
  immediately by the operator via authenticated endpoints
  ([RUNBOOK](RUNBOOK.md#admin-purge)). Deletion is permanent.

## Who can see what

| Surface | Access | Contains |
|---|---|---|
| `/searches/{id}`, `/searches/{id}/results` | Public (ID required) | That search's query + results |
| `/searches` (history list) | Public | Recent queries incl. text — see limitations below |
| `/admin/stats` | `X-Admin-Key` only | Aggregate metrics + top *normalized* queries |
| Purge endpoints | `X-Admin-Key` only | Deletion counts only, never content |
| Application logs | Platform (Render) | Method/path/status/latency + operational event metrics; **no query text, no headers, no secrets** |

Admin authentication fails closed: with no key configured, every admin
request is denied. Comparison is constant-time.

## Current limitations (known and documented)

- **Anonymous history exposure:** anyone can list recent queries via
  `GET /api/v1/searches`. Because nothing identifies a requester, this
  exposes topics, not people — but it is real exposure and a deliberate,
  reviewed trade-off slated for hardening (roadmap M18).
- **No user deletion requests:** there is no mechanism for an anonymous
  visitor to claim or remove a past search; the retention clock and operator
  purge are the deletion paths.
- Raw source payloads are retained as long as their search — provenance was
  chosen over storage minimization within the 30-day window.
- This service stores no encrypted-at-rest fields beyond platform defaults;
  confidentiality relies on Neon/Render platform controls plus application
  authorization boundaries described above.

## Out of scope here

GDPR/CCPA posture, data-processing agreements, breach-notification process:
SignalPulse is a portfolio system without legal review. Nothing in this file
should be read as a compliance assertion.
