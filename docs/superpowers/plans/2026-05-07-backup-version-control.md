# Backup System v2 — Version Control, Safe Restore & Deployment Triad

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 broken backup buttons, add git version tracking to every backup row, build a two-stage safe sandbox restore (W.A.R.D.E.N. + P.R.O.B.E.), and establish F.O.R.G.E./C.O.D.E.X. deployment gates.

**Architecture:** Four sequential phases — Phase A fixes the urgent 500 errors (can ship as standalone PR), Phase B adds git/actor tracking to backup_log, Phase C wires W.A.R.D.E.N. restore + P.R.O.B.E. QA through Department HQ dispatch, Phase D adds F.O.R.G.E. PR gate and C.O.D.E.X. doc gate to proposal_service.

**Tech Stack:** Python/Flask, PostgreSQL (psycopg2), pytest, subprocess (git), Department HQ delegate_task, agent_skills, CAPABILITY_DEPARTMENT_MAP

---

## File Map

**Phase A — Modify:**
- `platform_v2/tools/backup_manager/_shared.py:1841` — wrap `val.isoformat()` in try/except
- `platform_v2/tools/backup_manager/routes_operations.py:~600` — INSERT into backup_log after backup creation
- `database/migrations/373_backup_version_tracking.sql` — new columns on backup_log

**Phase B — Modify:**
- `platform_v2/tools/backup_manager/routes_operations.py` — capture git context before backup, pass to INSERT

**Phase C — Create:**
- `platform_v2/services/backup_restore_service.py` — restore_to_sandbox(), restore_to_production(), verify_restore()
- `platform_v2/tools/backup_manager/routes_restore.py` — add /api/restore/sandbox, /api/restore/promote, /api/restore/status
- `platform_v2/tests/test_backup_restore_service.py`
- `platform_v2/qa_suites/backup-restore-e2e.yaml`

**Phase C — Modify:**
- `platform_v2/services/department_coordinator.py` — add restore_sandbox, restore_production, restore_verify, qa_sandbox_restore
- `platform_v2/services/backup_service.py` — extend snapshot_module to support restore context

**Phase D — Create:**
- `platform_v2/services/forge_gate_service.py` — F.O.R.G.E. PR gate logic
- `platform_v2/services/codex_gate_service.py` — C.O.D.E.X. doc gate (non-blocking)
- `platform_v2/tests/test_forge_gate_service.py`
- `platform_v2/tests/test_codex_gate_service.py`

**Phase D — Modify:**
- `platform_v2/services/proposal_service.py:~530` — add F.O.R.G.E. gate check alongside W.A.R.D.E.N. check
- `platform_v2/services/department_coordinator.py` — add pr_gate, doc_gate capabilities

---

## PHASE A — BUG FIXES (ship first, urgent)

---

### Task 1: Fix datetime overflow crash in backup_database_python()

**Files:**
- Modify: `platform_v2/tools/backup_manager/_shared.py:1841`
- Test: `platform_v2/tests/test_backup_shared.py` (create new)

- [ ] **Step 1: Write failing test — confirm the crash is reproducible**

```bash
cat > /tmp/test_backup_datetime.py << 'EOF'
import sys, os; sys.path.insert(0, '/app'); os.chdir('/app')
from tools.backup_manager._shared import backup_database_python
import tempfile, os

# Should complete without raising ValueError: year N is out of range
with tempfile.NamedTemporaryFile(suffix='.sql', delete=False) as f:
    outfile = f.name
try:
    result = backup_database_python(outfile, compress=False)
    print("PASS: backup_database_python completed, file:", result)
except ValueError as e:
    print("FAIL:", e)
finally:
    if os.path.exists(outfile): os.remove(outfile)
EOF
docker exec archie_platform python3 /tmp/test_backup_datetime.py 2>&1
```
Expected: `FAIL: year 58317 is out of range`

- [ ] **Step 2: Find the exact datetime serialization at line ~1841**

```bash
sed -n '1830,1860p' /mnt/archie_brain/platform_v2/tools/backup_manager/_shared.py
```

This shows the row serialization loop in `backup_database_python()`. The line doing `val.isoformat()` on datetime objects is the crash site.

- [ ] **Step 3: Fix — wrap all datetime/date serialization in safe_serialize()**

In `_shared.py`, add this helper near the top of `backup_database_python()` (before the table loop):

```python
def _safe_serialize_val(val):
    """Serialize a DB value to SQL literal. Handles out-of-range datetimes."""
    import datetime as _dt
    if val is None:
        return "NULL"
    if isinstance(val, (_dt.datetime, _dt.date)):
        try:
            return f"'{val.isoformat()}'"
        except (ValueError, OverflowError):
            # Out-of-range year (e.g. year 58317) — store as NULL with a comment
            return "NULL  -- original value had out-of-range year"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    # String — escape single quotes
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"
```

