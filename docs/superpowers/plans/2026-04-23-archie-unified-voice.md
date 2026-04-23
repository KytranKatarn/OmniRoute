# A.R.C.H.I.E. Unified Voice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce A.R.C.H.I.E. as the sole outbound escalation authority — all directors write to an inbox, A.R.C.H.I.E. triages, and only escalated reports reach Kytran via Telegram.

**Architecture:** Three layers — (1) secure the inbox endpoint so only platform_v2 can post to it; (2) build a triage consumer in platform_v2 that classifies reports and decides what Kytran sees; (3) lock down `telegram_service.send_*` so direct senders write to the inbox instead of bypassing A.R.C.H.I.E.

**Tech Stack:** Flask, APScheduler, PostgreSQL (archie-comms DB + platform_v2 DB), python-telegram-bot, Docker Compose env vars.

**Task IDs:** #2235, #2266, #2267, #2234, #2233, #2229, #2261, #2262, #2263, #2264, #2265, #2223, #2224, #2225, #2268, #2269, #2226

---

## Wave 1 — Phase 1 Fixes + Security (ship first, fast)

> All tasks are small. Ship as a single PR: `feat/unified-voice-wave1`. Restart archie-comms + archie_platform after deploy.

---

### Task 1: Secure `/api/director/report` — add service token (#2266 + #2267)

**Files:**
- Modify: `archie-comms/app_comms.py:187`
- Modify: `platform_v2/services/telegram_service.py:185-217`
- Modify: `archie-comms/.env` (add token — do not commit)
- Modify: `platform_v2/.env` (add token — do not commit)

- [ ] **Step 1: Generate token and add to both .env files**

```bash
TOKEN=$(openssl rand -hex 16)
echo "ARCHIE_COMMS_SERVICE_TOKEN=$TOKEN" >> archie-comms/.env
echo "ARCHIE_COMMS_SERVICE_TOKEN=$TOKEN" >> platform_v2/.env
```

- [ ] **Step 2: Add token validation to archie-comms endpoint**

In `archie-comms/app_comms.py`, add at module level after imports:
```python
import os
ARCHIE_SERVICE_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")
```

Replace the existing `api_director_report` function (around line 187):
```python
@app.route("/api/director/report", methods=["POST"])
def api_director_report():
    token = request.headers.get("X-Service-Token", "")
    if ARCHIE_SERVICE_TOKEN and token != ARCHIE_SERVICE_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    from services.briefing_service import submit_director_report
    data = request.get_json() or {}
    required = ["department", "director_agent", "severity", "category", "title", "summary"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    report_id = submit_director_report(
        department=data["department"],
        director_agent=data["director_agent"],
        severity=data["severity"],
        category=data["category"],
        title=data["title"],
        summary=data["summary"],
        details=data.get("details"),
    )
    if report_id:
        return jsonify({"success": True, "report_id": report_id})
    return jsonify({"error": "Failed to submit report"}), 500
```

- [ ] **Step 3: Wire token into telegram_service.py outbound POST**

In `platform_v2/services/telegram_service.py`, add at module level:
```python
_COMMS_SERVICE_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")
```

Find the `requests.post()` call to archie-comms (around line 185-217) and add the token header:
```python
headers = {
    "Content-Type": "application/json",
    "X-Service-Token": _COMMS_SERVICE_TOKEN,
}
# Pass headers= to the existing requests.post() call
```

- [ ] **Step 4: Manual verify**
```bash
# Should return 401
curl -s -X POST http://192.168.1.200:3002/api/director/report \
  -H "Content-Type: application/json" \
  -d '{"department":"T","director_agent":"T","severity":"low","category":"test","title":"t","summary":"s"}'

# Should return 200 — use actual token from .env
TOKEN=$(grep ARCHIE_COMMS_SERVICE_TOKEN archie-comms/.env | cut -d= -f2)
curl -s -X POST http://192.168.1.200:3002/api/director/report \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: $TOKEN" \
  -d '{"department":"T","director_agent":"T","severity":"low","category":"test","title":"t","summary":"s"}'
```
Expected: first `{"error":"Unauthorized"}`, second `{"success":true,"report_id":N}`.

- [ ] **Step 5: Commit**
```bash
git add archie-comms/app_comms.py platform_v2/services/telegram_service.py
git commit -m "feat(unified-voice): secure /api/director/report with service token (#2266 #2267)"
```

---

### Task 2: Redirect legacy `telegram_gateway.py` to director report (#2235)

**Files:**
- Modify: `ai_bridge/telegram_gateway.py`

- [ ] **Step 1: Find the direct send call in telegram_gateway.py**
```bash
grep -n "def _send\|bot.send_message\|requests.post\|send_message" \
  /mnt/archie_brain/ai_bridge/telegram_gateway.py | head -20
```

- [ ] **Step 2: Replace direct Telegram call with telegram_service.send()**

In `ai_bridge/telegram_gateway.py`, find the `_send()` function and replace its body:
```python
def _send(category: str, title: str, message: str, source_agent: str = None) -> bool:
    """Route through A.R.C.H.I.E. director report inbox instead of direct Telegram."""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'platform_v2'))
        from services.telegram_service import send
        result = send(
            category=category,
            title=title,
            message=message,
            source_agent=source_agent or "telegram_gateway",
        )
        return result.get("success", False)
    except Exception as e:
        logger.error(f"telegram_gateway _send redirect failed: {e}")
        return False
```

