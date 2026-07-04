"""Full internal-suite batch using the new Path B shared-session flow."""

import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain")

import requests
from services import qa_service
from services.qa_spec_runner import _authenticate, _resolve_env_vars
from database import get_db_cursor

start = time.time()
suites = qa_service.get_suites()
internal = [s for s in suites if s.get("suite_type") == "internal"]

ids = [s["id"] for s in internal]
specs = {}
with get_db_cursor() as (conn, cur):
    cur.execute("SELECT id, spec FROM qa_test_suites WHERE id = ANY(%s)", (ids,))
    for r in cur.fetchall():
        specs[r["id"]] = r["spec"] or {}

shared_session = None
shared_key = None
shared_pw = None
results = []

for s in internal:
    spec_resolved = _resolve_env_vars(specs.get(s["id"]) or {})
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
            except Exception as e:
                print(f"  pre-auth FAILED for {s['name']}: {e}")
                shared_session = None
                shared_key = None
                shared_pw = None

    res = qa_service.run_suite(
        s["id"],
        triggered_by="claude_pathb_full",
        session=(shared_session if use_shared else None),
        skip_auth=use_shared,
    )
    p = res.get("passed", 0)
    f = res.get("failed", 0)
    e = res.get("errors", 0)
    results.append((s["name"], p, f, e, use_shared))
    time.sleep(2)

dur = time.time() - start
errored = [r for r in results if r[3] > 0 or r[2] > 0]
shared_count = sum(1 for r in results if r[4])
print(f"Total: {len(results)} suites, {dur:.0f}s, shared_session={shared_count}, errored={len(errored)}")
for r in errored[:20]:
    print(f"  ERROR: {r[0]:35} pass={r[1]} fail={r[2]} err={r[3]} shared={r[4]}")
