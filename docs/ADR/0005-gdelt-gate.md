# ADR 0005: GDELT gate evaluation — NO-GO (not enabled)

- **Status:** Accepted (NO-GO)
- **Date:** 2026-08-19
- **Milestone:** M2-C
- **Related:** ADR 0002, 0003, 0004; PROJECT_SPEC.md §16, §17

## Context

The original specification listed GDELT as a candidate news source. M2-C was
run as an explicit go/no-go experiment rather than an automatic integration:
build the adapter to the same contract, then answer whether GDELT improves
SignalPulse enough to justify keeping it registered. The adapter
(`app/sources/gdelt.py`) queries GDELT DOC 2.0 `ArtList` mode — public, no
API key, `seendate` as the only timestamp.

The key risk identified up front: `seendate` is when GDELT *first saw* an
article, not its publication time. The adapter therefore never maps
`seendate` to `published_at` (always `None`), preserving it only in `raw` —
the same provenance rule established for Wikipedia.

## Evaluation (live, 2026-08-19)

Five identical queries were run through the real GDELT DOC 2.0 API and The
Guardian API ("artificial intelligence", "climate change", "electric
vehicles", "crypto regulation"), paced 45–90 s between GDELT calls per its
rate limit.

| Criterion | GDELT | Guardian |
|---|---|---|
| Success rate | 1 / 5 (20%); 4 × HTTP 429 | 5 / 5 (100%) |
| Response latency | 27.7 s success; 11–13 s per 429 | ~1.2 s |
| Language of results | 10/10 non-English (CN, ID, FR, DE, FI, TW) | 100% English |
| `published_at` | never available (seendate is first-seen) | real, per article |
| Result metadata | title, URL, domain, language, country; no description, no author | title, URL, description, author, published date |
| Relevance to query | several tangential hits (e.g. TV police-safety story returned for "electric vehicles") | on-topic journalism |
| Duplicate URLs | none observed in the one sample | none |
| Attribution | domain + sourcecountry available | publisher-only |

Findings:

1. **Reliability is the disqualifier.** 80% of paced requests failed with
   HTTP 429 even 45–90 s apart, and every response — success or error — took
   11–28 s. A registered GDELT source would either stall every search for
   ~12–28 s or report `rate_limited` most of the time. A source that is
   unavailable 80% of the time adds latency without coverage.
2. **Relevance is wrong for this product.** The only successful query
   returned 10/10 results in Chinese, Indonesian, French, German and Finnish
   from aggregator-style domains, with several off-topic titles. SignalPulse
   is English-first across its UI and its other sources.
3. **Timestamp trust.** `seendate` cannot be surfaced as a publication date
   (the original specification's concern is confirmed). This alone would
   make GDELT weaker than Guardian on every timeline-related feature.
4. **No compensating value.** The one differentiator — global multilingual
   reach — does not serve the current English-first user; GDELT adds no
   unique high-value English coverage that Guardian lacks.

## Decision

**NO-GO.** GDELT is removed from the active source registry. The architecture
remains intact: the adapter, fixtures, and offline tests stay in the
repository as a complete, working, tested component (`app/sources/gdelt.py`,
`tests/test_gdelt.py`, `tests/fixtures/gdelt_*.json`) that can be re-enabled
with a single `registry.register(...)` line if a multilingual / long-tail
use case or a reliable GDELT tier ever justifies it.

## Consequences

- The registry returns to Wikipedia + Guardian + Reddit; searches keep the
  established latency profile and English-first relevance.
- The GDELT adapter remains fully offline-tested (23 tests) and is safe to
  keep in the tree: it is never invoked by the pipeline or API.
- `SearchParams.window_hours` (added so the adapter could honor the search
  window) remains part of the generic adapter contract and is now passed by
  the pipeline to every source — a small, source-agnostic improvement.
- The evaluation data (this ADR) is the durable record of why GDELT is not
  enabled, preventing silent re-addition.