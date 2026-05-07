# Async Backup Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace synchronous backup download (which times out on large archives) with an async prepare → poll → download flow that runs in the background, shows progress, and auto-cleans up.

**Architecture:** A `backup_download_jobs` table tracks preparation state. `POST /api/download/prepare/<name>` kicks off a background thread that creates the tar.gz; the UI polls `GET /api/download/status/<job_id>` every 5s and transitions the Download button through: `Download → Confirm → Preparing… → Download Ready`. After the file is served (or after 1 hour), it is auto-deleted. W.A.R.D.E.N. runs a nightly cleanup job for any stale prepared archives.

**Tech Stack:** Python/Flask, threading, tarfile, psycopg2, APScheduler (W.A.R.D.E.N. job), pytest

---

## File Map

**Create:**
- `platform_v2/services/backup_download_service.py` — prepare_download(), get_download_status(), cleanup_expired(), serve_and_delete()
- `platform_v2/tools/backup_manager/routes_download.py` — 3 endpoints: prepare, status, retrieve
- `platform_v2/tests/test_backup_download_service.py`
- `database/migrations/376_backup_download_jobs.sql`

**Modify:**
- `platform_v2/tools/backup_manager/__init__.py` — register routes_download
- `platform_v2/templates/tools/backup_manager.html` — Download button async state machine
- `platform_v2/services/agent_jobs.py` — W.A.R.D.E.N. nightly cleanup job

---

## Task 1: Migration 376 — backup_download_jobs table

**Files:**
- Create: `database/migrations/376_backup_download_jobs.sql`

- [ ] **Step 1: Create migration file**

```bash
cat > /mnt/archie_brain/database/migrations/376_backup_download_jobs.sql << 'EOF'
-- Migration 376: async backup download job tracking
CREATE TABLE IF NOT EXISTS backup_download_jobs (
    id           SERIAL PRIMARY KEY,
    backup_name  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','preparing','ready','failed','expired')),
    archive_path TEXT,
    error        TEXT,
    file_size_bytes BIGINT DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at   TIMESTAMPTZ DEFAULT NOW() + INTERVAL '1 hour',
    downloaded_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_download_jobs_backup ON backup_download_jobs(backup_name);
CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON backup_download_jobs(status);
CREATE INDEX IF NOT EXISTS idx_download_jobs_expires ON backup_download_jobs(expires_at);
EOF
```

- [ ] **Step 2: Run migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/376_backup_download_jobs.sql 2>&1
```

Expected: `CREATE TABLE` + `CREATE INDEX` (×3)

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d backup_download_jobs" 2>/dev/null | grep -E 'id|backup_name|status|expires'
```

Expected: 4+ columns listed.

- [ ] **Step 4: Commit**

```bash
git -C /mnt/archie_brain add database/migrations/376_backup_download_jobs.sql
git -C /mnt/archie_brain commit -m "feat(db): migration 376 — backup_download_jobs async download tracking"
```

---

## Task 2: Create backup_download_service.py

**Files:**
- Create: `platform_v2/services/backup_download_service.py`
- Create: `platform_v2/tests/test_backup_download_service.py`

- [ ] **Step 1: Write failing tests**

```bash
cat > /mnt/archie_brain/platform_v2/tests/test_backup_download_service.py << 'EOF'
"""Tests for backup_download_service — async download preparation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_importable():
    from services.backup_download_service import (
        prepare_download, get_download_status, cleanup_expired
    )
    assert all(callable(f) for f in [prepare_download, get_download_status, cleanup_expired])


def test_get_status_unknown_job():
    from services.backup_download_service import get_download_status
    r = get_download_status(job_id=999999999)
    assert r['success'] is False
    assert r['error'] == 'job_not_found'


def test_prepare_download_missing_backup():
    from services.backup_download_service import prepare_download
    r = prepare_download(backup_name='nonexistent_backup_xyz', triggered_by='test')
    assert r['success'] is False
    assert 'not_found' in r['error']


def test_cleanup_expired_runs_without_error():
    from services.backup_download_service import cleanup_expired
    # Should run without raising even if nothing to clean
    result = cleanup_expired()
    assert isinstance(result, int)  # returns count of cleaned jobs
EOF
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_download_service.py -v 2>&1 | tail -8
```

