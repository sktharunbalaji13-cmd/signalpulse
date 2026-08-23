# ADR 0014: Hacker News as a fourth production source

- **Status:** Accepted
- **Date:** 2026-08-23
- **Milestone:** M17.5.1
- **Related:** M17.5 audit; ADR 0002–0004 (source integrations); ADR 0005 (GDELT gate precedent); ADR 0007 (BM25 not used)

## Context

The M16.0 roadmap identified source coverage as the next product gap. The
M17.5 read-only audit evaluated candidate sources and recommended **Hacker
News via the public Algolia HN Search API**, based on measured evidence:

- Keyless, auth-free public endpoint (`hn.algolia.com/api/v1/search`);
  ~10k requests/hour/IP courtesy budget vs SignalPulse's ~1 request per
  search (~50/day) — usage is a rounding error.
- Live probes (M17.5): HTTP 200 in ~1.7 s cold / ~0.7 s warm for a real
  query with `tags=story`; server-side `numericFilters=created_at_i>`
  confirmed working — a clean mapping for `SearchParams.window_hours`.
- Hit shape covers everything `SourceResult` needs: title, url, author,
  `created_at_i` (real publication timestamp), `story_text`.

The Firebase official API was **not** selected: it has no keyword-search
capability at all (ID lookups only), so it cannot implement `search()`
without an impossible crawl-first design.

## Decision

1. **Register `hacker_news` → `HackerNewsAdapter`** as the fourth production
   source. `source_type="news"`: HN predominantly links to external
   journalism/technical content; the existing freshness model supports news
   out of the box and no new type is introduced (a new type would require a
   deliberate freshness-model change per its own validation).
2. **Result mapping:** `title` (blank titles skipped), external `url` when
   present else the stable discussion link built from `objectID` (mirrors
   Reddit's canonical-URL rule), null-safe `author`, UTC `published_at` from
   `created_at_i` (never fabricated), `story_text[:500]` or `None`,
   `language=None`, full hit JSON preserved verbatim as provenance.
3. **Error handling follows house convention:** timeout → `timeout`;
   HTTP 429 → `rate_limited`; other HTTP/network/malformed → `failed`; empty
   result sets are successes with zero results. One request per search, no
   pagination beyond `hitsPerPage`, no retries.
4. **No credentials** — nothing to configure in any environment.

## Consequences

- Every search now fans out to four sources. Wikipedia/Guardian/Reddit paths,
  C4 ranking, deduplication, filtering, retention, and the frontend required
  **zero changes**; pipeline integration tests gained explicit HN mocks and
  two assertions updated (source-event set/count 3→4).
- Cross-source duplicate detection improves without code change: when HN and
  Guardian link the same article, existing canonical-URL dedup annotates them
  into one group.
- Ranking impact is inherently bounded: default quality 0.50 (unknown-name
  default), title-only lexical relevance for link posts, and the ±0.05 band
  round-robin prevent dominance. No `SOURCE_QUALITY["Hacker News"]` entry yet;
  adding one is a separate, eval-gated decision if ever justified.
- Privacy: hits are public story metadata from a keyless endpoint — nothing
  credential-shaped can appear, so raw payloads are stored verbatim. Author
  usernames are nullable public handles, treated like Reddit's under the
  30-day retention policy ([ADR 0013](0013-data-retention-policy.md)).

Measured vs assumed: latency/yield/rate-budget figures above were **measured**
in M17.5 live probes; quality-ranking behavior within C4 is **verified by
construction from code** (weights/constants) and will be observable in
production telemetry after deployment.
