# M3-D ranking experiment ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â combination formula, behavioural acceptance first

- Fixed now: `2026-08-19T12:00:00Z`; corpus revision 2, unchanged.
- Status: **research measurement only; NOT production ranking, NOT wired, NOT tuned**.

## 1. Components and candidates

- Relevance: naive lexical baseline, min-max normalised per search to [0, 1] (the ADR 0007 production core). BM25: not used.
- Freshness: the M3-C production scorer (accepted curve, bit-identical).
- Quality: {'The Guardian': 0.9, 'Wikipedia': 0.8, 'Global Wire': 0.85} (+ 0.50 for unknown sources); diversity band Ãƒâ€šÃ‚Â±0.05.

| candidate               | weights (rel/fresh/qual) per type                                                        | diversity |
| ----------------------- | ---------------------------------------------------------------------------------------- | --------- |
| C0_relevance_only       | {'news': (1.0, 0.0, 0.0), 'social': (1.0, 0.0, 0.0), 'reference': (1.0, 0.0, 0.0)}       | False     |
| C1_design               | {'news': (0.55, 0.3, 0.15), 'social': (0.55, 0.3, 0.15), 'reference': (0.65, 0.1, 0.25)} | False     |
| C2_balanced             | {'news': (0.5, 0.3, 0.2), 'social': (0.5, 0.3, 0.2), 'reference': (0.6, 0.15, 0.25)}     | False     |
| C3_relevance_heavy      | {'news': (0.7, 0.2, 0.1), 'social': (0.7, 0.2, 0.1), 'reference': (0.75, 0.1, 0.15)}     | False     |
| C4_design_diversity     | {'news': (0.55, 0.3, 0.15), 'social': (0.55, 0.3, 0.15), 'reference': (0.65, 0.1, 0.25)} | True      |
| M10_SEM1_semantic_blend | {'news': (0.55, 0.3, 0.15), 'social': (0.55, 0.3, 0.15), 'reference': (0.65, 0.1, 0.25)} | True      |

## 2. Behavioural acceptance tests (defined before corpus measurement)

| probe | behaviour                                                                                        | C0   | C1   | C2   | C3   | C4   |
| ----- | ------------------------------------------------------------------------------------------------ | ---- | ---- | ---- | ---- | ---- |
| P1    | fresh irrelevant 'Update' (4 h) must not outrank relevant (24 h)                                 | PASS | PASS | PASS | PASS | PASS |
| P2    | relevant 30 d old must outrank fresh 'Update' (4 h)                                              | PASS | PASS | PASS | PASS | PASS |
| P3    | Guardian before Reddit at equal relevance + freshness                                            | PASS | PASS | PASS | PASS | PASS |
| P4    | timeless authoritative reference beats fresh partial news; weak reference loses to relevant news | PASS | PASS | PASS | PASS | PASS |
| P5    | relevant without published_at outranks fresh 'Update'                                            | PASS | PASS | PASS | PASS | PASS |
| P6    | tie-break: URL lexicographic; deterministic                                                      | PASS | PASS | PASS | PASS | PASS |
| P7    | duplicate pair: equal scores, neighbours unchanged                                               | PASS | PASS | PASS | PASS | PASS |
| P8    | diversity alternates source types within the Ãƒâ€šÃ‚Â±0.05 band                                  | PASS | PASS | PASS | PASS | PASS |
| P9    | relevant 4 h old outranks relevant 30 d old                                                      | PASS | PASS | PASS | PASS | PASS |

All 9 probes must pass for a candidate to be admissible.

## 3. Corpus measurement (unchanged v2 corpus, secondary evidence)

Means over 16 queries (P@5, P@10, MRR, nDCG@10); the M3-A0 baseline is the reference:

| stage                   | P@5    | P@10   | MRR    | nDCG@10 | rel-0 in top-10 | fresh junk in top-10 |
| ----------------------- | ------ | ------ | ------ | ------- | --------------- | -------------------- |
| baseline (M3-A0)        | 0.7875 | 0.8250 | 0.8958 | 0.6909  | -               | -                    |
| C0_relevance_only       | 0.8250 | 0.8313 | 0.8333 | 0.6916  | 1.6875          | 0                    |
| C1_design               | 0.8750 | 0.8625 | 0.8750 | 0.7768  | 1.375           | 0.0625               |
| C2_balanced             | 0.8750 | 0.8625 | 0.8750 | 0.7766  | 1.375           | 0.0625               |
| C3_relevance_heavy      | 0.8500 | 0.8500 | 0.8438 | 0.7173  | 1.5             | 0                    |
| C4_design_diversity     | 0.8750 | 0.8688 | 0.8750 | 0.7850  | 1.3125          | 0.0625               |
| M10_SEM1_semantic_blend | 0.8875 | 0.8688 | 0.9062 | 0.8084  | 1.3125          | 0.0625               |

## 4. Observations

- Acceptance: every candidate clears the behavioural probes (the bar is behavioural, not metric).
- Corpus caveat: the v2 corpus timestamps correlate with relevance by authoring (M3-C, rho ÃƒÂ¢Ã¢â‚¬Â°Ã‹â€  0.41), so adding freshness can inflate corpus nDCG without meaning it is better: the probes are the controlled evidence, corpus numbers are indicative.
- Fresh junk: mean count of rel-0 items in the top 10 (and of those with freshness >= 0.7).
- Diversity is toggleable and only reorders within the Ãƒâ€šÃ‚Â±0.05 band (P8).
- No weights were tuned against the corpus; no production ranker was wired.