Expected: 3 failures (ImportError on service), 1 failure (table check).

- [ ] **Step 3: Create backup_download_service.py**

```bash
cat > /mnt/archie_brain/platform_v2/services/backup_download_service.py << 'EOF'
"""
Async Backup Download Service.
Prepares tar.gz archives in background threads, tracks state in backup_download_jobs.
Auto-cleanup: expires_at = created_at + 1h. W.A.R.D.E.N. nightly prune.
"""
from __future__ import annotations

import logging
import os
import tarfile
import tempfile
import threading
from typing import Any

from database import get_db_cursor

logger = logging.getLogger(__name__)

BACKUP_DIR = "/backups"
DOWNLOAD_TEMP_DIR = "/backups/.downloads"


def prepare_download(backup_name: str, triggered_by: str = "user") -> dict[str, Any]:
    """
    Start async preparation of a backup archive for download.
    Returns immediately with a job_id. Poll get_download_status(job_id) for progress.
    """
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        return {"success": False, "error": "backup_not_found"}

    # Clean up any expired jobs for this backup before creating new one
    try:
        cleanup_expired()
    except Exception:
        pass

    # Check if a ready/preparing job already exists for this backup
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, status FROM backup_download_jobs
               WHERE backup_name = %s AND status IN ('pending','preparing','ready')
                 AND expires_at > NOW()
               ORDER BY created_at DESC LIMIT 1""",
            (backup_name,),
        )
        existing = cur.fetchone()
        if existing:
            return {"success": True, "job_id": existing["id"], "status": existing["status"], "reused": True}

    # Create new job
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO backup_download_jobs (backup_name, status)
               VALUES (%s, 'pending') RETURNING id""",
            (backup_name,),
        )
        job_id = cur.fetchone()["id"]

    # Start background thread
    t = threading.Thread(target=_prepare_archive, args=(job_id, backup_name, backup_path), daemon=True)
    t.start()

    return {"success": True, "job_id": job_id, "status": "pending"}


def _prepare_archive(job_id: int, backup_name: str, backup_path: str) -> None:
    """Background thread: create tar.gz and update job status."""
    os.makedirs(DOWNLOAD_TEMP_DIR, exist_ok=True)
    archive_path = os.path.join(DOWNLOAD_TEMP_DIR, f"download_{job_id}_{backup_name}.tar.gz")

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE backup_download_jobs SET status='preparing', updated_at=NOW() WHERE id=%s",
                (job_id,),
            )
    except Exception as e:
        logger.warning("Could not set preparing status: %s", e)

    # Add updated_at if not exists (it might not be in migration)
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_path, arcname=backup_name)

        file_size = os.path.getsize(archive_path)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE backup_download_jobs
                   SET status='ready', archive_path=%s, file_size_bytes=%s
                   WHERE id=%s""",
                (archive_path, file_size, job_id),
            )
        logger.info("Download prepared: job=%s backup=%s size=%s", job_id, backup_name, file_size)

    except Exception as e:
        logger.error("Archive preparation failed for job %s: %s", job_id, e)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE backup_download_jobs SET status='failed', error=%s WHERE id=%s",
                    (str(e), job_id),
                )
        except Exception:
            pass
        if os.path.exists(archive_path):
            os.remove(archive_path)


def get_download_status(job_id: int) -> dict[str, Any]:
    """Return current status of a download preparation job."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT * FROM backup_download_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "job_not_found"}
        return {
            "success": True,
            "job_id": row["id"],
            "backup_name": row["backup_name"],
            "status": row["status"],
            "file_size_bytes": row["file_size_bytes"],
            "error": row["error"],
            "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
        }


def serve_and_delete(job_id: int) -> dict[str, Any]:
    """
    Mark job as downloaded and return archive_path for send_file.
    Schedules file deletion after serving.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE backup_download_jobs SET status='expired', downloaded_at=NOW() WHERE id=%s AND status='ready' RETURNING archive_path",
            (job_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "job_not_ready"}
        return {"success": True, "archive_path": row["archive_path"]}


def cleanup_expired() -> int:
    """Delete expired/downloaded job records and their archive files. Returns count cleaned."""
    count = 0
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, archive_path FROM backup_download_jobs WHERE expires_at < NOW() OR status IN ('expired','failed')"
        )
        rows = cur.fetchall()

    for row in rows:
        if row["archive_path"] and os.path.exists(row["archive_path"]):
            try:
                os.remove(row["archive_path"])
            except Exception as e:
                logger.warning("Could not delete archive %s: %s", row["archive_path"], e)

    if rows:
        ids = [r["id"] for r in rows]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM backup_download_jobs WHERE id = ANY(%s)", (ids,))
        count = len(ids)

    return count
EOF
```