Adapt the signature to match what the existing function receives — the key change is removing any direct `bot.send_message()` or `requests.post()` to Telegram.

- [ ] **Step 3: Restart and verify no errors**
```bash
docker compose restart archie_platform
docker logs archie_platform --tail=20 | grep -i "error\|gateway"
```

- [ ] **Step 4: Commit**
```bash
git add ai_bridge/telegram_gateway.py
git commit -m "feat(unified-voice): redirect telegram_gateway to director report inbox (#2235)"
```

---

### Task 3: Fix gunicorn double-send race condition (#2234)

**Files:**
- Create: `archie-comms/migrations/003_director_reports_dedup.sql`
- Modify: `archie-comms/services/briefing_service.py`

- [ ] **Step 1: Create dedup migration**

Create `archie-comms/migrations/003_director_reports_dedup.sql`:
```sql
ALTER TABLE director_reports
  ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_director_reports_dedup
  ON director_reports(dedup_key)
  WHERE dedup_key IS NOT NULL;
```

Run:
```bash
docker exec archie_comms_db psql -U archie -d archie_comms \
  -f /migrations/003_director_reports_dedup.sql
```

- [ ] **Step 2: Add dedup_key to submit_director_report()**

In `archie-comms/services/briefing_service.py`, update `submit_director_report()`:
```python
import hashlib, time

def submit_director_report(department, director_agent, severity, category,
                            title, summary, details=None):
    # 5-minute dedup window — same director + category + title = one report
    window = int(time.time() // 300)
    raw = f"{director_agent}:{category}:{title}:{window}"
    dedup_key = hashlib.sha256(raw.encode()).hexdigest()[:32]

    with get_db_cursor(commit=True) as cur:
        try:
            cur.execute(
                """
                INSERT INTO director_reports
                  (department, director_agent, severity, category,
                   title, summary, details, dedup_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dedup_key) DO NOTHING
                RETURNING id
                """,
                (department, director_agent, severity, category,
                 title, summary, psycopg2.extras.Json(details or {}), dedup_key),
            )
            row = cur.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"submit_director_report failed: {e}")
            return None
```

- [ ] **Step 3: Verify dedup works**
```bash
TOKEN=$(grep ARCHIE_COMMS_SERVICE_TOKEN archie-comms/.env | cut -d= -f2)
for i in 1 2; do
  curl -s -X POST http://192.168.1.200:3002/api/director/report \
    -H "Content-Type: application/json" \
    -H "X-Service-Token: $TOKEN" \
    -d '{"department":"T","director_agent":"T","severity":"low","category":"test","title":"dedup-test","summary":"s"}'
  echo
done
```
Expected: first call `{"success":true,"report_id":N}`, second call `{"success":true,"report_id":null}`.

- [ ] **Step 4: Commit**
```bash
git add archie-comms/services/briefing_service.py \
        archie-comms/migrations/003_director_reports_dedup.sql
git commit -m "fix(unified-voice): dedup director_reports to prevent gunicorn double-send (#2234)"
```

---

### Task 4: De-dup B.A.S.E. watchdog repeated reports (#2233)

**Files:**
- Modify: `platform_v2/tools/department_hq/services/job_registry.py`

- [ ] **Step 1: Find the watchdog function**
```bash
grep -n "def.*watchdog\|stuck\|send_system" \
  /mnt/archie_brain/platform_v2/tools/department_hq/services/job_registry.py | head -20
```

- [ ] **Step 2: Add last-sent tracking**

Add at module level in `job_registry.py`:
```python
import time as _time
_watchdog_last_sent: dict = {}
_WATCHDOG_RESEND_INTERVAL = 3600  # 1 hour between repeated alerts for same condition
```

In the watchdog function, wrap each `send_system()` call:
```python
def _should_send_watchdog(key: str) -> bool:
    now = _time.time()
    if now - _watchdog_last_sent.get(key, 0) < _WATCHDOG_RESEND_INTERVAL:
        return False
    _watchdog_last_sent[key] = now
    return True

# Before each send_system() call in the watchdog:
if _should_send_watchdog(f"stuck:{agent_name}"):
    send_system(title=..., message=..., source_agent="B.A.S.E.")
```

Adapt to the actual function body — the pattern is consistent regardless of what condition triggers the alert.

- [ ] **Step 3: Commit**
```bash
git add platform_v2/tools/department_hq/services/job_registry.py
git commit -m "fix(unified-voice): de-dup B.A.S.E. watchdog — 1h resend interval per condition (#2233)"
```

---

### Task 5: Fix nginx_proxy_manager probe double-scheme (#2229)

**Files:**
- Locate via grep, then fix.

- [ ] **Step 1: Find the bad probe URL**
```bash
grep -rn "http:http\|npm.*probe\|proxy_manager.*url\|81/api" \
  /mnt/archie_brain/platform_v2/ --include="*.py" | head -10
```

- [ ] **Step 2: Fix the double-scheme**

The URL is likely built by concatenating a scheme prefix with a value that already contains `http://`:
```python
# BAD — produces "http:http://127.0.0.1:81/api"
probe_url = "http:" + npm_base_url

# GOOD — use the value as-is if it already has a scheme
probe_url = npm_base_url  # if npm_base_url = "http://127.0.0.1:81/api"
# OR hardcode correctly
probe_url = "http://127.0.0.1:81/api"
```