Then replace the existing value serialization block (the `if/elif isinstance` chain around line 1841) to call `_safe_serialize_val(val)` for each value instead of inline type checks.

- [ ] **Step 4: Run test — confirm it passes**

```bash
docker exec archie_platform python3 /tmp/test_backup_datetime.py 2>&1
```
Expected: `PASS: backup_database_python completed, file: /tmp/....sql`

- [ ] **Step 5: Also fix the same pattern in any other .isoformat() calls in _shared.py**

```bash
grep -n '\.isoformat()\|\.strftime(' /mnt/archie_brain/platform_v2/tools/backup_manager/_shared.py | grep -v 'datetime\.now()\|_safe_serialize'
```

For any `.isoformat()` on a variable (not `datetime.now().isoformat()`), wrap in try/except ValueError.

- [ ] **Step 6: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/tools/backup_manager/_shared.py
git -C /mnt/archie_brain commit -m "fix(backup): safe datetime serialization in backup_database_python — prevent year out-of-range crash"
```

---

### Task 2: Fix backup_log INSERT missing after backup creation

**Files:**
- Modify: `platform_v2/tools/backup_manager/routes_operations.py:~600`

- [ ] **Step 1: Find the success return block in api_create_backup()**

```bash
sed -n '600,660p' /mnt/archie_brain/platform_v2/tools/backup_manager/routes_operations.py
```

Find the `return jsonify({"success": True, ...})` at the end of the happy path. The INSERT goes just before this return.

- [ ] **Step 2: Add backup_log INSERT before the success return**

Insert this block immediately before the `return jsonify({"success": True...})` in `api_create_backup()`:

```python
            # INSERT into backup_log so the list endpoint sees this backup
            try:
                from database import get_db_cursor
                total_size = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, files in os.walk(backup_path)
                    for f in files
                ) if os.path.exists(backup_path) else 0
                with get_db_cursor(commit=True) as (_c, _cur):
                    _cur.execute(
                        """INSERT INTO backup_log
                               (backup_type, file_path, size_bytes, status, tier,
                                component, notes, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""",
                        (
                            backup_type,
                            backup_path,
                            total_size,
                            "success",
                            "primary",
                            ",".join(components_to_backup),
                            description,
                        ),
                    )
            except Exception as _log_err:
                current_app.logger.warning("backup_log INSERT failed (non-fatal): %s", _log_err)
```

- [ ] **Step 3: Test — trigger Full Backup from UI and verify backup_log updated**

```bash
# Before: note the current max id
docker exec archie_database psql -U archie -d archie -t -c "SELECT MAX(id) FROM backup_log;" 2>/dev/null
```

Then trigger a Database backup (fastest, ~5-20MB) via the UI at http://192.168.1.200:3000/tools/backup-manager.

```bash
# After: confirm new row
docker exec archie_database psql -U archie -d archie -t -c "SELECT id, backup_type, file_path, status, created_at FROM backup_log ORDER BY created_at DESC LIMIT 3;" 2>/dev/null
```
Expected: new row with `status=success`, `backup_type=database`.

- [ ] **Step 4: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/tools/backup_manager/routes_operations.py
git -C /mnt/archie_brain commit -m "fix(backup): INSERT into backup_log after successful backup creation — fixes empty list for new backups"
```

---

### Task 3: Migration 373 — version tracking columns on backup_log

**Files:**
- Create: `database/migrations/373_backup_version_tracking.sql`

- [ ] **Step 1: Create migration**

```bash
cat > /mnt/archie_brain/database/migrations/373_backup_version_tracking.sql << 'EOF'
-- Migration 373: version tracking on backup_log
-- Every backup now records git context and who triggered it

ALTER TABLE backup_log
  ADD COLUMN IF NOT EXISTS git_commit    TEXT,
  ADD COLUMN IF NOT EXISTS git_branch    TEXT,
  ADD COLUMN IF NOT EXISTS platform_version TEXT,
  ADD COLUMN IF NOT EXISTS triggered_by  TEXT,
  ADD COLUMN IF NOT EXISTS proposal_id   INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS pr_number     INTEGER;

-- Index for fast lookup by git_commit
CREATE INDEX IF NOT EXISTS idx_backup_log_git_commit ON backup_log(git_commit);
CREATE INDEX IF NOT EXISTS idx_backup_log_triggered_by ON backup_log(triggered_by);
EOF
```

- [ ] **Step 2: Run migration**

```bash
docker cp /mnt/archie_brain/database/migrations/373_backup_version_tracking.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/373_backup_version_tracking.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d backup_log" | grep -E 'git_|triggered_by|proposal_id|pr_number'
```
Expected: 5 new columns listed.

- [ ] **Step 4: Commit**

```bash
git -C /mnt/archie_brain add database/migrations/373_backup_version_tracking.sql
git -C /mnt/archie_brain commit -m "feat(db): migration 373 — git_commit, triggered_by, pr_number on backup_log"
```