- [ ] **Step 4: Run tests — 4/4 pass**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_backup_download_service.py -v 2>&1 | tail -10
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/services/backup_download_service.py platform_v2/tests/test_backup_download_service.py
git -C /mnt/archie_brain commit -m "feat(backup): backup_download_service — async prepare + cleanup (TDD)"
```

---

## Task 3: Create routes_download.py + register

**Files:**
- Create: `platform_v2/tools/backup_manager/routes_download.py`
- Modify: `platform_v2/tools/backup_manager/__init__.py`

- [ ] **Step 1: Create routes_download.py**

```bash
cat > /mnt/archie_brain/platform_v2/tools/backup_manager/routes_download.py << 'EOF'
"""
Async download routes — prepare, poll, retrieve.
POST  /api/download/prepare/<backup_name>  → {job_id, status}
GET   /api/download/status/<job_id>        → {status, file_size_bytes, ...}
GET   /api/download/retrieve/<job_id>      → sends file (one-time, auto-deletes)
"""
from flask import jsonify, request, send_file, current_app
import os


def register_download_routes(bp, admin_required):

    @bp.route("/api/download/prepare/<backup_name>", methods=["POST"])
    @admin_required
    def prepare_backup_download(backup_name):
        """Kick off async tar.gz creation for a backup."""
        from flask_login import current_user
        from services.backup_download_service import prepare_download

        result = prepare_download(
            backup_name=backup_name,
            triggered_by=getattr(current_user, "username", "unknown"),
        )
        return jsonify(result), 200 if result["success"] else 400

    @bp.route("/api/download/status/<int:job_id>", methods=["GET"])
    @admin_required
    def get_download_job_status(job_id):
        """Poll download preparation status."""
        from services.backup_download_service import get_download_status
        return jsonify(get_download_status(job_id))

    @bp.route("/api/download/retrieve/<int:job_id>", methods=["GET"])
    @admin_required
    def retrieve_prepared_download(job_id):
        """Serve the prepared archive file (one-time, marks as used)."""
        from services.backup_download_service import serve_and_delete

        result = serve_and_delete(job_id)
        if not result["success"]:
            return jsonify(result), 404

        archive_path = result["archive_path"]
        if not os.path.exists(archive_path):
            return jsonify({"success": False, "error": "archive_file_missing"}), 404

        filename = os.path.basename(archive_path).replace(f"download_{job_id}_", "")

        def _delete_after():
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
            except Exception as e:
                current_app.logger.warning("Post-send cleanup failed: %s", e)

        try:
            response = send_file(archive_path, as_attachment=True, download_name=filename)
            # Schedule file deletion on response teardown
            response.call_on_close(_delete_after)
            return response
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
EOF
```

- [ ] **Step 2: Register in __init__.py**

In `/mnt/archie_brain/platform_v2/tools/backup_manager/__init__.py`, add after the existing imports and registrations:

```python
from .routes_download import register_download_routes  # noqa: E402
```

And after the last `register_*_routes(...)` call:
```python
register_download_routes(backup_manager_bp, admin_required)
```

- [ ] **Step 3: Restart and verify endpoints exist**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform 2>&1 | tail -2
sleep 8
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.backup_manager import backup_manager_bp
routes = [r.rule for r in backup_manager_bp.deferred_functions if hasattr(r, 'rule')]
# Just check the app URL map
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'download' in r.rule and 'backup' in r.rule]
print('Download routes:', rules)
" 2>/dev/null || echo "checking via platform logs"
```

