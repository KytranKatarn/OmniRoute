# Security Network Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden admin platform access with login flood alerts, IP allowlisting, and module role visibility enforcement.

**Architecture:** Three independent changes: (1) autonomy job in `agent_loop.py` that detects excessive successful logins and fires Telegram alerts via `send_security()`; (2) one-time Python script that configures an NPM IP allowlist via the NPM REST API; (3) single `minimum_role` change in `module_registry.py` for `archie_chat`.

**Tech Stack:** Python (Flask, APScheduler), PostgreSQL (`audit_log`, `system_config`), NPM REST API (`http://nginx_proxy_manager:81/api`).

---

## File Map

| File | Action |
|------|--------|
| `ai_bridge/agent_loop.py` | Add `_run_login_anomaly_check()` method + job registration |
| `scripts/setup_npm_ip_allowlist.py` | Create — one-time NPM access list setup script |
| `platform_v2/module_registry.py` | Change `archie_chat` `minimum_role` from `"ADMIN"` to `"COLLABORATOR"` |

**Note on media_studio:** `minimum_role="USER"` already — no change needed. Business partners (COLLABORATOR ≥ USER) already have access.

---

## Task 1: Login Anomaly Detection Job

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Find where to add the job registration**

```bash
grep -n "login_anomaly\|add_job.*interval\|IntervalTrigger" ai_bridge/agent_loop.py | tail -20
```

Find the last `self.scheduler.add_job(...)` block in `_setup_jobs()`. The new job goes immediately after it.

Also find the last `def _run_` method in the file to know where to insert the function:

```bash
grep -n "def _run_" ai_bridge/agent_loop.py | tail -10
```

- [ ] **Step 2: Add job registration**

Inside `_setup_jobs()`, after the last existing `self.scheduler.add_job(...)` block, add:

```python
        self.scheduler.add_job(
            with_app_context(self._run_login_anomaly_check),
            trigger=IntervalTrigger(minutes=30),
            id="login_anomaly_check",
            name="Agent Loop: Login Anomaly Check",
            replace_existing=True,
        )
```

- [ ] **Step 3: Add the job function**

Add this method to the `AgentLoop` class (after the last `def _run_` method, before the class ends):

```python
    def _run_login_anomaly_check(self):
        """Alert on accounts with excessive successful logins in 24h."""
        import time as _time
        _start = _time.time()
        processed = 0
        try:
            from database import get_db_cursor
            from services.time_utils import now_utc
            from services.telegram_service import send_security

            # Read configurable threshold (default: 10 logins / 24h)
            threshold = 10
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT value FROM system_config WHERE key = 'login_anomaly_threshold'"
                )
                row = cur.fetchone()
                if row and row[0]:
                    try:
                        threshold = int(row[0])
                    except (ValueError, TypeError):
                        pass

            # Find users exceeding threshold in last 24h
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT a.user_id, u.username, u.email,
                           COUNT(*) AS login_count,
                           array_agg(DISTINCT a.ip_address) AS ips,
                           MIN(a.created_at) AS first_login,
                           MAX(a.created_at) AS last_login
                    FROM audit_log a
                    JOIN users u ON a.user_id = u.id
                    WHERE a.action = 'login_success'
                      AND a.created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY a.user_id, u.username, u.email
                    HAVING COUNT(*) >= %s
                    """,
                    [threshold],
                )
                rows = cur.fetchall() or []

            processed = len(rows)
            now = now_utc()

            for row in rows:
                user_id, username, email, login_count, ips, first_login, last_login = row

                # Rate-limit: one alert per user per 24h
                alert_key = f"anomaly_alert_{user_id}"
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT value FROM system_config WHERE key = %s", [alert_key]
                    )
                    existing = cur.fetchone()
                if existing and existing[0]:
                    try:
                        from datetime import datetime
                        last_alert = datetime.fromisoformat(existing[0])
                        if (now - last_alert).total_seconds() < 86400:
                            continue
                    except (ValueError, TypeError):
                        pass

                # Send Telegram security alert
                ip_list = ", ".join(
                    str(ip) for ip in (ips or []) if ip
                ) or "unknown"
                fmt = "%H:%M"
                window = (
                    f"{first_login.strftime(fmt) if first_login else '?'}"
                    f" → {last_login.strftime(fmt) if last_login else '?'}"
                )
                send_security(
                    title="Login Anomaly Detected",
                    message=(
                        f"User: {username} ({email})\n"
                        f"Logins in 24h: {login_count}\n"
                        f"IPs: {ip_list}\n"
                        f"Window: {window}"
                    ),
                )

                # Record alert sent (suppress repeats for 24h)
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO system_config (key, value)
                           VALUES (%s, %s)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                                                           updated_at = NOW()""",
                        [alert_key, now.isoformat()],
                    )
                logger.info(
                    "login_anomaly_check: alert sent for user_id=%s (%d logins)",
                    user_id,
                    login_count,
                )

            duration_ms = int((_time.time() - _start) * 1000)
            self._log_cycle("login_anomaly_check", processed, 0, duration_ms)
        except Exception as e:
            duration_ms = int((_time.time() - _start) * 1000)
            self._log_cycle("login_anomaly_check", 0, 1, duration_ms, error_message=str(e))
            logger.error("login_anomaly_check failed: %s", e)
```

