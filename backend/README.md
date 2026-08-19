# SignalPulse Backend

FastAPI backend for SignalPulse (see `../PROJECT_SPEC.md`).

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and adjust values. Settings are read via
pydantic-settings: `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `LOG_LEVEL`, plus
Wikipedia adapter settings (`WIKIPEDIA_USER_AGENT`, `WIKIPEDIA_TIMEOUT_SECONDS`,
`WIKIPEDIA_LANG`, `WIKIPEDIA_MAX_RESULTS`) and Guardian Open Platform settings
(`GUARDIAN_API_KEY`, `GUARDIAN_API_URL`, `GUARDIAN_TIMEOUT_SECONDS`,
`GUARDIAN_MAX_RESULTS`) and Reddit OAuth2 settings (`REDDIT_CLIENT_ID`,
`REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `REDDIT_TOKEN_URL`,
`REDDIT_API_BASE`, `REDDIT_TIMEOUT_SECONDS`, `REDDIT_MAX_RESULTS`).
Get a free Guardian key at https://open-platform.theguardian.com/ and create
a Reddit "script" app at https://www.reddit.com/prefs/apps for the client
credentials. With empty credentials a source stays registered but reports as
unavailable; nothing else breaks.

## Run

```powershell
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

On startup the app creates the SQLite database and tables automatically
(`signalpulse.db` in the backend directory; git-ignored). No migrations yet —
the schema is still evolving.

## Search workflow (M2)

```
POST /api/v1/searches        → 202 {search_id, status: running}  (returns immediately)
        │  background task fans out to every enabled source adapter
        ▼
wikipedia adapter ──┐
guardian adapter ───┤
                    ├─ asyncio.gather → SourceResult objects → SQLite (results + source_events)
reddit adapter ─────┘
        ▼
search status updated → completed | partial | failed
GET  /api/v1/searches/{id}             → status, per-source events, result count
GET  /api/v1/searches/{id}/results     → paginated normalized results
GET  /api/v1/searches?limit=20         → history, newest first
```

Sources run **concurrently** with isolated failures: one source failing never
cancels or discards another's results. If Wikipedia succeeds and Guardian
fails, the search is `partial` and Wikipedia results remain available; the
failed source is recorded in `source_events` (status, latency, error type,
safe message). All sources fail -> `failed`; all succeed -> `completed`.
The pipeline only talks to the registry, so adding a source is an adapter +
one registration line, not an orchestration rewrite. Wikipedia and Guardian
are verified live; the Reddit adapter is verified offline against fixtures
(live verification deferred until Reddit credentials are provisioned).

### Manual end-to-end test (live call)

```powershell
# start the backend first: uvicorn app.main:app --reload
$created = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/searches" `
  -ContentType "application/json" -Body '{"query":"artificial intelligence","window_hours":24}'
