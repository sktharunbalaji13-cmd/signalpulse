# SignalPulse Runbook

Operational procedures for the deployed system. Variable **names** are listed;
secret values live only in Render's environment configuration and must never
be committed, logged, or shared.

## Environments

| Piece | Where | Deploys via |
|---|---|---|
| Backend API | Render web service (`signalpulse`) | auto-deploy on push to `main` |
| Frontend | Render static site | auto-deploy on push to `main` |
| Database | Neon PostgreSQL | — |

## Health check

```bash
curl https://signalpulse-e12w.onrender.com/api/v1/health
# 200 {"status":"ok","service":"signalpulse-api","version":"0.1.0","db":"ok"}
```

`status=ok` requires a successful database round-trip; a down DB yields
HTTP 503 with `{"status":"degraded","db":"down"}`. Cold starts after idle can
take 30–60 s (Render free tier).

## CI verification

Every push to `main` runs [.github/workflows/ci.yml](../.github/workflows/ci.yml):
backend `ruff check .` + `pytest`, eval `ruff check eval --config
backend/pyproject.toml` + `pytest eval/tests`, frontend TypeScript build.
CI must be green before considering a deploy good.

## Database migrations

Schema is managed by Alembic from `backend/migrations` (single source of
truth: the SQLAlchemy models). Runtime boot uses idempotent `create_all`,
which does **not** alter existing tables — deliberate migrations are applied
manually:

```powershell
cd backend
. .venv/Scripts/activate   # or use the venv python directly
python -m alembic upgrade head     # applies pending revisions against DATABASE_URL
python -m alembic current          # confirm applied revision
python -m alembic upgrade head --sql   # offline: print SQL without connecting
```

Current head: `c7d2e94a1b58` (adds `ix_searches_created_at`). Verify before
applying that `DATABASE_URL` points at the intended database.

## Admin stats

```bash
curl -H "X-Admin-Key: $ADMIN_API_KEY" \
  "https://signalpulse-e12w.onrender.com/api/v1/admin/stats?window=7d"
```

Windows: `24h`, `7d`, `30d` (anything else → 422). Without the header (or
with an empty configured key) the endpoint returns 401.

## Admin purge

```bash
# Purge one search and all dependent rows:
curl -X DELETE -H "X-Admin-Key: $ADMIN_API_KEY" \
  "https://signalpulse-e12w.onrender.com/api/v1/admin/searches/{search_id}"

# Purge everything older than the retention cutoff:
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" \
  "https://signalpulse-e12w.onrender.com/api/v1/admin/purge-expired"
```

Responses contain deletion counts only — never query text or content.
Unknown IDs return 404. Prefer `purge-expired`; it is idempotent and a no-op
when nothing is expired.

## Retention behavior

- Policy: searches older than `RETENTION_DAYS` (default 30) are deleted with
  their dependent rows; clock is `searches.created_at`.
- Automatic execution: background task at application startup/cold start
  (Render has no scheduler) — eventually consistent between restarts.
- Manual execution any time via the authenticated purge endpoint above.
- Deletion order respects FKs (`duplicate_groups → source_events → results →
  searches`); each 200-row batch commits atomically.
- Admin statistics are computed live, so purged rows disappear immediately.

## Environment variables (names only)

Backend service (Render):

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Neon connection string (required) |
| `ADMIN_API_KEY` | Enables admin surface; empty/unset = all admin requests fail closed with 401 |
| `RETENTION_DAYS` | Optional; default 30; values < 1 are rejected at startup |
| `SEMANTIC_ENABLED` | Currently **false/disabled**; set `true` only with sufficient CPU (see below) |
| `GUARDIAN_API_KEY` | The Guardian Open Platform key |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit OAuth app credentials (**not currently configured**) |
| `CORS_ORIGINS` | Comma-separated frontend origins |

Frontend service: `VITE_API_BASE` (public backend URL).

### Configuring Reddit credentials *(planned — not yet done)*

1. Create a Reddit "script" app (OAuth client-credentials type).
2. Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` on the Render backend
   service; the service restarts automatically.
3. Verify: run a search containing social-discussion topics and check
   `/admin/stats` shows Reddit `success` events; search status should become
   `completed` when all three sources succeed.

No code changes are required; the adapter raises a clean per-source failure
while credentials are absent.

### Activating SEM1 semantic ranking *(currently disabled)*

`SEMANTIC_ENABLED=true` turns the stage on for new searches. It was measured
at ~3.5 s/search of inference on the Render free tier — do not enable there.
Activation is justified only after infrastructure with adequate CPU/RAM, and
should be followed by a latency check via `/admin/stats`
(`semantic.avg_ms`, `semantic.ok` counts).

## Rollback considerations

- **Application code:** Render redeploys from Git; roll back by re-deploying
  the previous commit. Schema migrations are additive so far (index creation);
  old code remains compatible with newer schema heads.
- **Migrations:** each revision ships a `downgrade()`. `alembic downgrade -1`
  reverses one step; verify against a non-production database first.
- **Retention:** reducing deletions requires no rollback mechanism — data
  older than the cutoff is gone permanently once deleted; restore-from-backup
  is a Neon platform operation, not automated here.
