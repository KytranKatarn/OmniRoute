# Backup Manager Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 Backup Manager gaps: DB/filesystem drift, GFS double-counting of shell-script backups, pre-deploy backup wiring, editable retention policy with W.A.R.D.E.N. panel, async package creation, and a new Standalone Systems tab for all 9 standalone products.

**Architecture:** All changes are additive to the existing Backup Manager module (`platform_v2/tools/backup_manager/`). Backend changes go to route files and `_shared.py`; W.A.R.D.E.N. jobs go to `platform_v2/services/agent_jobs.py`; UI changes go to `platform_v2/templates/tools/backup_manager.html`. New routes follow the existing `register_*_routes(bp, admin_required)` pattern.

**Tech Stack:** Flask, PostgreSQL (psycopg2), APScheduler (CronTrigger), Python threading for async jobs. Tests use pytest with Flask test client and a real test DB.

---

## File Map

| File | Change |
|------|--------|
| `platform_v2/tools/backup_manager/_shared.py` | Add DB sync to `cleanup_old_backups()`; exclude `Daily_Triage` from GFS; add `STANDALONE_PRODUCTS` registry + `backup_standalone()` |
| `platform_v2/tools/backup_manager/routes_admin.py` | Add `POST /api/cleanup-orphan-log-entries` |
| `platform_v2/tools/backup_manager/routes_operations.py` | Read GFS values from `system_config`; add `PUT /retention-policy` |
| `platform_v2/tools/backup_manager/routes_standalones.py` | **New file** — 4 standalone backup endpoints |
| `platform_v2/tools/backup_manager/routes_storage.py` | Make `create_deployment_package` async; add `GET /api/deployment-package-status/<job_id>` |
| `platform_v2/tools/backup_manager/__init__.py` | Register `routes_standalones` blueprint |
| `platform_v2/services/proposal_service.py` | Call `create_backup_programmatic()` + insert into `improvement_deployments` before deploy |
| `platform_v2/services/agent_jobs.py` | Add 3 W.A.R.D.E.N. jobs: pre-deploy verify, version-bump packager, standalone backup |
| `platform_v2/templates/tools/backup_manager.html` | Retention UI editable + W.A.R.D.E.N. panel; Deployment Packages async UI; new Standalone Systems tab |
| `database/migrations/376_retention_config.sql` | Seed 3 `system_config` keys for GFS values |
| `database/migrations/377_deployment_package_jobs.sql` | New `deployment_package_jobs` table |
| `database/migrations/378_backup_log_standalone.sql` | Add `standalone_name` column to `backup_log` |
| `platform_v2/tests/test_backup_consolidation.py` | **New** — tests for all 6 work items |

---

## Task 1: Fix DB/Filesystem Drift (Issue A)

**Files:**
- Modify: `platform_v2/tools/backup_manager/_shared.py` (around `cleanup_old_backups`)
- Modify: `platform_v2/tools/backup_manager/routes_admin.py`
- Create: `platform_v2/tests/test_backup_consolidation.py`

- [ ] **Step 1: Write failing tests**

Create `platform_v2/tests/test_backup_consolidation.py`:

```python
import pytest
import os
import tempfile
from unittest.mock import patch


def test_cleanup_removes_db_row_when_dir_deleted(app, db_conn):
    """cleanup_old_backups should delete backup_log row when it deletes the dir."""
    with app.app_context():
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_name = "20260101_060000_test_old"
            backup_path = os.path.join(tmpdir, backup_name)
            os.makedirs(backup_path)

            with db_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO backup_log (backup_name, backup_type, size_bytes, status, created_at) "
                    "VALUES (%s, 'full', 1024, 'completed', NOW() - INTERVAL '30 days') RETURNING id",
                    (backup_name,)
                )
                row_id = cur.fetchone()[0]
            db_conn.commit()

            with patch('tools.backup_manager._shared.BACKUP_DIR', tmpdir):
                from tools.backup_manager._shared import cleanup_old_backups
                cleanup_old_backups(dry_run=False)

            with db_conn.cursor() as cur:
                cur.execute("SELECT id FROM backup_log WHERE id = %s", (row_id,))
                assert cur.fetchone() is None, "backup_log row should have been deleted"


def test_cleanup_orphan_log_entries_removes_db_only_rows(client):
    """POST /api/cleanup-orphan-log-entries removes rows with no matching dir."""
    resp = client.post('/tools/backup-manager/api/cleanup-orphan-log-entries')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['success'] is True
    assert 'removed_count' in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py -v 2>&1 | tail -20
```
Expected: FAIL — `cleanup_old_backups` does not delete DB rows.

- [ ] **Step 3: Add DB sync to `cleanup_old_backups()` in `_shared.py`**

Find `cleanup_old_backups` in `platform_v2/tools/backup_manager/_shared.py`. In the block that deletes the directory, add a DB delete immediately after the `shutil.rmtree` call:

```python
if not dry_run:
    try:
        shutil.rmtree(backup["path"])
        # Sync: remove the backup_log row for this backup
        with get_backup_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM backup_log WHERE backup_name = %s",
                (backup["name"],)
            )
    except Exception as e:
        logger.warning("Failed to delete backup dir or DB row %s: %s", backup["name"], e)
```

- [ ] **Step 4: Add orphan-cleanup endpoint to `routes_admin.py`**

In `platform_v2/tools/backup_manager/routes_admin.py`, inside `register_admin_routes(bp, admin_required)`, add:

```python
@bp.route("/api/cleanup-orphan-log-entries", methods=["POST"])
@admin_required
def cleanup_orphan_log_entries():
    """Remove backup_log rows whose backup directory no longer exists on disk."""
    try:
        removed = []
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
            cur.execute(
                "SELECT backup_name FROM backup_log "
                "WHERE backup_type NOT IN ('standalone', 'module') AND backup_name IS NOT NULL"
            )
            rows = cur.fetchall()

        for row in rows:
            name = row["backup_name"]
            if name and not os.path.exists(os.path.join(BACKUP_DIR, name)):
                removed.append(name)

        if removed:
            with get_backup_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "DELETE FROM backup_log WHERE backup_name = ANY(%s)",
                    (removed,)
                )

        return jsonify({"success": True, "removed_count": len(removed), "removed": removed})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

Add the missing imports at the top of `routes_admin.py` if not already present:
```python
import os
from tools.backup_manager._shared import BACKUP_DIR, get_backup_db_cursor
from psycopg2.extras import RealDictCursor
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py -v 2>&1 | tail -15
```
Expected: Both tests PASS

- [ ] **Step 6: Restart and verify**

```bash
docker compose restart archie_platform
# Browser: Backup Manager → Retention tab → Run Cleanup (dry run) — count should reflect real disk dirs
```

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/backup_manager/_shared.py \
        platform_v2/tools/backup_manager/routes_admin.py \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "fix(backup-manager): sync backup_log DB rows when deleting dirs + orphan cleanup endpoint"
```

---

## Task 2: Exclude Daily_Triage from GFS Retention (Issue B)

**Context:** `scripts/backup_triage.sh` is a host-level cron job writing `*_Daily_Triage` folders to the same `/backups/` directory. The script keeps its own retention (last 15). The GFS scanner currently counts `Daily_Triage` folders as platform backups, consuming the 7-daily quota twice per day.

**Files:**
- Modify: `platform_v2/tools/backup_manager/_shared.py` (`get_backup_retention_status` and `cleanup_old_backups`)

- [ ] **Step 1: Add test**

In `platform_v2/tests/test_backup_consolidation.py`, append:

