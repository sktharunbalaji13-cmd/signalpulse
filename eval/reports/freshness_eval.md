# M3-C freshness experiment — candidate functions, measured independently

- Fixed now: `2026-08-19T12:00:00Z` (corpus `RETRIEVED`); corpus revision 2, unchanged.
- Status: **research measurement only; NOT production, NOT combined with relevance**.

## 1. Candidates

| name            | description                                              |
| --------------- | -------------------------------------------------------- |
| control_none    | no freshness (constant 1.0) — control                    |
| design          | §4 curve: exp 24h/12h, floor 0.05, ref 0.5, missing 0.25 |
| shape_linear30d | linear decay to floor over 30 days                       |
| shape_step      | step function: 1.0 / 0.7 / 0.4 / 0.2 bands               |
| hl_06h          | news 6h, social 3h half-life                             |
| hl_12h          | news 12h, social 6h half-life                            |
| hl_48h          | news 48h, social 24h half-life                           |
| hl_168h         | news 7d, social 3.5d half-life                           |
| floor_00        | exponential with floor 0.0                               |
| floor_25        | exponential with floor 0.25                              |
| ref_09          | reference constant 0.9 (never penalised)                 |
| miss_00         | missing timestamp scores 0.0                             |
| miss_05         | missing timestamp scores 0.5                             |
| social_24       | social half-life 24h (same as news)                      |

## 2. Admissibility gate (all four invariants must pass)

| name            | missing_handled | no_retrieved_substitution | monotonic | future_clamped |
| --------------- | --------------- | ------------------------- | --------- | -------------- |
| control_none    | True            | True                      | True      | True           |
| design          | True            | True                      | True      | True           |
| shape_linear30d | True            | True                      | True      | True           |
| shape_step      | True            | True                      | True      | True           |
| hl_06h          | True            | True                      | True      | True           |
| hl_12h          | True            | True                      | True      | True           |
| hl_48h          | True            | True                      | True      | True           |
| hl_168h         | True            | True                      | True      | True           |
| floor_00        | True            | True                      | True      | True           |
| floor_25        | True            | True                      | True      | True           |
| ref_09          | True            | True                      | True      | True           |
| miss_00         | True            | True                      | True      | True           |
| miss_05         | True            | True                      | True      | True           |
| social_24       | True            | True                      | True      | True           |

Passed by all candidates: 14/14 (`control_none`, `design`, `shape_linear30d`, `shape_step`, `hl_06h`, `hl_12h`, `hl_48h`, `hl_168h`, `floor_00`, `floor_25`, `ref_09`, `miss_00`, `miss_05`, `social_24`).

## 3. Corpus behaviour (unchanged v2 corpus, fixed now)

- 365 items; timestamps span at most 6 days, so the corpus only exercises the steep (breaking-news) part of any decay curve — long-age behaviour is probed in §4.

Freshest 10 items (these are the very-recent-but-weakly-relevant population):

| id     | title                                      | type | rel | age_h |
| ------ | ------------------------------------------ | ---- | --- | ----- |
| q01_14 | Update                                     | news | 0   | 4.0   |
| q02_18 | Update                                     | news | 0   | 5.0   |
| q03_08 | Update                                     | news | 0   | 6.0   |
| q03_19 | Weather forecast: warm and sunny this week | news | 0   | 7.0   |
| q04_09 | Update                                     | news | 0   | 8.0   |
| q05_08 | Update                                     | news | 0   | 9.0   |
| q06_08 | Update                                     | news | 0   | 10.0  |
| q07_08 | Update                                     | news | 0   | 11.0  |
| q08_08 | Update                                     | news | 0   | 11.5  |
| q09_08 | Update                                     | news | 0   | 13.0  |

Per candidate (per-source-type stats, plus the two tensions):