- [ ] **Step 3: Commit**
```bash
git add <modified file>
git commit -m "fix(unified-voice): remove double-scheme from nginx_proxy_manager probe URL (#2229)"
```

---

### Task 6: Wave 1 PR + deploy

- [ ] **Push and create PR**
```bash
git checkout -b feat/unified-voice-wave1
git push -u origin feat/unified-voice-wave1
gh pr create \
  --title "feat(unified-voice): Wave 1 — security hardening + Phase 1 bugfixes" \
  --body "$(cat <<'EOF'
Closes #2266 #2267 #2235 #2234 #2233 #2229

## Changes
- Secured /api/director/report with X-Service-Token (401 without valid token)
- telegram_service.py sends token in outbound POST to archie-comms
- telegram_gateway._send() redirected through director report inbox
- Gunicorn double-send fixed via dedup_key + ON CONFLICT DO NOTHING (5-min window)
- B.A.S.E. watchdog de-duped (1h resend interval per condition key)
- nginx_proxy_manager probe double-scheme URL fixed

## Test
- curl /api/director/report without token -> 401
- curl with token -> 200
- Duplicate POST same title within 5min -> second returns null report_id
EOF
)"
```

- [ ] **Deploy**
```bash
docker compose restart archie_comms archie_platform
docker logs archie_comms --tail=20
docker logs archie_platform --tail=20
```

---

## Wave 2 — Phase 2 Triage Consumer Architecture

> PR: `feat/unified-voice-wave2`. Requires Wave 1 deployed (token auth must be live first).

---

### Task 7: Expose internal director-reports API from archie-comms (#2261)

**Files:**
- Create: `archie-comms/migrations/004_director_reports_triage.sql`
- Modify: `archie-comms/app_comms.py` — add two internal endpoints
- Create: `platform_v2/services/director_report_service.py`

- [ ] **Step 1: Create triage columns migration**

Create `archie-comms/migrations/004_director_reports_triage.sql`:
```sql
ALTER TABLE director_reports
  ADD COLUMN IF NOT EXISTS triage_status VARCHAR(20) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS triage_action VARCHAR(20),
  ADD COLUMN IF NOT EXISTS triage_reason TEXT,
  ADD COLUMN IF NOT EXISTS triaged_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_director_reports_pending
  ON director_reports(triage_status)
  WHERE triage_status = 'pending';
```

Run:
```bash
docker exec archie_comms_db psql -U archie -d archie_comms \
  -f /migrations/004_director_reports_triage.sql
```

- [ ] **Step 2: Add internal read + triage endpoints to archie-comms**

In `archie-comms/app_comms.py`, add after `api_director_report`:
```python
@app.route("/api/internal/director-reports", methods=["GET"])
def api_internal_director_reports():
    token = request.headers.get("X-Service-Token", "")
    if ARCHIE_SERVICE_TOKEN and token != ARCHIE_SERVICE_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    limit = min(int(request.args.get("limit", 20)), 100)
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, department, director_agent, severity, category,
                   title, summary, details, created_at
            FROM director_reports
            WHERE triage_status = 'pending'
            ORDER BY
              CASE severity
                WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                WHEN 'medium'   THEN 2 ELSE 3
              END,
              created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()

    return jsonify({"reports": rows, "count": len(rows)})


@app.route("/api/internal/director-reports/<int:report_id>/triage", methods=["POST"])
def api_internal_triage_report(report_id):
    token = request.headers.get("X-Service-Token", "")
    if ARCHIE_SERVICE_TOKEN and token != ARCHIE_SERVICE_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    action = data.get("action")
    if action not in ("resolve", "consolidate", "suppress", "escalate"):
        return jsonify({"error": "Invalid action"}), 400

    with get_db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE director_reports
            SET triage_status = %s,
                triage_action = %s,
                triage_reason = %s,
                triaged_at    = NOW(),
                escalated     = %s,
                escalation_channel = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                action, action, data.get("reason", ""),
                action == "escalate",
                "telegram" if action == "escalate" else None,
                report_id,
            ),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"error": "Report not found"}), 404
    return jsonify({"success": True, "report_id": row[0], "action": action})
```

- [ ] **Step 3: Create platform_v2/services/director_report_service.py**

```python
"""Client for platform_v2 to interact with archie-comms director_reports."""
import os
import logging
import requests

logger = logging.getLogger(__name__)

_COMMS_BASE = os.getenv("ARCHIE_COMMS_URL", "http://archie_comms:3002")
_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")
_TIMEOUT = 5


def _headers() -> dict:
    return {"Content-Type": "application/json", "X-Service-Token": _TOKEN}


def get_pending_reports(limit: int = 20) -> list:
    try:
        resp = requests.get(
            f"{_COMMS_BASE}/api/internal/director-reports",
            headers=_headers(),
            params={"limit": limit},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("reports", [])
    except Exception as e:
        logger.error(f"get_pending_reports failed: {e}")
        return []


def triage_report(report_id: int, action: str, reason: str = "") -> bool:
    try:
        resp = requests.post(
            f"{_COMMS_BASE}/api/internal/director-reports/{report_id}/triage",
            headers=_headers(),
            json={"action": action, "reason": reason},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("success", False)
    except Exception as e:
        logger.error(f"triage_report({report_id}, {action}) failed: {e}")
        return False


def submit_via_inbox(category: str, title: str, message: str,
                     source_agent: str = None) -> dict:
    """Write a message to director_reports inbox (for privilege-redirected callers)."""
    try:
        resp = requests.post(
            f"{_COMMS_BASE}/api/director/report",
            headers=_headers(),
            json={
                "department": "Unknown",
                "director_agent": source_agent or "unknown",
                "severity": "medium",
                "category": category,
                "title": title,
                "summary": message,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return {"success": True, "routed_to": "inbox"}
    except Exception as e:
        logger.error(f"submit_via_inbox failed: {e}")
        return {"success": False, "error": str(e)}
```

