# Technical Debt Register

## TZ-001: SQLite drops timezone information on datetime round-trip

- **Status:** Open (accepted debt)
- **Discovered:** M2-A live verification (2026-08-19)
- **Impact:** `published_at` / `retrieved_at` are normalized to UTC by the
  adapters (verified in tests), but SQLite does not store tzinfo, so rows read
  back serialize without a timezone marker (e.g. `2026-04-10T00:52:48` instead
  of `...Z`). Browser-side `new Date()` then interprets them as local time,
  shifting display by the UTC offset.
- **Why not fixed now:** M2-B scope discipline; a fix touches the persistence
  / serialization path and needs deliberate design (e.g. store naive-UTC and
  emit an explicit UTC marker in API schemas, or add a real migration layer).
- **Address before:** production deployment and/or the PostgreSQL/Neon
  migration (PostgreSQL `timestamptz` round-trips correctly, but the fix
  should be deliberate either way).