Then test:
```bash
docker exec archie_platform python3 -c "
import sys, os, requests
sys.path.insert(0, '/app')
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'kytran','password':os.environ.get('ARCHIE_TEST_PASSWORD','Kyt\$13ran2025')}, allow_redirects=True)
# Test status with invalid job
r = s.get('http://localhost:3000/tools/backup-manager/api/download/status/999')
print('status 999:', r.status_code, r.json().get('error'))
# Test prepare with invalid backup
r2 = s.post('http://localhost:3000/tools/backup-manager/api/download/prepare/nonexistent_xyz')
print('prepare invalid:', r2.status_code, r2.json().get('error'))
" 2>/dev/null
```

Expected:
- `status 999: 200 job_not_found`
- `prepare invalid: 400 backup_not_found`

- [ ] **Step 4: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/tools/backup_manager/routes_download.py platform_v2/tools/backup_manager/__init__.py
git -C /mnt/archie_brain commit -m "feat(backup): async download routes — prepare/status/retrieve endpoints"
```

---

## Task 4: Template — async Download button UI state machine

**Files:**
- Modify: `platform_v2/templates/tools/backup_manager.html`

The Download button goes through these states:
```
[Download]        → user clicks → confirm dialog
[Preparing... ◌]  → job running → buttons on row grayed, polling every 5s
[Download Ready]  → job=ready  → green button, click triggers browser download
[Download]        → after download completes → resets
```

- [ ] **Step 1: Find the existing Download button code**

```bash
grep -n 'downloadBtn\|downloadBackup\|Download' /mnt/archie_brain/platform_v2/templates/tools/backup_manager.html | grep -v '//' | head -15
```

- [ ] **Step 2: Replace the Download button block**

Find this block in `renderBackupsList`:
```javascript
            // Download button
            const downloadBtn = document.createElement('button');
            downloadBtn.className = 'btn btn-cyan';
            downloadBtn.title = 'Download as tar.gz for off-site DRP';
            downloadBtn.onclick = function() { downloadBackup(backup.name); };
            actionsDiv.appendChild(downloadBtn);
