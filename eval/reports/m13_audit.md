# M13.0 - Production Observability & Security Audit

## Phase 1 - Live Deployment Verification

- Health: 200 | db=ok | status=ok
- Admin stats endpoint present: True (status 200)
- Bogus window -> 422 (expected 422)
- Deployment verified as post-M12: YES

## Phase 2 - Production Statistics

### Window: 24h
- Total searches: 38
- By status: {"partial": 38}
- Latency p50/p95/p99: 1047.0 / 1594.0 / 1688.0
  - Reddit: avg_latency_ms=175, failed=38
  - The Guardian: avg_latency_ms=1082, avg_results=9, success=38
  - Wikipedia: avg_latency_ms=604, avg_results=9, success=38
- Dedup groups: 3 - removed: 4
- Semantic: {"disabled": 5, "ok": 11, "searches_with_stage": 16, "avg_ms": 3500}
- Empty-result queries: 0

### Window: 7d
- Total searches: 106
- By status: {"partial": 106}
- Latency p50/p95/p99: 1741.0 / 3098.0 / 3580.0
  - Reddit: avg_latency_ms=176, failed=106
  - The Guardian: avg_latency_ms=1766, avg_results=10, success=106
  - Wikipedia: avg_latency_ms=1256, avg_results=10, success=106
- Dedup groups: 3 - removed: 4
- Semantic: {"disabled": 5, "ok": 11, "searches_with_stage": 16, "avg_ms": 3500}
- Empty-result queries: 0

### Window: 30d
- Total searches: 106
- By status: {"partial": 106}
- Latency p50/p95/p99: 1741.0 / 3098.0 / 3580.0
  - Reddit: avg_latency_ms=176, failed=106
  - The Guardian: avg_latency_ms=1766, avg_results=10, success=106
  - Wikipedia: avg_latency_ms=1256, avg_results=10, success=106
- Dedup groups: 3 - removed: 4
- Semantic: {"disabled": 5, "ok": 11, "searches_with_stage": 16, "avg_ms": 3500}
- Empty-result queries: 0

## Phase 3 - Source Health Analysis (7d)

- **Reddit**: success=0 fail/timeout=106 (0%) | avg_latency=176ms | avg_yield=?
- **The Guardian**: success=106 fail/timeout=0 (100%) | avg_latency=1766ms | avg_yield=10
- **Wikipedia**: success=106 fail/timeout=0 (100%) | avg_latency=1256ms | avg_yield=10

## Phase 4 - Semantic Stage Status (7d)
- Full data: {"disabled": 5, "ok": 11, "searches_with_stage": 16, "avg_ms": 3500, "note": "SEM1 dormant by default; activate via SEMANTIC_ENABLED=true"}
- Distinguishes statuses: disabled=5, ok=11, failed=0, timeout=0, unavailable=0

## Phase 5 - Query Characteristics (7d)
- Empty-result count: 0
- 'rate limit test' x 30
- 'artificial intelligence' x 27
- 'quantum computing' x 3
- 'climate policy' x 2
- 'java' x 2
- 'machine learning ethics' x 2
- 'burst 0' x 1
- 'burst 1' x 1
- 'burst 10' x 1
- 'burst 11' x 1

## Phases 6-8 - Security & Privacy & Access Control

- Anonymous GET /api/v1/admin/stats -> 200
- Field classification:
  - window: **PUBLIC-SAFE**
  - generated_at: **PUBLIC-SAFE**
  - searches.total: **INTERNAL**
  - searches.by_status: **INTERNAL**
  - latency_ms.p50/p95/p99: **INTERNAL**
  - sources.*.success/fail/timeout counts: **INTERNAL**
  - sources.*.avg_latency_ms: **INTERNAL**
  - sources.*.avg_results: **INTERNAL**
  - dedup.total_groups/duplicates_removed: **INTERNAL**
  - semantic.status/ok/failed/ms: **INTERNAL**
  - queries.empty_result_count: **INTERNAL**
  - queries.top_normalized_queries[].query: **SENSITIVE (user-entered text)**

- Authentication system: **NONE** (no auth/JWT/API keys/sessions exist)
- Reverse proxy protection: none beyond Render's HTTPS termination
- Endpoint not linked from frontend: confirmed by code inspection

## Phase 9 - Admin Stats Endpoint Latency
- Samples: 9 across all windows
- Min/Median/Max: 305ms / 343ms / 590ms