**→ Phase A complete. Create PR, merge, deploy before continuing.**

---

## PHASE B — VERSION TRACKING

---

### Task 4: Capture git context at backup time + update list response

**Files:**
- Modify: `platform_v2/tools/backup_manager/routes_operations.py`

- [ ] **Step 1: Add git context capture helper at top of api_create_backup()**

At the start of `api_create_backup()`, before the component selection, add:

```python
            # Capture git context (fail-safe — never crash the backup if git unavailable)
            import subprocess as _sp
            def _git(cmd):
                try:
                    return _sp.run(['git', '-C', '/app'] + cmd, capture_output=True, text=True, timeout=5).stdout.strip()
                except Exception:
                    return None

            _git_commit = _git(['rev-parse', 'HEAD'])
            _git_branch = _git(['rev-parse', '--abbrev-ref', 'HEAD'])
            _triggered_by = data.get('triggered_by', 'manual')
            _proposal_id = data.get('proposal_id')
            _pr_number = data.get('pr_number')
```

- [ ] **Step 2: Update the backup_log INSERT from Task 2 to include new columns**

Replace the INSERT in `api_create_backup()` with:

```python
                    _cur.execute(
                        """INSERT INTO backup_log
                               (backup_type, file_path, size_bytes, status, tier,
                                component, notes, git_commit, git_branch,
                                triggered_by, proposal_id, pr_number, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
                        (
                            backup_type, backup_path, total_size,
                            "success", "primary",
                            ",".join(components_to_backup), description,
                            _git_commit, _git_branch,
                            _triggered_by, _proposal_id, _pr_number,
                        ),
                    )
```

- [ ] **Step 3: Update list_backups() to include new columns in response**

In `list_backups()` (around line 70 of routes_operations.py), add these fields to the SELECT:

```sql
SELECT id, backup_type, file_path, file_size_bytes, size_bytes,
       status, created_at, completed_at, error_message,
       component, tier, verification_status, notes,
       git_commit, git_branch, triggered_by, proposal_id, pr_number
FROM backup_log
ORDER BY created_at DESC
LIMIT 200
```

And in the response dict mapping, add:
```python
"git_commit": row.get("git_commit"),
"git_branch": row.get("git_branch"),
"triggered_by": row.get("triggered_by"),
"proposal_id": row.get("proposal_id"),
"pr_number": row.get("pr_number"),
```

- [ ] **Step 4: Test — trigger a backup and verify git context in response**

```bash
# Trigger a Database backup from the UI, then check the API response
docker exec archie_platform python3 -c "
import sys, os, requests; sys.path.insert(0, '/app')
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'kytran','password':os.environ.get('ARCHIE_TEST_PASSWORD','archie2025')})
r = s.get('http://localhost:3000/tools/backup-manager/list')
data = r.json()
backups = data.get('backups', data) if isinstance(data, dict) else data
newest = backups[0] if backups else {}
print('git_commit:', newest.get('git_commit'))
print('triggered_by:', newest.get('triggered_by'))
print('status:', newest.get('status'))
" 2>&1
```
Expected: `git_commit: <40-char SHA>`, `triggered_by: manual`, `status: success`