| name            | news min/med/max     | news %<0.5 | social min/med/max   | ref med | rel0 fresh>=0.9 | rel0 fresh>=0.7 | rel>=1 fresh<0.5 |
| --------------- | -------------------- | ---------- | -------------------- | ------- | --------------- | --------------- | ---------------- |
| control_none    | 1.0/1.0/1.0          | 0.0        | 1.0/1.0/1.0          | 0.5     | 109             | 109             | 0                |
| design          | 0.0632/0.3016/0.8964 | 87.0       | 0.0537/0.1443/0.3324 | 0.5     | 0               | 10              | 191              |
| shape_linear30d | 0.8047/0.9393/0.9947 | 0.0        | 0.8733/0.9472/0.9723 | 0.5     | 58              | 109             | 0                |
| shape_step      | 0.7/0.7/1.0          | 0.0        | 0.7/0.7/1.0          | 0.5     | 18              | 109             | 0                |
| hl_06h          | 0.05/0.0547/0.6485   | 98.9       | 0.05/0.0501/0.0574   | 0.5     | 0               | 0               | 210              |
| hl_12h          | 0.0502/0.1166/0.804  | 96.8       | 0.05/0.0594/0.134    | 0.5     | 0               | 3               | 210              |
| hl_48h          | 0.1621/0.5389/0.9467 | 38.7       | 0.1094/0.3492/0.568  | 0.5     | 4               | 18              | 77               |
| hl_168h         | 0.5659/0.8358/0.9845 | 0.0        | 0.4802/0.7329/0.8489 | 0.5     | 18              | 60              | 0                |
| floor_00        | 0.0139/0.2649/0.8909 | 88.7       | 0.0039/0.0992/0.2973 | 0.5     | 0               | 9               | 196              |
| floor_25        | 0.2604/0.4486/0.9182 | 51.1       | 0.2529/0.3244/0.473  | 0.5     | 1               | 14              | 93               |
| ref_09          | 0.0632/0.3016/0.8964 | 87.0       | 0.0537/0.1443/0.3324 | 0.9     | 1               | 11              | 191              |
| miss_00         | 0.0632/0.3016/0.8964 | 87.0       | 0.0537/0.1443/0.3324 | 0.5     | 0               | 10              | 191              |
| miss_05         | 0.0632/0.3016/0.8964 | 87.0       | 0.0537/0.1443/0.3324 | 0.5     | 0               | 10              | 191              |
| social_24       | 0.0632/0.3016/0.8964 | 87.0       | 0.1094/0.3492/0.568  | 0.5     | 0               | 10              | 189              |

## 4. Controlled probes (fixed timestamps; 0 h = now)

News decay curves (age in hours):

| name            | 0.0 | 1.0    | 12.0   | 24.0   | 48.0   | 168.0  | 720.0  | 8760.0 | 17520.0 |
| --------------- | --- | ------ | ------ | ------ | ------ | ------ | ------ | ------ | ------- |
| control_none    | 1.0 | 1.0    | 1.0    | 1.0    | 1.0    | 1.0    | 1.0    | 1.0    | 1.0     |
| design          | 1.0 | 0.973  | 0.7218 | 0.525  | 0.2875 | 0.0574 | 0.05   | 0.05   | 0.05    |
| shape_linear30d | 1.0 | 0.9987 | 0.9842 | 0.9683 | 0.9367 | 0.7783 | 0.05   | 0.05   | 0.05    |
| shape_step      | 1.0 | 1.0    | 1.0    | 0.7    | 0.7    | 0.4    | 0.2    | 0.2    | 0.2     |
| hl_06h          | 1.0 | 0.8964 | 0.2875 | 0.1094 | 0.0537 | 0.05   | 0.05   | 0.05   | 0.05    |
| hl_12h          | 1.0 | 0.9467 | 0.525  | 0.2875 | 0.1094 | 0.0501 | 0.05   | 0.05   | 0.05    |
| hl_48h          | 1.0 | 0.9864 | 0.8489 | 0.7218 | 0.525  | 0.134  | 0.05   | 0.05   | 0.05    |
| hl_168h         | 1.0 | 0.9961 | 0.9541 | 0.9104 | 0.8293 | 0.525  | 0.0987 | 0.05   | 0.05    |
| floor_00        | 1.0 | 0.9715 | 0.7071 | 0.5    | 0.25   | 0.0078 | 0.0    | 0.0    | 0.0     |
| floor_25        | 1.0 | 0.9786 | 0.7803 | 0.625  | 0.4375 | 0.2559 | 0.25   | 0.25   | 0.25    |
| ref_09          | 1.0 | 0.973  | 0.7218 | 0.525  | 0.2875 | 0.0574 | 0.05   | 0.05   | 0.05    |
| miss_00         | 1.0 | 0.973  | 0.7218 | 0.525  | 0.2875 | 0.0574 | 0.05   | 0.05   | 0.05    |
| miss_05         | 1.0 | 0.973  | 0.7218 | 0.525  | 0.2875 | 0.0574 | 0.05   | 0.05   | 0.05    |
| social_24       | 1.0 | 0.973  | 0.7218 | 0.525  | 0.2875 | 0.0574 | 0.05   | 0.05   | 0.05    |