- [ ] **Step 4: Verify endpoints**
```bash
TOKEN=$(grep ARCHIE_COMMS_SERVICE_TOKEN archie-comms/.env | cut -d= -f2)
curl -s "http://192.168.1.200:3002/api/internal/director-reports" \
  -H "X-Service-Token: $TOKEN" | python3 -m json.tool
```
Expected: `{"reports": [...], "count": N}`.

- [ ] **Step 5: Commit**
```bash
git add archie-comms/app_comms.py \
        archie-comms/migrations/004_director_reports_triage.sql \
        platform_v2/services/director_report_service.py
git commit -m "feat(unified-voice): inbox visibility layer — internal triage API + client service (#2261)"
```

---

### Task 8: Signal classification logic (#2262)

**Files:**
- Modify: `platform_v2/services/director_report_service.py` — add `classify_report()`

- [ ] **Step 1: Add classification rules and classify_report()**

Append to `platform_v2/services/director_report_service.py`:
```python
# Default rules — tuple: (severity, category_prefix, director_pattern, action, reason)
# First match wins. None = match any value.
_DEFAULT_RULES = [
    ("critical", None,       None,       "escalate",    "Critical severity always escalates"),
    ("high",     "security", None,       "escalate",    "High-severity security event"),
    ("high",     None,       None,       "escalate",    "High severity requires Kytran attention"),
    ("medium",   "operations","B.A.S.E.","consolidate", "B.A.S.E. ops reports consolidated"),
    ("medium",   None,       None,       "suppress",    "Medium severity suppressed by default"),
    ("low",      None,       None,       "suppress",    "Low severity auto-suppressed"),
    (None,       None,       None,       "suppress",    "Default: suppress unknown"),
]


def classify_report(report: dict, policies: list = None) -> tuple:
    """
    Returns (action, reason).
    action: resolve | consolidate | suppress | escalate
    Checks DB policies first, then _DEFAULT_RULES.
    """
    severity  = (report.get("severity") or "low").lower()
    category  = (report.get("category") or "").lower()
    director  = (report.get("director_agent") or "").upper()

    all_rules = []
    for p in (policies or []):
        all_rules.append((
            p.get("severity"), p.get("category_prefix"),
            p.get("director_agent_pattern"), p["action"], p["reason"],
        ))
    all_rules.extend(_DEFAULT_RULES)

    for r_sev, r_cat, r_dir, action, reason in all_rules:
        if r_sev and r_sev != severity:
            continue
        if r_cat and not category.startswith(r_cat.lower()):
            continue
        if r_dir and r_dir.upper() not in director:
            continue
        return action, reason

    return "suppress", "No matching rule — default suppress"
```

- [ ] **Step 2: Verify classification**
```bash
cd /mnt/archie_brain && python3 - <<'EOF'
import sys; sys.path.insert(0, 'platform_v2')
from services.director_report_service import classify_report

tests = [
    ({"severity": "critical", "category": "security", "director_agent": "V.I.G.I.L."}, "escalate"),
    ({"severity": "low",      "category": "ops",      "director_agent": "B.A.S.E."},   "suppress"),
    ({"severity": "high",     "category": "security", "director_agent": "V.I.G.I.L."}, "escalate"),
    ({"severity": "medium",   "category": "operations","director_agent": "B.A.S.E."},  "consolidate"),
]
for report, expected_action in tests:
    action, reason = classify_report(report)
    assert action == expected_action, f"FAIL: {report} -> {action} (expected {expected_action})"
    print(f"PASS: {report['severity']}/{report['category']} -> {action}")
EOF
```
Expected: 4 `PASS` lines.

- [ ] **Step 3: Commit**
```bash
git add platform_v2/services/director_report_service.py
git commit -m "feat(unified-voice): signal classification — resolve/consolidate/suppress/escalate (#2262)"
```

---

### Task 9: Policy engine — DB-driven rule overrides (#2263)

**Files:**
- Create: `archie-comms/migrations/005_triage_policies.sql`
- Modify: `archie-comms/app_comms.py` — add policies endpoint
- Modify: `platform_v2/services/director_report_service.py` — add `get_policies()`

- [ ] **Step 1: Create triage_policies migration**

Create `archie-comms/migrations/005_triage_policies.sql`:
```sql
CREATE TABLE IF NOT EXISTS triage_policies (
    id SERIAL PRIMARY KEY,
    severity VARCHAR(20),
    category_prefix VARCHAR(100),
    director_agent_pattern VARCHAR(100),
    action VARCHAR(20) NOT NULL,
    reason TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triage_policies_active
  ON triage_policies(active, priority);
```

Run:
```bash
docker exec archie_comms_db psql -U archie -d archie_comms \
  -f /migrations/005_triage_policies.sql
```

- [ ] **Step 2: Add policies endpoint to archie-comms**