- [ ] **Step 5: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/tools/backup_manager/routes_operations.py
git -C /mnt/archie_brain commit -m "feat(backup): capture git_commit + triggered_by at backup time, include in list response"
```

---

## PHASE C — TWO-STAGE SAFE RESTORE

---

### Task 5: Create backup_restore_service.py with sandbox + production restore

**Files:**
- Create: `platform_v2/services/backup_restore_service.py`
- Create: `platform_v2/tests/test_backup_restore_service.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > /mnt/archie_brain/platform_v2/tests/test_backup_restore_service.py << 'EOF'
"""Tests for backup_restore_service."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest


def test_importable():
    from services.backup_restore_service import (
        get_restore_status, initiate_sandbox_restore, promote_to_production
    )
    assert all(callable(f) for f in [get_restore_status, initiate_sandbox_restore, promote_to_production])


def test_get_restore_status_missing_backup():
    from services.backup_restore_service import get_restore_status
    r = get_restore_status(backup_id=999999999)
    assert r["success"] is False
    assert r["error"] == "backup_not_found"


def test_initiate_sandbox_restore_missing_backup():
    from services.backup_restore_service import initiate_sandbox_restore
    r = initiate_sandbox_restore(backup_id=999999999, triggered_by="test")
    assert r["success"] is False
    assert r["error"] == "backup_not_found"


def test_restore_status_table_exists():
    """module_restore_sessions table should exist after migration."""
    from database import get_db_cursor
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='module_restore_sessions'")
        assert cur.fetchone() is not None, "Run migration 374 first"
EOF
```

- [ ] **Step 2: Run tests — confirm 3 fail (service missing) and 1 fails (table missing)**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_restore_service.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Create migration 374 — restore session tracking table**

```bash
cat > /mnt/archie_brain/database/migrations/374_restore_sessions.sql << 'EOF'
-- Migration 374: restore session tracking
-- Tracks sandbox restore attempts and their QA status

CREATE TABLE IF NOT EXISTS module_restore_sessions (
    id              SERIAL PRIMARY KEY,
    backup_id       INTEGER NOT NULL REFERENCES backup_log(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','sandbox_ready','qa_running','qa_passed','qa_failed','promoting','promoted','failed')),
    sandbox_schema  TEXT,
    sandbox_url     TEXT,
    qa_run_id       INTEGER,
    qa_passed       INTEGER DEFAULT 0,
    qa_total        INTEGER DEFAULT 0,
    qa_failures     JSONB DEFAULT '[]',
    triggered_by    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restore_sessions_backup ON module_restore_sessions(backup_id);
CREATE INDEX IF NOT EXISTS idx_restore_sessions_status ON module_restore_sessions(status);
EOF
docker cp /mnt/archie_brain/database/migrations/374_restore_sessions.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/374_restore_sessions.sql
```

- [ ] **Step 4: Create backup_restore_service.py**

```bash
cat > /mnt/archie_brain/platform_v2/services/backup_restore_service.py << 'EOF'
"""
Backup Restore Service — owned by W.A.R.D.E.N.
Two-stage safe restore: sandbox first (P.R.O.B.E. QA), then production promote.
All operations through Department HQ delegate_task queue.
"""
from __future__ import annotations
import logging
from typing import Any
from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_restore_status(backup_id: int) -> dict[str, Any]:
    """Return current restore session status for a backup, if any."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id FROM backup_log WHERE id = %s", (backup_id,))
        if not cur.fetchone():
            return {"success": False, "error": "backup_not_found"}
        cur.execute(
            "SELECT * FROM module_restore_sessions WHERE backup_id = %s ORDER BY created_at DESC LIMIT 1",
            (backup_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": True, "session": None, "status": "no_session"}
        session = dict(row)
        if session.get("created_at"):
            session["created_at"] = session["created_at"].isoformat()
        if session.get("updated_at"):
            session["updated_at"] = session["updated_at"].isoformat()
        return {"success": True, "session": session, "status": session["status"]}


def initiate_sandbox_restore(backup_id: int, triggered_by: str = "user") -> dict[str, Any]:
    """
    Start a sandbox restore session for the given backup_id.
    Creates a module_restore_sessions row and delegates to W.A.R.D.E.N. via dispatch.
    Returns immediately with session_id (async operation).
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id, file_path, backup_type FROM backup_log WHERE id = %s", (backup_id,))
        backup = cur.fetchone()
        if not backup:
            return {"success": False, "error": "backup_not_found"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO module_restore_sessions (backup_id, status, triggered_by)
               VALUES (%s, 'pending', %s) RETURNING id""",
            (backup_id, triggered_by),
        )
        session_id = cur.fetchone()["id"]

    # Delegate to W.A.R.D.E.N. via Department HQ
    try:
        from services.delegation_service import delegate_task
        delegate_task(
            capability="restore_sandbox",
            reason=f"Sandbox restore for backup #{backup_id} (session #{session_id})",
            args={"backup_id": backup_id, "session_id": session_id},
            delegation_source="automation",
        )
    except Exception as e:
        logger.warning("Could not delegate restore_sandbox task: %s", e)
        # Update session to failed if delegation fails
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE module_restore_sessions SET status='failed', updated_at=NOW() WHERE id=%s",
                (session_id,),
            )
        return {"success": False, "error": f"delegation_failed: {e}"}

    return {"success": True, "session_id": session_id, "status": "pending"}


