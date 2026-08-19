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
`WIKIPEDIA_LANG`, `WIKIPEDIA_MAX_RESULTS`).

## Run

```powershell
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

On startup the app creates the SQLite database and tables automatically
(`signalpulse.db` in the backend directory; git-ignored). No migrations yet —
the schema is still evolving.

## Search workflow (M1 step 2)

```
POST /api/v1/searches        → 202 {search_id, status: running}  (returns immediately)
        │  background task runs the enabled source adapters
        ▼
wikipedia adapter → SourceResult objects → persisted to SQLite (results + source_events)
        ▼
search status updated → completed | partial | failed
GET  /api/v1/searches/{id}             → status, per-source events, result count
GET  /api/v1/searches/{id}/results     → paginated normalized results
GET  /api/v1/searches?limit=20         → history, newest first
```

Only `wikipedia` is enabled. The pipeline iterates the registry, so adding a
source is a registration change, not an orchestration rewrite.

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
- **`app/sources/wikipedia.py`** — the first adapter (official MediaWiki action
  API, no key, no scraping).
- **`app/services/search_pipeline.py`** — the background job: iterates enabled
  sources, persists results, records `source_events`, transitions the search
  status (`completed`/`partial`/`failed`). No dedup/ranking yet.

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