- [ ] **Step 4: Verify syntax**

```bash
python3 -m py_compile ai_bridge/agent_loop.py && echo "SYNTAX OK"
```

Expected: `SYNTAX OK`

- [ ] **Step 5: Quick smoke test — verify the query works**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT a.user_id, u.username, COUNT(*) AS login_count,
       array_agg(DISTINCT a.ip_address) AS ips
FROM audit_log a
JOIN users u ON a.user_id = u.id
WHERE a.action = 'login_success'
  AND a.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY a.user_id, u.username
HAVING COUNT(*) >= 1
ORDER BY login_count DESC
LIMIT 5;
"
```

Expected: Results (or empty if no logins today) — confirms query runs without error.

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(security): add login anomaly detection job — Telegram alert on N+ logins/24h"
```

---

## Task 2: NPM IP Allowlist Setup Script

**Files:**
- Create: `scripts/setup_npm_ip_allowlist.py`

This is a **one-time setup script** — run it once to configure NPM, not an autonomy job.

- [ ] **Step 1: Seed the IP allowlist in system_config**

Replace `YOUR_HOME_IP` and `YOUR_VPN_IP` with the actual IPs before running:

```bash
docker exec archie_database psql -U archie -d archie -c "
INSERT INTO system_config (key, value, description)
VALUES ('admin_ip_allowlist', '[\"YOUR_HOME_IP\", \"YOUR_VPN_IP\"]', 'IPs allowed to access platform.kytranempowerment.com')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
"
```

Verify:
```bash
docker exec archie_database psql -U archie -d archie -t -c "SELECT value FROM system_config WHERE key='admin_ip_allowlist';"
```

- [ ] **Step 2: Create the setup script**

Create `scripts/setup_npm_ip_allowlist.py` with this content:

```python
#!/usr/bin/env python3
"""One-time script: create NPM access list + apply to platform.kytranempowerment.com proxy host."""

import json
import os
import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor

NPM_URL = os.getenv("NPM_API_URL", "http://nginx_proxy_manager:81/api")
NPM_EMAIL = os.getenv("NPM_ADMIN_EMAIL", "")
NPM_PASSWORD = os.getenv("NPM_ADMIN_PASSWORD", "")
PLATFORM_DOMAIN = "platform.kytranempowerment.com"
LIST_NAME = "Admin Platform Allowlist"


def npm_request(method, path, token=None, body=None):
    """Make an NPM API request using urllib (no extra deps)."""
    import urllib.request, urllib.error
    url = NPM_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code} for {method} {path}: {body}")
        raise


def get_token():
    resp = npm_request("POST", "/tokens", body={"identity": NPM_EMAIL, "secret": NPM_PASSWORD})
    return resp["token"]


def get_ip_list():
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT value FROM system_config WHERE key = 'admin_ip_allowlist'")
        row = cur.fetchone()
    if not row or not row[0]:
        print("ERROR: system_config key 'admin_ip_allowlist' not set.")
        print("Set it with:")
        print('  INSERT INTO system_config (key, value) VALUES (\'admin_ip_allowlist\', \'["x.x.x.x"]\') ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;')
        sys.exit(1)
    ips = json.loads(row[0])
    if not ips:
        print("ERROR: admin_ip_allowlist is empty.")
        sys.exit(1)
    return ips


def find_proxy_host(token):
    hosts = npm_request("GET", "/proxy-hosts", token=token)
    for host in hosts:
        domains = host.get("domain_names", [])
        if PLATFORM_DOMAIN in domains:
            return host
    print(f"ERROR: No proxy host found for {PLATFORM_DOMAIN}")
    print("Existing hosts:", [h.get("domain_names") for h in hosts])
    sys.exit(1)


def create_or_get_access_list(token, ips):
    """Create access list if it doesn't exist, return its ID."""
    lists = npm_request("GET", "/access-lists", token=token)
    for lst in lists:
        if lst.get("name") == LIST_NAME:
            print(f"Access list '{LIST_NAME}' already exists (id={lst['id']}). Updating clients...")
            # Update with current IPs
            clients = [{"address": ip, "comment": "allowlisted", "directive": "allow"} for ip in ips]
            npm_request("PUT", f"/access-lists/{lst['id']}", token=token, body={
                "name": LIST_NAME,
                "satisfy_any": False,
                "pass_auth": False,
                "clients": clients,
                "items": [],
            })
            return lst["id"]

    # Create new
    clients = [{"address": ip, "comment": "allowlisted", "directive": "allow"} for ip in ips]
    resp = npm_request("POST", "/access-lists", token=token, body={
        "name": LIST_NAME,
        "satisfy_any": False,
        "pass_auth": False,
        "clients": clients,
        "items": [],
    })
    print(f"Created access list '{LIST_NAME}' (id={resp['id']})")
    return resp["id"]


def apply_to_host(token, host, list_id):
    host_id = host["id"]
    npm_request("PUT", f"/proxy-hosts/{host_id}", token=token, body={
        "domain_names": host["domain_names"],
        "forward_scheme": host["forward_scheme"],
        "forward_host": host["forward_host"],
        "forward_port": host["forward_port"],
        "access_list_id": list_id,
        "certificate_id": host.get("certificate_id", 0),
        "ssl_forced": host.get("ssl_forced", False),
        "caching_enabled": host.get("caching_enabled", False),
        "block_exploits": host.get("block_exploits", False),
        "allow_websocket_upgrade": host.get("allow_websocket_upgrade", False),
        "http2_support": host.get("http2_support", False),
        "hsts_enabled": host.get("hsts_enabled", False),
        "hsts_subdomains": host.get("hsts_subdomains", False),
        "locations": host.get("locations", []),
    })
    print(f"Applied access list {list_id} to proxy host {host_id} ({PLATFORM_DOMAIN})")


def main():
    print(f"NPM URL: {NPM_URL}")
    print(f"Target domain: {PLATFORM_DOMAIN}")

    ips = get_ip_list()
    print(f"Allowlisted IPs: {ips}")

    token = get_token()
    print("NPM authentication: OK")

    host = find_proxy_host(token)
    print(f"Found proxy host id={host['id']} for {PLATFORM_DOMAIN}")

    list_id = create_or_get_access_list(token, ips)

    apply_to_host(token, host, list_id)
    print("Done. Access list is now enforced.")
    print("Test: access the platform from a non-allowlisted IP — should get 403.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the script from inside the platform container**

First set your actual home/VPN IPs in system_config (Step 1 above), then:

```bash
docker exec -e NPM_API_URL="$NPM_API_URL" \
  -e NPM_ADMIN_EMAIL="$NPM_ADMIN_EMAIL" \
  -e NPM_ADMIN_PASSWORD="$NPM_ADMIN_PASSWORD" \
  archie_platform \
  python3 /mnt/archie_brain/scripts/setup_npm_ip_allowlist.py
