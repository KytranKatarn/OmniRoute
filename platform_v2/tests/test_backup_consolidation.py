"""Tests for backup DB/filesystem drift fixes.

Task 1: cleanup_old_backups syncs backup_log rows on delete.
         Orphan cleanup endpoint removes DB-only rows.

backup_log schema (relevant columns):
  id, backup_type, file_path, size_bytes, status, created_at, component, tier
"""

import os
import sys
import tempfile

import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _login_as_admin(client, user_id=62):
    """Set Flask-Login session for an admin user (probe account, id=62)."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_cleanup_removes_db_row_when_dir_deleted(app):
    """cleanup_old_backups should delete backup_log row when it deletes the dir."""
    with app.app_context():
        from tools.backup_manager._shared import cleanup_old_backups, get_backup_db_cursor

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_name = "20260101_060000_test_old"
            backup_path = os.path.join(tmpdir, backup_name)
            os.makedirs(backup_path)

            # Insert a backup_log row linked to this path
            with get_backup_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO backup_log (backup_type, file_path, size_bytes, status, created_at) "
                    "VALUES ('full', %s, 1024, 'completed', NOW() - INTERVAL '30 days') RETURNING id",
                    (backup_path,),
                )
                row_id = cur.fetchone()[0]

            # Patch BACKUP_DIR and retention so cleanup targets our test backup
            fake_retention = {
                "delete": [backup_name],
                "keep": [],
                "stats": {"delete_size_mb": 0},
            }
            with patch("tools.backup_manager._shared.BACKUP_DIR", tmpdir), patch(
                "tools.backup_manager._shared.get_backup_retention_status",
                return_value=fake_retention,
            ):
                cleanup_old_backups(dry_run=False)

            # The backup_log row should be gone
            with get_backup_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT id FROM backup_log WHERE id = %s", (row_id,))
                assert cur.fetchone() is None, "backup_log row should have been deleted"

            assert not os.path.exists(backup_path), "directory should have been removed from disk"


def test_cleanup_orphan_log_entries_removes_db_only_rows(client, app):
    """POST /api/cleanup-orphan-log-entries removes rows with no matching dir."""
    with app.app_context():
        from tools.backup_manager._shared import get_backup_db_cursor

        # Insert a backup_log row whose file_path does NOT exist on disk
        orphan_path = "/backups/20250101_000000_orphan_test_nonexistent"
        with get_backup_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO backup_log (backup_type, file_path, size_bytes, status, created_at) "
                "VALUES ('full', %s, 0, 'completed', NOW() - INTERVAL '60 days') RETURNING id",
                (orphan_path,),
            )
            orphan_id = cur.fetchone()[0]

    _login_as_admin(client)
    resp = client.post("/tools/backup-manager/api/cleanup-orphan-log-entries")
    data = resp.get_json()

    # Endpoint must exist and succeed
    assert resp.status_code == 200
    assert data["success"] is True
    assert "removed_count" in data

    # Our orphan row should have been removed
    with app.app_context():
        from tools.backup_manager._shared import get_backup_db_cursor

        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT id FROM backup_log WHERE id = %s", (orphan_id,))
            assert cur.fetchone() is None, "orphan backup_log row should have been deleted"


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

    with patch("tools.backup_manager._shared.BACKUP_DIR", str(tmp_path)):
        from tools.backup_manager._shared import get_backup_retention_status

        status = get_backup_retention_status()

    total = status["stats"]["total_backups"]
    all_names = status["keep"] + status["delete"]
    assert total == 3, f"Expected 3 platform backups, got {total}"
    assert not any("Daily_Triage" in n for n in all_names), "Daily_Triage should be excluded from GFS"


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

        with patch("tools.backup_manager._shared.create_backup_programmatic") as mock_backup:
            mock_backup.return_value = {
                "success": True,
                "backup_name": "20260507_120000_pre_deploy",
                "backup_path": "/backups/20260507_120000_pre_deploy",
                "backup": {},
            }
            from services.proposal_service import deploy_to_production

            deploy_to_production(proposal_id)

        with db_conn.cursor() as cur:
            cur.execute("SELECT backup_name FROM improvement_deployments WHERE proposal_id = %s", (proposal_id,))
            row = cur.fetchone()
        assert row is not None, "improvement_deployments row should have been created"
        assert row[0] == "20260507_120000_pre_deploy"


def test_retention_status_reports_the_canonical_engine_not_a_synthetic_triple(client):
    """RETIRED SHAPE PINNED (#5141). This used to assert `retention_daily == 3` after
    seeding system_config — i.e. it asserted the very thing the endpoint was changed to
    stop reporting.

    routes_operations.py calls the old synthesised "7 daily + 4 weekly + 6 monthly" answer
    FICTION in as many words: nothing enforced those numbers. Retention is per-(component,
    tier) in scripts/backup/retention_prune.py, run nightly. The endpoint now reports what
    is real — the engine, the schedule, and the last canonical prune.

    Asserting the ABSENCE of retention_daily is the anti-regression: restoring that key
    would mean restoring a number no pruner reads.
    """
    _login_as_admin(client)
    resp = client.get("/tools/backup-manager/retention-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["managed"] == "automatic"
    assert "retention_prune.py" in data["engine"]
    assert "retention_daily" not in data, "the synthetic global triple is back — nothing enforces it (#5141)"


def test_put_retention_policy_is_retired_and_refuses_honestly(client):
    """RETIRED (#5141). This asserted 200 + success — the behaviour that was removed
    BECAUSE it was a silent no-op: the canonical engine never read the system_config keys
    this endpoint wrote, so "saving" reported success and changed nothing.

    410 + retired:True is the fix, not a regression. Pinning it stops the no-op returning.
    """
    _login_as_admin(client)
    resp = client.put(
        "/tools/backup-manager/retention-policy",
        json={"daily": 10, "weekly": 5, "monthly": 8},
        content_type="application/json",
    )
    assert resp.status_code == 410, "a retired endpoint must refuse, not pretend to save"
    body = resp.get_json()
    assert body["retired"] is True
    assert body["success"] is False


def test_create_deployment_package_returns_job_id(client):
    """POST /api/create-deployment-package should return job_id immediately."""
    import time

    _login_as_admin(client)
    start = time.time()
    resp = client.post(
        "/tools/backup-manager/api/create-deployment-package",
        json={"version_tag": "v5.33.0", "description": "test", "target_platform": "linux"},
        content_type="application/json",
    )
    elapsed = time.time() - start
    data = resp.get_json()
    assert resp.status_code == 200
    assert data.get("success") is True
    assert "job_id" in data
    assert elapsed < 5.0, f"Should return in <5s, took {elapsed:.1f}s"


def test_get_deployment_package_status_returns_status(client, db_conn):
    """GET /api/deployment-package-status/<job_id> should return job status."""
    _login_as_admin(client)
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO deployment_package_jobs (package_name, status, progress_pct) "
            "VALUES ('test-pkg', 'building', 45) RETURNING id"
        )
        job_id = cur.fetchone()[0]
    db_conn.commit()

    resp = client.get(f"/tools/backup-manager/api/deployment-package-status/{job_id}")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["status"] == "building"
    assert data["progress_pct"] == 45


def test_standalone_list_returns_all_9_products(client):
    """GET /api/standalones/list should return all 9 standalone products."""
    _login_as_admin(client)
    resp = client.get("/tools/backup-manager/api/standalones/list")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["success"] is True
    names = [s["name"] for s in data["standalones"]]
    for expected in [
        "kbs",
        "media_hub",
        "creed",
        "kso",
        "gov_watch",
        "civic_watch",
        "legal_watch",
        "market_watch",
        "wtf",
    ]:
        assert expected in names, f"Missing standalone: {expected}"


def test_standalone_backup_returns_job_id(client):
    """POST /api/standalones/backup should return job_id immediately."""
    _login_as_admin(client)
    resp = client.post(
        "/tools/backup-manager/api/standalones/backup",
        json={"standalone_names": ["kso"]},
        content_type="application/json",
    )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert "job_id" in data
