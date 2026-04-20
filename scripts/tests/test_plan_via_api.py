"""Test AI remediation plan via the REAL HTTP API endpoint (with admin login).

Exercises the full stack:
  POST /auth/login  (session cookie)
  POST /tools/security-network/api/compliance/plan/<rule_id>  scan_id in body
  GET  /tools/security-network/api/compliance/plan/<plan_id>

All requests go through:
  Flask route -> compliance_service.generate_remediation_plan ->
    Bridge dispatcher -> Department HQ coordinator -> F.O.R.G.E. (qwen2.5-coder:7b)
"""
import sys
import time
import json
import urllib.request
import urllib.parse
import http.cookiejar

BASE = "http://192.168.1.200:3000"
USER = "admin"
PASS = "Kyt$13ran2025"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def post_json(path, payload, timeout=600):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def post_form(path, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    with opener.open(req, timeout=30) as r:
        return r.status


def get_json(path, timeout=30):
    req = urllib.request.Request(BASE + path)
    with opener.open(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode() or "{}")


print("1. Login as admin...")
try:
    code = post_form("/login", {"username": USER, "password": PASS})
    print(f"   login HTTP {code}  cookies={len(list(jar))}")
except Exception as e:
    print(f"   login failed: {e}")
    sys.exit(1)


# Pick a rule to test — args[1] or default D-238030 (untested so far, high sev)
rule_id = sys.argv[1] if len(sys.argv) > 1 else "D-238030"

# Find the latest failing scan for this rule
import subprocess

q = subprocess.check_output(
    [
        "docker", "exec", "archie_database", "psql", "-U", "archie", "-d", "archie",
        "-tAc",
        f"SELECT scan_id FROM compliance_scan_results WHERE rule_id='{rule_id}' AND status='fail' ORDER BY scanned_at DESC LIMIT 1;",
    ]
).decode().strip()
print(f"2. Using scan_id={q} for rule={rule_id}")

print(f"3. POST /api/compliance/plan/{rule_id} ...")
t0 = time.time()
try:
    code, body = post_json(
        f"/tools/security-network/api/compliance/plan/{rule_id}",
        {"scan_id": q},
        timeout=600,
    )
    elapsed = round(time.time() - t0, 1)
    print(f"   HTTP {code}  elapsed={elapsed}s")
    print(f"   success={body.get('success')}  plan_id={body.get('plan_id')}  fallback={body.get('fallback')}")
    plan = body.get("plan") or {}
    print(f"   steps={len(plan.get('steps') or [])}  exempt={plan.get('exemption_candidate')}")
    print(f"   downtime={plan.get('estimated_downtime')}")
    print(f"   impact: {(plan.get('impact_analysis') or '')[:250]}")
except Exception as e:
    print(f"   FAILED: {e}")
    sys.exit(1)

# Verify retrieval endpoint
plan_id = body.get("plan_id")
if plan_id:
    print(f"4. GET /api/compliance/plan/{plan_id} ...")
    code, body2 = get_json(f"/tools/security-network/api/compliance/plan/{plan_id}")
    print(f"   HTTP {code}  plan.rule_id={body2.get('plan', {}).get('rule_id')}")

print()
print("END-TO-END API TEST PASSED" if body.get("success") else "API TEST FAILED")
