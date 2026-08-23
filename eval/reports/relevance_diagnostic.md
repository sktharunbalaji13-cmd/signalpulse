# M9 - C4 relevance signal diagnostic

- corpus revision 2
- equal-raw tie groups: 85; label-split: 63 across 16/16 queries
- separable within split groups - title-tf: 2, description-tf: 2, coverage-ratio: 2, any: 2

## Part 1 - controlled scenarios

### Scenario A - frequency blindness (query: ai safety)

| doc | raw (C4) | title-tf | desc-tf | coverage |
|---|---|---|---|---|
| once | 6 | 2 | 0 | 1.00 |
| twice | 6 | 4 | 0 | 1.00 |
| five | 6 | 6 | 0 | 1.00 |

- raw identical for 1x/2x/5x occurrences: term FREQUENCY is invisible.

### Scenario B - coverage tiers (query: artificial intelligence safety)

| doc | raw (C4) | title-tf | desc-tf | coverage |
|---|---|---|---|---|
| 3/3 title | 9 | 3 | 0 | 1.00 |
| 2/3 title | 6 | 2 | 0 | 0.67 |
| 1/3 title | 3 | 1 | 0 | 0.33 |

- 9 > 6 > 3: per-term reward linear; different coverages do NOT tie here.
- Placement asymmetry follows in Scenario C.

### Scenario C - title vs description placement

| doc | raw (C4) | title-tf | desc-tf | coverage |
|---|---|---|---|---|
| all title | 9 | 3 | 0 | 1.00 |
| all description | 3 | 0 | 3 | 0.00 |
| split t2+d1 | 7 | 2 | 1 | 0.67 |

- all-in-description (3) TIES one single title hit (3): placement collapse.
- split t2+d1 (7) outranks pure-title-partial (6): composition matters.

### Scenario D - phrase vs scattered vs partial (3-term query)

| doc | raw (C4) | title-tf | desc-tf | coverage |
|---|---|---|---|---|
| phrase | 6 | 2 | 0 | 0.67 |
| scattered | 9 | 3 | 0 | 1.00 |
| partial | 6 | 2 | 0 | 0.67 |

- phrase == scattered (both 9): adjacency invisible (M7 confirmed; not retried).
- both beat partial (6): full coverage rewarded.

### Scenario E - description length invariance (query: ai safety)

| doc | raw (C4) | title-tf | desc-tf | coverage |
|---|---|---|---|---|
| short desc | 2 | 0 | 2 | 0.00 |
| long desc | 2 | 0 | 2 | 0.00 |

- Same hits regardless of length: length-invariant by design (defensible).

## Part 2 - frozen corpus v2: equal-raw groups with differing gold labels

- equal-raw groups (>=2 items): **85**
- groups whose gold labels DIFFER (information collapsed by binary presence): **63** across 16/16 queries
- separable by unused title-tf: **2** · description-tf: **2** · title-coverage-ratio: **2** · any-of-those: **2**

First examples encountered (deterministic order, not selected):
- `q01_ev_battery_recycling` raw=7: q01_05(rel=1,ttf=2,dtf=1); q01_12(rel=2,ttf=2,dtf=1); q01_20(rel=2,ttf=2,dtf=1)
- `q01_ev_battery_recycling` raw=6: q01_01(rel=2,ttf=2,dtf=0); q01_02(rel=2,ttf=2,dtf=0); q01_22(rel=1,ttf=2,dtf=0); q01_23(rel=0,ttf=2,dtf=0)
- `q01_ev_battery_recycling` raw=5: q01_06(rel=1,ttf=1,dtf=2); q01_07(rel=0,ttf=1,dtf=2)
- `q01_ev_battery_recycling` raw=4: q01_03(rel=2,ttf=1,dtf=1); q01_15(rel=1,ttf=1,dtf=1)
- `q01_ev_battery_recycling` raw=0: q01_10(rel=2,ttf=0,dtf=0); q01_11(rel=2,ttf=0,dtf=0); q01_13(rel=2,ttf=0,dtf=0); q01_14(rel=0,ttf=0,dtf=0); q01_16(rel=0,ttf=0,dtf=0); q01_18(rel=1,ttf=0,dtf=0)
- `q02_quantum_computing` raw=6: q02_21(rel=0,ttf=2,dtf=0); q02_22(rel=1,ttf=2,dtf=0)
- `q02_quantum_computing` raw=4: q02_09(rel=1,ttf=1,dtf=1); q02_13(rel=1,ttf=1,dtf=1); q02_19(rel=1,ttf=1,dtf=1); q02_23(rel=0,ttf=1,dtf=1)
- `q02_quantum_computing` raw=3: q02_01(rel=2,ttf=1,dtf=0); q02_02(rel=2,ttf=1,dtf=0); q02_03(rel=2,ttf=1,dtf=0); q02_05(rel=1,ttf=1,dtf=0); q02_06(rel=1,ttf=1,dtf=0); q02_08(rel=1,ttf=1,dtf=0); q02_11(rel=2,ttf=1,dtf=0); q02_12(rel=2,ttf=1,dtf=0); q02_15(rel=1,ttf=1,dtf=0); q02_17(rel=2,ttf=1,dtf=0)
- `q02_quantum_computing` raw=1: q02_07(rel=0,ttf=0,dtf=1); q02_14(rel=1,ttf=0,dtf=1)
- `q02_quantum_computing` raw=0: q02_10(rel=0,ttf=0,dtf=0); q02_16(rel=0,ttf=0,dtf=0); q02_18(rel=0,ttf=0,dtf=0); q02_20(rel=1,ttf=0,dtf=0)