Per-candidate probe summary:

| name            | ref@now | ref@2y | future | future==now | missing news/social/ref |
| --------------- | ------- | ------ | ------ | ----------- | ----------------------- |
| control_none    | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| design          | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| shape_linear30d | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| shape_step      | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| hl_06h          | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| hl_12h          | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| hl_48h          | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| hl_168h         | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| floor_00        | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| floor_25        | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |
| ref_09          | 0.9     | 0.9    | 1.0    | True        | 0.25/0.25/0.9           |
| miss_00         | 0.5     | 0.5    | 1.0    | True        | 0.0/0.0/0.5             |
| miss_05         | 0.5     | 0.5    | 1.0    | True        | 0.5/0.5/0.5             |
| social_24       | 0.5     | 0.5    | 1.0    | True        | 0.25/0.25/0.5           |

## 5. Interaction with relevance (analysis only — NO combination)

Spearman between candidate freshness and gold relevance, overall and per type (`constant (no variance)` = no rank variance in that group):

| name            | spearman overall | news                   | social                 | reference              |
| --------------- | ---------------- | ---------------------- | ---------------------- | ---------------------- |
| control_none    | -0.1489          | constant (no variance) | constant (no variance) | constant (no variance) |
| design          | 0.407            | 0.4522                 | 0.3623                 | constant (no variance) |
| shape_linear30d | 0.2709           | 0.4522                 | 0.3623                 | constant (no variance) |
| shape_step      | -0.1914          | -0.1354                | 0.0372                 | constant (no variance) |
| hl_06h          | 0.4307           | 0.4522                 | 0.3623                 | constant (no variance) |
| hl_12h          | 0.4186           | 0.4522                 | 0.3623                 | constant (no variance) |
| hl_48h          | 0.4312           | 0.4522                 | 0.3623                 | constant (no variance) |
| hl_168h         | 0.2674           | 0.4522                 | 0.3623                 | constant (no variance) |
| floor_00        | 0.4052           | 0.4522                 | 0.3623                 | constant (no variance) |
| floor_25        | 0.4779           | 0.4522                 | 0.3623                 | constant (no variance) |
| ref_09          | 0.4367           | 0.4522                 | 0.3623                 | constant (no variance) |
| miss_00         | 0.407            | 0.4522                 | 0.3623                 | constant (no variance) |
| miss_05         | 0.407            | 0.4522                 | 0.3623                 | constant (no variance) |
| social_24       | 0.4116           | 0.4522                 | 0.3623                 | constant (no variance) |

## 6. Observations

- All 14 candidates pass the admissibility gate; the choice is behavioural, not mechanical.
- The corpus timestamps span only 0.2–6 days and are dominated by 1–6-day-old items: under the design 24 h half-life, 87% of news scores below 0.5 and 191 relevant items score below 0.5. The curve behaves as specified (see probes); this is a property of the corpus's age distribution, and it is exactly the distribution M3-D weighting must be validated against.
- Within a source type, every monotone candidate (exp/linear/hl/floor variants) has the same Spearman vs relevance (news 0.4522, social 0.3623): rank correlation is invariant to monotone transforms, so curve shape changes only score spacing, never order within a type. Only non-monotone shapes (step) or per-type constants change the interaction.
- The measured overall Spearman (0.41 for design) reflects how the corpus was authored (timestamps were written to look realistic, not randomised against relevance). The corpus is not designed to isolate freshness from relevance, so the interaction numbers are indicative, not causal; the controlled probes (§4) are the definitive measurements.
- Decoy tension: the freshest 10 items (§3) are rel-0/rel-1 near-miss or 'Update' items — the very-recent-but-weakly-relevant population a combined ranker must not let dominate. Under the design curve none of them reach 0.9 (the freshest is ~5 h old, scoring 0.88), which is the separation the curve provides at M3-D combination time.
- Reference timelessness holds for every candidate: a 2-year-old reference item scores exactly like a fresh one; missing timestamps score the documented neutral (0.25 news/social, 0.5 reference) instead of zero or a retrieved_at substitution.
- No combined ranking is computed anywhere in this experiment.
