# M8 — C4 normalization diagnostic

Fixed now: `2026-08-22T12:00:00+00:00` · replica verified against production `rank_items`.

### Scenario A — similar relevance

| rank | id | raw | norm_rel | fresh | qual | w_rel·rel | w_f·f | w_q·q | FINAL |
|---|---|---|---|---|---|---|---|---|---|
| 1 | a1 | 6 | 1.0 | 0.5832 | 0.9 | 0.55 | 0.175 | 0.135 | **0.86** |
| 2 | a2 | 6 | 1.0 | 0.4494 | 0.9 | 0.55 | 0.1348 | 0.135 | **0.8198** |
| 3 | a3 | 6 | 1.0 | 0.3492 | 0.9 | 0.55 | 0.1048 | 0.135 | **0.7898** |
| 4 | a4 | 2 | 0.3333 | 0.5115 | 0.5 | 0.1833 | 0.1534 | 0.075 | **0.4118** |

- All four contain ≥1 query term; raw spread 4-8; top doc defines scale.

### Scenario B — single outlier recompresses everyone

- b1: norm_rel 1.0 → 0.5714, final 0.8425 → 0.6068
- b2: norm_rel 0.375 → 0.2143, final 0.4761 → 0.3877

### Scenario C — strong-old vs weak-fresh (uncompressed)

- winner: `strong_old` · final gap: 0.2731

### Scenario D — exact phrase vs scattered tokens

- identical raw & components → order decided only by tie-break URL: ['phrase', 'scatter']
- C4 gives the consecutive phrase zero extra weight (motivates C5 test).

### Scenario E — one doc's raw jumps (+2-class event)

- top: norm_rel 1.0 → 0.6667, final 0.7712 → 0.5879
- mid: norm_rel 0.5 → 1.0, final 0.694 → 0.969
- low: norm_rel 0.0 → 0.0, final 0.4269 → 0.4269

- order before: ['top', 'mid', 'low'] → after: ['mid', 'top', 'low']
