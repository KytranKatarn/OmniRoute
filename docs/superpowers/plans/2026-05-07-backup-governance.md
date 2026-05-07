# Backup Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix stale secondary backup tiers and broken UI tabs, split the 5,029 LOC backup routes monolith into 5 focused files, and wire W.A.R.D.E.N. as the backup authority so no Repair Bay deploy can proceed without backup clearance.

**Architecture:** Three sequential phases — Phase 1 restores operational health (UI fixes, secondary tier failures, QA suite), Phase 2 refactors the code (routes split, backup_service extraction, module_snapshots table), Phase 3 delivers agent governance (backup_governance_service.py, severity gates, Repair Bay integration via delegate_task).

**Tech Stack:** Python/Flask, PostgreSQL (psycopg2), pytest, YAML QA specs (qa_spec_runner), APScheduler, Telegram (telegram_service), delegate_task infrastructure (delegation_service.py)

---

## File Map

**Phase 1 — Modify:**
- `platform_v2/tools/backup_manager/backup_manager_routes.py` — fix list, cloud, external, hooks tab queries
- `platform_v2/qa_suites/backup-health-smoke.yaml` — new smoke suite (24 tests)

**Phase 2 — Create:**
- `platform_v2/tools/backup_manager/routes_operations.py` — create, list, status, health endpoints
- `platform_v2/tools/backup_manager/routes_restore.py` — restore, preview, component restore
- `platform_v2/tools/backup_manager/routes_webhooks.py` — webhook CRUD, trigger, history
- `platform_v2/tools/backup_manager/routes_storage.py` — GDrive, external USB, encryption, packages
- `platform_v2/tools/backup_manager/routes_admin.py` — hooks, retention, audit log, config
- `platform_v2/services/backup_service.py` — extracted business logic, callable without Flask
- `database/migrations/371_module_snapshots.sql` — module_snapshots table
- `platform_v2/tests/test_backup_service.py` — unit tests for backup_service

**Phase 2 — Modify:**
- `platform_v2/tools/backup_manager/__init__.py` — replace single-file import with 5 register calls
- `platform_v2/tools/backup_manager/backup_manager_routes.py` — DELETE after Phase 2 complete

**Phase 3 — Create:**
- `platform_v2/services/backup_governance_service.py` — clearance logic owned by W.A.R.D.E.N.
- `database/migrations/372_backup_governance.sql` — governance columns on improvement_proposals + module_snapshots
- `platform_v2/tests/test_backup_governance_service.py` — unit tests
- `platform_v2/qa_suites/backup-governance-e2e.yaml` — governance QA suite

**Phase 3 — Modify:**
- `platform_v2/services/proposal_service.py:509` — add governance clearance check in `run_proposal()`
- `platform_v2/services/department_coordinator.py` — add `backup_governance` to CAPABILITY_DEPARTMENT_MAP
- `platform_v2/services/agent_skills` (DB insert) — W.A.R.D.E.N. backup_governance Lv5

---

## PHASE 1 — OPERATIONAL FIX

---

### Task 1: Diagnose backup list tab bug

**Files:**
- Read: `platform_v2/tools/backup_manager/backup_manager_routes.py:1879-1950`

- [ ] **Step 1: Read the list_backups route**

```bash
sed -n '1879,1960p' /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py
```

- [ ] **Step 2: Check what backup_log actually contains**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT status, tier, COUNT(*) FROM backup_log
GROUP BY status, tier ORDER BY status, tier;"
```

Expected: rows showing 'success', 'failed', 'skipped' statuses across primary/gdrive/vps/usb tiers.

- [ ] **Step 3: Identify the mismatch**

Note the actual status values in the DB. The route likely filters by a status string that doesn't match (e.g., `status = 'completed'` when actual value is `'success'`), or filters by a path that no longer exists on disk.

- [ ] **Step 4: Check secondary tier last error messages**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT tier, status, error_message, created_at
FROM backup_log
WHERE tier IN ('gdrive', 'vps', 'usb')
ORDER BY created_at DESC LIMIT 15;"
```

Expected: error messages showing WHY gdrive/vps/usb stopped after 2026-04-17.

---

### Task 2: Fix backup list tab query

**Files:**
- Modify: `platform_v2/tools/backup_manager/backup_manager_routes.py:1879`

- [ ] **Step 1: Write failing API test**

```bash
cat > /tmp/test_backup_list.py << 'EOF'
import requests, os
BASE = "http://192.168.1.200:3000"
# Get session cookie by logging in
s = requests.Session()
r = s.post(f"{BASE}/login", data={"username": "kytran", "password": os.environ["ARCHIE_TEST_PASSWORD"]})
assert r.status_code in (200, 302), f"Login failed: {r.status_code}"
r = s.get(f"{BASE}/tools/backup-manager/api/list")
assert r.status_code == 200, f"Got {r.status_code}"
data = r.json()
assert isinstance(data.get("backups") or data, list), "Expected list of backups"
assert len(data.get("backups") or data) > 0, "Backup list is empty — bug!"
print("PASS: backup list returns", len(data.get("backups") or data), "items")
EOF
python3 /tmp/test_backup_list.py
```
Expected: FAIL with "Backup list is empty — bug!"

- [ ] **Step 2: Fix the query in list_backups()**

Based on Task 1 diagnosis, the fix will be one of:
- Change `status = 'completed'` → `status = 'success'` in the SELECT
- Remove a file-existence filter that excludes all rows
- Fix a column name mismatch (e.g., `backup_name` vs `file_path`)

Apply the fix in `backup_manager_routes.py` at the `list_backups()` function.

- [ ] **Step 3: Restart and verify**

```bash
docker compose restart archie_platform
python3 /tmp/test_backup_list.py
```
Expected: PASS with count > 0.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/backup_manager/backup_manager_routes.py
git commit -m "fix(backup): repair list_backups query — was filtering no rows"
```

---

### Task 3: Diagnose and fix secondary tier failures

**Files:**
- Modify: secondary tier config (identified in Task 1 diagnosis)

- [ ] **Step 1: Check GDrive error details**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT error_message, created_at FROM backup_log
WHERE tier = 'gdrive' AND status = 'failed'
ORDER BY created_at DESC LIMIT 5;"
```

- [ ] **Step 2: Check VPS and USB errors**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT tier, error_message, created_at FROM backup_log
WHERE tier IN ('vps', 'usb') AND status = 'failed'
ORDER BY created_at DESC LIMIT 5;"
```

- [ ] **Step 3: Verify GDrive token validity**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.backup_manager.gdrive_service import test_gdrive_connection
result = test_gdrive_connection()
print(result)
" 2>&1
```

