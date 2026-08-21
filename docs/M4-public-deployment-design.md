# M4 — Public Deployment: Design & Pre-Deployment Checklist

**Status:** Design + pre-deployment measurement only. **Nothing is deployed and
no production behaviour is changed** until this checkpoint is reviewed.
**M0–M3.5 is frozen** — retrieval, deduplication, freshness, C4 ranking, M3-E
filters, M3.5 source timeout, and provenance semantics are preserved. M4 is
infrastructure and configuration, not retrieval behaviour.

**Priority (locked):** Reliability → Speed → Source quality → Provenance →
Intelligence → AI.

## 1. Objective

Turn the tested local application into a real public web application that an
ordinary user can open over HTTPS, search, and use reliably — no unnecessary
delay, clear failure states, backend-only credentials.

## 2. Deployment architecture

```
Browser
   │  HTTPS
   ▼
Frontend: React + Vite static build          (Render Static Site / web service)
   │  /api/v1/*  (CORS-enabled, VITE_API_BASE)
   ▼
FastAPI backend (uvicorn)                    (Render Web Service, one instance)
   │  httpx (server-side only; keys never leave the backend)
   ▼  Guardian / Reddit / Wikipedia
   │  BackgroundTasks (in-process; single instance — no Celery/Redis needed)
   ▼
Neon PostgreSQL (serverless, scale-to-zero)  (DATABASE_URL)
```

Deliberately **no** Redis, Celery, vector DB, or message broker: the workload is
a ≤ ~5 s concurrent fan-out per search run by an in-process BackgroundTask on a
single instance. These are re-evaluated only if/when there are multiple backend
instances or durable queuing needs (PROJECT_SPEC §11).

## 3. Hosting choices (aligned with PROJECT_SPEC, verified 2026)

| Component | Host | Rationale |
|---|---|---|
| Backend | Render free **Web Service** (750 hr/mo, 512 MB / 0.1 CPU) | `uvicorn app.main:app`; free tier, CI-friendly. Cold start 30–60 s after ~15 min idle — acceptable for a portfolio demo; optional keepalive. |
| Frontend | Render **Static Site** (`npm run build` → `dist`) or the web service | Static assets; `VITE_API_BASE` set to the backend URL at build. |
| Database | **Neon Postgres** free (0.5 GB, scale-to-zero) | Render free Postgres expires after 30 days; Neon is "free forever" with no card. |
| Domain/HTTPS | Render-provided HTTPS subdomain (auto cert); custom domain later | Zero-config cert on free tier. |
| Redis/Celery | none | not justified at this scale |

## 4. Database: SQLite → PostgreSQL (config change, not a rewrite)

- The ORM is portable and has been **audited**: no SQLite-only SQL anywhere;
  the M4 pre-deployment test (`backend/tests/test_postgres_compat.py`) compiles
  the full schema DDL and the production filter/order queries against the
  PostgreSQL dialect and asserts they are valid (6 checks).
- **Driver**: add `psycopg[binary]` (SQLAlchemy 2.0 uses psycopg 3 via
  `postgresql+psycopg://`). `db/session.py` already applies SQLite-only
  `connect_args` only when the URL is SQLite, so the switch is the
  `DATABASE_URL` value (e.g. `postgresql+psycopg://user:pass@host/db`).
- **JSON columns** (`Search.stats`, `Result.raw`, `Result.rank_components`,
  `DuplicateGroup.duplicate_evidence`) map to PostgreSQL `JSON`.
- **Migrations**: introduce **Alembic** (M4). Baseline = the current
  `create_all` schema; forward-only migrations; **never destructive**; back up a
  Neon snapshot before each migration. Production DDL is verified by the
  Postgres-dialect compilation test; a live connectivity + round-trip check is a
  checklist step (§13).

## 5. TZ-001 closure (production timezone behaviour)

- **Root cause**: SQLite drops `tzinfo` on datetime round-trip, so rows serialize
  without a UTC marker and the browser reinterprets them as local time.