```

Expected output:
```
NPM URL: http://nginx_proxy_manager:81/api
Target domain: platform.kytranempowerment.com
Allowlisted IPs: [...]
NPM authentication: OK
Found proxy host id=N for platform.kytranempowerment.com
Created access list 'Admin Platform Allowlist' (id=M)
Applied access list M to proxy host N (platform.kytranempowerment.com)
Done. Access list is now enforced.
```

- [ ] **Step 4: Verify from a non-allowlisted IP (optional)**

If you have a second device on a different network (mobile data), try accessing `https://platform.kytranempowerment.com` — should return 403 Forbidden.

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_npm_ip_allowlist.py
git commit -m "feat(security): add NPM IP allowlist setup script for admin platform"
```

---

## Task 3: Module Visibility — archie_chat to COLLABORATOR

**Files:**
- Modify: `platform_v2/module_registry.py`

- [ ] **Step 1: Find the current minimum_role for archie_chat**

```bash
grep -n "archie_chat\|A\.R\.C\.H\.I\.E\. Chat\|minimum_role" platform_v2/module_registry.py | head -20
```

Look for the `ModuleDefinition(...)` block that has `module_id="archie_chat"` (or name containing "Chat") and note its `minimum_role` value.

- [ ] **Step 2: Verify media_studio is already USER**

```bash
grep -n -A8 'name="Media Studio"' platform_v2/module_registry.py | grep minimum_role
```

Expected: `minimum_role="USER"` — no change needed.

- [ ] **Step 3: Change archie_chat minimum_role**

Find the exact text. It will look like one of:

```python
        minimum_role="ADMIN",
```

near a block with `module_id="archie_chat"` or `name="A.R.C.H.I.E. Chat"`. Read the surrounding 10 lines to confirm it's the right block, then change only that `minimum_role` line:

Old:
```python
        minimum_role="ADMIN",
```

New:
```python
        minimum_role="COLLABORATOR",
