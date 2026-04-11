"""Generate AI remediation plans for every currently-failing rule."""
import sys
import time
import json

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from database import get_db_cursor
from tools.security_network import compliance_service

with get_db_cursor() as (conn, cur):
    cur.execute(
        """SELECT rule_id, pack_id, severity, scan_id
           FROM compliance_scan_results
           WHERE scan_id = (SELECT scan_id FROM compliance_scans
                            ORDER BY started_at DESC LIMIT 1)
             AND status = 'fail'
           ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    rule_id"""
    )
    rows = [dict(r) for r in cur.fetchall()]

print(f"Found {len(rows)} failing rules. Generating plans sequentially.")
print(f"Expected runtime: ~{len(rows) * 3} min (ballpark)")
print("=" * 80)

results = []
t_start = time.time()
for i, r in enumerate(rows):
    rid = r["rule_id"]
    pack = r["pack_id"]
    sev = r["severity"]
    scan = str(r["scan_id"])
    t0 = time.time()
    try:
        res = compliance_service.generate_remediation_plan(scan, rid, user_id=2)
        elapsed = round(time.time() - t0, 1)
        plan = res.get("plan") or {}
        steps = len(plan.get("steps") or [])
        fallback = res.get("fallback")
        plan_id = res.get("plan_id")
        exempt = plan.get("exemption_candidate")
        downtime = plan.get("estimated_downtime", "")[:40]
        err = res.get("error") or ""
        status = "FALLBACK" if fallback else "REAL"
        print(
            f"[{i+1}/{len(rows)}] {rid:14} [{sev:6}] {pack:20} "
            f"{elapsed:6}s id={plan_id:3} {status:9} "
            f"steps={steps} exempt={exempt} dt={downtime}"
        )
        results.append(
            {
                "rule_id": rid,
                "pack_id": pack,
                "severity": sev,
                "elapsed": elapsed,
                "plan_id": plan_id,
                "fallback": fallback,
                "steps": steps,
                "exempt": exempt,
                "downtime": downtime,
                "error": err,
            }
        )
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        print(f"[{i+1}/{len(rows)}] {rid:14} ERROR after {elapsed}s: {e}")
        results.append({"rule_id": rid, "error": str(e), "elapsed": elapsed})

total = round(time.time() - t_start, 1)
real_count = sum(1 for r in results if not r.get("fallback") and not r.get("error"))
fb_count = sum(1 for r in results if r.get("fallback"))
err_count = sum(1 for r in results if r.get("error"))

print("=" * 80)
print(f"DONE in {total}s ({round(total/60,1)} min)")
print(f"REAL plans: {real_count}   FALLBACK: {fb_count}   ERRORS: {err_count}")

with open("/tmp/plan_sweep_results.json", "w") as f:
    json.dump({"total_seconds": total, "results": results}, f, indent=2)
print("Full results: /tmp/plan_sweep_results.json")