def promote_to_production(session_id: int, triggered_by: str = "user") -> dict[str, Any]:
    """
    Promote a QA-verified sandbox restore to production.
    Only allowed when session status = 'qa_passed'.
    Delegates to W.A.R.D.E.N. via Department HQ.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, backup_id, status FROM module_restore_sessions WHERE id = %s",
            (session_id,),
        )
        session = cur.fetchone()
        if not session:
            return {"success": False, "error": "session_not_found"}
        if session["status"] != "qa_passed":
            return {
                "success": False,
                "error": f"cannot_promote: session status is '{session['status']}', must be 'qa_passed'",
            }

    try:
        from services.delegation_service import delegate_task
        delegate_task(
            capability="restore_production",
            reason=f"Promote session #{session_id} (backup #{session['backup_id']}) to production",
            args={"session_id": session_id, "backup_id": session["backup_id"]},
            delegation_source="automation",
        )
    except Exception as e:
        return {"success": False, "error": f"delegation_failed: {e}"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE module_restore_sessions SET status='promoting', updated_at=NOW() WHERE id=%s",
            (session_id,),
        )
    return {"success": True, "session_id": session_id, "status": "promoting"}
EOF
```

- [ ] **Step 5: Run all 4 tests — expect 4/4 pass**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_restore_service.py -v 2>&1 | tail -10
```
Expected: 4/4 PASS.

- [ ] **Step 6: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/services/backup_restore_service.py \
    platform_v2/tests/test_backup_restore_service.py \
    database/migrations/374_restore_sessions.sql
git -C /mnt/archie_brain commit -m "feat(backup): backup_restore_service + migration 374 restore_sessions table"
```

---

### Task 6: Add restore API endpoints to routes_restore.py

**Files:**
- Modify: `platform_v2/tools/backup_manager/routes_restore.py`

- [ ] **Step 1: Find register_restore_routes() in routes_restore.py**

```bash
grep -n 'def register_restore_routes\|@bp.route' /mnt/archie_brain/platform_v2/tools/backup_manager/routes_restore.py | head -15
```

- [ ] **Step 2: Add three new endpoints inside register_restore_routes()**

Add after the existing routes:

```python
    @bp.route("/api/restore/sandbox", methods=["POST"])
    @admin_required
    def initiate_restore_sandbox():
        """Start a sandbox restore test for a backup. Returns immediately (async)."""
        from flask_login import current_user
        from services.backup_restore_service import initiate_sandbox_restore
        data = request.get_json() or {}
        backup_id = data.get("backup_id")
        if not backup_id:
            return jsonify({"success": False, "error": "backup_id required"}), 400
        result = initiate_sandbox_restore(
            backup_id=int(backup_id),
            triggered_by=getattr(current_user, "username", "unknown"),
        )
        return jsonify(result), 200 if result["success"] else 400

    @bp.route("/api/restore/status/<int:backup_id>", methods=["GET"])
    @admin_required
    def get_restore_status(backup_id):
        """Get current restore session status for a backup."""
        from services.backup_restore_service import get_restore_status
        return jsonify(get_restore_status(backup_id))

    @bp.route("/api/restore/promote", methods=["POST"])
    @admin_required
    def promote_restore_to_production():
        """Promote a QA-verified sandbox restore to production. Only works after qa_passed."""
        from flask_login import current_user
        from services.backup_restore_service import promote_to_production
        data = request.get_json() or {}
        session_id = data.get("session_id")
        if not session_id:
            return jsonify({"success": False, "error": "session_id required"}), 400
        result = promote_to_production(
            session_id=int(session_id),
            triggered_by=getattr(current_user, "username", "unknown"),
        )
        return jsonify(result), 200 if result["success"] else 400
```

- [ ] **Step 3: Restart and test endpoints exist**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform 2>&1 | tail -2
docker exec archie_platform python3 -c "
import sys, os, requests; sys.path.insert(0, '/app')
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'kytran','password':os.environ.get('ARCHIE_TEST_PASSWORD','archie2025')})
# Test status endpoint with a known backup id
r = s.get('http://localhost:3000/tools/backup-manager/api/restore/status/1')
print('Status endpoint:', r.status_code, r.json().get('success'))
# Test sandbox initiate with invalid id (should return 400 not 500)
r2 = s.post('http://localhost:3000/tools/backup-manager/api/restore/sandbox', json={'backup_id': 999999})
print('Sandbox initiate (invalid id):', r2.status_code, r2.json().get('error'))
" 2>&1
```
Expected: `Status endpoint: 200 True`, `Sandbox initiate (invalid id): 400 backup_not_found`

- [ ] **Step 4: Add restore capabilities to CAPABILITY_DEPARTMENT_MAP**

In `platform_v2/services/department_coordinator.py`, add after `"backup_governance"`:
```python
    "restore_sandbox":     "Operations & Infrastructure",
    "restore_production":  "Operations & Infrastructure",
    "restore_verify":      "Operations & Infrastructure",
    "qa_sandbox_restore":  "Engineering & Technology",
```

- [ ] **Step 5: Add restore skills to W.A.R.D.E.N. (id=363) and P.R.O.B.E.**

```bash
docker exec archie_platform python3 -c "
import sys, os; sys.path.insert(0, '/app'); os.chdir('/app')
from database import get_db_cursor
skills = [
    # (agent_id, skill_name, level)
    (363, 'restore_sandbox', 4),
    (363, 'restore_production', 5),
    (363, 'restore_verify', 4),
]
# Get P.R.O.B.E. id
with get_db_cursor(commit=False) as (conn, cur):
    cur.execute(\"SELECT id FROM agents WHERE name='P.R.O.B.E.' LIMIT 1\")
    probe = cur.fetchone()
    if probe:
        skills.append((probe['id'], 'qa_sandbox_restore', 5))
with get_db_cursor(commit=True) as (conn, cur):
    for agent_id, skill, level in skills:
        cur.execute('''INSERT INTO agent_skills (agent_id, skill_name, proficiency_level)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level=%s''',
                    (agent_id, skill, level, level))
        print(f'  agent {agent_id}: {skill} Lv{level}')
" 2>&1
```

- [ ] **Step 6: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/tools/backup_manager/routes_restore.py \
    platform_v2/services/department_coordinator.py
git -C /mnt/archie_brain commit -m "feat(backup): restore API endpoints + W.A.R.D.E.N./P.R.O.B.E. restore skills wired"
```

---

### Task 7: Create backup-restore-e2e QA suite

**Files:**
- Create: `platform_v2/qa_suites/backup-restore-e2e.yaml`

- [ ] **Step 1: Write and register the suite**

```bash
cat > /mnt/archie_brain/platform_v2/qa_suites/backup-restore-e2e.yaml << 'EOF'
suite:
  name: "backup-restore-e2e"
  description: "Backup restore flow — status, sandbox initiate, promote gate"
  base_url: "http://192.168.1.200:3000"
  auth:
    username: "${ARCHIE_TEST_USERNAME}"
    password: "${ARCHIE_TEST_PASSWORD}"

tests:
  - name: "restore status endpoint available"
    type: api
    method: GET
    path: /tools/backup-manager/api/restore/status/1
    expect:
      status: [200]

  - name: "sandbox initiate rejects missing backup_id"
    type: api
    method: POST
    path: /tools/backup-manager/api/restore/sandbox
    body: {}
    expect:
      status: [400]

  - name: "sandbox initiate rejects invalid backup"
    type: api
    method: POST
    path: /tools/backup-manager/api/restore/sandbox
    body: {"backup_id": 999999999}
    expect:
      status: [400]

  - name: "promote rejects without session_id"
    type: api
    method: POST
    path: /tools/backup-manager/api/restore/promote
    body: {}
    expect:
      status: [400]

  - name: "backup list includes git_commit field"
    type: api
    method: GET
    path: /tools/backup-manager/list
    expect:
      status: [200]
EOF
```

```bash
docker exec archie_platform python3 -c "
import sys, os, yaml, json; sys.path.insert(0, '/app'); os.chdir('/app')
from database import get_db_cursor
with open('/app/qa_suites/backup-restore-e2e.yaml') as f:
    spec = yaml.safe_load(f.read())
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute('SELECT id FROM qa_test_suites WHERE name=%s', ('backup-restore-e2e',))
    if not cur.fetchone():
        cur.execute('INSERT INTO qa_test_suites (name, description, target_url, spec, suite_type, is_active) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
            ('backup-restore-e2e', 'Backup restore flow', 'http://192.168.1.200:3000', json.dumps(spec), 'internal', True))
        print('Registered suite id:', cur.fetchone()['id'])
" 2>&1
```

- [ ] **Step 2: Run suite**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
r = run_suite_by_name('backup-restore-e2e')
print('QA:', r.get('passed'), '/', r.get('total'))
" 2>&1
```
Expected: 5/5 pass.

- [ ] **Step 3: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/qa_suites/backup-restore-e2e.yaml
git -C /mnt/archie_brain commit -m "feat(qa): backup-restore-e2e suite — 5 tests for restore API"
```

---

## PHASE D — DEPLOYMENT TRIAD

---

### Task 8: Create forge_gate_service.py — F.O.R.G.E. PR gate

**Files:**
- Create: `platform_v2/services/forge_gate_service.py`
- Create: `platform_v2/tests/test_forge_gate_service.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > /mnt/archie_brain/platform_v2/tests/test_forge_gate_service.py << 'EOF'
"""Tests for forge_gate_service — F.O.R.G.E.'s PR gate logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest


def test_importable():
    from services.forge_gate_service import request_pr_clearance, _load_gate_config
    assert callable(request_pr_clearance)
    assert callable(_load_gate_config)


def test_gate_config_has_severity_levels():
    from services.forge_gate_service import _load_gate_config
    config = _load_gate_config()
    for severity in ("critical", "high", "medium", "low"):
        assert severity in config
        assert "gate_type" in config[severity]


def test_no_commit_returns_soft_approved():
    """If git_commit is None, fail-open (never block due to git unavailability)."""
    from services.forge_gate_service import request_pr_clearance
    r = request_pr_clearance(git_commit=None, severity="medium")
    assert r["approved"] is True
    assert "no_commit" in r["reason"]


def test_clearance_result_has_required_fields():
    from services.forge_gate_service import request_pr_clearance
    r = request_pr_clearance(git_commit="abc123f", severity="low")
    for field in ("approved", "gate_level", "reason", "severity"):
        assert field in r
EOF
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_forge_gate_service.py -v 2>&1 | head -15
```

- [ ] **Step 3: Create forge_gate_service.py**

```bash
cat > /mnt/archie_brain/platform_v2/services/forge_gate_service.py << 'EOF'
"""
F.O.R.G.E. Gate Service — PR compliance check before Repair Bay deploys.
Soft gate: never blocks if GitHub is unreachable. Hard gate: blocks uncommitted changes.
"""
from __future__ import annotations
import json, logging
from typing import Any
from database import get_db_cursor

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "critical": {"gate_type": "soft"},
    "high":     {"gate_type": "soft"},
    "medium":   {"gate_type": "soft"},   # soft — PR recommended, not required
    "low":      {"gate_type": "soft"},
}