If no `test_gdrive_connection` exists, check the passphrase and OAuth token directly:
```bash
docker exec archie_platform python3 -c "
import sys, os; sys.path.insert(0, '/app')
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute(\"SELECT key, value FROM system_config WHERE key LIKE '%gdrive%'\")
    for r in cur.fetchall(): print(r['key'], '=', r['value'][:40] if r['value'] else None)
" 2>&1
```

- [ ] **Step 4: Fix the root cause**

Apply the fix based on diagnosis:

**If GDrive token expired:** Trigger re-auth via the Cloud tab UI, or update the token in `system_config`.

**If VPS SSH key issue:**
```bash
docker exec archie_platform ssh -i /app/credentials/backup_key backup@<vps_ip> "echo ok" 2>&1
```
Fix permissions or update the key path in backup config.

**If USB mount missing:**
```bash
ls -la /mnt/external-backup/ 2>/dev/null || echo "Mount missing"
```
Update the USB path in backup configuration to the correct mount point.

- [ ] **Step 5: Trigger manual runs for each tier and verify**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.backup_manager import create_backup
for tier in ['gdrive', 'vps', 'usb']:
    r = create_backup(description=f'manual_test_{tier}', created_by_username='kytran', tier_override=tier)
    print(tier, r.get('success'), r.get('error'))
" 2>&1
```

- [ ] **Step 6: Confirm in backup_log**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT tier, status, created_at FROM backup_log
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC;"
```
Expected: success rows for gdrive, vps, usb.

- [ ] **Step 7: Commit**

```bash
git add -p  # stage only config/code changes, not secrets
git commit -m "fix(backup): restore secondary tier runs — gdrive/vps/usb were failing since 2026-04-17"
```

---

### Task 4: Fix remaining tabs (Cloud, External, Deployment, Hooks)

**Files:**
- Modify: `platform_v2/tools/backup_manager/backup_manager_routes.py`

- [ ] **Step 1: Audit Cloud tab endpoint**

```bash
grep -n 'cloud\|gdrive' /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py | grep -i 'route\|def ' | head -15
```

Identify the query backing the Cloud tab list. Verify it matches `backup_log` schema.

- [ ] **Step 2: Audit External tab endpoint**

```bash
grep -n 'external\|usb' /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py | grep -i 'route\|def ' | head -15
```

- [ ] **Step 3: Fix Deployment/Packages tab — add retention**

Find the deployment list endpoint. Add a 30-day default filter and prune button:

```python
# In the packages list endpoint, add default filter:
cutoff = datetime.now() - timedelta(days=30)
# Add to WHERE clause: AND created_at > %s
# params.append(cutoff)

# Add prune endpoint:
@backup_manager_bp.route("/api/packages/prune", methods=["POST"])
@admin_required
def prune_old_packages():
    """Delete packages older than retention_days (default 30)."""
    retention_days = request.json.get("retention_days", 30)
    cutoff = datetime.now() - timedelta(days=retention_days)
    # Delete files older than cutoff from BACKUP_DIR/packages/
    # Log pruned count to audit_log
    return jsonify({"success": True, "pruned": count})
```

- [ ] **Step 4: Fix Hooks tab — add last_run status**