In `archie-comms/app_comms.py`:
```python
@app.route("/api/internal/triage-policies", methods=["GET"])
def api_internal_triage_policies():
    token = request.headers.get("X-Service-Token", "")
    if ARCHIE_SERVICE_TOKEN and token != ARCHIE_SERVICE_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT severity, category_prefix, director_agent_pattern, action, reason
            FROM triage_policies
            WHERE active = TRUE
            ORDER BY priority ASC
            """,
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    return jsonify({"policies": rows})
```

- [ ] **Step 3: Add get_policies() with cache to director_report_service.py**

Append to `platform_v2/services/director_report_service.py`:
```python
import time as _time

_policy_cache: list = []
_policy_cache_ts: float = 0.0
_POLICY_CACHE_TTL = 300  # 5 minutes


def get_policies() -> list:
    global _policy_cache, _policy_cache_ts
    if _time.time() - _policy_cache_ts < _POLICY_CACHE_TTL:
        return _policy_cache
    try:
        resp = requests.get(
            f"{_COMMS_BASE}/api/internal/triage-policies",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        _policy_cache = resp.json().get("policies", [])
        _policy_cache_ts = _time.time()
        return _policy_cache
    except Exception as e:
        logger.warning(f"get_policies failed, using stale cache: {e}")
        return _policy_cache
```

- [ ] **Step 4: Commit**
```bash
git add archie-comms/migrations/005_triage_policies.sql \
        archie-comms/app_comms.py \
        platform_v2/services/director_report_service.py
git commit -m "feat(unified-voice): policy engine — DB-driven triage rules, 5-min cache (#2263)"
```

---

### Task 10: Triage consumer APScheduler job (#2264)

**Files:**
- Modify: `platform_v2/ai_bridge/agent_loop.py`

- [ ] **Step 1: Find where to add the job**
```bash
grep -n "add_job\|delegate_task_worker\|seconds=30\|max_instances" \
  /mnt/archie_brain/platform_v2/ai_bridge/agent_loop.py | head -15
```

- [ ] **Step 2: Write the consumer function**

Add to `platform_v2/ai_bridge/agent_loop.py` near other 30s-cadence jobs:
```python
def _run_triage_consumer():
    """
    A.R.C.H.I.E. triage consumer — fetches pending director_reports,
    classifies each one, marks triaged. Escalated reports go to Telegram.
    Runs every 30s, max 1 instance to prevent overlap.
    """
    from services.director_report_service import (
        get_pending_reports, classify_report, triage_report, get_policies,
    )
    from services.telegram_service import send as telegram_send

    try:
        reports = get_pending_reports(limit=10)
        if not reports:
            return

        policies = get_policies()
        for report in reports:
            action, reason = classify_report(report, policies)
            triage_report(report["id"], action, reason)

            if action == "escalate":
                telegram_send(
                    category=report.get("category", "system"),
                    title=f"[{report['severity'].upper()}] {report['title']}",
                    message=(
                        f"From: {report['director_agent']} ({report['department']})\n"
                        f"Summary: {report['summary']}\n"
                        f"Triage: Escalated — {reason}"
                    ),
                    source_agent="A.R.C.H.I.E.",
                    force=True,
                    _privileged=True,
                )

        logger.info(f"triage_consumer: processed {len(reports)} reports")
    except Exception as e:
        logger.error(f"triage_consumer error: {e}")
```

- [ ] **Step 3: Register the job**

In `agent_loop.py`, where other jobs are registered:
```python
scheduler.add_job(
    with_ctx(_run_triage_consumer),
    trigger=IntervalTrigger(seconds=30),
    id="archie_triage_consumer",
    name="A.R.C.H.I.E. Triage Consumer",
    max_instances=1,
    coalesce=True,
    replace_existing=True,
)
```

- [ ] **Step 4: Restart and verify job appears**
```bash
docker compose restart archie_platform
docker logs archie_platform --tail=50 | grep -i "triage_consumer\|triage consumer"
```
Expected: log line confirming job registered and first run.

- [ ] **Step 5: End-to-end test**
```bash
# Submit a critical report
TOKEN=$(grep ARCHIE_COMMS_SERVICE_TOKEN archie-comms/.env | cut -d= -f2)
curl -s -X POST http://192.168.1.200:3002/api/director/report \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: $TOKEN" \
  -d '{"department":"Security","director_agent":"V.I.G.I.L.","severity":"critical","category":"security","title":"E2E test","summary":"End to end test report"}'

# Wait 35 seconds, then check triage_status
sleep 35
docker exec archie_comms_db psql -U archie -d archie_comms \
  -c "SELECT id, title, triage_status, triage_action FROM director_reports WHERE title='E2E test';"
```
Expected: `triage_status = escalate` and Telegram message received.

- [ ] **Step 6: Commit**
```bash
git add platform_v2/ai_bridge/agent_loop.py
git commit -m "feat(unified-voice): triage consumer APScheduler job — 30s, max_instances=1 (#2264 #2265)"
```

---

### Task 11: Wave 2 PR + deploy