- **Resolution**: `DateTime(timezone=True)` columns become PostgreSQL
  `TIMESTAMP WITH TIME ZONE` (verified by `test_postgres_compat.py`), which
  round-trips timezone-aware datetimes correctly. The API then serializes a
  tz-aware datetime with its offset (Pydantic/FastAPI), so the browser's
  `new Date()` parses correctly.
- The retrieval code already defends against naive datetimes (assumes UTC —
  e.g. `ranking._ts_key`), so no scoring/filtering change is needed.
- **Pre-deployment verification**: schema-level (test) now; **live** round-trip
  check against Neon in the checklist (§13): persist a `published_at`, read it
  back, assert it is timezone-aware and serializes with a UTC marker.

## 6. Environment & secrets

- `pydantic-settings` reads environment variables; `backend/.env` is gitignored;
  `.env.example` documents every variable; **no real secrets committed**.
- Production secrets (Render env vars, never in frontend/repo/logs):
  - `DATABASE_URL` (Neon)
  - `GUARDIAN_API_KEY`
  - `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`
  - `WIKIPEDIA_USER_AGENT` (identify the bot)
- `ENVIRONMENT=production`, `LOG_LEVEL=INFO` (or DEBUG briefly during launch).
- The frontend receives **no** credentials — it only calls the public API.

## 7. Production CORS

- `CORS_ORIGINS` set to the exact production frontend origin(s)
  (e.g. `https://signalpulse.onrender.com`); `allow_credentials=False` (public
  API, no cookies). Keep it an allow-list, never `*`.

## 8. Frontend → production API

- `VITE_API_BASE=https://<backend-url>` set at build time (env var).
- The frontend polls search status (700 ms) and already renders partial results;
  M3.5 §15.3.3 surfaces a `status`/`done` marker for cleaner progressive UX
  (UI polish, M4).

## 9. HTTPS / domain

- Render auto-provisions an HTTPS certificate on its subdomain.
- Custom domain (optional, later): point a DNS record and let Render issue the
  cert (or front with Cloudflare). Not required for the MVP launch.

## 10. Health / readiness

- Extend `/health` (currently liveness-only) with a **readiness** check that the
  database is reachable (e.g. `SELECT 1`) and that the source registry is
  loaded. Keep `/health` fast; return 200 only when ready.
- This gives Render's health checks a reliable signal.

## 11. Monitoring & error visibility

- Structured `log_event` already records source outcomes and `search.stats`
  carries per-stage timings (`sources_ms`, `postpass_ms`, `total_ms`).
- Add a request-logging middleware (method, path, status, latency_ms) at INFO.
- Render log dashboard for visibility; optional free uptime monitor
  (e.g. UptimeRobot) pinging `/health`.
- No external APM for the MVP; re-evaluate only if real issues demand it.

## 12. Rate limiting / abuse protection (now justified — public traffic)

- **Per-client-IP token bucket on `POST /searches`** + a **global in-flight
  search cap** → explicit HTTP 429 on burst. In-process on the single instance
  (no Redis needed).
- Query/page bounds already validated (200-char, `page`/`per_page` caps).
- Exact limits calibrated at M4 from the post-deploy latency verification; the
  design here fixes the mechanism, not the final numbers.

## 13. Caching (evidence-driven)

- **Deferred** (M3.5 decision): determinism (P8) proves identical repeat
  queries are cacheable, but with no public load there is no evidence caching
  materially improves UX or protects upstream APIs. Revisit after real traffic;
  if added: only completed results, TTL-bound, provenance-preserving, keyed by
  `normalized_query + window_hours + M3-E filter params`, never partial/in-progress.

## 14. Rollback strategy

- **Code**: Render one-click redeploy of a previous commit (backend + frontend).
- **Database**: forward-only Alembic migrations; take a Neon backup/snapshot
  before each migration; no destructive DDL; if a migration fails, stop and fix
  forward (no automatic downgrade). Recover from snapshot if needed.

## 15. Real-world latency verification (post-deploy)

- `curl` TTFB on `/health` and on a full search (submit → first → completed);
  compare against the M3.5 targets (submit < 500 ms, first ≤ 3 s, completed ≤ 5 s).
