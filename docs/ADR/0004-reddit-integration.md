# ADR 0004: Reddit social source integration (official OAuth2 API, offline-verified)

- **Status:** Accepted
- **Date:** 2026-08-19
- **Milestone:** M2-B
- **Related:** ADR 0002 (Wikipedia), ADR 0003 (Guardian), PROJECT_SPEC.md §16, §17

## Context

M2-B adds Reddit as the first social source, contrasting with Wikipedia
(reference) and The Guardian (news). Reddit's API surface differs from both:

1. Reddit requires OAuth2 authentication even for search — there is no
   unauthenticated public search endpoint.
2. Posts are user-generated: titles, authors, and content are not curated or
   verified, and link posts carry outbound URLs that are not Reddit URLs.
3. Reddit may be blocked in some networks and its availability is less
   predictable than the news/reference APIs, so the adapter must fail cleanly
   and never degrade other sources.

## Decision

### 1. Official OAuth2 client-credentials flow only

`RedditAuth` exchanges `client_id` + `client_secret` for a bearer token via
`POST https://www.reddit.com/api/v1/access_token` (`grant_type=client_credentials`),
then searches `GET https://oauth.reddit.com/search` with `Authorization:
Bearer`. No scraping, no unauthenticated fallback, no third-party wrappers.

- Credentials come from pydantic-settings environment variables
  (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`) and are never logged or
  included in error messages or `raw` payloads.
- Missing credentials raise `SourceError(kind="failed")` **before any
  request**, so the source reports as unavailable rather than failing loudly.
- The token is cached for Reddit's reported lifetime minus a 60-second
  safety margin, and the cache is keyed by the credential pair so changing
  credentials invalidates it.
- The HTTP client is passed per call and owned by the adapter's `search()`
  (or the caller via `RedditAdapter(client=...)`), so no auth state ever
  references a closed client.

### 2. Canonical URLs never trust outbound link targets

A Reddit link post's `url` field points at an arbitrary external site.
`_canonical_url` prefers the API `permalink`, falls back to a constructed
`/r/{subreddit}/comments/{id}/` URL, and only then accepts a value that is
already a canonical `https://www.reddit.com/...` URL. External URLs are
never used as navigation targets.

### 3. Normalization rules for user-generated content

- `title`: required; whitespace-only titles are skipped.
- `author`: `[deleted]` and missing authors become `None`.
- `description`: `selftext` truncated to the 500-character canonical limit;
  empty -> `None`.
- `published_at`: `created_utc` epoch converted to UTC; unparseable ->
  `None`. Timestamps are never fabricated.
- `language`: `None` (Reddit does not expose language in the search API).
- `raw`: the post payload passed through `_strip_sensitive`, which
  recursively drops any key matching `token|secret|credential|authorization|password|api[-_]?key`.

### 4. Error classification

| Condition | `error_type` |
|---|---|
| timeout (token or search) | `timeout` |
| HTTP 429 (token or search) | `rate_limited` |
| HTTP 401/403 (token or search) | `failed` with a generic auth message |
| malformed JSON, missing `data.children`, network error | `failed` |

The registry, pipeline, API, and frontend are unchanged: Reddit registers
with `source_type = "social"`, `source_name = "Reddit"`, and the existing
`SourceChip`/`SourceStatusSummary` components render it generically.

### 5. Fixture-first verification; live verification deferred

Every test runs against respx-mocked fixtures; CI never touches Reddit.
The adapter is verified offline for auth, normalization, error paths, and
pipeline integration. Live verification against the real API is deferred
until Reddit application approval grants credentials for this project —
the configuration and `backend/README.md` describe exactly what to set.

## Consequences

- A search can now return reference, news, and social results through the
  same normalized model; per-source status, latency, and errors are exposed
  per ADR 0003.
- A Reddit outage or blocked network degrades only Reddit: the search
  stays `partial` with other sources intact.
- UGC provenance is preserved (`raw` + canonical URL + author), but nothing
  in the pipeline treats Reddit content as verified fact.
- 93 backend tests (23 of them Reddit-specific) and 13 frontend tests run
  fully offline.
- Operations must set `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` for Reddit
  to report success; until then it reports as unavailable.