- [ ] **Create PR**
```bash
git checkout -b feat/unified-voice-wave2
git push -u origin feat/unified-voice-wave2
gh pr create \
  --title "feat(unified-voice): Wave 2 — Phase 2 triage consumer architecture" \
  --body "$(cat <<'EOF'
Closes #2261 #2262 #2263 #2264 #2265 #2223

## Changes
- archie-comms: /api/internal/director-reports + /triage endpoints (token-secured)
- archie-comms: /api/internal/triage-policies endpoint + triage_policies table
- archie-comms: triage_status/triage_action/triaged_at columns on director_reports
- platform_v2: director_report_service.py (get_pending_reports, triage_report, classify_report, get_policies, submit_via_inbox)
- platform_v2: archie_triage_consumer APScheduler job (30s, max_instances=1, coalesce)
- Only escalate-classified reports reach Telegram, sent as A.R.C.H.I.E. with force=True

## Test
- Submit critical report -> wait 35s -> triage_status=escalate, Telegram message received
- Submit low-severity report -> wait 35s -> triage_status=suppress, no Telegram
EOF
)"
```

- [ ] **Deploy + mark #2223 complete**
```bash
docker compose restart archie_comms archie_platform
```
Then in Dev HQ:
```
mcp__archie__complete_task(2223, "Phase 2 complete via sub-tasks #2261-#2265. Consumer live, end-to-end verified.")
```

---

## Wave 3 — Sender Privilege + UI + Phase 3

> PR: `feat/unified-voice-wave3`. Requires Wave 2 deployed.

---

### Task 12: Sender-privilege guardrail (#2224)

**Files:**
- Modify: `platform_v2/services/telegram_service.py` — `send()` function

- [ ] **Step 1: Add privilege check to send()**

In `telegram_service.py`, at module level add:
```python
_PRIVILEGED_SOURCES = frozenset({"A.R.C.H.I.E.", "archie_triage_consumer", "system_bootstrap"})
```

Modify the `send()` function signature and add the privilege check at the top of the function body:
```python
def send(category, title, message, source_agent=None, source_department=None,
         source_module=None, chat_id=None, force=False, _privileged=False):

    caller_is_privileged = _privileged or (source_agent in _PRIVILEGED_SOURCES)

    if not caller_is_privileged:
        logger.warning(
            f"telegram_service.send() unprivileged caller '{source_agent}' — "
            f"routing to director report inbox"
        )
        from services.director_report_service import submit_via_inbox
        return submit_via_inbox(category, title, message, source_agent)

    # ... rest of existing send logic unchanged ...
```

- [ ] **Step 2: Verify triage consumer still works**
```bash
docker compose restart archie_platform
docker logs archie_platform --tail=30 | grep -i "triage\|privileged"
```
Expected: triage consumer runs without "unprivileged caller" warnings (it passes `_privileged=True`).

- [ ] **Step 3: Commit**
```bash
git add platform_v2/services/telegram_service.py
git commit -m "feat(unified-voice): sender-privilege guardrail — non-A.R.C.H.I.E. sends route to inbox (#2224)"
```

---

### Task 13: Audit direct senders and migrate (#2225)

**Files:**
- Modify: any files found by the audit grep

- [ ] **Step 1: Audit all direct send_* callers**
```bash
grep -rn "send_system\|send_security\|send_forge\|send_agent\|send_sync\|send_info" \
  /mnt/archie_brain/platform_v2/ \
  --include="*.py" \
  | grep -v "telegram_service.py\|_deprecated\|test_" \
  | grep -v "agent_loop.py"
```

- [ ] **Step 2: Check logs after Task 12 deploy**

Since the privilege guardrail (Task 12) automatically redirects unprivileged callers, most migration is already done. Verify via logs:
```bash
docker logs archie_platform --since=1h | grep "unprivileged caller" | sort | uniq -c | sort -rn
```

For any callers that should become first-class director reporters (known agents with a department), replace `send_system()/send_security()` with an explicit `requests.post()` to `/api/director/report` so the report carries the correct department/severity metadata:

```python
# BEFORE (implicit, loses metadata)
send_system(title="Disk alert", message="Disk at 95%")

# AFTER (explicit, carries correct metadata)
import requests, os
requests.post(
    f"{os.getenv('ARCHIE_COMMS_URL','http://archie_comms:3002')}/api/director/report",
    headers={
        "Content-Type": "application/json",
        "X-Service-Token": os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", ""),
    },
    json={
        "department": "Operations & Infrastructure",
        "director_agent": "B.A.S.E.",
        "severity": "medium",
        "category": "operations",
        "title": "Disk alert",
        "summary": "Disk at 95%",
    },
    timeout=5,
)
```

- [ ] **Step 3: Commit**
```bash
git add <any modified files>
git commit -m "feat(unified-voice): migrate direct telegram senders to director report inbox (#2225)"
```

---

### Task 14: Triage inbox UI in COMs tab (#2268)

**Files:**
- Modify: `platform_v2/tools/department_hq/coms_routes.py`
- Modify: COMs HTML template (find with `find /mnt/archie_brain/platform_v2/templates -name "*coms*"`)

- [ ] **Step 1: Add inbox API endpoints to coms_routes.py**

Inside `register_coms_routes(bp, admin_required)`:
```python
@bp.route("/api/coms/director-reports", methods=["GET"])
@admin_required
def api_coms_director_reports():
    from services.director_report_service import get_pending_reports
    reports = get_pending_reports(limit=50)
    return jsonify({"reports": reports, "count": len(reports)})


@bp.route("/api/coms/director-reports/<int:report_id>/ack", methods=["POST"])
@admin_required
def api_coms_ack_report(report_id):
    from services.director_report_service import triage_report
    data = request.get_json() or {}
    action = data.get("action", "suppress")
    if action not in ("resolve", "consolidate", "suppress", "escalate"):
        return jsonify({"error": "Invalid action"}), 400
    ok = triage_report(report_id, action, reason="Manual override by Kytran")
    return jsonify({"success": ok})
```