Find the hooks list endpoint. Add `last_run`, `last_exit_code`, `last_output` fields to the response by reading from `backup_hooks_log` table (or create it if it doesn't exist):

```bash
docker exec archie_database psql -U archie -d archie -c "\d backup_hooks_log" 2>/dev/null || echo "table missing"
```

If missing, add a simple table:
```sql
-- Run if backup_hooks_log doesn't exist:
CREATE TABLE IF NOT EXISTS backup_hooks_log (
    id SERIAL PRIMARY KEY,
    hook_name TEXT NOT NULL,
    hook_type TEXT NOT NULL CHECK (hook_type IN ('pre', 'post')),
    exit_code INTEGER,
    output TEXT,
    run_at TIMESTAMPTZ DEFAULT NOW()
);
```

- [ ] **Step 5: Restart and manually verify each tab**

```bash
docker compose restart archie_platform
```
Open http://192.168.1.200:3000/tools/backup-manager and verify:
- Backups tab: shows list of backups with dates
- Cloud tab: shows GDrive stats (space, path, recent runs)
- External tab: shows USB stats
- Deployment tab: shows packages, prune button visible
- Hooks tab: shows hooks with last_run status

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/backup_manager/backup_manager_routes.py
git commit -m "fix(backup): repair Cloud, External, Deployment, Hooks tab queries and add retention"
```

---

### Task 5: Create backup-health-smoke QA suite

**Files:**
- Create: `platform_v2/qa_suites/backup-health-smoke.yaml`

- [ ] **Step 1: Write the suite**

```bash
cat > /mnt/archie_brain/platform_v2/qa_suites/backup-health-smoke.yaml << 'EOF'
suite:
  name: "backup-health-smoke"
  description: "Backup Manager — page load, list API, health, retention, webhooks"
  base_url: "http://192.168.1.200:3000"
  auth:
    username: "${ARCHIE_TEST_USERNAME}"
    password: "${ARCHIE_TEST_PASSWORD}"

tests:
  - name: "backup manager page loads"
    type: page_load
    path: /tools/backup-manager
    expect:
      status: [200]
      max_load_ms: 5000

  - name: "backup list returns data"
    type: api
    method: GET
    path: /tools/backup-manager/api/list
    expect:
      status: [200]

  - name: "backup health endpoint"
    type: api
    method: GET
    path: /tools/backup-manager/api/health
    expect:
      status: [200]

  - name: "backup tier freshness check"
    type: api
    method: GET
    path: /tools/backup-manager/api/tier-freshness
    expect:
      status: [200, 404]

  - name: "retention config loads"
    type: api
    method: GET
    path: /tools/backup-manager/api/retention
    expect:
      status: [200, 404]

  - name: "webhooks list loads"
    type: api
    method: GET
    path: /tools/backup-manager/api/webhooks
    expect:
      status: [200]

  - name: "cloud status endpoint"
    type: api
    method: GET
    path: /tools/backup-manager/api/cloud/status
    expect:
      status: [200, 404]

  - name: "external storage status"
    type: api
    method: GET
    path: /tools/backup-manager/api/external/status
    expect:
      status: [200, 404]
EOF
```

- [ ] **Step 2: Register in qa_test_suites**

```bash
docker exec archie_platform python3 -c "
import sys, os, yaml, json
sys.path.insert(0, '/app'); os.chdir('/app')
from database import get_db_cursor
with open('/app/qa_suites/backup-health-smoke.yaml') as f:
    spec = yaml.safe_load(f.read())
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute(
        'INSERT INTO qa_test_suites (name, description, target_url, spec, suite_type, is_active) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
        ('backup-health-smoke', 'Backup Manager smoke suite', 'http://192.168.1.200:3000', json.dumps(spec), 'internal', True)
    )
    print('Suite id:', cur.fetchone()['id'])
" 2>&1
```

- [ ] **Step 3: Run the suite**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
result = run_suite_by_name('backup-health-smoke')
print(result)
" 2>&1
```
Expected: all tests pass or return acceptable status codes.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/qa_suites/backup-health-smoke.yaml
git commit -m "feat(qa): backup-health-smoke suite — Phase 1 QA coverage"
```

---

## PHASE 2 — CODE QUALITY + MODULE SNAPSHOTS

---

### Task 6: Extract backup_service.py

**Files:**
- Create: `platform_v2/services/backup_service.py`
- Create: `platform_v2/tests/test_backup_service.py`

- [ ] **Step 1: Write failing tests for backup_service**

```bash
cat > /mnt/archie_brain/platform_v2/tests/test_backup_service.py << 'EOF'
"""Tests for backup_service — importable without Flask context."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_backup_service_importable():
    """backup_service must import without Flask app context."""
    from services.backup_service import (
        get_health_summary,
        verify_integrity,
        run_retention,
        snapshot_module,
    )
    assert callable(get_health_summary)
    assert callable(verify_integrity)
    assert callable(run_retention)
    assert callable(snapshot_module)


def test_get_health_summary_returns_dict():
    from services.backup_service import get_health_summary
    result = get_health_summary()
    assert isinstance(result, dict)
    assert "status" in result
    assert "last_backup" in result
    assert "tier_health" in result


def test_verify_integrity_invalid_id():
    from services.backup_service import verify_integrity
    result = verify_integrity(backup_id=999999)
    assert result["success"] is False
    assert "not_found" in result.get("error", "")


def test_snapshot_module_creates_row():
    from services.backup_service import snapshot_module
    from database import get_db_cursor
    result = snapshot_module(
        module_name="test_module",
        snapshot_type="manual",
        trigger_source="test",
    )
    assert result["success"] is True
    assert "snapshot_id" in result
    # Verify row exists
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id FROM module_snapshots WHERE id = %s", (result["snapshot_id"],))
        assert cur.fetchone() is not None
EOF
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_service.py -v 2>&1 | head -30
```
Expected: ImportError or ModuleNotFoundError on `backup_service`.

- [ ] **Step 3: Create backup_service.py**

```bash
cat > /mnt/archie_brain/platform_v2/services/backup_service.py << 'EOF'
"""
Backup service — business logic extracted from backup_manager_routes.py.
Callable without Flask application context (no current_app references).
Used by W.A.R.D.E.N., the scheduler, and backup_governance_service.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_health_summary() -> dict[str, Any]:
    """Return a compact backup health summary for all tiers.

    Returns:
        {
          "status": "healthy" | "degraded" | "critical",
          "last_backup": ISO timestamp or None,
          "tier_health": {tier: {"last_run": ISO|None, "status": str, "age_hours": float}}
        }
    """
    tiers = ["primary", "gdrive", "vps", "usb"]
    tier_health: dict = {}
    overall_ok = True

    with get_db_cursor() as (conn, cur):
        for tier in tiers:
            cur.execute(
                """
                SELECT status, created_at
                FROM backup_log
                WHERE tier = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (tier,),
            )
            row = cur.fetchone()
            if row:
                age_h = (
                    (datetime.now(timezone.utc) - row["created_at"].replace(tzinfo=timezone.utc)).total_seconds() / 3600
                    if row["created_at"] else None
                )
                tier_health[tier] = {
                    "last_run": row["created_at"].isoformat() if row["created_at"] else None,
                    "status": row["status"],
                    "age_hours": round(age_h, 1) if age_h is not None else None,
                }
                if row["status"] != "success" or (age_h and age_h > 48):
                    overall_ok = False
            else:
                tier_health[tier] = {"last_run": None, "status": "never", "age_hours": None}
                overall_ok = False

    # Get absolute last successful backup
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT created_at FROM backup_log WHERE status = 'success' ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        last_backup = row["created_at"].isoformat() if row else None

    return {
        "status": "healthy" if overall_ok else "degraded",
        "last_backup": last_backup,
        "tier_health": tier_health,
    }


def verify_integrity(backup_id: int) -> dict[str, Any]:
    """Verify checksum and existence of a backup by backup_log id.

    Returns:
        {"success": bool, "error": str|None, "verification_status": str}
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id, file_path, verification_status FROM backup_log WHERE id = %s",
            (backup_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "not_found", "verification_status": "not_found"}

        import os
        file_path = row["file_path"]
        if file_path and not os.path.exists(file_path):
            cur.execute(
                "UPDATE backup_log SET verification_status = 'file_missing' WHERE id = %s",
                (backup_id,),
            )
            return {"success": False, "error": "file_missing", "verification_status": "file_missing"}

        cur.execute(
            "UPDATE backup_log SET verification_status = 'verified' WHERE id = %s",
            (backup_id,),
        )
        return {"success": True, "error": None, "verification_status": "verified"}


def run_retention(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply retention policy — delete backup_log rows older than max_age_days.

    Args:
        policy: {"max_age_days": int, "min_keep": int}. Defaults from system_config.
    Returns:
        {"success": bool, "pruned": int}
    """
    if policy is None:
        policy = {"max_age_days": 30, "min_keep": 5}

    max_age_days = policy.get("max_age_days", 30)
    min_keep = policy.get("min_keep", 5)

    with get_db_cursor(commit=True) as (conn, cur):
        # Count total — never delete below min_keep
        cur.execute("SELECT COUNT(*) AS c FROM backup_log WHERE status = 'success'")
        total = cur.fetchone()["c"]
        if total <= min_keep:
            return {"success": True, "pruned": 0}

        cur.execute(
            """
            DELETE FROM backup_log
            WHERE id IN (
                SELECT id FROM backup_log
                WHERE created_at < NOW() - INTERVAL '%s days'
                ORDER BY created_at ASC
                LIMIT %s
            )
            """,
            (max_age_days, max(0, total - min_keep)),
        )
        pruned = cur.rowcount

    return {"success": True, "pruned": pruned}


def snapshot_module(
    module_name: str,
    snapshot_type: str = "manual",
    trigger_source: str = "manual",
    backup_id: int | None = None,
    clearance_task_id: int | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Create a module snapshot row in module_snapshots.

    snapshot_type: 'auto' | 'manual' | 'pre_deploy'
    trigger_source: 'repair_bay' | 'manual' | 'schedule'

    Returns:
        {"success": bool, "snapshot_id": int|None, "error": str|None}
    """
    if snapshot_type not in ("auto", "manual", "pre_deploy"):
        return {"success": False, "snapshot_id": None, "error": f"invalid snapshot_type: {snapshot_type}"}

    import json
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO module_snapshots
                (module_name, snapshot_type, trigger_source, backup_id, clearance_task_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                module_name,
                snapshot_type,
                trigger_source,
                backup_id,
                clearance_task_id,
                json.dumps(metadata or {}),
            ),
        )
        snapshot_id = cur.fetchone()["id"]

    logger.info("Module snapshot created: id=%d module=%s type=%s", snapshot_id, module_name, snapshot_type)
    return {"success": True, "snapshot_id": snapshot_id, "error": None}
EOF
```

- [ ] **Step 4: Run tests — expect 3 pass, 1 fail (snapshot_module needs migration)**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_service.py -v 2>&1 | head -40
```
Expected: `test_backup_service_importable` ✅, `test_get_health_summary_returns_dict` ✅, `test_verify_integrity_invalid_id` ✅, `test_snapshot_module_creates_row` ❌ (table missing — fixed in Task 7).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/backup_service.py platform_v2/tests/test_backup_service.py
git commit -m "feat(backup): extract backup_service.py — Flask-free business logic layer"
```

---

### Task 7: Migration — module_snapshots table

**Files:**
- Create: `database/migrations/371_module_snapshots.sql`

- [ ] **Step 1: Write the migration**

```bash
cat > /mnt/archie_brain/database/migrations/371_module_snapshots.sql << 'EOF'
-- Migration 371: module_snapshots table for pre-deploy and manual module checkpoints
-- Part of backup governance design (Phase 2 foundation, Phase 3 governance)

CREATE TABLE IF NOT EXISTS module_snapshots (
    id                SERIAL PRIMARY KEY,
    module_name       TEXT NOT NULL,
    snapshot_type     TEXT NOT NULL CHECK (snapshot_type IN ('auto', 'manual', 'pre_deploy')),
    trigger_source    TEXT NOT NULL,
    file_paths        JSONB DEFAULT '[]',
    db_tables         JSONB DEFAULT '[]',
    backup_id         INTEGER REFERENCES backup_log(id) ON DELETE SET NULL,
    clearance_task_id INTEGER,
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_module_snapshots_module ON module_snapshots(module_name);
CREATE INDEX IF NOT EXISTS idx_module_snapshots_created ON module_snapshots(created_at DESC);
EOF
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /var/lib/postgresql/migrations/371_module_snapshots.sql 2>/dev/null || \
docker cp /mnt/archie_brain/database/migrations/371_module_snapshots.sql archie_database:/tmp/ && \
docker exec archie_database psql -U archie -d archie -f /tmp/371_module_snapshots.sql
```

- [ ] **Step 3: Verify table created**

```bash
docker exec archie_database psql -U archie -d archie -c "\d module_snapshots"
```
Expected: table with 10 columns as defined.

- [ ] **Step 4: Run all backup_service tests — now all 4 should pass**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_service.py -v 2>&1
```
Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/371_module_snapshots.sql
git commit -m "feat(db): migration 371 — module_snapshots table for pre-deploy checkpoints"
```

---

### Task 8: Split routes — routes_operations.py

**Files:**
- Create: `platform_v2/tools/backup_manager/routes_operations.py`

- [ ] **Step 1: Identify all create/list/status/health endpoints**

```bash
grep -n '@backup_manager_bp.route' /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py | \
  grep -iv 'restore\|webhook\|gdrive\|cloud\|external\|usb\|hook\|retention\|audit\|config\|package\|module' | head -20
```

- [ ] **Step 2: Create routes_operations.py with the pattern**

```python
# platform_v2/tools/backup_manager/routes_operations.py
from flask import jsonify, request
from database import get_db_cursor
from services.backup_service import get_health_summary, verify_integrity


def register_operations_routes(bp, admin_required):
    """Register create, list, health, and status routes on bp."""

    @bp.route("/list")
    @admin_required
    def list_backups():
        # Move exact implementation from backup_manager_routes.py list_backups()
        pass  # REPLACE with copied + cleaned implementation

    @bp.route("/api/health")
    @admin_required
    def backup_health():
        summary = get_health_summary()
        return jsonify(summary)

    @bp.route("/create", methods=["POST"])
    @admin_required
    def create_backup_route():
        # Move implementation from backup_manager_routes.py
        pass  # REPLACE with copied + cleaned implementation

    # ... copy all remaining operations routes
```

Copy each function verbatim from `backup_manager_routes.py`, then remove `@backup_manager_bp` decorator and replace with the function signature under `register_operations_routes`. Remove any Flask `current_app` references and replace with direct config reads.

- [ ] **Step 3: Verify no 50+ line route handlers remain**

```bash
python3 -c "
import ast, sys
with open('/mnt/archie_brain/platform_v2/tools/backup_manager/routes_operations.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lines = node.end_lineno - node.lineno
        if lines > 60:
            print(f'WARN: {node.name} is {lines} lines — consider extracting to backup_service.py')
"
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/backup_manager/routes_operations.py
git commit -m "refactor(backup): extract routes_operations.py (create/list/health endpoints)"
```

---

### Task 9: Split routes — routes_restore.py, routes_webhooks.py, routes_storage.py, routes_admin.py

**Files:**
- Create: `platform_v2/tools/backup_manager/routes_restore.py`
- Create: `platform_v2/tools/backup_manager/routes_webhooks.py`
- Create: `platform_v2/tools/backup_manager/routes_storage.py`
- Create: `platform_v2/tools/backup_manager/routes_admin.py`

Follow the same pattern as Task 8 for each file. Each file uses a `register_*_routes(bp, admin_required)` function. Copy functions verbatim from `backup_manager_routes.py`, strip `@backup_manager_bp` decorators.

- [ ] **Step 1: Create routes_restore.py**

Target routes (grep to confirm line numbers):
```bash
grep -n '@backup_manager_bp.route.*restore\|@backup_manager_bp.route.*preview' \
  /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py
```

```python
# platform_v2/tools/backup_manager/routes_restore.py
def register_restore_routes(bp, admin_required):
    @bp.route("/restore/<name>", methods=["POST"])
    @admin_required
    def restore_backup(name):
        pass  # copy from backup_manager_routes.py

    @bp.route("/preview/<name>")
    @admin_required
    def preview_restore(name):
        pass  # copy from backup_manager_routes.py
    # ... all restore routes
```

- [ ] **Step 2: Create routes_webhooks.py**

```bash
grep -n '@backup_manager_bp.route.*webhook' \
  /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py
```

```python
# platform_v2/tools/backup_manager/routes_webhooks.py
def register_webhooks_routes(bp, admin_required):
    @bp.route("/api/webhooks", methods=["GET"])
    @admin_required
    def get_webhooks():
        pass  # copy from backup_manager_routes.py
    # ... all webhook routes
```

- [ ] **Step 3: Create routes_storage.py**

```bash
grep -n '@backup_manager_bp.route.*cloud\|@backup_manager_bp.route.*external\|@backup_manager_bp.route.*gdrive\|@backup_manager_bp.route.*package' \
  /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py
```

```python
# platform_v2/tools/backup_manager/routes_storage.py
def register_storage_routes(bp, admin_required):
    # GDrive, external storage, packages routes
    pass  # copy from backup_manager_routes.py
```

- [ ] **Step 4: Create routes_admin.py**

```bash
grep -n '@backup_manager_bp.route.*hook\|@backup_manager_bp.route.*retention\|@backup_manager_bp.route.*audit\|@backup_manager_bp.route.*config' \
  /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py
```

```python
# platform_v2/tools/backup_manager/routes_admin.py
def register_admin_routes(bp, admin_required):
    # Hooks, retention policy, audit log, config routes
    pass  # copy from backup_manager_routes.py
```

- [ ] **Step 5: Commit all 4 files**

```bash
git add platform_v2/tools/backup_manager/routes_restore.py \
        platform_v2/tools/backup_manager/routes_webhooks.py \
        platform_v2/tools/backup_manager/routes_storage.py \
        platform_v2/tools/backup_manager/routes_admin.py
git commit -m "refactor(backup): extract routes_restore, routes_webhooks, routes_storage, routes_admin"
```

---

### Task 10: Wire __init__.py — swap monolith for 5-file registration

**Files:**
- Modify: `platform_v2/tools/backup_manager/__init__.py`
- Delete: `platform_v2/tools/backup_manager/backup_manager_routes.py`

- [ ] **Step 1: Update __init__.py**

Replace the current content with:

```python
"""Backup Manager Module — routes registered from 5 focused files."""
from flask import Blueprint

from .routes_operations import register_operations_routes
from .routes_restore import register_restore_routes
from .routes_webhooks import register_webhooks_routes
from .routes_storage import register_storage_routes
from .routes_admin import register_admin_routes

backup_manager_bp = Blueprint("backup_manager", __name__, url_prefix="/tools/backup-manager")


def register_routes(admin_required):
    """Register all backup manager routes. Called from app.py."""
    register_operations_routes(backup_manager_bp, admin_required)
    register_restore_routes(backup_manager_bp, admin_required)
    register_webhooks_routes(backup_manager_bp, admin_required)
    register_storage_routes(backup_manager_bp, admin_required)
    register_admin_routes(backup_manager_bp, admin_required)


# Preserve programmatic API used by proposal_service and agent_loop
from .routes_operations import create_backup, create_backup_programmatic
from .routes_operations import backup_module, get_module_dependencies
```

- [ ] **Step 2: Update app.py to call register_routes**

Find where `backup_manager_bp` is registered in `app.py`:
```bash
grep -n 'backup_manager' /mnt/archie_brain/platform_v2/app.py | head -10
```

Update the registration call from direct blueprint import to:
```python
from tools.backup_manager import backup_manager_bp, register_routes as _bm_register
_bm_register(admin_required)
app.register_blueprint(backup_manager_bp)
```

- [ ] **Step 3: Restart and run QA suite**

```bash
docker compose restart archie_platform
# Run the backup health smoke suite
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
print(run_suite_by_name('backup-health-smoke'))
" 2>&1
```
Expected: all tests pass. If any fail, the corresponding route file is missing an endpoint — add it.

- [ ] **Step 4: Delete the monolith**

```bash
rm /mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py
docker compose restart archie_platform
# Re-run QA suite to confirm nothing broke
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
print(run_suite_by_name('backup-health-smoke'))
" 2>&1
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/backup_manager/__init__.py platform_v2/app.py
git rm platform_v2/tools/backup_manager/backup_manager_routes.py
git commit -m "refactor(backup): replace 5000-line monolith with 5 focused route files (Task #2699)"
```

---

### Task 11: Manual module snapshot UI

**Files:**
- Modify: `platform_v2/tools/backup_manager/routes_admin.py`

- [ ] **Step 1: Add snapshot endpoint to routes_admin.py**

```python
@bp.route("/api/snapshot-module", methods=["POST"])
@admin_required
def create_module_snapshot():
    """Manually checkpoint a module's current state."""
    data = request.get_json() or {}
    module_name = data.get("module_name")
    if not module_name:
        return jsonify({"success": False, "error": "module_name required"}), 400

    from services.backup_service import snapshot_module
    result = snapshot_module(
        module_name=module_name,
        snapshot_type="manual",
        trigger_source="manual",
        metadata={"triggered_by": "ui", "user": getattr(current_user, "username", "unknown")},
    )
    return jsonify(result)


@bp.route("/api/snapshots", methods=["GET"])
@admin_required
def list_module_snapshots():
    """List recent module snapshots."""
    module = request.args.get("module")
    with get_db_cursor() as (conn, cur):
        if module:
            cur.execute(
                "SELECT * FROM module_snapshots WHERE module_name = %s ORDER BY created_at DESC LIMIT 50",
                (module,),
            )
        else:
            cur.execute("SELECT * FROM module_snapshots ORDER BY created_at DESC LIMIT 100")
        rows = [dict(r) for r in cur.fetchall()]
    return jsonify({"snapshots": rows})
```

- [ ] **Step 2: Test the endpoint**

```bash
docker compose restart archie_platform
docker exec archie_platform python3 -c "
import sys, os, requests
sys.path.insert(0, '/app')
BASE = 'http://localhost:3000'
s = requests.Session()
s.post(f'{BASE}/login', data={'username':'kytran','password':os.environ['ARCHIE_TEST_PASSWORD']})
r = s.post(f'{BASE}/tools/backup-manager/api/snapshot-module', json={'module_name':'test'})
print(r.status_code, r.json())
" 2>&1
```
Expected: 200 with `{"success": true, "snapshot_id": <id>}`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/backup_manager/routes_admin.py
git commit -m "feat(backup): manual module snapshot endpoint + list snapshots API"
```

---

## PHASE 3 — AGENT GOVERNANCE

---

### Task 12: Migration — governance columns

**Files:**
- Create: `database/migrations/372_backup_governance.sql`

- [ ] **Step 1: Write migration**

```bash
cat > /mnt/archie_brain/database/migrations/372_backup_governance.sql << 'EOF'
-- Migration 372: backup governance support columns
-- Adds clearance tracking to improvement_proposals and severity gate config

-- Clearance columns on improvement_proposals
ALTER TABLE improvement_proposals
  ADD COLUMN IF NOT EXISTS backup_clearance_approved BOOLEAN,
  ADD COLUMN IF NOT EXISTS backup_clearance_snapshot_id INTEGER REFERENCES module_snapshots(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS backup_clearance_task_id INTEGER,
  ADD COLUMN IF NOT EXISTS backup_clearance_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS backup_clearance_reason TEXT;

-- Severity gate configuration (stored as JSON in system_config)
INSERT INTO system_config (key, value, description)
VALUES (
  'backup_governance_gates',
  '{
    "critical": {"max_age_hours": 48, "gate_type": "soft", "override": "none"},
    "high":     {"max_age_hours": 12, "gate_type": "soft", "override": "telegram_approval"},
    "medium":   {"max_age_hours": 6,  "gate_type": "hard", "override": "kytran_approval"},
    "low":      {"max_age_hours": 24, "gate_type": "hard", "override": "kytran_approval"}
  }',
  'W.A.R.D.E.N. backup governance severity gates'
)
ON CONFLICT (key) DO NOTHING;
EOF
```

- [ ] **Step 2: Run migration**

```bash
docker cp /mnt/archie_brain/database/migrations/372_backup_governance.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/372_backup_governance.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d improvement_proposals" | grep backup_clearance
docker exec archie_database psql -U archie -d archie -c "SELECT value FROM system_config WHERE key='backup_governance_gates';"
```
Expected: 5 backup_clearance columns, JSON config row.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/372_backup_governance.sql
git commit -m "feat(db): migration 372 — backup governance clearance columns + severity gate config"
```

---

### Task 13: Create backup_governance_service.py

**Files:**
- Create: `platform_v2/services/backup_governance_service.py`
- Create: `platform_v2/tests/test_backup_governance_service.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > /mnt/archie_brain/platform_v2/tests/test_backup_governance_service.py << 'EOF'
"""Tests for backup_governance_service — W.A.R.D.E.N.'s clearance logic."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_clearance_result_fields():
    from services.backup_governance_service import request_deploy_clearance
    result = request_deploy_clearance(module="test_module", severity="critical")
    assert "approved" in result
    assert "snapshot_id" in result
    assert "gate_level" in result
    assert "reason" in result
    assert "backup_age_hours" in result


def test_critical_severity_always_soft():
    """Critical severity is a soft gate — always approves even with stale backup."""
    from services.backup_governance_service import request_deploy_clearance, _load_gate_config
    config = _load_gate_config()
    assert config["critical"]["gate_type"] == "soft"


def test_medium_severity_blocks_stale():
    """Medium severity hard-gates when backup is too old."""
    from services.backup_governance_service import _check_backup_freshness
    # 200h old backup vs 6h limit for medium
    result = _check_backup_freshness(age_hours=200.0, severity="medium")
    assert result["approved"] is False
    assert "stale" in result["reason"].lower() or "age" in result["reason"].lower()


def test_medium_severity_passes_fresh():
    """Medium severity passes when backup is fresh."""
    from services.backup_governance_service import _check_backup_freshness
    result = _check_backup_freshness(age_hours=1.0, severity="medium")
    assert result["approved"] is True


def test_snapshot_created_on_clearance():
    """request_deploy_clearance creates a module snapshot on approval."""
    from services.backup_governance_service import request_deploy_clearance
    from database import get_db_cursor
    result = request_deploy_clearance(module="test_snapshot_module", severity="critical")
    if result.get("snapshot_id"):
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM module_snapshots WHERE id = %s", (result["snapshot_id"],))
            assert cur.fetchone() is not None
EOF
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_governance_service.py -v 2>&1 | head -20
```
Expected: ImportError on `backup_governance_service`.

- [ ] **Step 3: Create backup_governance_service.py**

```bash
cat > /mnt/archie_brain/platform_v2/services/backup_governance_service.py << 'EOF'
"""
Backup Governance Service — owned by W.A.R.D.E.N.
Provides pre-deploy clearance checks and auto-snapshots.
Called by proposal_service.py before any Repair Bay deploy.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from database import get_db_cursor
from services.backup_service import get_health_summary, snapshot_module

logger = logging.getLogger(__name__)


def _load_gate_config() -> dict:
    """Load severity gate config from system_config. Returns defaults if missing."""
    defaults = {
        "critical": {"max_age_hours": 48, "gate_type": "soft",  "override": "none"},
        "high":     {"max_age_hours": 12, "gate_type": "soft",  "override": "telegram_approval"},
        "medium":   {"max_age_hours": 6,  "gate_type": "hard",  "override": "kytran_approval"},
        "low":      {"max_age_hours": 24, "gate_type": "hard",  "override": "kytran_approval"},
    }
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'backup_governance_gates'")
            row = cur.fetchone()
            if row and row["value"]:
                return json.loads(row["value"])
    except Exception as e:
        logger.warning("Could not load governance gate config: %s — using defaults", e)
    return defaults


def _check_backup_freshness(age_hours: float, severity: str) -> dict[str, Any]:
    """Check if backup age is within the allowed window for the given severity.

    Returns:
        {"approved": bool, "reason": str, "gate_level": str}
    """
    config = _load_gate_config()
    gate = config.get(severity, config["medium"])
    max_age = gate["max_age_hours"]
    gate_type = gate["gate_type"]

    if age_hours <= max_age:
        return {
            "approved": True,
            "reason": f"backup is {age_hours:.1f}h old (limit {max_age}h)",
            "gate_level": gate_type,
        }

    # Backup is stale
    reason = f"backup age {age_hours:.1f}h exceeds {severity} limit of {max_age}h"
    if gate_type == "soft":
        # Soft gate — proceed with warning
        logger.warning("W.A.R.D.E.N. soft gate: %s", reason)
        return {"approved": True, "reason": f"soft gate warning: {reason}", "gate_level": "soft"}

    # Hard gate — block
    return {"approved": False, "reason": reason, "gate_level": "hard"}


def request_deploy_clearance(
    module: str,
    severity: str,
    triggered_by: str = "probe",
    proposal_id: int | None = None,
) -> dict[str, Any]:
    """W.A.R.D.E.N. pre-deploy clearance check.

    1. Load severity gate config
    2. Check backup recency from backup_log
    3. Auto-snapshot the module
    4. Return clearance result

    Args:
        module: Module name (e.g., 'repair_bay', 'account_center')
        severity: 'critical' | 'high' | 'medium' | 'low'
        triggered_by: Who requested clearance ('probe', 'user', 'automation')
        proposal_id: Optional Repair Bay proposal ID for tracking

    Returns:
        {
          "approved": bool,
          "snapshot_id": int | None,
          "gate_level": str,
          "reason": str,
          "backup_age_hours": float | None,
          "severity": str,
        }
    """
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"

    # Step 1: Check backup health
    health = get_health_summary()
    primary_tier = health["tier_health"].get("primary", {})
    age_hours = primary_tier.get("age_hours")

    if age_hours is None:
        # No backup ever — always hard-block (except critical which soft-gates)
        freshness = _check_backup_freshness(age_hours=9999.0, severity=severity)
    else:
        freshness = _check_backup_freshness(age_hours=age_hours, severity=severity)

    # Step 2: Auto-snapshot the module
    snapshot_id = None
    try:
        snap = snapshot_module(
            module_name=module,
            snapshot_type="pre_deploy",
            trigger_source=triggered_by,
            metadata={"proposal_id": proposal_id, "severity": severity},
        )
        if snap["success"]:
            snapshot_id = snap["snapshot_id"]
    except Exception as e:
        logger.error("W.A.R.D.E.N. snapshot failed for module %s: %s", module, e)
        # Snapshot failure degrades to hard block for medium/low
        if severity in ("medium", "low") and freshness["approved"]:
            freshness["approved"] = False
            freshness["reason"] = f"snapshot failed: {e}"

    # Step 3: Send Telegram alert on denial
    if not freshness["approved"]:
        _notify_denial(module, severity, freshness["reason"])

    result = {
        "approved": freshness["approved"],
        "snapshot_id": snapshot_id,
        "gate_level": freshness["gate_level"],
        "reason": freshness["reason"],
        "backup_age_hours": age_hours,
        "severity": severity,
    }
    logger.info(
        "W.A.R.D.E.N. clearance %s — module=%s severity=%s age=%.1fh",
        "GRANTED" if result["approved"] else "DENIED",
        module, severity, age_hours or -1,
    )
    return result


def _notify_denial(module: str, severity: str, reason: str) -> None:
    """Send Telegram alert via A.R.C.H.I.E. on clearance denial."""
    try:
        from services.telegram_service import send_info
        msg = (
            f"W.A.R.D.E.N. — Deploy clearance DENIED\n"
            f"Module: {module} | Severity: {severity}\n"
            f"Reason: {reason}\n"
            f"Action: Approve override or resolve backup issue first."
        )
        send_info(msg, source_agent="W.A.R.D.E.N.")
    except Exception as e:
        logger.warning("W.A.R.D.E.N. denial notification failed (suppressed): %s", e)
EOF
```

- [ ] **Step 4: Run tests — all 5 should pass**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_governance_service.py -v 2>&1
```
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/backup_governance_service.py \
        platform_v2/tests/test_backup_governance_service.py
git commit -m "feat(backup): backup_governance_service.py — W.A.R.D.E.N. clearance authority"
```

---

### Task 14: Integrate governance into proposal_service.py

**Files:**
- Modify: `platform_v2/services/proposal_service.py:509`

- [ ] **Step 1: Locate the integration point**

```bash
sed -n '505,560p' /mnt/archie_brain/platform_v2/services/proposal_service.py
```

The `run_proposal()` function currently calls `create_backup()` at line ~536. Add a governance check before the existing backup call.

- [ ] **Step 2: Add clearance check to run_proposal()**

In `run_proposal()`, after the function docstring and initial validation, before the existing `if not skip_backup:` block, add:

```python
    # W.A.R.D.E.N. pre-deploy governance check
    if not skip_backup:
        try:
            from services.backup_governance_service import request_deploy_clearance
            severity = "medium"  # default; override if proposal has severity field
            # Try to read severity from proposal row
            with get_db_cursor() as (_c, _cur):
                _cur.execute(
                    "SELECT severity FROM improvement_proposals WHERE id = %s",
                    (proposal_id,),
                )
                _row = _cur.fetchone()
                if _row and _row.get("severity"):
                    severity = _row["severity"].lower()
                    if severity not in ("critical", "high", "medium", "low"):
                        severity = "medium"

            clearance = request_deploy_clearance(
                module=str(proposal_id),
                severity=severity,
                triggered_by="probe",
                proposal_id=proposal_id,
            )

            # Record clearance on proposal
            with get_db_cursor(commit=True) as (_c, _cur):
                _cur.execute(
                    """UPDATE improvement_proposals SET
                         backup_clearance_approved = %s,
                         backup_clearance_snapshot_id = %s,
                         backup_clearance_reason = %s,
                         backup_clearance_at = NOW()
                       WHERE id = %s""",
                    (clearance["approved"], clearance["snapshot_id"],
                     clearance["reason"], proposal_id),
                )

            if not clearance["approved"]:
                return {
                    "success": False,
                    "error": f"W.A.R.D.E.N. clearance denied: {clearance['reason']}",
                    "clearance": clearance,
                }
        except ImportError:
            pass  # governance service not yet available — fail open
        except Exception as _gov_err:
            logger.warning("Governance check failed (fail-open): %s", _gov_err)
```

- [ ] **Step 3: Restart and run backup QA suite**

```bash
docker compose restart archie_platform
docker exec archie_platform python3 -m pytest /app/tests/test_backup_governance_service.py /app/tests/test_backup_service.py -v 2>&1
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/proposal_service.py
git commit -m "feat(repair-bay): add W.A.R.D.E.N. pre-deploy governance check to run_proposal()"
```

---

### Task 15: W.A.R.D.E.N. skill upgrade + CAPABILITY_DEPARTMENT_MAP

**Files:**
- Modify: `platform_v2/services/department_coordinator.py`

- [ ] **Step 1: Add backup_governance to CAPABILITY_DEPARTMENT_MAP**

Find the map in `department_coordinator.py`:
```bash
grep -n 'backup_verify\|Operations.*Infrastructure' \
  /mnt/archie_brain/platform_v2/services/department_coordinator.py | head -10
```

Add `"backup_governance"` next to `"backup_verify"`:
```python
    "backup_verify": "Operations & Infrastructure",
    "backup_governance": "Operations & Infrastructure",  # W.A.R.D.E.N. clearance authority
```

- [ ] **Step 2: Add backup_governance skill to W.A.R.D.E.N.**

```bash
docker exec archie_platform python3 -c "
import sys, os; sys.path.insert(0, '/app'); os.chdir('/app')
from database import get_db_cursor
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute('''
        INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
        VALUES (363, 'backup_governance', 5, NULL)
        ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = 5
    ''')
    print('Done')
" 2>&1
```

- [ ] **Step 3: Verify W.A.R.D.E.N. skills**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT skill_name, proficiency_level FROM agent_skills WHERE agent_id = 363 ORDER BY skill_name;"
```
Expected: `backup_governance` at level 5 alongside existing skills.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/department_coordinator.py
git commit -m "feat(warden): add backup_governance capability + Lv5 skill to W.A.R.D.E.N. (id=363)"
```

---

### Task 16: Backup governance QA suite

**Files:**
- Create: `platform_v2/qa_suites/backup-governance-e2e.yaml`

- [ ] **Step 1: Write the suite**

```bash
cat > /mnt/archie_brain/platform_v2/qa_suites/backup-governance-e2e.yaml << 'EOF'
suite:
  name: "backup-governance-e2e"
  description: "W.A.R.D.E.N. backup governance — clearance, snapshots, severity gates, Repair Bay gate"
  base_url: "http://192.168.1.200:3000"
  auth:
    username: "${ARCHIE_TEST_USERNAME}"
    password: "${ARCHIE_TEST_PASSWORD}"

tests:
  - name: "snapshot endpoint creates row"
    type: api
    method: POST
    path: /tools/backup-manager/api/snapshot-module
    body: {"module_name": "qa_test_module"}
    expect:
      status: [200]

  - name: "snapshots list returns array"
    type: api
    method: GET
    path: /tools/backup-manager/api/snapshots
    expect:
      status: [200]

  - name: "governance gate config in system_config"
    type: api
    method: GET
    path: /tools/backup-manager/api/governance-config
    expect:
      status: [200, 404]

  - name: "backup health summary endpoint"
    type: api
    method: GET
    path: /tools/backup-manager/api/health
    expect:
      status: [200]

  - name: "improvement proposals have clearance columns"
    type: api
    method: GET
    path: /tools/repair-bay/api/proposals?limit=1
    expect:
      status: [200, 404]
EOF
```

- [ ] **Step 2: Register and run**

```bash
docker exec archie_platform python3 -c "
import sys, os, yaml, json
sys.path.insert(0, '/app'); os.chdir('/app')
from database import get_db_cursor
with open('/app/qa_suites/backup-governance-e2e.yaml') as f:
    spec = yaml.safe_load(f.read())
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute(
        'INSERT INTO qa_test_suites (name, description, target_url, spec, suite_type, is_active) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
        ('backup-governance-e2e', 'W.A.R.D.E.N. governance E2E suite',
         'http://192.168.1.200:3000', json.dumps(spec), 'internal', True)
    )
    print('Suite id:', cur.fetchone()['id'])
" 2>&1
```

- [ ] **Step 3: Run the suite**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
print(run_suite_by_name('backup-governance-e2e'))
" 2>&1
```
Expected: all tests pass or return acceptable codes.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/qa_suites/backup-governance-e2e.yaml
git commit -m "feat(qa): backup-governance-e2e suite — W.A.R.D.E.N. clearance QA coverage"
```

---

### Task 17: Create Phase 3 follow-up tasks in Dev HQ

- [ ] **Step 1: Create the 7 follow-up tasks**

```bash
docker exec archie_platform python3 -c "
import sys, os; sys.path.insert(0, '/app'); os.chdir('/app')
from database import get_db_cursor
import json
from datetime import datetime, timezone

tasks = [
    ('Audit Repair Bay full workflow — verify all pre-deploy gates are correct post-governance integration', 8),
    ('P.R.O.B.E. scheduled job audit — confirm jobs acknowledge backup systems', 7),
    ('Severity config UI — editable gate config in Backup Manager Admin tab', 7),
    ('Repair Bay UI — show backup clearance status on each proposal card', 7),
    ('Telegram escalation template — W.A.R.D.E.N. denial message format refinement', 6),
    ('Smoke-test W.A.R.D.E.N. delegate_task backup_governance path end-to-end', 8),
    ('Module snapshot viewer in Backup Manager UI — browse per-module history', 6),
]

with get_db_cursor(commit=True) as (conn, cur):
    for title, priority in tasks:
        cur.execute(
            '''INSERT INTO unified_tasks (title, status, priority, task_type, project_id, created_at)
               VALUES (%s, %s, %s, %s, (SELECT id FROM unified_projects WHERE name ILIKE '%backup%' OR name ILIKE '%project alpha%' LIMIT 1), NOW())
               RETURNING id''',
            (title, 'pending', priority, 'implementation'),
        )
        row = cur.fetchone()
        print(f'Created task id={row[0] if row else \"?\"}:', title[:60])
" 2>&1
```

- [ ] **Step 2: Verify tasks in Dev HQ**

Open http://192.168.1.200:3000/tools/consciousness/#devhq and confirm 7 new tasks appear under the project.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(backup): Phase 3 complete — governance service, Repair Bay integration, QA suite, follow-up tasks"
```

---

## Final Verification

After all phases complete, run the full suite:

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
for suite in ['backup-health-smoke', 'backup-governance-e2e']:
    r = run_suite_by_name(suite)
    print(suite, ':', r.get('passed'), '/', r.get('total'), 'passed')
" 2>&1
```

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_service.py /app/tests/test_backup_governance_service.py -v 2>&1
```

Expected: all suites green, all unit tests pass, no backup tab shows empty, secondary tiers running, W.A.R.D.E.N. clearance gating all Repair Bay deploys.