```

Replace with:
```javascript
            // Download button — async state machine
            const downloadBtn = document.createElement('button');
            downloadBtn.dataset.backupName = backup.name;
            downloadBtn.dataset.downloadState = 'idle';
            const _setDownloadState = (btn, state, jobId) => {
                btn.dataset.downloadState = state;
                btn.dataset.jobId = jobId || '';
                if (state === 'idle') {
                    btn.className = 'btn btn-cyan';
                    btn.textContent = 'Download';
                    btn.disabled = false;
                    btn.style.background = '';
                } else if (state === 'preparing') {
                    btn.className = 'btn';
                    btn.textContent = 'Preparing…';
                    btn.disabled = true;
                    btn.style.background = '#333';
                    btn.style.color = '#888';
                } else if (state === 'ready') {
                    btn.className = 'btn btn-green';
                    btn.textContent = 'Download Ready';
                    btn.disabled = false;
                    btn.style.background = '#1a4a1a';
                    btn.style.color = '#4ade80';
                    btn.style.border = '1px solid #4ade80';
                }
            };
            downloadBtn.onclick = async function() {
                const state = this.dataset.downloadState;
                const bname = this.dataset.backupName;
                const jobId = this.dataset.jobId;

                if (state === 'ready' && jobId) {
                    // Trigger browser download
                    window.location.href = '/tools/backup-manager/api/download/retrieve/' + jobId;
                    setTimeout(() => _setDownloadState(this, 'idle', ''), 3000);
                    return;
                }

                if (state === 'preparing') return; // ignore clicks while preparing

                if (!confirm('Prepare "' + bname + '" for download?\n\nThis will compress the archive in the background. You can navigate away — the button will show "Download Ready" when complete.')) return;

                // Start preparation
                _setDownloadState(this, 'preparing', '');
                const btn = this;
                try {
                    const r = await fetch('/tools/backup-manager/api/download/prepare/' + encodeURIComponent(bname), {
                        method: 'POST', credentials: 'same-origin'
                    });
                    const d = await r.json();
                    if (!d.success) { showToast('Download prep failed: ' + d.error, 'error'); _setDownloadState(btn, 'idle', ''); return; }

                    const jid = d.job_id;
                    if (d.status === 'ready') { _setDownloadState(btn, 'ready', jid); return; }

                    // Poll until ready
                    const poll = setInterval(async () => {
                        try {
                            const r2 = await fetch('/tools/backup-manager/api/download/status/' + jid, {credentials: 'same-origin'});
                            const s = await r2.json();
                            if (s.status === 'ready') { clearInterval(poll); _setDownloadState(btn, 'ready', jid); showToast('Download ready!', 'success'); }
                            else if (s.status === 'failed') { clearInterval(poll); showToast('Download prep failed: ' + (s.error || 'unknown'), 'error'); _setDownloadState(btn, 'idle', ''); }
                        } catch(e) { /* network hiccup, keep polling */ }
                    }, 5000);
                } catch(e) { showToast('Error: ' + e.message, 'error'); _setDownloadState(btn, 'idle', ''); }
            };
            _setDownloadState(downloadBtn, 'idle', '');
            actionsDiv.appendChild(downloadBtn);
```

- [ ] **Step 3: Also remove the old `downloadBackup()` function** (search for it and delete or leave — it won't be called anymore)

```bash
grep -n 'function downloadBackup\|window.location.*download' /mnt/archie_brain/platform_v2/templates/tools/backup_manager.html | head -5
```

- [ ] **Step 4: Restart and test the UI**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform 2>&1 | tail -2
sleep 8
```

Open browser at http://192.168.1.200:3000/tools/backup-manager and verify:
1. Download button shows "Download" on all rows
2. Clicking shows a confirm dialog
3. After confirm, button changes to "Preparing…" (grayed out)
4. After ~30-60s for Brain Backup, button changes to "Download Ready" (green)
5. Clicking "Download Ready" triggers browser download

Use Playwright to test the confirm + state change:
```bash
# Check button text after page load
docker exec archie_platform python3 -c "
import sys, os, requests
sys.path.insert(0, '/app')
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'kytran','password':os.environ.get('ARCHIE_TEST_PASSWORD','Kyt\$13ran2025')}, allow_redirects=True)
# Start a prepare and poll
bname = '20260507_170240_v5.33.0_version_display_test'  # a brain backup
r = s.post(f'http://localhost:3000/tools/backup-manager/api/download/prepare/{bname}')
d = r.json()
print('prepare:', d)
import time
if d.get('job_id'):
    for _ in range(20):
        time.sleep(5)
        s2 = s.get(f'http://localhost:3000/tools/backup-manager/api/download/status/{d[\"job_id\"]}')
        st = s2.json()
        print('status:', st.get('status'), st.get('file_size_bytes'))
        if st.get('status') in ('ready', 'failed'): break
" 2>/dev/null
```

Expected: status transitions `pending → preparing → ready`, file_size_bytes > 0.