```python
def test_gfs_excludes_daily_triage_folders(tmp_path):
    """GFS retention should not count *_Daily_Triage folders (managed by backup_triage.sh)."""
    for name in [
        "20260507_060001_daily",
        "20260507_060001_Daily_Triage",
        "20260506_060001_daily",
        "20260506_060001_Daily_Triage",
        "20260505_060001_daily",
    ]:
        (tmp_path / name).mkdir()

    with patch('tools.backup_manager._shared.BACKUP_DIR', str(tmp_path)):
        from tools.backup_manager._shared import get_backup_retention_status
        status = get_backup_retention_status()

    total = status["stats"]["total_backups"]
    all_names = status["keep"] + status["delete"]
    assert total == 3, f"Expected 3 platform backups, got {total}"
    assert not any("Daily_Triage" in n for n in all_names), "Daily_Triage should be excluded from GFS"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_gfs_excludes_daily_triage_folders -v 2>&1 | tail -10
```
Expected: FAIL — total will be 5 not 3.

- [ ] **Step 3: Add exclusion in `get_backup_retention_status()` and `cleanup_old_backups()`**

In `get_backup_retention_status()`, find `for item in os.listdir(BACKUP_DIR):` and add inside the `if os.path.isdir(backup_path) and item != "modules":` block, before the `try:`:

```python
# Skip Daily_Triage dirs — managed by scripts/backup_triage.sh with its own retention
if item.endswith("_Daily_Triage"):
    continue
```

In `cleanup_old_backups()`, apply the same exclusion — add `if backup["name"].endswith("_Daily_Triage"): continue` immediately after the backups list is built and sorted.

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_gfs_excludes_daily_triage_folders -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/backup_manager/_shared.py \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "fix(backup-manager): exclude Daily_Triage dirs from GFS (managed by backup_triage.sh)"
```

---

## Task 3: Wire Deployment Backups Trigger (Work Item 1)

**Context:** `deploy_to_production()` in `proposal_service.py` (line 955) creates a manual tar.gz backup but never calls `create_backup_programmatic()` or writes to `improvement_deployments`. The Deployment Backups tab queries `improvement_deployments WHERE backup_name IS NOT NULL`, so it always shows empty.

**Files:**
- Modify: `platform_v2/services/proposal_service.py` (around line 955)
- Modify: `platform_v2/services/agent_jobs.py`

- [ ] **Step 1: Add test**

In `platform_v2/tests/test_backup_consolidation.py`, append:

```python
def test_deploy_to_production_creates_improvement_deployment_row(app, db_conn):
    """deploy_to_production() should insert an improvement_deployments row with backup_name set."""
    with app.app_context():
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO improvement_proposals (title, description, status, category, priority) "
                "VALUES ('Test proposal', 'test', 'approved', 'code', 5) RETURNING id"
            )
            proposal_id = cur.fetchone()[0]
        db_conn.commit()

        with patch('tools.backup_manager._shared.create_backup_programmatic') as mock_backup:
            mock_backup.return_value = {
                'success': True,
                'backup_name': '20260507_120000_pre_deploy',
                'backup_path': '/backups/20260507_120000_pre_deploy',
                'backup': {}
            }
            from services.proposal_service import deploy_to_production
            deploy_to_production(proposal_id)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT backup_name FROM improvement_deployments WHERE proposal_id = %s",
                (proposal_id,)
            )
            row = cur.fetchone()
        assert row is not None, "improvement_deployments row should have been created"
        assert row[0] == '20260507_120000_pre_deploy'
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_deploy_to_production_creates_improvement_deployment_row -v 2>&1 | tail -15
```
Expected: FAIL

- [ ] **Step 3: Modify `deploy_to_production()` in `proposal_service.py`**

In `deploy_to_production()` (line ~955), after the `if proposal["status"] != "approved": return` check, replace the existing manual backup block (the `backup_dir.mkdir()` through `backup_files` lines) with:

```python
# --- Create pre-deploy backup via Backup Manager ---
from tools.backup_manager._shared import create_backup_programmatic
from database import get_db_cursor as _get_db_cursor

backup_result = create_backup_programmatic(
    description=f"Pre-deploy snapshot for proposal #{proposal_id}: {proposal['title'][:60]}",
    created_by_username="system",
    proposal_id=proposal_id,
)
backup_name = backup_result.get("backup_name", "") if backup_result.get("success") else ""

# Record in improvement_deployments so Deployment Backups tab shows it
if backup_name:
    try:
        with _get_db_cursor(commit=True) as (dconn, dcur):
            dcur.execute(
                """INSERT INTO improvement_deployments
                   (proposal_id, backup_name, deployment_type, status)
                   VALUES (%s, %s, 'manual', 'deploying')""",
                (proposal_id, backup_name)
            )
    except Exception as be:
        logger.warning("Failed to record pre-deploy backup in improvement_deployments: %s", be)
