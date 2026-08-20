# M3-E filter experiment — query-time result controls, behavioural acceptance first

- Fixed now: `2026-08-19T12:00:00Z`; corpus revision 2, unchanged.
- Ranking: accepted M3-D C4 model (frozen), rank_position is the single source of truth.
- Status: **design + measurement only; NOT implemented, NOT wired**.

## 1. Designed view semantics (API query params, zero schema change)

- `source_type` (repeatable): membership in the requested verticals.
- `time=24h|7d|30d|all`: hard age window on `published_at` for **news/social only**; reference always included (timeless context); NULL `published_at` excluded except `all`. No hard freshness-score filter: freshness is a soft weighted signal (M3-C).
- `duplicates=all|canonical`: canonical view hides `is_duplicate` members; group metadata is not reduced.
- `language`: exact match on the stored column; NULL-language rows excluded while active.
- Invalid values are rejected explicitly (HTTP 422 in production); pagination is over the filtered view.

## 2. Behavioural acceptance tests (defined before corpus measurement)

| probe | behaviour                                                                      | result |
| ----- | ------------------------------------------------------------------------------ | ------ |
| P1    | filtered subset order == projection of the full C4 order; scores unchanged     | PASS   |
| P2    | source_type vertical filter: membership, OR repeats, empty view                | PASS   |
| P3    | time window semantics: type scoping, reference timelessness, NULL published_at | PASS   |
| P4    | time filter preserves the order of the kept set                                | PASS   |
| P5    | duplicates=canonical hides members without touching group metadata             | PASS   |
| P6    | filtered-out canonical does not cascade; members remain valid rows             | PASS   |
| P7    | invalid filter values fail explicitly (422-class), never silently              | PASS   |
| P8    | deterministic view + deterministic pagination over the filtered set            | PASS   |
| P9    | graceful degradation on partial results; filters never retrieve                | PASS   |
| P10   | filters are read-only: stored rows bit-identical (provenance invariant)        | PASS   |
| P11   | language filter: exact match, NULL excluded, invalid code rejected             | PASS   |

All 11 probes must pass for the design to be admissible.

## 3. Corpus measurement (unchanged v2 corpus, C4-ranked)

Means over 16 queries. nDCG@10/P@10/MRR are computed on the filtered view against the full-query ideal, so narrow filters score low even when every kept item is relevant — read them together with the coverage columns. Duplicate annotations use the harness canonical approximation (min by source_name, url); view semantics are independent of which member is canonical (P5/P6):

| config                  | kept | share | rel1-cov | rel2-cov | nDCG@10 | P@10   | MRR    | rel0@10 | fresh-junk@10 |
| ----------------------- | ---- | ----- | -------- | -------- | ------- | ------ | ------ | ------- | ------------- |
| F0_default              | 22.8 | 1.00  | 1.000    | 1.000    | 0.7850  | 0.8688 | 0.8750 | 1.31    | 0.06          |
| F1_news_only            | 17.8 | 0.78  | 0.699    | 0.852    | 0.7244  | 0.7938 | 0.7708 | 2.06    | 0.19          |
| F2_social_only          | 2.2  | 0.10  | 0.123    | 0.014    | 0.1436  | 0.1938 | 0.9688 | 0.25    | 0.00          |
| F3_reference_only       | 2.9  | 0.13  | 0.177    | 0.134    | 0.3317  | 0.2812 | 1.0000 | 0.06    | 0.00          |
| F4_time_24h             | 5.0  | 0.22  | 0.238    | 0.195    | 0.3710  | 0.3625 | 1.0000 | 1.12    | 0.56          |
| F5_time_7d              | 22.8 | 1.00  | 1.000    | 1.000    | 0.7850  | 0.8688 | 0.8750 | 1.31    | 0.06          |
| F6_time_30d             | 22.8 | 1.00  | 1.000    | 1.000    | 0.7850  | 0.8688 | 0.8750 | 1.31    | 0.06          |
| F7_duplicates_canonical | 18.4 | 0.81  | 0.729    | 0.368    | 0.5150  | 0.7375 | 0.8750 | 2.62    | 0.31          |
| F8_news_time_7d         | 17.8 | 0.78  | 0.699    | 0.852    | 0.7244  | 0.7938 | 0.7708 | 2.06    | 0.19          |
| F9_news_social_time_24h | 2.1  | 0.09  | 0.061    | 0.060    | 0.0798  | 0.0938 | 0.2188 | 1.12    | 0.62          |
| F10_language_en         | 20.6 | 0.90  | 0.877    | 0.986    | 0.7875  | 0.8438 | 0.8750 | 1.56    | 0.12          |

## 4. Language filter coverage (real-source metadata map)

Rows carrying a `language` value today: 330 of 365 (90.4%). By source:

| source                | rows | en  | null |
| --------------------- | ---- | --- | ---- |
| Global Wire           | 67   | 67  | 0    |
| The Guardian          | 217  | 217 | 0    |
| Wikipedia             | 46   | 46  | 0    |
| r/science (Reddit)    | 14   | 0   | 14   |
| r/technology (Reddit) | 19   | 0   | 19   |
| r/worldnews (Reddit)  | 2    | 0   | 2    |

## 5. Observations

- All 11 behavioural probes pass: filtered subsets stay correctly ranked, provenance is untouched, invalid filters fail explicitly, pagination is deterministic, partial results degrade gracefully.
- Vertical filters (F1-F3) are pure projections: their metrics are the C4 list restricted to a type, with no re-ranking. Social-only (F2) and reference-only (F3) are narrow views (2.2 and 2.9 kept items on average) — expected for a news-dominant corpus.
- Time windows (F4-F6): `24h` keeps ~22% of items and ~20% of rel-2 coverage (a genuinely recent view); `7d`/`30d` barely reduce this corpus because its items are authored fresh (honest corpus property, not a filter weakness). Reference context survives every window (timeless by design).
- `duplicates=canonical` (F7) hides duplicate members, so rel-coverage undercounts stories: every story is still present once (canonical member kept); the drop reflects duplicate members that carried rel-2 labels, not lost stories.
- Language (F10) is honest but costly today: 330/365 rows (90.4%) carry a language value, but social rows have none, so `language=en` excludes the entire social vertical. On this corpus the en view keeps nDCG@10 0.7875 (slightly above F0) — the drop of social rows happens to remove junk. Decision for implementation: ship the filter with this documented behaviour; enriching metadata is an M3.5/M4 concern.
- The view is a read-only SELECT over `rank_position`: no re-ranking, no re-normalisation, no writes, no retrieval — no filter can cause an indefinite search.
