"""M13.0 - Production Observability & Security Audit (READ-ONLY).

No files modified. No commits. Writes only a report to eval/reports/.
"""

import json
import time
import urllib.request
from pathlib import Path

BASE = "https://signalpulse-e12w.onrender.com"
REPORT: list[str] = []


def emit(text: str) -> None:
    REPORT.append(text)
    print(text)


def call(path: str, method: str = "GET", body=None, timeout: int = 90):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body else None
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            ms = round((time.perf_counter() - t0) * 1000)
            return r.status, json.loads(r.read().decode()), ms
    except urllib.error.HTTPError as e:
        ms = round((time.perf_counter() - t0) * 1000)
        body = e.read().decode()
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, body, ms


def main() -> int:
    # === PHASE 1: LIVE DEPLOYMENT =============================================
    emit("# M13.0 - Production Observability & Security Audit")
    emit("")
    emit("## Phase 1 - Live Deployment Verification")
    emit("")

    s, health, _ = call("/api/v1/health")
    emit(f"- Health: {s} | db={health.get('db')} | status={health.get('status')}")
    assert s == 200, f"health returned {s}"

    s, stats24, _ = call("/api/v1/admin/stats?window=24h")
    admin_present = s == 200
    emit(f"- Admin stats endpoint present: {admin_present} (status {s})")
    assert admin_present, "pre-M12 deployment detected"

    s, bogus, _ = call("/api/v1/admin/stats?window=bogus")
    emit(f"- Bogus window -> {s} (expected 422)")
    emit("- Deployment verified as post-M12: YES")
    emit("")

    # === PHASE 2: PRODUCTION STATS =============================================
    emit("## Phase 2 - Production Statistics")
    emit("")

    window_stats = {}
    for w in ("24h", "7d", "30d"):
        s, body, _ = call(f"/api/v1/admin/stats?window={w}")
        window_stats[w] = body
        searches = body.get("searches", {})
        latency = body.get("latency_ms", {})
        sources = body.get("sources", {})
        dedup = body.get("dedup", {})
        semantic = body.get("semantic", {})

        emit(f"### Window: {w}")
        emit(f"- Total searches: {searches.get('total', 0)}")
        emit(f"- By status: {json.dumps(searches.get('by_status', {}))}")
        emit(f"- Latency p50/p95/p99: "
             f"{latency.get('p50', 'N/A')} / {latency.get('p95', 'N/A')} / "
             f"{latency.get('p99', 'N/A')}")
        for src_name in sorted(sources):
            e = sources[src_name]
            parts = [
                f"{k}={v}" for k, v in sorted(e.items())
                if k != "_latencies" and k != "_results"
            ]
            emit(f"  - {src_name}: {', '.join(parts)}")
        emit(
            f"- Dedup groups: {dedup.get('total_groups', 0)} - "
            f"removed: {dedup.get('duplicates_removed', 0)}"
        )
        emit(f"- Semantic: {json.dumps({k: v for k, v in semantic.items() if k != 'note'})}")
        emit(f"- Empty-result queries: {body.get('queries', {}).get('empty_result_count', 'N/A')}")
        emit("")

    # === PHASE 3: SOURCE HEALTH ================================================
    emit("## Phase 3 - Source Health Analysis (7d)")
    emit("")
    stats_7d = window_stats["7d"]
    src = stats_7d.get("sources", {})
    for name in sorted(src):
        e = src[name]
        ok = e.get("success", 0)
        fail = sum(e.get(k, 0) for k in ("failed", "timeout", "rate_limited"))
        total_src = ok + fail
        rate = f"{ok / total_src * 100:.0f}%" if total_src else "n/a"
        emit(f"- **{name}**: success={ok} fail/timeout={fail} ({rate}) | "
             f"avg_latency={e.get('avg_latency_ms', '?')}ms | "
             f"avg_yield={e.get('avg_results', '?')}")
    emit("")

    # === PHASE 4: SEMANTIC ======================================================
    sem_7d = stats_7d.get("semantic", {})
    emit("## Phase 4 - Semantic Stage Status (7d)")
    emit(f"- Full data: {json.dumps(sem_7d)}")
    emit(f"- Distinguishes statuses: disabled={sem_7d.get('disabled', 0)}, "
         f"ok={sem_7d.get('ok', 0)}, failed={sem_7d.get('failed', 0)}, "
         f"timeout={sem_7d.get('timeout', 0)}, unavailable={sem_7d.get('unavailable', 0)}")
    emit("")

    # === PHASE 5: QUERIES ========================================================
    queries_7d = stats_7d.get("queries", {})
    emit("## Phase 5 - Query Characteristics (7d)")
    emit(f"- Empty-result count: {queries_7d.get('empty_result_count', 'N/A')}")
    top_q = queries_7d.get("top_normalized_queries", [])
    for tq in top_q:
        emit(f"- '{tq['query']}' x {tq['count']}")
    emit("")

    # === PHASE 6-8: SECURITY & PRIVACY ==========================================
    emit("## Phases 6-8 - Security & Privacy & Access Control")
    emit("")

    s_anon, _, _ = call("/api/v1/admin/stats?window=30d")
    emit(f"- Anonymous GET /api/v1/admin/stats -> {s_anon}")

    fields_classified = [
        ("window", "PUBLIC-SAFE"),
        ("generated_at", "PUBLIC-SAFE"),
        ("searches.total", "INTERNAL"),
        ("searches.by_status", "INTERNAL"),
        ("latency_ms.p50/p95/p99", "INTERNAL"),
        ("sources.*.success/fail/timeout counts", "INTERNAL"),
        ("sources.*.avg_latency_ms", "INTERNAL"),
        ("sources.*.avg_results", "INTERNAL"),
        ("dedup.total_groups/duplicates_removed", "INTERNAL"),
        ("semantic.status/ok/failed/ms", "INTERNAL"),
        ("queries.empty_result_count", "INTERNAL"),
        ("queries.top_normalized_queries[].query", "SENSITIVE (user-entered text)"),
    ]
    emit("- Field classification:")
    for k, v in fields_classified:
        emit(f"  - {k}: **{v}**")

    emit("")
    emit("- Authentication system: **NONE** (no auth/JWT/API keys/sessions exist)")
    emit("- Reverse proxy protection: none beyond Render's HTTPS termination")
    emit("- Endpoint not linked from frontend: confirmed by code inspection")
    emit("")

    # === PHASE 9: ADMIN LATENCY ==================================================
    lat_admin = []
    for w in ("24h", "7d", "30d"):
        for _ in range(3):
            _, _, ms = call(f"/api/v1/admin/stats?window={w}")
            lat_admin.append(ms)
    emit("## Phase 9 - Admin Stats Endpoint Latency")
    emit(f"- Samples: {len(lat_admin)} across all windows")
    emit(f"- Min/Median/Max: {min(lat_admin)}ms / "
         f"{sorted(lat_admin)[len(lat_admin)//2]}ms / {max(lat_admin)}ms")
    emit("")

    # write report
    out = Path(__file__).resolve().parent / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "m13_audit.md").write_text("\n".join(REPORT), encoding="utf-8")
    print(f"wrote {out / 'm13_audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())