```

Keep all lines after the backup block unchanged.

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_deploy_to_production_creates_improvement_deployment_row -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 5: Add W.A.R.D.E.N. pre-deploy verify job in `agent_jobs.py`**

After `_run_warden_download_cleanup()` (around line 3380), add:

```python
def _run_warden_pre_deploy_verify():
    """W.A.R.D.E.N. — verify checksum of most recent pre-deploy backup (runs every 5 min)."""
    try:
        from database import get_db_cursor
        from tools.backup_manager._shared import BACKUP_DIR

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT backup_name FROM improvement_deployments
                   WHERE backup_name IS NOT NULL AND status = 'deploying'
                   AND deployed_at > NOW() - INTERVAL '10 minutes'
                   ORDER BY deployed_at DESC LIMIT 1"""
            )
            row = cur.fetchone()

        if not row:
            return

        backup_name = row[0]
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            logger.warning("W.A.R.D.E.N.: pre-deploy backup dir missing: %s", backup_name)
            return

        # Check metadata.json exists as a lightweight integrity check
        metadata_path = os.path.join(backup_path, "metadata.json")
        ok = os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0
        if not ok:
            logger.error("W.A.R.D.E.N.: pre-deploy backup integrity check FAILED: %s", backup_name)
            try:
                from services.telegram_service import send_alert
                send_alert(
                    f"W.A.R.D.E.N.: Pre-deploy backup integrity FAILED for {backup_name}. "
                    f"Review before accepting deploy."
                )
            except Exception:
                pass
        else:
            logger.info("W.A.R.D.E.N.: pre-deploy backup verified OK: %s", backup_name)
    except Exception as e:
        logger.warning("W.A.R.D.E.N. pre-deploy verify failed (non-fatal): %s", e)
```

Inside `register_agent_welfare_jobs()`, after the `warden_download_cleanup` job block, add:

```python
scheduler.add_job(
    with_ctx(_run_warden_pre_deploy_verify),
    trigger=IntervalTrigger(minutes=5),
    id="warden_pre_deploy_verify",
    name="W.A.R.D.E.N.: Pre-Deploy Backup Verify",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

- [ ] **Step 6: Restart and manually verify**

```bash
docker compose restart archie_platform
# In Repair Bay: deploy any approved proposal
# Check Backup Manager → Deployment Backups tab — entry should now appear
```

- [ ] **Step 7: Commit**

```bash
git add platform_v2/services/proposal_service.py \
        platform_v2/services/agent_jobs.py \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "feat(backup-manager): wire pre-deploy backup trigger + improvement_deployments insert + W.A.R.D.E.N. verify"
```

---

## Task 4: Retention — Editable GFS Policy (Work Item 2, backend)

**Files:**
- Create: `database/migrations/376_retention_config.sql`
- Modify: `platform_v2/tools/backup_manager/_shared.py`
- Modify: `platform_v2/tools/backup_manager/routes_operations.py`
- Modify: `platform_v2/services/agent_jobs.py` (`backup_retention_prune`)

- [ ] **Step 1: Write failing tests**

In `platform_v2/tests/test_backup_consolidation.py`, append:

```python
def test_retention_policy_reads_from_system_config(client, db_conn):
    """retention-status should reflect system_config values, not hardcoded constants."""
    with db_conn.cursor() as cur:
        for key, val in [('retention_daily', '3'), ('retention_weekly', '2'), ('retention_monthly', '2')]:
            cur.execute(
                "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (key, val)
            )
    db_conn.commit()

    resp = client.get('/tools/backup-manager/retention-status')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data.get('retention_daily') == 3


def test_put_retention_policy_updates_system_config(client, db_conn):
    """PUT /retention-policy should update system_config keys."""
    resp = client.put(
        '/tools/backup-manager/retention-policy',
        json={'daily': 10, 'weekly': 5, 'monthly': 8},
        content_type='application/json'
    )
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    with db_conn.cursor() as cur:
        cur.execute("SELECT value FROM system_config WHERE key = 'retention_daily'")
        assert cur.fetchone()[0] == '10'
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_retention_policy_reads_from_system_config platform_v2/tests/test_backup_consolidation.py::test_put_retention_policy_updates_system_config -v 2>&1 | tail -15
```
Expected: FAIL

- [ ] **Step 3: Create and run migration**

Create `database/migrations/376_retention_config.sql`:

```sql
INSERT INTO system_config (key, value, updated_at)
VALUES
    ('retention_daily',   '7',  NOW()),
    ('retention_weekly',  '4',  NOW()),
    ('retention_monthly', '6',  NOW())
ON CONFLICT (key) DO NOTHING;
```

Run:
```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/database/migrations/376_retention_config.sql
```
Expected: `INSERT 0 3`

- [ ] **Step 4: Add `get_retention_config()` to `_shared.py`**

In `platform_v2/tools/backup_manager/_shared.py`, add after the constants block:

```python
def get_retention_config():
    """Read GFS retention values from system_config. Falls back to 7/4/6 if missing."""
    defaults = {"daily": 7, "weekly": 4, "monthly": 6}
    try:
        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT key, value FROM system_config "
                "WHERE key IN ('retention_daily', 'retention_weekly', 'retention_monthly')"
            )
            for key, val in cur.fetchall():
                short = key.replace("retention_", "")
                try:
                    defaults[short] = int(val)
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    return defaults
```

- [ ] **Step 5: Update `get_backup_retention_status()` to use `get_retention_config()`**

Replace the three hardcoded constant loops in `get_backup_retention_status()`:

```python
cfg = get_retention_config()

daily_kept = 0
for backup in backups:
    if daily_kept < cfg["daily"]:
        keep.add(backup["name"])
        daily_kept += 1

weeks_seen = set()
for backup in backups:
    week_key = backup["date"].strftime("%Y-%W")
    if week_key not in weeks_seen and len(weeks_seen) < cfg["weekly"]:
        keep.add(backup["name"])
        weeks_seen.add(week_key)

months_seen = set()
for backup in backups:
    month_key = backup["date"].strftime("%Y-%m")
    if month_key not in months_seen and len(months_seen) < cfg["monthly"]:
        keep.add(backup["name"])
        months_seen.add(month_key)
```

- [ ] **Step 6: Update `retention_status()` and add `PUT /retention-policy` in `routes_operations.py`**

Replace `retention_status()` body:

```python
def retention_status():
    try:
        from tools.backup_manager._shared import get_retention_config
        cfg = get_retention_config()
        status = get_backup_retention_status()

        # Read last-run info
        last_run = "Never"
        last_count = "0"
        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT key, value FROM system_config "
                "WHERE key IN ('retention_last_run', 'retention_last_deleted_count')"
            )
            for key, val in cur.fetchall():
                if key == "retention_last_run":
                    last_run = val
                elif key == "retention_last_deleted_count":
                    last_count = val

        return jsonify({
            "success": True,
            "retention_policy": f"{cfg['daily']} daily + {cfg['weekly']} weekly + {cfg['monthly']} monthly",
            "retention_daily": cfg["daily"],
            "retention_weekly": cfg["weekly"],
            "retention_monthly": cfg["monthly"],
            "last_run": last_run,
            "last_deleted_count": last_count,
            **status,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

Add inside `register_operations_routes(bp, admin_required)`:

```python
@bp.route("/retention-policy", methods=["PUT"])
@admin_required
def update_retention_policy():
    data = request.get_json() or {}
    updates = {}
    for key in ("daily", "weekly", "monthly"):
        val = data.get(key)
        if val is not None:
            try:
                updates[f"retention_{key}"] = max(1, int(val))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": f"Invalid value for {key}"}), 400
    if not updates:
        return jsonify({"success": False, "error": "No valid fields provided"}), 400

    with get_backup_db_cursor(commit=True) as (conn, cur):
        for k, v in updates.items():
            cur.execute(
                "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (k, str(v))
            )
    return jsonify({"success": True, "updated": updates})
```

- [ ] **Step 7: Update `backup_retention_prune()` in `agent_jobs.py` to write result**

In `backup_retention_prune()` (around line 3285), after the cleanup succeeds, add:

```python
from database import get_db_cursor
from services.time_utils import now_utc
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute(
        "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        ('retention_last_run', now_utc().isoformat())
    )
    cur.execute(
        "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        ('retention_last_deleted_count', str(len(result.get('deleted', []))))
    )
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_retention_policy_reads_from_system_config platform_v2/tests/test_backup_consolidation.py::test_put_retention_policy_updates_system_config -v 2>&1 | tail -15
```
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add database/migrations/376_retention_config.sql \
        platform_v2/tools/backup_manager/_shared.py \
        platform_v2/tools/backup_manager/routes_operations.py \
        platform_v2/services/agent_jobs.py \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "feat(backup-manager): editable GFS retention policy via system_config + W.A.R.D.E.N. last-run tracking"
```

---

## Task 5: Retention Tab UI — Editable Fields + W.A.R.D.E.N. Panel (Work Item 2, frontend)

**Files:**
- Modify: `platform_v2/templates/tools/backup_manager.html` (Retention tab, around line 444)

- [ ] **Step 1: Replace static GFS cards with editable inputs**

In the `<!-- RETENTION TAB -->` section, replace the static `.retention-grid` block with:

```html
<div class="retention-grid" id="retentionPolicyGrid">
    <div class="retention-card">
        <input type="number" id="retentionDaily" min="1" max="30" value="7"
               style="width:60px;font-size:2rem;font-weight:700;background:transparent;
                      border:none;border-bottom:2px solid #ec4899;color:#f472b6;text-align:center;">
        <div class="label"><span data-i18n="backup_manager.daily_backups">Daily Backups</span></div>
    </div>
    <div class="retention-card">
        <input type="number" id="retentionWeekly" min="1" max="12" value="4"
               style="width:60px;font-size:2rem;font-weight:700;background:transparent;
                      border:none;border-bottom:2px solid #ec4899;color:#f472b6;text-align:center;">
        <div class="label"><span data-i18n="backup_manager.weekly_backups">Weekly Backups</span></div>
    </div>
    <div class="retention-card">
        <input type="number" id="retentionMonthly" min="1" max="24" value="6"
               style="width:60px;font-size:2rem;font-weight:700;background:transparent;
                      border:none;border-bottom:2px solid #ec4899;color:#f472b6;text-align:center;">
        <div class="label"><span data-i18n="backup_manager.monthly_backups">Monthly Backups</span></div>
    </div>
</div>
<div style="margin-top: var(--archie-space-3);">
    <button class="btn" onclick="saveRetentionPolicy()"
            style="border-color:#ec4899;color:#f472b6;">Save Policy</button>
</div>
```

- [ ] **Step 2: Add W.A.R.D.E.N. status panel after the button row**

After the existing `Check Retention` / `Preview Cleanup` / `Run Cleanup` button row, add:

```html
<div style="margin-top: var(--archie-space-5); padding: var(--archie-space-4);
            background: rgba(167,139,250,0.05); border: 1px solid rgba(167,139,250,0.2);
            border-radius: var(--archie-radius-lg);">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:var(--archie-space-3);">
        <div style="width:8px;height:8px;border-radius:50%;background:#a78bfa;" class="sc-live"></div>
        <span style="font-family:'Antonio',sans-serif;font-size:0.8rem;letter-spacing:2px;color:#a78bfa;">
            W.A.R.D.E.N. RETENTION AGENT
        </span>
    </div>
    <div id="wardenRetentionStatus" style="font-size:12px;color:var(--archie-text-secondary);">
        Loading W.A.R.D.E.N. status...
    </div>
</div>
```

- [ ] **Step 3: Add JavaScript for the Retention tab new features**

In the `// RETENTION TAB` JS section, add after `checkRetention()`:

```javascript
async function saveRetentionPolicy() {
    const daily = parseInt(document.getElementById('retentionDaily').value);
    const weekly = parseInt(document.getElementById('retentionWeekly').value);
    const monthly = parseInt(document.getElementById('retentionMonthly').value);
    if ([daily, weekly, monthly].some(v => isNaN(v) || v < 1)) {
        showToast('Invalid retention values', 'error');
        return;
    }
    try {
        const resp = await fetch('/tools/backup-manager/retention-policy', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({daily, weekly, monthly})
        });
        const data = await resp.json();
        if (data.success) showToast('Retention policy saved', 'success');
        else showToast('Failed: ' + escapeHtml(data.error || 'unknown'), 'error');
    } catch (e) { showToast('Network error', 'error'); }
}

async function loadWardenRetentionStatus() {
    try {
        const resp = await fetch('/tools/backup-manager/retention-status',
                                 {credentials: 'same-origin'});
        const data = await resp.json();
        const el = document.getElementById('wardenRetentionStatus');
        if (!el) return;
        if (data.retention_daily) document.getElementById('retentionDaily').value = data.retention_daily;
        if (data.retention_weekly) document.getElementById('retentionWeekly').value = data.retention_weekly;
        if (data.retention_monthly) document.getElementById('retentionMonthly').value = data.retention_monthly;

        // Build status text safely using textContent on child spans
        el.textContent = '';
        const parts = [
            ['Last prune: ', escapeHtml(String(data.last_run || 'Never'))],
            ['Deleted: ', escapeHtml(String(data.last_deleted_count || '0'))],
            ['Next: ', 'Sunday 04:00 EDT'],
        ];
        parts.forEach(([label, value], i) => {
            const lSpan = document.createElement('span');
            lSpan.textContent = (i > 0 ? ' · ' : '') + label;
            const vSpan = document.createElement('strong');
            vSpan.style.color = '#e2e8f0';
            vSpan.textContent = value;
            el.appendChild(lSpan);
            el.appendChild(vSpan);
        });
    } catch (e) { /* non-fatal */ }
}
```

Update `checkRetention()` to call `loadWardenRetentionStatus()` at the end. In the `switchTab` handler for `'retention'`, add `loadWardenRetentionStatus()` after `checkRetention()`.

- [ ] **Step 4: Restart and verify visually**

```bash
docker compose restart archie_platform
# Open Backup Manager → Retention tab
# Verify: number inputs show 7/4/6; Save button present
# Verify: W.A.R.D.E.N. panel shows "Last prune: ... · Deleted: ..."
# Change daily to 10, click Save, hard refresh — input should show 10
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/backup_manager.html \
        platform_v2/tools/backup_manager/routes_operations.py
git commit -m "feat(backup-manager): editable retention UI + W.A.R.D.E.N. status panel in Retention tab"
```

---

## Task 6: Async Deployment Package Creation (Work Item 3)

**Files:**
- Create: `database/migrations/377_deployment_package_jobs.sql`
- Modify: `platform_v2/tools/backup_manager/routes_storage.py`
- Modify: `platform_v2/templates/tools/backup_manager.html`
- Modify: `platform_v2/services/agent_jobs.py`

- [ ] **Step 1: Write failing tests**

In `platform_v2/tests/test_backup_consolidation.py`, append:

```python
def test_create_deployment_package_returns_job_id(client):
    """POST /api/create-deployment-package should return job_id immediately."""
    import time
    start = time.time()
    resp = client.post(
        '/tools/backup-manager/api/create-deployment-package',
        json={'version_tag': 'v5.33.0', 'description': 'test', 'target_platform': 'linux'},
        content_type='application/json'
    )
    elapsed = time.time() - start
    data = resp.get_json()
    assert resp.status_code == 200
    assert data.get('success') is True
    assert 'job_id' in data
    assert elapsed < 5.0, f"Should return in <5s, took {elapsed:.1f}s"


def test_get_deployment_package_status_returns_status(client, db_conn):
    """GET /api/deployment-package-status/<job_id> should return job status."""
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO deployment_package_jobs (package_name, status, progress_pct) "
            "VALUES ('test-pkg', 'building', 45) RETURNING id"
        )
        job_id = cur.fetchone()[0]
    db_conn.commit()

    resp = client.get(f'/tools/backup-manager/api/deployment-package-status/{job_id}')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['status'] == 'building'
    assert data['progress_pct'] == 45
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_create_deployment_package_returns_job_id platform_v2/tests/test_backup_consolidation.py::test_get_deployment_package_status_returns_status -v 2>&1 | tail -15
```
Expected: FAIL

- [ ] **Step 3: Create and run migration**

Create `database/migrations/377_deployment_package_jobs.sql`:

```sql
CREATE TABLE IF NOT EXISTS deployment_package_jobs (
    id              SERIAL PRIMARY KEY,
    package_name    VARCHAR(255) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'queued',
    progress_pct    INTEGER      DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT valid_pkg_status
        CHECK (status IN ('queued', 'building', 'ready', 'failed', 'expired'))
);
CREATE INDEX IF NOT EXISTS idx_deployment_package_jobs_status
    ON deployment_package_jobs(status, created_at DESC);
```

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/database/migrations/377_deployment_package_jobs.sql
```
Expected: `CREATE TABLE` and `CREATE INDEX`

- [ ] **Step 4: Refactor `create_deployment_package()` in `routes_storage.py` to be async**

Replace the existing synchronous body with an async wrapper that inserts a job row and launches a background thread. The original synchronous logic moves into a new `_build_deployment_package_bg()` helper that calls `_update_pkg_job(job_id, status, progress_pct)` at checkpoints:

```python
def _update_pkg_job(job_id, status, progress_pct, error=None):
    """Update deployment_package_jobs row. Called from background thread."""
    try:
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE deployment_package_jobs SET status=%s, progress_pct=%s, error=%s, "
                "completed_at = CASE WHEN %s IN ('ready','failed') THEN NOW() ELSE NULL END "
                "WHERE id=%s",
                (status, progress_pct, error, status, job_id)
            )
    except Exception as e:
        logger.warning("Failed to update pkg job %s: %s", job_id, e)


def _build_deployment_package_bg(job_id, package_name, description, version_tag,
                                  from_backup, target_platform):
    """Background thread: run original create_deployment_package logic with progress updates."""
    try:
        _update_pkg_job(job_id, 'building', 5)
        # ... (paste original function body here, inserting _update_pkg_job calls at key steps)
        # 10%: starting DB dump
        # 40%: DB dump done
        # 60%: code archive starting
        # 90%: archive done, packaging
        # 100% + status='ready': complete
        _update_pkg_job(job_id, 'ready', 100)
    except Exception as e:
        _update_pkg_job(job_id, 'failed', 0, error=str(e)[:500])
        logger.error("Deployment package build failed for job %s: %s", job_id, e)


@bp.route("/api/create-deployment-package", methods=["POST"])
@admin_required
def create_deployment_package():
    import threading
    from database import get_db_cursor
    data = request.get_json() or {}
    description = data.get("description", "Deployment package")
    version_tag = data.get("version_tag", get_platform_version())
    from_backup = data.get("from_backup")
    target_platform = data.get("target_platform", "linux")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_version = version_tag.replace(".", "_").replace(" ", "_")
    package_name = f"archie-deployment-{safe_version}-{timestamp}"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO deployment_package_jobs (package_name, status, progress_pct) "
            "VALUES (%s, 'queued', 0) RETURNING id",
            (package_name,)
        )
        job_id = cur.fetchone()[0]

    t = threading.Thread(
        target=_build_deployment_package_bg,
        args=(job_id, package_name, description, version_tag, from_backup, target_platform),
        daemon=True
    )
    t.start()
    return jsonify({"success": True, "job_id": job_id, "package_name": package_name, "status": "queued"})
```

- [ ] **Step 5: Add `GET /api/deployment-package-status/<job_id>` to `routes_storage.py`**

```python
@bp.route("/api/deployment-package-status/<int:job_id>")
@admin_required
def get_deployment_package_status(job_id):
    from database import get_db_cursor
    from psycopg2.extras import RealDictCursor as _RDC
    with get_db_cursor(commit=False) as (conn, cur):
        cur = conn.cursor(cursor_factory=_RDC)
        cur.execute(
            "SELECT id, package_name, status, progress_pct, error, created_at, completed_at "
            "FROM deployment_package_jobs WHERE id = %s",
            (job_id,)
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "Job not found"}), 404
    return jsonify({"success": True, **{k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                                        for k, v in dict(row).items()}})
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_create_deployment_package_returns_job_id platform_v2/tests/test_backup_consolidation.py::test_get_deployment_package_status_returns_status -v 2>&1 | tail -15
```
Expected: PASS

- [ ] **Step 7: Update Deployment Packages tab UI for async polling**

In `backup_manager.html`, replace `createDeploymentPackage()`:

```javascript
async function createDeploymentPackage() {
    const version = document.getElementById('packageVersion').value.trim() || '';
    const platform = document.getElementById('packagePlatform').value;
    const desc = document.getElementById('packageDescription').value.trim() || 'Deployment package';
    const btn = document.querySelector('[onclick="createDeploymentPackage()"]');
    btn.disabled = true;
    btn.textContent = 'Queuing...';
    try {
        const resp = await fetch('/tools/backup-manager/api/create-deployment-package', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({version_tag: version, target_platform: platform, description: desc})
        });
        const data = await resp.json();
        if (!data.success) {
            showToast('Failed: ' + escapeHtml(data.error || ''), 'error');
            btn.disabled = false; btn.textContent = 'Create Package';
            return;
        }
        btn.textContent = 'Building… 0%';
        _pollPackageJob(data.job_id, btn);
    } catch (e) {
        showToast('Network error', 'error');
        btn.disabled = false; btn.textContent = 'Create Package';
    }
}

function _pollPackageJob(jobId, btn) {
    const iv = setInterval(async () => {
        try {
            const resp = await fetch(
                '/tools/backup-manager/api/deployment-package-status/' + jobId,
                {credentials: 'same-origin'}
            );
            const data = await resp.json();
            if (data.status === 'building' || data.status === 'queued') {
                btn.textContent = 'Building… ' + (data.progress_pct || 0) + '%';
            } else if (data.status === 'ready') {
                clearInterval(iv);
                btn.disabled = false; btn.textContent = 'Create Package';
                showToast('Package ready: ' + escapeHtml(data.package_name || ''), 'success');
                loadDeploymentPackages();
            } else if (data.status === 'failed') {
                clearInterval(iv);
                btn.disabled = false; btn.textContent = 'Create Package';
                showToast('Package failed: ' + escapeHtml(data.error || 'unknown'), 'error');
            }
        } catch (e) {
            clearInterval(iv);
            btn.disabled = false; btn.textContent = 'Create Package';
        }
    }, 3000);
}
```

- [ ] **Step 8: Add W.A.R.D.E.N. version-bump job in `agent_jobs.py`**

After `_run_warden_pre_deploy_verify()`, add:

```python
def _run_warden_package_on_version_bump():
    """W.A.R.D.E.N. — nightly check: create deployment package if version changed since last package."""
    try:
        from database import get_db_cursor
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'platform_version'")
            row = cur.fetchone()
            if not row:
                return
            current_version = row[0]
            cur.execute(
                "SELECT package_name FROM deployment_package_jobs "
                "WHERE status = 'ready' ORDER BY created_at DESC LIMIT 1"
            )
            last_pkg = cur.fetchone()

        # If last package already contains current version, skip
        if last_pkg and current_version.replace(".", "_") in last_pkg[0]:
            return

        logger.info("W.A.R.D.E.N.: version bump to %s detected, queuing deployment package", current_version)
        import requests as _req
        _req.post(
            "http://127.0.0.1:3000/tools/backup-manager/api/create-deployment-package",
            json={"version_tag": current_version,
                  "description": f"W.A.R.D.E.N. auto-package for {current_version}"},
            timeout=10
        )
    except Exception as e:
        logger.warning("W.A.R.D.E.N. version-bump packager failed (non-fatal): %s", e)
```

Register inside `register_agent_welfare_jobs()`:

```python
scheduler.add_job(
    with_ctx(_run_warden_package_on_version_bump),
    trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),
    id="warden_version_bump_packager",
    name="W.A.R.D.E.N.: Nightly Version-Bump Package Check",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

- [ ] **Step 9: Restart and verify**

```bash
docker compose restart archie_platform
# Open Backup Manager → Deployment Packages tab
# Click Create Package → button changes to "Building… 0%", then increments
# After completion, package appears in list
```

- [ ] **Step 10: Commit**

```bash
git add database/migrations/377_deployment_package_jobs.sql \
        platform_v2/tools/backup_manager/routes_storage.py \
        platform_v2/services/agent_jobs.py \
        platform_v2/templates/tools/backup_manager.html \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "feat(backup-manager): async deployment package creation + polling UI + W.A.R.D.E.N. version-bump job"
```

---

## Task 7: Standalone Systems Tab — Backend (Work Item 4)

**Files:**
- Create: `database/migrations/378_backup_log_standalone.sql`
- Modify: `platform_v2/tools/backup_manager/_shared.py`
- Create: `platform_v2/tools/backup_manager/routes_standalones.py`
- Modify: `platform_v2/tools/backup_manager/__init__.py`

- [ ] **Step 1: Write failing tests**

In `platform_v2/tests/test_backup_consolidation.py`, append:

```python
def test_standalone_list_returns_all_9_products(client):
    """GET /api/standalones/list should return all 9 standalone products."""
    resp = client.get('/tools/backup-manager/api/standalones/list')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['success'] is True
    names = [s['name'] for s in data['standalones']]
    for expected in ['kbs', 'media_hub', 'creed', 'kso',
                     'gov_watch', 'civic_watch', 'legal_watch', 'market_watch', 'wtf']:
        assert expected in names, f"Missing standalone: {expected}"


def test_standalone_backup_returns_job_id(client):
    """POST /api/standalones/backup should return job_id immediately."""
    resp = client.post(
        '/tools/backup-manager/api/standalones/backup',
        json={'standalone_names': ['kso']},
        content_type='application/json'
    )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['success'] is True
    assert 'job_id' in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_standalone_list_returns_all_9_products platform_v2/tests/test_backup_consolidation.py::test_standalone_backup_returns_job_id -v 2>&1 | tail -10
```
Expected: FAIL (404)

- [ ] **Step 3: Create and run migration**

Create `database/migrations/378_backup_log_standalone.sql`:

```sql
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS standalone_name VARCHAR(100);
CREATE INDEX IF NOT EXISTS idx_backup_log_standalone
    ON backup_log(standalone_name) WHERE standalone_name IS NOT NULL;
```

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/database/migrations/378_backup_log_standalone.sql
```
Expected: `ALTER TABLE` and `CREATE INDEX`

- [ ] **Step 4: Add `STANDALONE_PRODUCTS` and `backup_standalone()` to `_shared.py`**

In `platform_v2/tools/backup_manager/_shared.py`, after the `BACKUP_DIR` constant, add:

```python
STANDALONE_PRODUCTS = [
    {"name": "kbs",          "display_name": "Kytran Business Suite",
     "code_path": "/mnt/archie_brain/kytran-business-suite",   "db_schema": "kbs",          "backup_type": "full"},
    {"name": "media_hub",    "display_name": "Media Hub",
     "code_path": "/mnt/archie_brain/standalone/media_hub",    "db_schema": "media_hub",    "backup_type": "config_only",
     "exclude_paths": ["/mnt/Plex", "/mnt/data2", "media/", "data/"],
     "exclude_extensions": [".mkv", ".mp4", ".avi", ".mov", ".m4v", ".iso"]},
    {"name": "creed",        "display_name": "C.R.E.E.D. Governance",
     "code_path": "/mnt/archie_brain/kytran-creed",            "db_schema": "creed",        "backup_type": "full"},
    {"name": "kso",          "display_name": "Kytran System Operations",
     "code_path": "/mnt/archie_brain/kytran-server-manager",   "db_schema": "kso",          "backup_type": "full"},
    {"name": "gov_watch",    "display_name": "Gov Watch",
     "code_path": "/mnt/standalone/kytran-gov-watch",          "db_schema": "gov_watch",    "backup_type": "full"},
    {"name": "civic_watch",  "display_name": "Civic Watch",
     "code_path": "/mnt/standalone/kytran-civic-watch",        "db_schema": "civic_watch",  "backup_type": "full"},
    {"name": "legal_watch",  "display_name": "Legal Watch",
     "code_path": "/mnt/standalone/kytran-legal-watch",        "db_schema": "legal_watch",  "backup_type": "full"},
    {"name": "market_watch", "display_name": "Market Watch",
     "code_path": "/mnt/standalone/kytran-market-watch",       "db_schema": "market_watch", "backup_type": "full"},
    {"name": "wtf",          "display_name": "What The Fact",
     "code_path": "/mnt/archie_brain/what-the-fact",           "db_schema": "wtf",          "backup_type": "full"},
]


def backup_standalone(standalone_name):
    """Backup one standalone: pg_dump of its schema + code tar.gz.
    Returns {'success': bool, 'backup_name': str, 'errors': list}."""
    import subprocess, tarfile

    product = next((p for p in STANDALONE_PRODUCTS if p["name"] == standalone_name), None)
    if not product:
        return {"success": False, "error": f"Unknown standalone: {standalone_name}", "errors": []}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"standalone_{standalone_name}_{timestamp}"
    dest_dir = os.path.join(BACKUP_DIR, "standalones", standalone_name)
    os.makedirs(dest_dir, exist_ok=True)
    backup_path = os.path.join(dest_dir, backup_name)
    os.makedirs(backup_path)

    errors = []

    # 1. pg_dump of schema
    db_dump_path = os.path.join(backup_path, f"{standalone_name}_schema.sql")
    pg_env = os.environ.copy()
    if os.getenv("DB_PASSWORD"):
        pg_env["PGPASSWORD"] = os.getenv("DB_PASSWORD", "")
    try:
        result = subprocess.run(
            ["pg_dump",
             "-h", os.getenv("DB_HOST", "192.168.1.200"),
             "-U", os.getenv("DB_USER", "archie"),
             "-d", os.getenv("DB_NAME", "archie"),
             "-n", product["db_schema"],
             "-f", db_dump_path],
            env=pg_env, capture_output=True, timeout=120
        )
        if result.returncode != 0:
            errors.append(f"pg_dump: {result.stderr.decode()[:200]}")
    except Exception as e:
        errors.append(f"pg_dump error: {e}")

    # 2. Code tar.gz
    code_archive = os.path.join(backup_path, f"{standalone_name}_code.tar.gz")
    code_path = product["code_path"]
    exclude_paths = product.get("exclude_paths", [])
    exclude_exts = set(e.lower() for e in product.get("exclude_extensions", []))
    code_size = 0
    if os.path.exists(code_path):
        try:
            with tarfile.open(code_archive, "w:gz") as tar:
                for dirpath, dirnames, filenames in os.walk(code_path):
                    dirnames[:] = [
                        d for d in dirnames
                        if not any(
                            excl.rstrip("/") in os.path.join(dirpath, d)
                            for excl in exclude_paths
                        )
                    ]
                    for fname in filenames:
                        if os.path.splitext(fname)[1].lower() in exclude_exts:
                            continue
                        fpath = os.path.join(dirpath, fname)
                        tar.add(fpath, arcname=os.path.relpath(fpath, code_path))
                        code_size += os.path.getsize(fpath)
        except Exception as e:
            errors.append(f"tar error: {e}")

    db_size = os.path.getsize(db_dump_path) if os.path.exists(db_dump_path) else 0
    total_size = code_size + db_size
    status = "completed" if not errors else "failed"

    try:
        with get_backup_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO backup_log "
                "(backup_name, backup_type, standalone_name, size_bytes, status, created_at) "
                "VALUES (%s, 'standalone', %s, %s, %s, NOW())",
                (backup_name, standalone_name, total_size, status)
            )
    except Exception as e:
        errors.append(f"DB log error: {e}")

    return {"success": not errors, "backup_name": backup_name,
            "backup_path": backup_path, "errors": errors}
```

- [ ] **Step 5: Create `routes_standalones.py`**

Create `platform_v2/tools/backup_manager/routes_standalones.py`:

```python
"""Backup Manager — standalone products backup routes."""
import os
import threading
import logging
from datetime import datetime
from flask import jsonify, request
from psycopg2.extras import RealDictCursor
from tools.backup_manager._shared import BACKUP_DIR, STANDALONE_PRODUCTS, backup_standalone, get_backup_db_cursor

logger = logging.getLogger(__name__)


def register_standalone_routes(bp, admin_required):

    @bp.route("/api/standalones/list")
    @admin_required
    def list_standalones():
        try:
            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    """SELECT DISTINCT ON (standalone_name)
                         standalone_name, backup_name, size_bytes, status, created_at
                       FROM backup_log
                       WHERE standalone_name IS NOT NULL
                       ORDER BY standalone_name, created_at DESC"""
                )
                last_backups = {r["standalone_name"]: r for r in cur.fetchall()}

            result = []
            for p in STANDALONE_PRODUCTS:
                last = last_backups.get(p["name"])
                result.append({
                    "name": p["name"],
                    "display_name": p["display_name"],
                    "code_path": p["code_path"],
                    "db_schema": p["db_schema"],
                    "backup_type": p["backup_type"],
                    "code_path_exists": os.path.exists(p["code_path"]),
                    "last_backup_name": last["backup_name"] if last else None,
                    "last_backup_at": last["created_at"].isoformat() if last and last["created_at"] else None,
                    "last_backup_size_bytes": last["size_bytes"] if last else None,
                    "last_backup_status": last["status"] if last else None,
                })
            return jsonify({"success": True, "standalones": result})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/standalones/backup", methods=["POST"])
    @admin_required
    def backup_standalones():
        data = request.get_json() or {}
        names = data.get("standalone_names", [p["name"] for p in STANDALONE_PRODUCTS])
        invalid = [n for n in names if not any(p["name"] == n for p in STANDALONE_PRODUCTS)]
        if invalid:
            return jsonify({"success": False, "error": f"Unknown standalones: {invalid}"}), 400

        job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_standalone"

        def _run():
            for name in names:
                try:
                    result = backup_standalone(name)
                    logger.info("Standalone backup %s: %s",
                                name, "ok" if result["success"] else str(result.get("errors")))
                except Exception as e:
                    logger.error("Standalone backup %s error: %s", name, e)

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"success": True, "job_id": job_id, "standalone_names": names})

    @bp.route("/api/standalones/history/<standalone_name>")
    @admin_required
    def standalone_backup_history(standalone_name):
        try:
            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    "SELECT backup_name, size_bytes, status, created_at FROM backup_log "
                    "WHERE standalone_name = %s ORDER BY created_at DESC LIMIT 10",
                    (standalone_name,)
                )
                rows = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "history": rows})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 6: Register in `__init__.py`**

In `platform_v2/tools/backup_manager/__init__.py`, find where other `register_*_routes` calls are and add:

```python
from tools.backup_manager.routes_standalones import register_standalone_routes
register_standalone_routes(backup_manager_bp, admin_required)
```

- [ ] **Step 7: Restart and run tests**

```bash
docker compose restart archie_platform
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py::test_standalone_list_returns_all_9_products platform_v2/tests/test_backup_consolidation.py::test_standalone_backup_returns_job_id -v 2>&1 | tail -15
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add database/migrations/378_backup_log_standalone.sql \
        platform_v2/tools/backup_manager/_shared.py \
        platform_v2/tools/backup_manager/routes_standalones.py \
        platform_v2/tools/backup_manager/__init__.py \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "feat(backup-manager): standalone products registry + backup_standalone() + list/backup/history routes"
```

---

## Task 8: Standalone Systems Tab — UI + W.A.R.D.E.N. (Work Item 4, frontend)

**Files:**
- Modify: `platform_v2/templates/tools/backup_manager.html`
- Modify: `platform_v2/services/agent_jobs.py`

- [ ] **Step 1: Add tab nav button**

In `backup_manager.html`, in the tab nav row (find the `data-tab="modules"` button), add after it:

```html
<button class="tab-btn" data-tab="standalones" onclick="switchTab('standalones')">
    Standalone Systems
</button>
```

- [ ] **Step 2: Add tab panel**

After the `<!-- MODULE BACKUPS TAB -->` closing `</div>` (around line 441), insert:

```html
<!-- STANDALONE SYSTEMS TAB -->
<div class="tab-content" id="tab-standalones">
    <div style="--frame-color: #10b981; margin-bottom: 20px;">
        <div class="lcars-frame" style="display:flex!important;align-items:stretch!important;">
            <div class="lcars-sidebar" style="display:flex!important;flex-direction:column!important;flex-shrink:0!important;width:56px!important;gap:4px!important;">
                <div style="height:52px!important;background:#10b981!important;border-radius:20px 0 0 0!important;flex-shrink:0!important;"></div>
                <div style="height:28px!important;border-radius:0 8px 8px 0!important;background:#10b981!important;flex-shrink:0!important;"></div>
                <div style="flex:1!important;background:rgba(16,185,129,0.2)!important;border-radius:0 8px 8px 0!important;min-height:20px!important;"></div>
                <div style="height:36px!important;background:#10b981!important;border-radius:0 0 0 20px!important;flex-shrink:0!important;"></div>
            </div>
            <div style="flex:1!important;display:flex!important;flex-direction:column!important;margin-left:8px!important;min-width:0!important;">
                <div style="height:44px!important;background:#10b981!important;border-radius:0 20px 20px 0!important;display:flex!important;align-items:center!important;padding:0 16px!important;flex-shrink:0!important;">
                    <span style="font-family:'Antonio',sans-serif!important;font-size:0.85rem!important;letter-spacing:2px!important;text-transform:uppercase!important;color:#010409!important;">STANDALONE SYSTEMS</span>
                </div>
                <div style="flex:1!important;padding:16px!important;">
                    <!-- W.A.R.D.E.N. status strip -->
                    <div id="wardenStandaloneStatus"
                         style="padding:10px 14px;margin-bottom:16px;background:rgba(167,139,250,0.05);
                                border:1px solid rgba(167,139,250,0.15);border-radius:8px;
                                font-size:12px;color:var(--archie-text-secondary);">
                        Loading W.A.R.D.E.N. standalone status...
                    </div>
                    <div style="margin-bottom:var(--archie-space-3);">
                        <h3 class="section-header" style="color:#10b981;">Standalone Systems</h3>
                        <p class="section-description">Code + DB schema backup for all 9 standalone products. Media Hub = configs + schema only.</p>
                    </div>
                    <div class="module-toolbar">
                        <div class="toolbar-left">
                            <button class="btn" onclick="selectAllStandalones()">All</button>
                            <button class="btn" onclick="deselectAllStandalones()">None</button>
                            <span class="stat"><strong id="selectedStandaloneCount">0</strong> selected</span>
                        </div>
                        <div class="toolbar-right">
                            <button class="btn" style="color:#10b981;border-color:#10b981"
                                    onclick="backupSelectedStandalones()">Backup Selected</button>
                        </div>
                    </div>
                    <div id="standaloneGrid" class="module-list" style="margin-top:12px;">
                        <div class="loading"><div class="spinner"></div><p>Loading...</p></div>
                    </div>
                </div>
                <div style="height:6px!important;background:#10b981!important;border-radius:0 0 20px 0!important;flex-shrink:0!important;"></div>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Add JavaScript for the Standalone Systems tab**

In the JS section, add:

```javascript
// STANDALONE SYSTEMS TAB
async function loadStandaloneSystems() {
    try {
        const resp = await fetch('/tools/backup-manager/api/standalones/list',
                                 {credentials: 'same-origin'});
        const data = await resp.json();
        if (!data.success) return;
        renderStandaloneGrid(data.standalones);
        _updateWardenStandaloneStrip(data.standalones);
    } catch (e) {
        const g = document.getElementById('standaloneGrid');
        if (g) { g.textContent = ''; const d = document.createElement('div'); d.className = 'empty-state'; d.textContent = 'Error loading standalones'; g.appendChild(d); }
    }
}

function renderStandaloneGrid(standalones) {
    const grid = document.getElementById('standaloneGrid');
    grid.textContent = '';
    standalones.forEach(s => {
        const row = document.createElement('div');
        row.className = 'module-row';
        row.dataset.name = s.name;
        row.onclick = function() { this.classList.toggle('selected'); _updateStandaloneCount(); };

        const check = document.createElement('div');
        check.className = 'check'; check.textContent = '✓';
        row.appendChild(check);

        const nameSpan = document.createElement('span');
        nameSpan.className = 'name';
        nameSpan.textContent = s.display_name + (s.backup_type === 'config_only' ? ' (configs)' : '');
        row.appendChild(nameSpan);

        const metaSpan = document.createElement('span');
        metaSpan.className = 'meta';
        metaSpan.textContent = s.db_schema + ' schema · ' + (s.code_path_exists ? '✓ code' : '✗ missing');
        row.appendChild(metaSpan);

        const ageSpan = document.createElement('span');
        ageSpan.className = 'backup-age';
        if (s.last_backup_at) {
            const days = Math.floor((Date.now() - new Date(s.last_backup_at).getTime()) / 86400000);
            ageSpan.textContent = days === 0 ? 'today' : days + 'd ago';
            ageSpan.classList.add(days < 7 ? 'recent' : 'stale');
        } else {
            ageSpan.textContent = 'never';
            ageSpan.classList.add('none');
        }
        row.appendChild(ageSpan);
        grid.appendChild(row);
    });
}

function _updateStandaloneCount() {
    const n = document.querySelectorAll('#standaloneGrid .module-row.selected').length;
    const el = document.getElementById('selectedStandaloneCount');
    if (el) el.textContent = String(n);
}

function selectAllStandalones() {
    document.querySelectorAll('#standaloneGrid .module-row').forEach(r => r.classList.add('selected'));
    _updateStandaloneCount();
}

function deselectAllStandalones() {
    document.querySelectorAll('#standaloneGrid .module-row').forEach(r => r.classList.remove('selected'));
    _updateStandaloneCount();
}

async function backupSelectedStandalones() {
    const names = Array.from(document.querySelectorAll('#standaloneGrid .module-row.selected'))
                       .map(r => r.dataset.name);
    if (!names.length) { showToast('Select at least one standalone', 'error'); return; }
    if (!confirm('Backup ' + names.length + ' standalone(s)? This may take several minutes.')) return;
    showToast('Starting backup of ' + names.length + ' standalone(s)…', 'info');
    try {
        const resp = await fetch('/tools/backup-manager/api/standalones/backup', {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({standalone_names: names})
        });
        const data = await resp.json();
        if (data.success) showToast('Backup running in background. Refresh in a few minutes.', 'success');
        else showToast('Failed: ' + escapeHtml(data.error || ''), 'error');
    } catch (e) { showToast('Network error', 'error'); }
}

function _updateWardenStandaloneStrip(standalones) {
    const el = document.getElementById('wardenStandaloneStatus');
    if (!el) return;
    const never = standalones.filter(s => !s.last_backup_at).length;
    const stale = standalones.filter(s => s.last_backup_at &&
        (Date.now() - new Date(s.last_backup_at).getTime()) > 7 * 86400000).length;

    el.textContent = '';
    const parts = document.createDocumentFragment();

    const agentLabel = document.createElement('span');
    agentLabel.style.cssText = 'color:#a78bfa;font-family:Antonio,sans-serif;font-size:0.75rem;letter-spacing:1.5px;';
    agentLabel.textContent = 'W.A.R.D.E.N.';
    parts.appendChild(agentLabel);

    const sep1 = document.createTextNode('  ');
    parts.appendChild(sep1);

    const neverSpan = document.createElement('span');
    neverSpan.style.color = never > 0 ? '#f87171' : '#4ade80';
    neverSpan.textContent = never + ' never backed up';
    parts.appendChild(neverSpan);

    parts.appendChild(document.createTextNode(' · '));

    const staleSpan = document.createElement('span');
    staleSpan.style.color = stale > 0 ? '#fbbf24' : '#4ade80';
    staleSpan.textContent = stale + ' stale (>7d)';
    parts.appendChild(staleSpan);

    parts.appendChild(document.createTextNode(' · Next auto: Wednesday 02:00 EDT'));
    el.appendChild(parts);
}
```

In `switchTab()`, add: `if (tabId === 'standalones') loadStandaloneSystems();`

- [ ] **Step 4: Add W.A.R.D.E.N. weekly standalone backup job in `agent_jobs.py`**

After `_run_warden_package_on_version_bump()`, add:

```python
def _run_warden_standalone_backup():
    """W.A.R.D.E.N. — weekly backup of all 9 standalone products (Wednesdays 02:00 EDT)."""
    try:
        from tools.backup_manager._shared import STANDALONE_PRODUCTS, backup_standalone
        results = {}
        for p in STANDALONE_PRODUCTS:
            try:
                r = backup_standalone(p["name"])
                results[p["name"]] = "ok" if r["success"] else f"FAILED: {r.get('errors', [])}"
            except Exception as e:
                results[p["name"]] = f"ERROR: {e}"
            logger.info("W.A.R.D.E.N. standalone backup %s: %s", p["name"], results[p["name"]])

        failed = [k for k, v in results.items() if v != "ok"]
        msg = (f"W.A.R.D.E.N. standalone backup: {len(results)-len(failed)}/{len(results)} ok"
               + (f" — FAILED: {', '.join(failed)}" if failed else ""))
        logger.info(msg)
        try:
            from services.telegram_service import send_info
            send_info(msg)
        except Exception:
            pass
    except Exception as e:
        logger.error("W.A.R.D.E.N. standalone backup job failed: %s", e)
```

Register inside `register_agent_welfare_jobs()`:

```python
scheduler.add_job(
    with_ctx(_run_warden_standalone_backup),
    trigger=CronTrigger(day_of_week="wed", hour=2, minute=0, timezone="America/Toronto"),
    id="warden_standalone_backup",
    name="W.A.R.D.E.N.: Weekly Standalone Systems Backup",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

- [ ] **Step 5: Restart and verify visually**

```bash
docker compose restart archie_platform
# Open Backup Manager — new "Standalone Systems" tab visible
# Tab loads 9 rows with correct display names, db_schema, code_path_exists status, age
# W.A.R.D.E.N. strip shows count of never/stale + next run time
# Select "KSO", click Backup Selected → success toast
# Refresh after ~30s → KSO row shows "today"
```

- [ ] **Step 6: Run full test suite**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_backup_consolidation.py -v 2>&1 | tail -30
```
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add platform_v2/templates/tools/backup_manager.html \
        platform_v2/services/agent_jobs.py \
        platform_v2/tests/test_backup_consolidation.py
git commit -m "feat(backup-manager): Standalone Systems tab UI + W.A.R.D.E.N. weekly backup job"
```

---

## Final: Push PR

```bash
git push -u origin feat/backup-manager-consolidation-spec
gh pr create \
  --title "feat(backup-manager): consolidation — 4 improvements + 2 bug fixes" \
  --body "$(cat <<'EOF'
## Summary
- Fix DB/filesystem drift: cleanup now deletes backup_log rows + orphan-cleanup endpoint
- Exclude Daily_Triage dirs from GFS (managed by backup_triage.sh with its own retention)
- Wire pre-deploy backup trigger in proposal_service.py + improvement_deployments insert
- Editable GFS retention policy (system_config) + W.A.R.D.E.N. history panel in Retention tab
- Async Deployment Package creation with progress polling + W.A.R.D.E.N. version-bump job
- New Standalone Systems tab: backup code + DB schema for all 9 standalone products, W.A.R.D.E.N. weekly job (Wed 02:00 EDT)

## Migrations (run in order)
- 376_retention_config.sql
- 377_deployment_package_jobs.sql
- 378_backup_log_standalone.sql

## Test Plan
- [ ] pytest platform_v2/tests/test_backup_consolidation.py — all pass
- [ ] Retention tab: number inputs show 7/4/6, change + save persists
- [ ] Deployment Packages: Create Package returns immediately, progress % polls to completion
- [ ] Standalone Systems tab: 9 rows load, backup KSO, row shows today after ~30s
- [ ] Deploy a Repair Bay proposal, Deployment Backups tab shows the entry

Generated with Claude Code
EOF
)"
```
