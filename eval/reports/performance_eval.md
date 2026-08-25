# M3.5 reliability & performance measurement — current pipeline vs locked targets

- Status: **design + measurement; pipeline-level source timeout IMPLEMENTED (design 15.3.1), production otherwise unchanged**.
- Pipeline-level source timeout: `4.5` s (asyncio.wait_for per source; a hung adapter is cancelled, so no indefinite search).
- Locked targets: submission < 500 ms; first useful results <= 3000 ms; completed <= 5000 ms; source timeout ~5 s; no indefinite searches.
- Controlled delays: fast 0.4 s, slow 2.0 s (proportionally below the real ~5 s timeouts).

## 1. Probes (controlled, measured against the current production pipeline)

| probe | behaviour                                                                                            | measured                                                                                                            | result |
| ----- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------ |
| P1    | submission cost < 500 ms                                                                             | {'submission_ms': 11.62}                                                                                            | PASS   |
| P2    | happy path: first results <= 3 s, completed <= 5 s, progressive (first < done)                       | {'submission_ms': 10.88, 'first_ms': 494.63660013861954, 'done_ms': 568.49, 'duration_ms': 505, 'result_count': 13} | PASS   |
| P3    | slow source does not hold the fast sources hostage (concurrent isolation)                            | {'first_ms': 502.76400009170175, 'done_ms': 2135.04, 'slow_delay_ms': 2000.0}                                       | PASS   |
| P4    | a timing-out source is recorded and does not block the job (no indefinite wait for a failing source) | {'done_ms': 539.1}                                                                                                  | PASS   |
| P5    | one source down -> useful partial results                                                            | {'done_ms': 529.34, 'result_count': 3}                                                                              | PASS   |
| P6    | all sources down -> clear failed state, zero results, per-source errors                              | {'done_ms': 488.51}                                                                                                 | PASS   |
| P7    | every scenario terminates within the deadline (no indefinite search in the probe matrix)             | {'max_done_ms': 2135.04}                                                                                            | PASS   |
| P8    | identical repeat searches -> identical results (cacheability evidence)                               | {'result_count': 8}                                                                                                 | PASS   |
| P9    | 4 concurrent searches complete correctly within a bounded wall clock                                 | {'wall_ms': 837.79, 'throughput': 4.77, 'statuses': ['completed', 'completed', 'completed', 'completed']}           | PASS   |
| P10   | results endpoint latency with a large result set (p50 < 500 ms)                                      | {'p50_ms': 14.9}                                                                                                    | PASS   |
| P11   | credentials never exposed in API responses (backend-only)                                            | {'leaked_urls': []}                                                                                                 | PASS   |
| P12   | post-pass (dedup + ranking) budget stays small at ~90 rows                                           | {'postpass_ms': 100, 'total_ms': 515, 'rows': 90}                                                                   | PASS   |
| P13   | worst case: a hung source is bounded by the pipeline timeout; completed within the <= 5 s budget     | {'timeout_s': 1.0, 'sources_ms': 1028, 'postpass_ms': 53, 'completed_ms': 1128.88, 'status': 'partial'}             | PASS   |

All 13 probes must pass; a FAIL is a finding to close in the M3.5 implementation checkpoint.

## 2. Findings

- Submission is a DB insert (P1) — comfortably under 500 ms.
- Happy path is progressive (P2): first useful results appear well before completion and both are within the 3 s / 5 s targets when sources are fast.
- Slow-source isolation holds (P3): a slow source does not delay the fast ones; a timing-out or failing source is recorded and does not block completion (P4/P5); all-sources-down gives a clear failed state with zero results (P6).
- Every scenario terminates within the deadline (P7) — and now the pipeline enforces a per-source ``asyncio.wait_for`` (P13): a source that hangs without raising is cancelled and recorded as a timeout, so 'no indefinite search' is a hard guarantee independent of adapter behaviour.
- Post-pass (dedup + ranking) budget is small at ~90 rows (P12); worst case completed = source timeout (4.5 s configured) + post-pass + margin stays within the locked <= 5 s target (P13).
- Repeat searches are deterministic (P8) => completed results are cacheable; caching is deferred until implemented and measured to help (§15.3.5).
- Concurrent searches complete correctly (P9) on SQLite at this scale; watch for write contention at higher N / under M4 hosting.
- Results endpoint is fast on a 60-row set (P10); credentials never appear in API responses (P11).
