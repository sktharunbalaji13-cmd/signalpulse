# ADR 0002: Canonical source contract and Wikipedia integration (M1 step 1)

- **Status:** Accepted
- **Date:** 2026-08-19
- **Related spec:** PROJECT_SPEC.md v0.2 (§10, §15, §16, §25)

## Context

M1 builds the first vertical slice: query → Wikipedia adapter → canonical
results. Two things must be fixed before any source code beyond the scaffold:

1. The canonical model every source must produce.
2. The adapter interface + registry that keep the application independent of
   any single source's response format.

The validated source set (Appendix A) means Guardian, GDELT, and Reddit will
arrive in later milestones — the contract must be ready for them without
rework.

## Decision

### Canonical `SourceResult` (exactly the spec fields, no additions)
`source_type`, `source_name`, `title`, `description`, `url`, `author`,
`published_at`, `retrieved_at`, `language`, `raw`. Rules: `published_at` is
`Optional` and defaults to `None` (never guessed); `retrieved_at` is mandatory
and always set by our system in UTC; `raw` is mandatory and preserves the
untouched API payload for provenance (PROJECT_SPEC.md §16). The only extra type
introduced is a minimal `SearchParams` (`limit`) — required to give the
interface a typed signature without inventing source-specific options.

### Minimal adapter interface
`BaseSourceAdapter` is an ABC with one abstract method,
`async search(query, params) -> list[SourceResult]`. No generic base classes,
no plug-in frameworks, no `get_status()` yet — the spec allows it later when
`/api/v1/sources` health reporting is built (§10, §25).

### Registry with a default instance
`SourceRegistry` maps name → adapter; the module registers `wikipedia` at
import time. Future adapters change one line here and nothing else.

### Wikipedia via the official action API
`generator=search` + `prop=extracts` in a single `w/api.php` request. No HTML
scraping, no API key, configurable User-Agent (`WIKIPEDIA_USER_AGENT`),
`maxlag=5`, 5 s default timeout. `published_at` stays `None` — the search API's
timestamp is last-edit time, which is not a trustworthy publication time.

### Temporary direct endpoint
`GET /api/v1/sources/{source_name}/search?q=...` invokes the adapter through
the registry synchronously. It proves the adapter works; it is explicitly
temporary — M1 step 2 replaces it with the job/polling pipeline, background
tasks, and DB persistence from the spec (§8, §9, §31).

## Consequences

- The application layer never sees Wikipedia's response format — only
  `SourceResult`.
- Adding Guardian/GDELT/Reddit later touches only `sources/` + the registry.
- Wikipedia gives no `published_at`; freshness scoring (M1 step 3 / §18) will
  fall back to `retrieved_at` — already accounted for in §19.
- The direct endpoint is not the final search API and will not be expanded.