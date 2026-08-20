# ADR 0006: dedupe_key is a non-unique identification key (annotate-don't-delete)

- **Status:** Accepted
- **Date:** 2026-08-20
- **Milestone:** M3-A
- **Related:** ADR 0002, 0003, 0004; PROJECT_SPEC.md §12; docs/M3-retrieval-intelligence-design.md §9

## Context

The original specification (§12) declared `UNIQUE (search_id, dedupe_key)` on
the `results` table. That constraint was written under a "deduplicate-and-drop"
model: when duplicates were found, all but one row would be removed, so at most
one row per canonical URL could exist within a search.

M3-A (A2–A4) adopted an **annotate-don't-delete** model (design §2, §7): every
result keeps its own row, and duplicates are marked via `duplicate_group_id` /
`is_duplicate` and grouped in `duplicate_groups`. Under that model two (or
more) rows in the same search that are duplicates of each other must **both
exist** and legitimately share the same `dedupe_key`:

| search_id | dedupe_key | is_duplicate |
|---|---|---|
| 123 | abc123 | false |
| 123 | abc123 | true |
| 123 | abc123 | true |

The two requirements — preserve all provenance rows, yet enforce that a
canonical URL appears once per search — cannot both hold while the column is
unique. The constraint surfaced immediately when wiring the pipeline: persisting
`dedupe_key` on every row of a duplicate pair violated `UNIQUE (search_id,
dedupe_key)`.

## Decision

Remove `UNIQUE (search_id, dedupe_key)` from `results`.

`dedupe_key` identifies a canonicalized URL/result for deduplication purposes
and is **not** a uniqueness constraint. Multiple result rows within the same
search may legitimately share a `dedupe_key` because duplicates are annotated
rather than deleted.

Uniqueness of the deduplicated view is preserved in application logic, not the
schema: within a search, each `DuplicateGroup` has exactly one canonical member
(`canonical_result_id`) and every result belongs to at most one group.

## Consequences

- The `results` table no longer enforces per-search uniqueness of the
  canonicalized URL; group logic does.
- `duplicate_groups` (with `search_id`, `canonical_result_id`, `member_count`,
  `duplicate_evidence`) is the provenance container recording contributing
  sources per cluster (design §9, PROJECT_SPEC.md §12).
- No data migration is required: the constraint existed only in the original
  spec and in `create_all`-generated dev schemas; no released data is affected.
- Full test suites are green after the change: 172 backend tests, 44 eval
  tests, ruff clean on both.