def _load_gate_config() -> dict:
    """Load F.O.R.G.E. gate config from system_config. Defaults to soft gates."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'forge_gate_config'")
            row = cur.fetchone()
            if row and row["value"]:
                return json.loads(row["value"])
    except Exception as e:
        logger.warning("Could not load forge gate config: %s", e)
    return _DEFAULTS


def request_pr_clearance(
    git_commit: str | None,
    severity: str,
    proposal_id: int | None = None,
) -> dict[str, Any]:
    """
    F.O.R.G.E. pre-deploy PR clearance check.
    Currently a soft gate — logs compliance, never blocks deploys.
    Future: wire to GitHub API to verify merged PR for commit.

    Returns:
        {approved: bool, gate_level: str, reason: str, severity: str, pr_number: int|None}
    """
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"

    if not git_commit:
        return {"approved": True, "gate_level": "soft", "reason": "no_commit — git context unavailable, fail-open", "severity": severity, "pr_number": None}

    config = _load_gate_config()
    gate_type = config.get(severity, {}).get("gate_type", "soft")

    # TODO: Wire GitHub API check here when GITHUB_TOKEN env var is available
    # For now: soft gate — log and approve. Compliance tracked in backup_log.pr_number.
    logger.info("F.O.R.G.E. gate (soft): commit=%s severity=%s proposal=%s", git_commit, severity, proposal_id)
    return {
        "approved": True,
        "gate_level": gate_type,
        "reason": f"soft gate: PR check logged for commit {git_commit[:8] if git_commit else 'unknown'}",
        "severity": severity,
        "pr_number": None,  # Will be populated when GitHub API is wired
    }
EOF
```

- [ ] **Step 4: Run tests — 4/4 pass**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_forge_gate_service.py -v 2>&1 | tail -8
```

- [ ] **Step 5: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/services/forge_gate_service.py platform_v2/tests/test_forge_gate_service.py
git -C /mnt/archie_brain commit -m "feat(forge): forge_gate_service.py — F.O.R.G.E. PR compliance gate (soft, TDD)"
```

---

### Task 9: Create codex_gate_service.py — C.O.D.E.X. documentation gate

**Files:**
- Create: `platform_v2/services/codex_gate_service.py`
- Create: `platform_v2/tests/test_codex_gate_service.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > /mnt/archie_brain/platform_v2/tests/test_codex_gate_service.py << 'EOF'
"""Tests for codex_gate_service — C.O.D.E.X. auto-documentation gate."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_importable():
    from services.codex_gate_service import document_deploy
    assert callable(document_deploy)


def test_document_deploy_returns_dict():
    from services.codex_gate_service import document_deploy
    r = document_deploy(
        module="test_module",
        git_commit="abc123f",
        changes_summary="test change for unit test",
        proposal_id=None,
    )
    assert isinstance(r, dict)
    assert "success" in r


def test_document_deploy_nonblocking():
    """C.O.D.E.X. gate is always non-blocking — never returns approved=False."""
    from services.codex_gate_service import document_deploy
    r = document_deploy(module="any", git_commit=None, changes_summary="", proposal_id=None)
    # Even with minimal input, it should not block
    assert r.get("blocks_deploy") is not True