- Account for Render free-tier **cold start** (30–60 s after ~15 min idle);
  document it and optionally keep the instance warm.
- Verify TZ-001 live: a `published_at`/`retrieved_at` in results serializes with
  a UTC marker and renders correctly in the browser.

# Pre-deployment checklist (the gate — run at the M4 implementation checkpoint)

## 16. Implementation status (M4 checkpoint)

### Implemented + verified locally (production-equivalent)
- **PostgreSQL + psycopg**: `psycopg[binary]` added; the ORM runs against real
  Postgres (verified via Docker Postgres, same engine as Neon).
- **Alembic migrations**: baseline migration created (`migrations/versions/`),
  applied to Postgres — 5 tables + `alembic_version`; `DateTime(timezone=True)`
  → `timestamp with time zone`, JSON columns → `JSON`.
- **TZ-001**: real Postgres round-trip verified — `published_at` keeps `tzinfo`
  and serializes with the `+00:00` UTC marker (`test_postgres_live.py`).
- **Postgres schema/query verification**: `test_postgres_compat.py` (dialect
  compile) + `test_postgres_live.py` (live, gated on `POSTGRES_TEST_URL`).
- **Production CORS**: `cors_allow_credentials` setting (default False, public API).
- **Health/readiness**: `/health` now does a DB reachability check → 200/`db=ok`
  when ready, 503/`db=down` when not (`test_production_hardening.py`).
- **Request observability**: `RequestLoggingMiddleware` logs
  method/path/status/latency_ms; stage timings already in `search.stats.timing_ms`.
- **In-process rate limiting + in-flight cap**: per-IP sliding window on
  `POST /searches` + global running-search cap → HTTP 429
  (`app/services/rate_limit.py`, tested).
- **Frontend production config**: `frontend/.env.production.example`
  (`VITE_API_BASE`); production build verified.

### Pending — live deployment (requires the user's Render + Neon accounts)
Render web service + static site, Neon Postgres provisioning, HTTPS/domain,
environment/secret injection, real-world latency/failure verification, and the
M4 go/no-go gate. These are external steps that need real credentials/accounts
and are executed via the pre-deployment checklist (§13).

## A. Postgres readiness
- [ ] `psycopg[binary]` added to `backend/pyproject.toml`.
- [ ] `backend/tests/test_postgres_compat.py` passes (schema DDL + filter/order SQL compile for PG).
- [ ] Alembic added; baseline migration == current `create_all` schema; forward-only.
- [ ] Local parity: run backend against a local Postgres (Docker Compose or local pg) and run the full suite.

## B. TZ-001
- [ ] Live round-trip check on Neon: persist + read back a tz-aware datetime, assert it stays tz-aware and serializes with a UTC marker.

## C. Environment & secrets
- [ ] `.env.example` is current and documents every production variable.
- [ ] No real secrets in the repo, `.gitignore` covers `.env*` (except example).
- [ ] Render env vars set: `DATABASE_URL`, `GUARDIAN_API_KEY`, `REDDIT_*`, `WIKIPEDIA_USER_AGENT`, `ENVIRONMENT`, `LOG_LEVEL`, `CORS_ORIGINS`.

## D. Frontend
- [ ] `VITE_API_BASE` points at the production backend at build time.
- [ ] Production build passes (`npm run build`).
- [ ] CORS allow-list contains the exact production origin; credentials off.

## E. Backend serving
- [ ] Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- [ ] Readiness check added and wired to Render health check.
- [ ] Request-logging middleware added.

## F. Security & abuse
- [ ] Rate limiting implemented and tested (burst → 429).
- [ ] Keys confirmed backend-only (no frontend/repo/log exposure).

## G. Reliability
- [ ] M3.5 pipeline timeout verified live (no indefinite search under real sources).
- [ ] Full backend + eval suites green; ruff clean under CI invocations.

## H. Go / no-go
- [ ] HTTPS reachable; `/health` returns ready; a real end-to-end search works from a browser.
- [ ] Latency meets targets (accounting for cold start); TZ-001 verified live.
- [ ] Rollback documented and drill-tested (redeploy previous commit).