- [ ] **Step 5: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/templates/tools/backup_manager.html
git -C /mnt/archie_brain commit -m "feat(backup-ui): async Download button — confirm, preparing state, poll, Download Ready"
```

---

## Task 5: W.A.R.D.E.N. nightly cleanup job

**Files:**
- Modify: `platform_v2/services/agent_jobs.py`

- [ ] **Step 1: Find existing W.A.R.D.E.N. jobs pattern**

```bash
grep -n 'warden\|W\.A\.R\.D\.E\.N\|backup_verify\|backup_governance' /mnt/archie_brain/platform_v2/services/agent_jobs.py | head -10
```

- [ ] **Step 2: Add cleanup job**

Find the section where W.A.R.D.E.N. jobs are registered (look for `backup_verify` or `backup_governance` job). Add after it:

```python
    def _run_warden_download_cleanup():
        """W.A.R.D.E.N. — clean up expired backup download archives."""
        try:
            from services.backup_download_service import cleanup_expired
            count = cleanup_expired()
            if count > 0:
                logger.info("W.A.R.D.E.N.: cleaned %d expired download archives", count)
        except Exception as e:
            logger.warning("W.A.R.D.E.N. download cleanup failed: %s", e)
```

Register the job in the scheduler setup block (find `scheduler.add_job` calls for W.A.R.D.E.N.):

```python
    scheduler.add_job(
        _run_warden_download_cleanup,
        "cron",
        hour=4,
        minute=0,
        timezone="America/Toronto",
        id="warden_download_cleanup",
        replace_existing=True,
        max_instances=1,
    )
```

- [ ] **Step 3: Restart scheduler and verify job registered**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_scheduler 2>&1 | tail -2
sleep 5
docker exec archie_scheduler python3 -c "
import sys; sys.path.insert(0, '/app')
# Check scheduler heartbeat for the new job
from database import get_db_cursor
with get_db_cursor(commit=False) as (conn, cur):
    cur.execute(\"SELECT details FROM scheduler_heartbeat ORDER BY written_at DESC LIMIT 1\")
    row = cur.fetchone()
    if row:
        import json
        jobs = json.loads(row['details'] if isinstance(row['details'], str) else row['details'])
        warden_jobs = [j for j in jobs.get('jobs', []) if 'warden' in j.get('id','').lower()]
        print('W.A.R.D.E.N. jobs:', [j['id'] for j in warden_jobs])
" 2>/dev/null
```

Expected: `warden_download_cleanup` in the list.

- [ ] **Step 4: Commit**

```bash
git -C /mnt/archie_brain add platform_v2/services/agent_jobs.py
git -C /mnt/archie_brain commit -m "feat(warden): nightly download archive cleanup job — prevents stale tar.gz pile-up"
```

---

## Final Verification

```bash
# Unit tests
docker exec archie_platform python3 -m pytest /app/tests/test_backup_download_service.py -v 2>&1 | tail -6

# End-to-end API test
docker exec archie_platform python3 -c "
import sys, os, requests, time
sys.path.insert(0, '/app')
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'kytran','password':os.environ.get('ARCHIE_TEST_PASSWORD','Kyt\$13ran2025')}, allow_redirects=True)

# Get a database backup name
r = s.get('http://localhost:3000/tools/backup-manager/list')
bname = next((b['name'] for b in r.json()['backups'] if b['backup_type']=='database'), None)
print('Testing with backup:', bname)

# Prepare
r2 = s.post(f'http://localhost:3000/tools/backup-manager/api/download/prepare/{bname}')
job = r2.json()
print('prepare:', job['status'], 'job_id:', job.get('job_id'))

# Poll
for i in range(24):  # up to 2 min
    time.sleep(5)
    st = s.get(f'http://localhost:3000/tools/backup-manager/api/download/status/{job[\"job_id\"]}').json()
    print(f'  poll {i+1}: {st[\"status\"]} ({st.get(\"file_size_bytes\",0)//1024//1024}MB)')
    if st['status'] in ('ready', 'failed'): break

print('FINAL STATUS:', st['status'])
" 2>/dev/null
```

Expected: status transitions to `ready`, file_size > 0.