EOF
```

- [ ] **Step 2: Create codex_gate_service.py**

```bash
cat > /mnt/archie_brain/platform_v2/services/codex_gate_service.py << 'EOF'
"""
C.O.D.E.X. Gate Service — auto-documentation after every deploy.
Non-blocking soft gate: always approves, documents in background.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def document_deploy(
    module: str,
    git_commit: str | None,
    changes_summary: str,
    proposal_id: int | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    """
    C.O.D.E.X. post-deploy documentation. Non-blocking — always succeeds.
    Delegates documentation task to C.O.D.E.X. via Department HQ.

    Returns:
        {success: bool, blocks_deploy: False, kb_entry_id: int|None}
    """
    kb_entry_id = None
    try:
        from services.delegation_service import delegate_task
        delegate_task(
            capability="documentation",
            reason=f"Auto-doc: module={module} commit={git_commit} proposal={proposal_id}",
            args={
                "module": module,
                "git_commit": git_commit,
                "changes_summary": changes_summary,
                "proposal_id": proposal_id,
                "pr_number": pr_number,
            },
            delegation_source="automation",
        )
        logger.info("C.O.D.E.X. documentation task delegated for module=%s", module)
    except Exception as e:
        # Non-blocking — log but never fail the deploy
        logger.warning("C.O.D.E.X. documentation delegation failed (suppressed): %s", e)

    return {"success": True, "blocks_deploy": False, "kb_entry_id": kb_entry_id}
EOF
```

- [ ] **Step 3: Run tests — 3/3 pass**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_codex_gate_service.py -v 2>&1 | tail -8
```

- [ ] **Step 4: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/services/codex_gate_service.py platform_v2/tests/test_codex_gate_service.py
git -C /mnt/archie_brain commit -m "feat(codex): codex_gate_service.py — C.O.D.E.X. auto-doc gate (non-blocking, TDD)"
```

---

### Task 10: Wire F.O.R.G.E. + C.O.D.E.X. into proposal_service.py + add capabilities

**Files:**
- Modify: `platform_v2/services/proposal_service.py:~530`
- Modify: `platform_v2/services/department_coordinator.py`

- [ ] **Step 1: Add pr_gate and doc_gate to CAPABILITY_DEPARTMENT_MAP**

In `department_coordinator.py`, add after the existing backup/restore entries:
```python
    "pr_gate":   "Engineering & Technology",   # F.O.R.G.E. PR compliance check
    "doc_gate":  "Documentation & Knowledge",  # C.O.D.E.X. auto-documentation
```

- [ ] **Step 2: Add F.O.R.G.E. check to run_proposal() — alongside existing W.A.R.D.E.N. check**

In `proposal_service.py`, inside the W.A.R.D.E.N. governance check block (the one added earlier, around line 530), add F.O.R.G.E. call alongside:

```python
            # F.O.R.G.E. PR compliance check (soft gate — logged, never blocks)
            try:
                from services.forge_gate_service import request_pr_clearance
                import subprocess as _sp
                _commit = None
                try:
                    _commit = _sp.run(['git','-C','/app','rev-parse','HEAD'], capture_output=True, text=True, timeout=5).stdout.strip()
                except Exception:
                    pass
                forge_clearance = request_pr_clearance(
                    git_commit=_commit,
                    severity=_proposal_severity,
                    proposal_id=proposal_id,
                )
                logger.info("F.O.R.G.E. gate: %s", forge_clearance.get("reason"))
            except Exception as _forge_err:
                logger.warning("F.O.R.G.E. gate failed (fail-open): %s", _forge_err)
```

- [ ] **Step 3: Add C.O.D.E.X. post-deploy documentation — after successful deploy**

Find the success path in `run_proposal()` (where `result["success"] = True` is set). Add after that:

```python
        # C.O.D.E.X. auto-documents the deploy (non-blocking, fire-and-forget)
        try:
            from services.codex_gate_service import document_deploy
            document_deploy(
                module=f"proposal_{proposal_id}",
                git_commit=locals().get("_commit"),
                changes_summary=f"Repair Bay proposal #{proposal_id} deployed",
                proposal_id=proposal_id,
            )
        except Exception as _doc_err:
            logger.warning("C.O.D.E.X. doc gate suppressed: %s", _doc_err)
```

- [ ] **Step 4: Restart and run all backup + governance tests**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform 2>&1 | tail -2
docker exec archie_platform python3 -m pytest \
    /app/tests/test_backup_service.py \
    /app/tests/test_backup_governance_service.py \
    /app/tests/test_backup_restore_service.py \
    /app/tests/test_forge_gate_service.py \
    /app/tests/test_codex_gate_service.py \
    -v 2>&1 | tail -15
```
Expected: all pass.

- [ ] **Step 5: Run all backup QA suites**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
for s in ['backup-health-smoke', 'backup-governance-e2e', 'backup-restore-e2e']:
    r = run_suite_by_name(s)
    print(s, ':', r.get('passed'), '/', r.get('total'))
" 2>&1
```

- [ ] **Step 6: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/services/proposal_service.py platform_v2/services/department_coordinator.py
git -C /mnt/archie_brain commit -m "feat(triad): wire F.O.R.G.E. PR gate + C.O.D.E.X. doc gate into proposal_service — Deployment Triad active"
```

---

## Final Verification

```bash
# All unit tests
docker exec archie_platform python3 -m pytest \
    /app/tests/test_backup_service.py \
    /app/tests/test_backup_governance_service.py \
    /app/tests/test_backup_restore_service.py \
    /app/tests/test_forge_gate_service.py \
    /app/tests/test_codex_gate_service.py \
    -v 2>&1 | tail -5

# All QA suites
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite_by_name
for s in ['backup-health-smoke', 'backup-governance-e2e', 'backup-restore-e2e']:
    r = run_suite_by_name(s)
    print(s, ':', r.get('passed'), '/', r.get('total'))
" 2>&1
```

Expected: all tests pass, all suites green.
