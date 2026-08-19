# ADR 0003: Guardian source integration with concurrent fan-out

- **Status:** Accepted
- **Date:** 2026-08-19
- **Milestone:** M2-A
- **Related:** ADR 0002 (Wikipedia integration), PROJECT_SPEC.md §16, §17

## Context

M2-A adds The Guardian as the second live source (news, in contrast to
Wikipedia's reference role). Two design questions arise:

1. How to add a second adapter without changing the pipeline's contract.
2. How to execute multiple sources in one search without a slow source
   delaying the others, and without one failure killing the search.

## Decision

### 1. Guardian adapter follows the existing contract

`GuardianAdapter` implements `BaseSourceAdapter` and returns the canonical
`SourceResult`. `source_type = "news"`, `source_name = "The Guardian"`.
Registration is a single line in `SourceRegistry`; the search pipeline and
API layer are unchanged. The Guardian Open Platform Content API
(`GET /search` with `api-key`) is used — no scraping.

Guardian specifics:

- `published_at` is taken from `webPublicationDate`, normalized to UTC.
  An unparseable timestamp yields `None` — timestamps are never fabricated.
- `author` from `fields.byline` (empty -> `None`).
- `description` from `fields.trailText`, truncated to the 500-character
  canonical limit.
- `raw` preserves the untouched result item for provenance.
- The API key comes from `GUARDIAN_API_KEY` (pydantic-settings). A missing
  key raises `SourceError(kind="failed")` before any request, so the source
  reports as unavailable instead of failing loudly. The key is never logged.
- Guardian reports API errors as HTTP 200 with
  `response.status = "error"`; the adapter maps `ApiKey*` errors to `failed`
  and `RateLimit*` errors to `rate_limited`, in addition to HTTP 429/401/403
  handling.

### 2. Sources run concurrently via `asyncio.gather`

`run_search_job` now fans out to every registered source with
`asyncio.gather(..., return_exceptions=True)`. Each source executes in its
own SQLAlchemy session — concurrent fan-out never shares a transaction.

### 3. Per-source failure isolation

`_run_source` never raises: `SourceError` and unexpected exceptions are
caught, recorded as a `SourceEvent` (status, result count, latency, error
type, safe message), and returned as a status dict. `asyncio.gather` with
`return_exceptions=True` additionally guarantees that one coroutine's
failure cannot cancel the others.

Overall search status is derived purely from per-source outcomes:

| Outcomes | Status |
|---|---|
| all sources succeed | `completed` |
| some sources fail | `partial` |
| all sources fail | `failed` |

## Consequences

- One search returns Wikipedia reference results and Guardian news results,
  combined through the same normalized model.
- A failing source never discards another source's results: Wikipedia
  succeeds + Guardian fails -> `partial` with Wikipedia results intact.
- The API exposes per-source outcomes (name, status, result count, latency,
  error type, safe error) via `GET /searches/{id}`.
- Tests remain fully offline (respx fixtures); CI never depends on the
  live Guardian API.
- The Guardian source requires an API key to report success; without one it
  is registered but reports as unavailable (`failed`), keeping the search
  `partial` when Wikipedia succeeds.