# ADR 0016: admin observability dashboard with HttpOnly session cookie

- **Status:** Accepted
- **Date:** 2026-08-23
- **Milestone:** M20.1
- **Related:** [ADR 0014](0014-hacker-news-source.md) (M14 admin auth), [ADR 0015](0015-search-history-privacy-boundary.md) (history boundary), M12 observability, M20.0 audit

## Context

SignalPulse has a complete, authenticated admin data surface (`/admin/stats`,
M12) guarded by a fail-closed `X-Admin-Key` (M14.1). M20.0 audited whether a
visual admin dashboard could render that telemetry without exposing the admin
key to the browser. The hard constraint: **the real `ADMIN_API_KEY` must never
enter the frontend bundle, environment variables shipped to the browser,
localStorage/sessionStorage, URL parameters, or React state that persists.**

The audit compared four architectures and rejected: shipping the key to the
browser (breaks M14), a full account/session system (over-engineering), and
reverse-proxy protection (unavailable on the Render free tier). The frontend
has no router; state/view architecture and `?s=` hash deep links are the
existing convention.

## Decision

1. **New login endpoint** `POST /api/v1/admin/login`: validates `X-Admin-Key`
   with the existing constant-time, fail-closed check, then issues a
   **short-lived in-memory token** stored only in process memory
   (`app/services/admin_session.py`; TTL 900 s default). The browser receives
   the token **only as an HttpOnly cookie** — never as a response body value
   and never exposed to JavaScript.
2. **Cookie attributes:** `HttpOnly; Secure; SameSite=None; Path=/api/v1/admin`
   in production. `SameSite=None` is required because the dashboard frontend
   (Render static host) and the API (Render web service) are different
   origins, so the cookie must be sent cross-site; `Secure` is mandatory
   alongside `SameSite=None`. Over plain HTTP (local tests) the cookie falls
   back to `SameSite=Lax` so the flow stays testable.
3. **CORS:** `allow_credentials=True` is enabled so the cross-origin
   dashboard can send/read the cookie. `allow_origins` remains an explicit
   allow-list (never `*`); the public API ignores credentials and is
   unaffected.
4. **Admin authorization accepts either:** a valid `X-Admin-Key` header
   (existing API/operator use, unchanged) **or** a valid admin-session cookie
   (dashboard use). Fails closed otherwise. `/admin/stats`, purge endpoints,
   and the new login/logout all use this boundary.
5. **Frontend:** `/admin` is a hash route (`#/admin`) rendered through the
   existing view-state architecture (no router dependency, matching the
   `?s=` convention). The dashboard shows Overview, Source Health,
   Deduplication, Semantic (clearly marked **EXPERIMENTAL / DORMANT**),
   Retention, and a 24h/7d/30d selector with **manual refresh only — no
   polling, no charts, no fake historical trends** (the endpoint is
   point-in-time). The key is typed once, sent only to `/admin/login`, and
   cleared from React state immediately after.
6. **Logout** `POST /api/v1/admin/logout` revokes the token and clears the
   cookie.

## Consequences

- The admin key never leaves the server after configuration. Compromise of the
  frontend bundle exposes only the dashboard UI, never credentials.
- Tokens are ephemeral and single-process (matching the single-worker
  deployment); any restart invalidates sessions, which is acceptable for an
  ops dashboard.
- The existing `/admin/stats` response contract is unchanged; API consumers
  (the M13/M15 verification scripts) continue to work via the header.
- New admin endpoints were added (`/login`, `/logout`) without altering any
  public search/history/results behavior.

## Non-goals (explicit)

No accounts, no passwords, no JWT infrastructure, no database sessions, no
charts or fabricated time-series, no automatic polling, no changes to
ranking/dedup/adapters/retention/SEM1/Reddit.