```

**Important:** There may be multiple ModuleDefinition entries for archie_chat (sidebar vs main). Change ALL of them that are for the archie_chat module.

- [ ] **Step 4: Verify the change**

```bash
grep -n "minimum_role" platform_v2/module_registry.py | grep -i "COLLABORATOR"
```

Expected: at least one line for archie_chat now showing COLLABORATOR.

```bash
python3 -c "from platform_v2.module_registry import get_all_modules; print('OK')" 2>/dev/null || python3 -m py_compile platform_v2/module_registry.py && echo "SYNTAX OK"
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/module_registry.py
git commit -m "feat(security): archie_chat minimum_role ADMIN→COLLABORATOR for business partner access"
```

---

## Task 4: Deploy, Verify, PR

- [ ] **Step 1: Restart scheduler (anomaly job runs there)**

```bash
docker compose restart archie_scheduler archie_platform
sleep 15
docker logs archie_scheduler 2>&1 | grep -i "login_anomaly\|error" | tail -10
```

Expected: `login_anomaly_check` job registered, no errors.

- [ ] **Step 2: Verify job is registered**

```bash
docker exec archie_database psql -U archie -d archie -t -c \
  "SELECT job_name, status, created_at FROM autonomy_loop_log WHERE job_name='login_anomaly_check' ORDER BY created_at DESC LIMIT 3;"
```

Wait up to 30 minutes for first run, or trigger manually:

```bash
docker exec archie_scheduler python3 -c "
import sys; sys.path.insert(0, '/mnt/archie_brain')
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
from ai_bridge.agent_loop import AgentLoop
# Just test the query runs
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute('''SELECT a.user_id, u.username, COUNT(*) AS cnt
                   FROM audit_log a JOIN users u ON a.user_id=u.id
                   WHERE a.action=\'login_success\'
                     AND a.created_at >= NOW() - INTERVAL \'24 hours\'
                   GROUP BY a.user_id, u.username
                   HAVING COUNT(*) >= 1
                   ORDER BY cnt DESC LIMIT 5''')
    for row in cur.fetchall(): print(row)
print('Query OK')
" 2>/dev/null
```

- [ ] **Step 3: Verify module visibility**

Temporarily promote a test account to COLLABORATOR role and verify the dashboard shows archie_chat:

```bash
docker exec archie_database psql -U archie -d archie -c \
  "UPDATE users SET role='COLLABORATOR' WHERE email='probe@kytranempowerment.com';"
```

Log in as probe@ in browser → verify A.R.C.H.I.E. Chat appears in dashboard but Repair Bay / DHQ do not.

Restore:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "UPDATE users SET role='admin' WHERE email='probe@kytranempowerment.com';"
```

- [ ] **Step 4: Create feature branch and push**

```bash
git checkout -b feat/security-login-anomaly-ip-allowlist
git push -u origin feat/security-login-anomaly-ip-allowlist
```

- [ ] **Step 5: Open PR**

```bash
gh pr create \
  --title "feat(security): login anomaly detection + IP allowlist + archie_chat COLLABORATOR role" \
  --body "$(cat <<'EOF'
## Summary
- New autonomy job `login_anomaly_check` (every 30min): fires `send_security()` Telegram alert when any account exceeds N successful logins in 24h window (default N=10, configurable via system_config)
- `scripts/setup_npm_ip_allowlist.py`: one-time script to create NPM access list from system_config IPs and apply to platform.kytranempowerment.com proxy host
- `archie_chat` minimum_role: ADMIN → COLLABORATOR — business partners can now access A.R.C.H.I.E. Chat (media_studio was already USER)

## Test plan
- [ ] login_anomaly_check job appears in autonomy_loop_log after scheduler restart
- [ ] Query runs without error on audit_log
- [ ] NPM access list script creates list and applies to platform proxy host
- [ ] COLLABORATOR-role account sees archie_chat in dashboard, NOT repair_bay or department_hq
- [ ] No native confirm()/prompt() dialogs (not applicable here)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Login anomaly detection job: Task 1 ✅
- `audit_log` query with `send_security()`: Task 1 ✅
- 24h rate-limit via system_config: Task 1 Step 3 ✅
- NPM IP allowlist setup script: Task 2 ✅
- IP list seeded from system_config: Task 2 Step 1 + Step 2 ✅
- `archie_chat` ADMIN → COLLABORATOR: Task 3 ✅
- media_studio already USER (no change): Task 3 Step 2 ✅

**Placeholder scan:** "YOUR_HOME_IP" and "YOUR_VPN_IP" in Task 2 Step 1 are intentional — the actual IPs are Kytran's private network details that should not be in a spec doc. The plan instructs to replace them at execution time. All code blocks are complete.

**Type consistency:**
- `send_security(title=..., message=...)` — matches `telegram_service.py` signature `def send_security(title: str, message: str, **kwargs)` ✅
- `_log_cycle("login_anomaly_check", processed, 0, duration_ms)` — matches existing call pattern ✅
- `system_config` table columns (key, value, updated_at) used consistently ✅
- NPM API paths `/tokens`, `/access-lists`, `/proxy-hosts` — standard NPM 2.x API ✅