Start-Sleep -Seconds 3
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/searches/$($created.search_id)"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/searches/$($created.search_id)/results"
```

## Architecture

```
api/routes → sources/registry → BaseSourceAdapter → SourceResult
```

- **`app/db/`** — SQLAlchemy 2.0: `models.py` (typed `Search`, `Result`,
  `SourceEvent`), `session.py` (engine + `SessionLocal` + `get_session`
  dependency). Status values are controlled enums, not free strings.
- **`app/sources/base.py`** — the contract: the canonical `SourceResult`
  Pydantic model, a small `SearchParams` model, and the abstract
  `BaseSourceAdapter` interface (`async search(query, params) ->
  list[SourceResult]`).
- **`app/sources/registry.py`** — maps source names to adapter instances.
  Adding a source = write an adapter + one `register` line; nothing else in the
  system changes.
- **`app/sources/wikipedia.py`** — reference adapter (official MediaWiki action
  API, no key, no scraping).
- **`app/sources/guardian.py`** — news adapter (Guardian Open Platform Content
  API, `api-key` from settings, no scraping).
- **`app/sources/reddit.py`** + **`app/sources/reddit_auth.py`** — social
  adapter (official Reddit OAuth2 client-credentials API, bearer token cache
  keyed to the credential pair, no scraping, no unauthenticated fallback).
- **`app/services/search_pipeline.py`** — the background job: fans out to all
  sources concurrently (`asyncio.gather`), persists results, records
  `source_events`, transitions the search status
  (`completed`/`partial`/`failed`). No dedup/ranking yet.

### SourceResult (canonical model)

Every source adapter must produce this shape. Fields:

| Field | Meaning |
|---|---|
| `source_type` | `news` / `reference` / `social` / `video` |
| `source_name` | human-readable source, e.g. "Wikipedia" |
| `title` / `description` | normalized title and snippet |
| `url` | canonical URL (query strings / fragments stripped) |
| `author` | optional |
| `published_at` | source's publication claim — `None` if unknown; **never fabricated** |
| `retrieved_at` | when **we** fetched it (always set, UTC) |
| `language` | optional |
| `raw` | untouched original API payload, preserved for provenance/audit |

## Wikipedia integration

`WikipediaAdapter` calls `GET https://en.wikipedia.org/w/api.php` with
`generator=search` + `prop=extracts` (one request, no pagination yet), a
configurable User-Agent identifying SignalPulse, `maxlag=5` politeness, and a
5 s default timeout. Failures raise `SourceError` (timeout, HTTP error,
malformed JSON). `published_at` is always `None` for now — Wikipedia search
results only expose last-edit time, which is not a trustworthy publication
timestamp.

## Guardian integration

`GuardianAdapter` calls `GET /search` on the Guardian Open Platform Content
API with `api-key`, `page-size`, `show-fields=trailText,byline` and
`order-by=relevance`. `webTitle` -> title, `webUrl` -> url, `fields.trailText`
-> description (truncated to 500 chars), `fields.byline` -> author,
`webPublicationDate` -> `published_at` normalized to UTC (never fabricated).
API errors arrive as HTTP 200 with `response.status = "error"` and are mapped
to `failed`/`rate_limited`; HTTP 401/403 -> `failed`, HTTP 429 ->
`rate_limited`. A missing `GUARDIAN_API_KEY` raises `SourceError` before any
request. See `docs/ADR/0003-guardian-integration.md` for the full decision
record.

## Reddit integration

`RedditAuth` exchanges `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` for a bearer
token (`POST /api/v1/access_token`, `grant_type=client_credentials`) and
caches it for Reddit's reported lifetime minus a safety margin; the cache is
keyed to the credential pair. `RedditAdapter` then searches
`GET {REDDIT_API_BASE}/search` (`q`, `limit`, `sort=relevance`,
`type=link`) with `Authorization: Bearer`. Both requests use a descriptive
`REDDIT_USER_AGENT` and the configured timeout.

Normalization: canonical URLs prefer the API `permalink` and never follow
outbound link targets; `[deleted]`/missing authors -> `None`; `selftext` ->
description truncated to 500 chars; `created_utc` -> `published_at` (UTC,
never fabricated); language is `None`. `raw` is the post payload with any key
matching `token|secret|credential|authorization|password|api[-_]?key`
recursively stripped. Timeouts -> `timeout`, HTTP 429 -> `rate_limited`,
HTTP 401/403 -> `failed` (generic message, no credentials), malformed
responses/network errors -> `failed`. A missing credential pair raises
`SourceError` before any request. See
`docs/ADR/0004-reddit-integration.md` for the full decision record.

## Manual API test (live call)

```powershell
# start the backend first: uvicorn app.main:app --reload
curl "http://127.0.0.1:8000/api/v1/sources/wikipedia/search?q=artificial+intelligence"
```

Response: `{ "query", "source", "results": [ SourceResult, ... ] }`.
Unknown sources return 404; source failures return 502.

## Tests

All tests run offline — HTTP is mocked with `respx` and recorded fixtures in
`tests/fixtures/`.

```powershell
pytest
```

## Lint

```powershell
ruff check .
```