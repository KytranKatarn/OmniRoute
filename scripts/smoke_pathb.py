"""Path B smoke test: run a handful of previously-failing suites with a
shared, pre-authenticated session. Mirrors the new _run_qa_scheduled path."""
import os
import sys
import time
sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain")

import requests
from services import qa_service
from services.qa_spec_runner import _authenticate, _resolve_env_vars
from database import get_db_cursor

# Pick 8 suites that were among the 27 failures in claude_pr507_validation
TARGET_NAMES = [
    "consciousness.yaml",
    "department_hq.yaml",
    "email_manager.yaml",
    "backup_manager.yaml",
    "compliance_badges.yaml",
    "creed_admin.yaml",
    "fitness.yaml",
    "therapy.yaml",
]

with get_db_cursor() as (conn, cur):
    cur.execute(
        "SELECT id, name, spec FROM qa_test_suites "
        "WHERE name = ANY(%s) AND is_active=true ORDER BY name",
        (TARGET_NAMES,),
    )
    rows = [dict(r) for r in cur.fetchall()]

print(f"Loaded {len(rows)} suites for smoke test")

# Build one shared session, auth once
shared_session = None
shared_key = None
shared_pw = None

results_summary = []
start = time.time()

for s in rows:
    spec_resolved = _resolve_env_vars(s["spec"] or {})
    suite_meta = (spec_resolved.get("suite") or {}) if isinstance(spec_resolved, dict) else {}
    base_url = (suite_meta.get("base_url") or "http://localhost:3000").rstrip("/")
    auth = suite_meta.get("auth") or {}
    has_auth = bool(auth.get("username") and auth.get("password"))

    use_shared = False
    if has_auth:
        key = (base_url, auth["username"])
        if shared_key == key and shared_pw == auth["password"] and shared_session is not None:
            use_shared = True
        else:
            try:
                fresh = requests.Session()
                _authenticate(fresh, base_url, auth)
                shared_session = fresh
                shared_key = key
                shared_pw = auth["password"]
                use_shared = True
                print(f"  pre-auth OK: {auth['username']} @ {base_url}")
            except Exception as e:
                print(f"  pre-auth FAILED for {base_url}: {e}")
                shared_session = None
                shared_key = None
                shared_pw = None

    t0 = time.time()
    res = qa_service.run_suite(
        s["id"],
        triggered_by="claude_pathb_smoke",
        session=(shared_session if use_shared else None),
        skip_auth=use_shared,
    )
    dur = time.time() - t0
    p = res.get("passed", 0)
    f = res.get("failed", 0)
    e = res.get("errors", 0)
    results_summary.append((s["name"], p, f, e, dur, use_shared))
    print(f"  {s['name']:30} pass={p:3} fail={f} err={e} sec={dur:.1f} shared={use_shared}")
    time.sleep(2)

dur_total = time.time() - start
print(f"\nTotal: {dur_total:.1f}s  passed_suites={sum(1 for r in results_summary if r[3]==0 and r[2]==0)}/{len(results_summary)}")
print(f"Errored suites: {[r[0] for r in results_summary if r[3] > 0 or r[2] > 0]}")