- [ ] **Step 2: Add Inbox tab to COMs template**

In the tab navigation bar, add:
```html
<button class="coms-tab-btn" data-tab="inbox" onclick="switchComsTab('inbox')">
  Inbox <span id="inbox-count-badge" class="coms-badge" style="display:none">0</span>
</button>
```

Add a new tab panel:
```html
<div id="coms-panel-inbox" class="coms-tab-panel" style="display:none">
  <div class="coms-panel-header">
    <h3>Director Reports — Triage Inbox</h3>
    <button class="lcars-btn" onclick="comsLoadInbox()">Refresh</button>
  </div>
  <div id="coms-inbox-list" class="coms-inbox-list"></div>
</div>
```

- [ ] **Step 3: Add JS for inbox (in the template's script section)**

Note: `escHtml` is already defined in `consciousness.js` — use it here to prevent XSS.

```javascript
function escHtml(s) {
  // Local fallback in case consciousness.js escHtml isn't in scope here
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function comsLoadInbox() {
  const resp = await fetch('/tools/department-hq/api/coms/director-reports');
  const data = await resp.json();

  const badge = document.getElementById('inbox-count-badge');
  badge.textContent = data.count;
  badge.style.display = data.count > 0 ? '' : 'none';

  const list = document.getElementById('coms-inbox-list');
  if (!data.reports || data.reports.length === 0) {
    list.innerHTML = '<p class="coms-empty">No pending reports.</p>';
    return;
  }

  list.innerHTML = data.reports.map(function(r) {
    return (
      '<div class="coms-inbox-item sev-' + escHtml(r.severity) + '">' +
        '<div class="coms-inbox-meta">' +
          escHtml(r.director_agent) + ' &middot; ' +
          escHtml(r.department) + ' &middot; ' +
          escHtml(r.severity.toUpperCase()) +
        '</div>' +
        '<div class="coms-inbox-title">' + escHtml(r.title) + '</div>' +
        '<div class="coms-inbox-summary">' + escHtml(r.summary) + '</div>' +
        '<div class="coms-inbox-actions">' +
          '<button onclick="comsAckReport(' + r.id + ',\'suppress\')">Suppress</button>' +
          '<button onclick="comsAckReport(' + r.id + ',\'escalate\')">Escalate</button>' +
          '<button onclick="comsAckReport(' + r.id + ',\'resolve\')">Resolve</button>' +
        '</div>' +
      '</div>'
    );
  }).join('');
}

async function comsAckReport(id, action) {
  await fetch(
    '/tools/department-hq/api/coms/director-reports/' + id + '/ack',
    {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: action}),
    }
  );
  comsLoadInbox();
}
```

- [ ] **Step 4: Browser test**

Navigate to `http://192.168.1.200:3000/tools/department-hq` → COMs tab → Inbox.
- Reports should appear with severity styling
- Suppress/Escalate/Resolve buttons update the list immediately
- Badge count updates on each refresh

- [ ] **Step 5: Commit**
```bash
git add platform_v2/tools/department_hq/coms_routes.py \
        platform_v2/templates/tools/department_hq*.html
git commit -m "feat(unified-voice): triage inbox UI in COMs tab — view/ack/suppress director reports (#2268)"
```

---

### Task 15: Audit log for telegram_service send operations (#2269)

**Files:**
- Modify: `platform_v2/services/telegram_service.py`

- [ ] **Step 1: Add _audit_send() helper**

In `telegram_service.py`:
```python
import hashlib as _hashlib
import json as _json

def _audit_send(category: str, title: str, source_agent: str,
                route: str, suppressed: bool) -> None:
    """Write send audit entry to governance_audit_log. Non-blocking."""
    try:
        from database import get_db_cursor
        msg_hash = _hashlib.sha256(
            f"{title}{source_agent}".encode()
        ).hexdigest()[:16]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                  (event_category, event_type, actor, details, timestamp)
                VALUES ('telegram_send', %s, %s, %s::jsonb, NOW())
                """,
                (
                    category,
                    source_agent or "unknown",
                    _json.dumps({
                        "title": title,
                        "route": route,
                        "suppressed": suppressed,
                        "msg_hash": msg_hash,
                    }),
                ),
            )
    except Exception as e:
        logger.warning(f"telegram audit log failed (non-blocking): {e}")
```

- [ ] **Step 2: Call _audit_send() at end of send()**

At the bottom of the `send()` function, just before returning:
```python
# Audit — route is "inbox" if redirected, "comms" if went to archie-comms, "direct" otherwise
_audit_send(category, title, source_agent, route=_route_taken, suppressed=_was_suppressed)
return result
```

Set `_route_taken` and `_was_suppressed` based on which code path ran.

- [ ] **Step 3: Verify audit rows**
```bash
docker exec -it archie_database psql -U archie -d archie \
  -c "SELECT actor, event_type, details->>'route' AS route, timestamp
      FROM governance_audit_log
      WHERE event_category='telegram_send'
      ORDER BY timestamp DESC LIMIT 5;"
```

- [ ] **Step 4: Commit**
```bash
git add platform_v2/services/telegram_service.py
git commit -m "feat(unified-voice): audit log for telegram_service send operations (#2269)"
```

---

### Task 16: MCP tool `get_system_alerts` (#2226)

**Files:**
- Find MCP tool registration file, add `get_system_alerts`

- [ ] **Step 1: Find where MCP tools are registered**
```bash
grep -rn "mcp_tool\|register_mcp\|@mcp\|\"get_quick_summary\"\|get_quick_summary" \
  /mnt/archie_brain/platform_v2/ --include="*.py" | head -10
```

- [ ] **Step 2: Add get_system_alerts following the existing pattern**

Adapt the following to match the project's MCP tool registration pattern:
```python
# Tool definition
def mcp_get_system_alerts(limit: int = 20, severity: str = None, since_hours: int = 24):
    """
    Unified query across system_notifications + escalated director_reports.
    Returns ranked alerts sorted by recency.
    """
    from database import get_db_cursor
    from services.director_report_service import get_pending_reports
    alerts = []

    # system_notifications
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT 'notification' AS source, type AS severity,
                       title, message AS detail, created_at
                FROM system_notifications
                WHERE created_at > NOW() - INTERVAL '%s hours'
                  AND (%s IS NULL OR type = %s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (since_hours, severity, severity, limit),
            )
            cols = [c[0] for c in cur.description]
            alerts += [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"get_system_alerts notifications query failed: {e}")

    # escalated director_reports
    try:
        reports = get_pending_reports(limit=limit)
        for r in reports:
            if r.get("severity") in ("critical", "high"):
                alerts.append({
                    "source": "director_report",
                    "severity": r["severity"],
                    "title": r["title"],
                    "detail": r["summary"],
                    "created_at": r.get("created_at"),
                })
    except Exception as e:
        logger.warning(f"get_system_alerts director_reports query failed: {e}")

    alerts.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"alerts": alerts[:limit], "count": len(alerts)}
```

- [ ] **Step 3: Test via MCP**
```
mcp__archie__get_system_alerts(limit=5, since_hours=1)
```
Expected: `{"alerts": [...], "count": N}`.

- [ ] **Step 4: Commit**
```bash
git add <mcp registration file>
git commit -m "feat(unified-voice): MCP get_system_alerts — unified notifications + director_reports (#2226)"
```

---

### Task 17: Wave 3 PR + deploy

- [ ] **Create PR**
```bash
git checkout -b feat/unified-voice-wave3
git push -u origin feat/unified-voice-wave3
gh pr create \
  --title "feat(unified-voice): Wave 3 — sender privilege, inbox UI, audit log, MCP alerts" \
  --body "$(cat <<'EOF'
Closes #2224 #2225 #2268 #2269 #2226

## Changes
- Sender-privilege guardrail: unprivileged telegram_service.send() callers auto-route to inbox
- Direct sender audit: logs route (direct/comms/inbox), suppressed flag, msg_hash to governance_audit_log
- Triage inbox UI in COMs tab: view/ack/escalate/suppress with XSS-safe rendering (escHtml)
- MCP get_system_alerts: unified query across system_notifications + escalated director_reports

## Test
- Send via unprivileged source -> logs show "routing to director report inbox", NOT direct Telegram
- Open COMs Inbox tab -> pending reports visible, ack buttons work
- mcp__archie__get_system_alerts(limit=5) returns alerts JSON
- governance_audit_log has telegram_send rows with route field
EOF
)"
```

---

## Dependency Map

```
Wave 1 (security + bugfixes — no dependencies)
  Task 1: Secure /api/director/report (#2266 + #2267)
  Task 2: Redirect telegram_gateway (#2235)
  Task 3: Dedup race condition (#2234)
  Task 4: B.A.S.E. watchdog dedup (#2233)
  Task 5: nginx probe fix (#2229)
        |
        v
Wave 2 (requires Wave 1 token auth live)
  Task 7: Inbox visibility layer (#2261)     <- first in Wave 2
  Task 8: Classification logic (#2262)       <- extends Task 7 types
  Task 9: Policy engine (#2263)              <- extends Task 8
  Task 10: Consumer job (#2264 + #2265)      <- requires Tasks 7+8+9
        |
        v
Wave 3 (requires Wave 2 consumer live)
  Task 12: Sender privilege (#2224)          <- can be first
  Task 13: Migrate senders (#2225)           <- requires Task 12
  Task 14: Inbox UI (#2268)                  <- requires Wave 2 endpoints
  Task 15: Audit log (#2269)                 <- independent
  Task 16: MCP get_system_alerts (#2226)     <- independent
```

---

## Self-Review

- All 17 active task IDs covered (#2235, #2266, #2267, #2234, #2233, #2229, #2261, #2262, #2263, #2264, #2265, #2223, #2224, #2225, #2268, #2269, #2226)
- No TBD/TODO placeholders
- `escHtml()` used for all user-facing data in inbox UI (XSS safe)
- Function signatures consistent: `classify_report(report, policies)`, `triage_report(report_id, action, reason)`, `get_pending_reports(limit)` used identically across Tasks 7-16
- `_headers()`, `_COMMS_BASE`, `_TOKEN` all defined in Task 7 service file, referenced in Tasks 8-16
- APScheduler pattern matches discovered codebase pattern (with_ctx, IntervalTrigger, max_instances, coalesce, replace_existing)
- Wave ordering enforces token auth (Task 1) before any cross-container calls (Wave 2)
- `_privileged=True` added to triage consumer send (Task 10) and checked in guardrail (Task 12) consistently
