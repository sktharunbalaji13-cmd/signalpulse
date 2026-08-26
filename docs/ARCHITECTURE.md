# SignalPulse Architecture

Current-state overview of the deployed system. Individual decisions and their
rationale live in the [ADR ledger](ADR) — this document describes *what is*,
not *why it was chosen*. Milestone history: [ROADMAP.md](ROADMAP.md).

## System shape

```
Browser (React/Vite, Render static hosting)
   │  HTTPS
   ▼
FastAPI (Render web service, single worker)
   ├── middleware: request logging (method/path/status/latency only)
   ├── rate limiting: 30 req / 60 s per client IP + max 8 in-flight searches
   ├── routes: /health · /searches · /searches/{id}/results · /sources/{name}/search
   │           /admin/stats · admin purge endpoints (X-Admin-Key)
   └── lifespan: idempotent create_all + background retention cleanup task
              │
              ▼
        PostgreSQL (Neon): searches · results · source_events · duplicate_groups
```

## Frontend

React 19 + Vite + TypeScript. A single `useSearch` state machine
(`frontend/src/hooks/useSearch.ts`) drives view states (`idle → submitting →
running → completed/partial/failed`), polling `GET /searches/{id}` every
700 ms while a search runs and rendering results progressively. Filters are
query-time views: changing them re-fetches results with query parameters —
no client-side re-ranking. History is server-side (`GET /searches`); nothing
user-identifying is persisted in the browser.

## API layer

FastAPI application factory (`backend/app/main.py`). Public routes are
unauthenticated by design (anonymous service). The admin surface shares one
fail-closed guard (`_verify_admin_key`): constant-time comparison of the
`X-Admin-Key` header against the configured key; an empty configured key
denies everything.

Rate limiting applies to search creation only (`enforce_create_limits`),
protecting the expensive pipeline path; reads and the sources proxy are
unrated today.

## Search pipeline

`POST /searches` persists a `searches` row immediately (`running`), then runs
`run_search_job` as a FastAPI background task:

1. **Fan-out** — all registered adapters run concurrently via
   `asyncio.gather`, each in its **own SQLAlchemy session** so transactions
   never cross adapter boundaries.
2. **Isolation** — every adapter call is bounded by
   `asyncio.wait_for(source_timeout_seconds=4.5)`; failures become
   `source_events` rows (success/failed/timeout/rate_limited), never
   exceptions that kill the job.
3. **Persistence** — each result is stored as a `results` row carrying the
   normalized fields plus the untouched `raw` source payload (provenance).
4. **Deduplication** — annotate-only: `dedupe_key` on every row, clusters
   detected via canonical URL / normalized title / fuzzy title, one canonical
   member per `duplicate_groups` row with recorded evidence methods.
5. **Optional semantic stage** — when enabled, embeds query and documents via
   local ONNX-int8 MiniLM and blends cosine scores into ranking. Any failure,
   timeout, or disabled flag degrades byte-equivalently to pure C4.
6. **C4 ranking** — deterministic composition of relevance, freshness,
   quality, and a diversity pass; final scores/components/order persist on the
   rows (`rank_score`, `rank_components`, `rank_position`).
7. **Terminal status** — `completed` (all sources ok), `partial` (some ok),
   `failed` (none ok), written with duration and stats JSON on the search row.

## Source adapters

All adapters implement `BaseSourceAdapter.search(query, params) ->
list[SourceResult]`. Registered and their production status:

| Adapter | Evidence class | Status |
|---|---|---|
| Wikipedia (MediaWiki action API) | Reference | Active |
| The Guardian (Open Platform API) | News | Active |
| Hacker News (Algolia API) | News | Active ([ADR 0014](ADR/0014-hacker-news-source.md)) |
| arXiv (Atom export API) | Research | Active ([ADR 0018](ADR/0018-arxiv-research-source.md)) |
| GitHub (REST repository search) | Code | Active; disabled without a token ([ADR 0019](ADR/0019-github-code-source.md)) |
| Stack Overflow (Stack Exchange API) | Q&A | Active; disabled without a key ([ADR 0020](ADR/0020-stackoverflow-qa-source.md)) |
| YouTube (Data API v3 `search.list`) | Video | Active; quota exhaustion maps to `rate_limited` ([ADR 0023](ADR/0023-youtube-video-source.md)) |
| Bluesky (AppView `searchPosts`) | Social | **Disabled by default** — anonymous path edge-blocked; M22.13 hybrid decision ([ADR 0024](ADR/0024-bluesky-disable-hybrid.md)) |
| Reddit (OAuth2 client-credentials) | Social | **Dormant** — blocked externally; third-party paths rejected ([ADR 0022](ADR/0022-third-party-reddit-providers-no-go.md)) |

GDELT exists but is deliberately unregistered ([ADR 0005](ADR/0005-gdelt-gate.md)).

Normalization rules include UTC timestamps, description caps, `[deleted]`
Reddit authors → null, credential-shaped keys stripped from raw payloads,
and canonical-URL-only navigation targets for social posts.

## Persistence

PostgreSQL (Neon) via SQLAlchemy 2; schema managed by Alembic
(`backend/migrations`, head `c7d2e94a1b58`). Four domain tables:

| Table | Purpose |
|---|---|
| `searches` | One row per query: raw + normalized text, status, timings, pipeline stats JSON |
| `results` | Ranked signals with provenance `raw` JSON, dedup annotations, rank components |
| `source_events` | Per-source outcome of every search (observability backbone) |
| `duplicate_groups` | Dedup clusters: canonical pick + evidence |

Foreign keys are `ON DELETE NO ACTION`; deletion order must be
`duplicate_groups → source_events → results → searches`. Indexes cover lookup
paths plus `ix_searches_created_at` (retention scans).

## Retention

30-day policy (ADR 0013), clock = `searches.created_at`, configurable via
`RETENTION_DAYS` (validated ≥ 1). Cleanup deletes expired searches and
dependents in batches of 200, each batch transactional. Runs as an isolated
background task at application startup/cold start (Render free tier has no
scheduler) — enforcement is eventually consistent between restarts — and can
be triggered manually via authenticated purge endpoints. Idempotent: no
expired rows means no work.

## Observability

- Structured event logging (`log_event`) to stdout: lifecycle events with ids,
  counts, latencies, and error kinds. Query text, headers, and secrets are
  never logged; the request logger records the path without its query string.
- `GET /api/v1/admin/stats?window=24h|7d|30d` (authenticated): totals, status
  mix, latency percentiles, per-source aggregates, dedup metrics, semantic
  stage states, top normalized queries, retention info. Aggregations are
  computed live from tables — no secondary structures to invalidate.

## Admin security

One mechanism guards the entire admin surface (stats + purges):
`X-Admin-Key` header compared with `secrets.compare_digest`; empty configured
key fails closed (401 for everyone until a secret is set). No sessions, no
cookies, no user identity anywhere in the system.

## Deployment architecture

- **Render free tier**: one backend web service (auto-deploy from `main`,
  spins down after idle) + static frontend hosting. Cold starts are accepted.
- **Neon**: serverless PostgreSQL, scale-to-zero; connection pooling handled
  by SQLAlchemy with `pool_pre_ping` and recycle.
- **CI** (GitHub Actions): backend ruff+pytest, eval ruff+pytest, frontend
  build — gating every push to `main`.
- Migrations are applied deliberately (`alembic upgrade head`) rather than at
  boot; runtime bootstrapping uses idempotent `create_all`.
