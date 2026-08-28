"""
A.R.C.H.I.E. Platform - Backup Manager Routes (UI layer)
========================================================

UI + OAuth + history surface for the 4-tier backup pipeline. The ACTUAL
backup work is done by shell/Python scripts in /mnt/archie_brain/scripts/backup/
(Phase 1-6 of project #270). This module does NOT produce dumps — it READS
``backup_log`` and exposes controls.

Pipeline entry point: ``scripts/backup/run_backup.sh daily|weekly|monthly``
    → component_db.sh (pg_dump -Fc via docker exec archie_database)
    → component_code.sh, component_gitbundle.sh, component_config.sh (AES-256),
      component_volumes.sh, component_convlogs.sh, component_kb_export.sh,
      component_vps_pull.sh, component_monthly_full.sh
    → tier_sync_usb.py, tier_sync_gdrive.py, tier_sync_vps.sh
    → retention_prune.py + verify_backups.sh (weekly)

Cron schedule: ``/etc/cron.d/archie-backup`` (installed by
``scripts/install_backup_cron.sh``). Runbook: ``scripts/backup/README.md``.
Quarterly DR drill: ``scripts/backup/dr_drill.sh`` (uses pgvector/pgvector:pg16
to match the production schema extension).

This Flask module surfaces:
- Dashboard/history view backed by the ``backup_log`` table (single source of
  truth — every component run + tier sync writes a row there).
- Google Drive OAuth connect flow (delegated to
  ``tools.google_work_suite.services.drive_service`` via gdrive_service.py shim).
- Retention configuration and manual triggers.
- Pre-change snapshot hook used by Repair Bay deploys.

Historical note: older legacy paths in this file (create_backup_programmatic,
backup_integration_service) were the broken pipeline that silently failed
from 2026-03-26 until Phase 1-5. They are kept only for pre-change snapshot
compatibility — all scheduled backups now flow through scripts/backup/.

FEATURES:
---------
- Full/Critical/Database backup creation
- Gzip compression for database backups (~82% size reduction)
- External USB storage sync for physical disaster recovery
- Backup locking to prevent concurrent operations (2-hour timeout)
- Pre/Post backup hooks for custom automation scripts
- Webhook notifications (with HMAC signature verification)
- Selective component restore with preview
- Backup comparison between versions
- Module-level backup management
- Deployment history tracking

BACKUP COMPONENTS:
------------------
Restorable (have restore logic):
- database: Full PostgreSQL dump (compressed with gzip)
- platform_v2: Flask app code, modules, templates
- ai_bridge: AI routing and model configuration
- docs: Documentation files
- scripts: Shell scripts (backup, cron jobs)
- nginx: Web server configuration
- n8n_workflows: Automation workflow definitions

Archive Only (backed up but not auto-restored):
- conversation_logs: Claude Code chat transcripts (~600MB+)
- n8n_persistence: n8n internal state/cache
- database_migrations: SQL migration files (in git)
- environment: .env files (sensitive, manual restore)

CONFIGURATION:
--------------
- BACKUP_DIR: /backups (inside container)
- EXTERNAL_BACKUP_DIR: /mnt/external-backup (USB mount)
- LOCK_FILE: /backups/.backup_lock
- LOCK_TIMEOUT: 7200 seconds (2 hours)
- HOOKS_DIR: /backups/.hooks/{pre,post}/

DATABASE TABLE:
---------------
- backup_webhooks: Webhook endpoints for notifications
  - url, event_types[], active, secret_key, last_triggered, last_status

API ENDPOINTS:
--------------
Backup Management:
- GET  /api/list                - List all backups with metadata
- POST /api/create              - Create new backup
- GET  /api/download/<name>     - Download backup as tar.gz
- POST /api/delete/<name>       - Delete a backup

Restore Operations:
- GET  /preview-restore/<name>  - Preview what restore would include
- POST /restore-selective/<name> - Restore specific components
- POST /restore/<name>          - Full restore (legacy)

External Storage:
- GET  /external-status         - USB storage stats and status
- GET  /external-list           - List backups on USB
- POST /sync-external/<name>    - Copy backup to USB

Comparison & Lock:
- GET  /compare/<b1>/<b2>       - Compare two backups
- GET  /lock-status             - Check if backup is in progress

Hooks & Webhooks:
- GET  /api/hooks               - List installed hook scripts
- GET  /api/webhooks            - List configured webhooks
- POST /api/webhooks            - Add new webhook
- DELETE /api/webhooks/<id>     - Remove webhook
- POST /api/webhooks/<id>/test  - Test webhook delivery

PROGRAMMATIC API:
-----------------
These functions can be imported and called directly:

    from tools.backup_manager.backup_manager_routes import (
        create_backup_programmatic,
        preview_restore,
        restore_components,
        compare_backups,
        copy_to_external_storage,
        trigger_webhooks
    )

LAST UPDATED: 2026-01-30
"""

from flask import jsonify, request, current_app
from functools import wraps
from flask_login import current_user
import logging
import os
import re

logger = logging.getLogger(__name__)
from database import _get_db_password
import subprocess
import json
from datetime import datetime, timedelta
import shutil
import psycopg2
import gzip
import time
import hashlib
import hmac
import requests
from contextlib import contextmanager

# Rate limiting storage (in-memory, resets on restart)
_rate_limit_store = {}


def rate_limit(max_requests, window_seconds, key_func=None):
    """
    Rate limiting decorator for backup operations.

    Args:
        max_requests: Maximum number of requests allowed in the window
        window_seconds: Time window in seconds
        key_func: Optional function to extract rate limit key (default: IP address)
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if key_func:
                key = key_func()
            else:
                key = request.remote_addr

            now = datetime.now()
            window_key = f"{f.__name__}:{key}"

            if window_key in _rate_limit_store:
                requests_list = _rate_limit_store[window_key]
                # Remove old requests outside window
                cutoff = now - timedelta(seconds=window_seconds)
                requests_list = [t for t in requests_list if t > cutoff]
                _rate_limit_store[window_key] = requests_list

                if len(requests_list) >= max_requests:
                    error_msg = f"Rate limit exceeded. " f"Max {max_requests} requests per {window_seconds} seconds."
                    return (
                        jsonify({"success": False, "error": error_msg}),
                        429,
                    )

                requests_list.append(now)
            else:
                _rate_limit_store[window_key] = [now]

            return f(*args, **kwargs)

        return decorated_function

    return decorator


# =============================================================================
# PROGRAMMATIC BACKUP FUNCTIONS (can be imported and called directly)
# =============================================================================


def _safe_name_fragment(text, max_len=80):
    """Reduce caller-supplied text to ONE safe path component.

    Backup names embed a description that is often a raw proposal title containing
    '/', ':', '[', ']', '#', quotes and parentheses. Anything path-significant must not
    survive: '/' and '\\' would create nested directories, '..' would traverse upward.
    Everything outside [A-Za-z0-9._-] collapses to '_', leading dots are stripped so the
    result can never be '.', '..' or a hidden file, and the whole thing is truncated so
    a long title cannot blow the filesystem's name limit. Returns 'backup' if nothing
    usable remains. (#5030)
    """
    text = str(text or "").strip()
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)  # kills / \ .. : [ ] # ' ( ) space
    text = re.sub(r"_{2,}", "_", text).strip("._-")
    return text[:max_len] or "backup"


def create_backup_programmatic(
    description="Auto-backup",
    created_by_username="system",
    proposal_id=None,
    compress=True,
):
    """
    Create a comprehensive backup of A.R.C.H.I.E. Platform (programmatic API)

    This function can be imported and called directly from other modules:
        from tools.backup_manager.backup_manager_routes import create_backup_programmatic

    Args:
        description: Description for this backup
        created_by_username: Username of who created the backup
        proposal_id: Optional proposal ID this backup is for
        compress: If True, compress database backup with gzip (default: True)

    Returns:
        {
            'success': True,
            'backup_name': '20260102_143022_Auto-backup',
            'backup_path': '/mnt/archie_brain/backups/20260102_143022_Auto-backup',
            'backup': { metadata }
        }
    """
    backup_path = None
    lock_acquired = False
    # Wall-clock for backup_log.duration_ms — started before any work so the number covers
    # the whole backup, matching what the UI /create route records.
    _t0 = time.time()

    try:
        # Generate backup name. The description is CALLER-SUPPLIED and reaches here as a
        # raw proposal title, e.g. "[MEDIUM] PYFLAKES: repair_bay/services/foo.py (...)".
        # Previously only spaces were replaced, so every '/' in the title became a real
        # DIRECTORY SEPARATOR: the payload ended up at
        #   <backups>/<ts>_..._repair_bay/services/foo.py_/database.sql.gz
        # which broke every consumer expecting <backup>/database.sql.gz (the sandbox
        # restore among them) — and a title containing '..' could have written OUTSIDE
        # BACKUP_DIR entirely. Sanitised to a single flat path component. (#5030)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}_{_safe_name_fragment(description)}"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        # Defence in depth: never operate outside BACKUP_DIR even if the sanitiser is
        # ever weakened. commonpath raises ValueError on unrelated paths.
        _root = os.path.realpath(BACKUP_DIR)
        _target = os.path.realpath(backup_path)
        if _target != _root and os.path.commonpath([_root, _target]) != _root:
            return {"success": False, "error": "refusing to write outside BACKUP_DIR"}

        # Acquire backup lock
        lock_acquired, lock_error = acquire_backup_lock(backup_name, created_by_username)
        if not lock_acquired:
            return {"success": False, "error": lock_error}

        # Execute pre-backup hooks
        pre_ok, pre_results = execute_pre_hooks(backup_name)
        if not pre_ok:
            release_backup_lock()
            return {
                "success": False,
                "error": "Pre-backup hook failed",
                "hook_results": pre_results,
            }

        os.makedirs(backup_path, exist_ok=True)

        print(f"Creating backup: {backup_name}")

        # 1. Backup database using Python with compression
        print("  Backing up database (compressed)..." if compress else "  Backing up database...")
        db_file = os.path.join(backup_path, "database.sql")
        actual_db_file = backup_database_python(db_file, compress=compress)
        db_file_name = os.path.basename(actual_db_file)
        print(f"  ✓ Database backup complete ({db_file_name})")

        # 2. Backup platform files
        print("  Backing up platform files...")
        platform_backup = os.path.join(backup_path, "platform_v2")

        platform_dirs = ["tools", "templates", "static", "consciousness", "migrations"]
        for dir_name in platform_dirs:
            src = os.path.join(PLATFORM_DIR, dir_name)
            if os.path.exists(src):
                dst = os.path.join(platform_backup, dir_name)
                shutil.copytree(src, dst, dirs_exist_ok=True)

        important_files = [
            "app.py",
            "requirements.txt",
            "docker-compose.yml",
            ".env",
            "config.py",
            "module_registry.py",
            "rbac.py",
        ]
        for file_name in important_files:
            src = os.path.join(PLATFORM_DIR, file_name)
            if os.path.exists(src):
                dst = os.path.join(platform_backup, file_name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
        print("  ✓ Platform files backup complete")

        # 3. Backup documentation
        print("  Backing up documentation...")
        docs_src = "/mnt/archie_brain/docs"
        docs_dst = os.path.join(backup_path, "docs")
        if os.path.exists(docs_src):
            shutil.copytree(docs_src, docs_dst, dirs_exist_ok=True)
            print(f"  ✓ Documentation backup complete - {len(os.listdir(docs_dst))} files")

        # 4. Backup AI bridge code
        print("  Backing up AI bridge...")
        ai_bridge_src = "/mnt/archie_brain/ai_bridge"
        ai_bridge_dst = os.path.join(backup_path, "ai_bridge")
        if os.path.exists(ai_bridge_src):
            shutil.copytree(ai_bridge_src, ai_bridge_dst, dirs_exist_ok=True)
            print("  ✓ AI bridge backup complete")

        # 5. Backup database migrations
        db_migrations_src = "/mnt/archie_brain/database/migrations"
        if os.path.exists(db_migrations_src):
            db_migrations_dst = os.path.join(backup_path, "database/migrations")
            os.makedirs(os.path.dirname(db_migrations_dst), exist_ok=True)
            shutil.copytree(db_migrations_src, db_migrations_dst, dirs_exist_ok=True)

        # 6. Backup n8n workflows
        n8n_src = "/mnt/archie_brain/n8n_workflows"
        if os.path.exists(n8n_src):
            shutil.copytree(n8n_src, os.path.join(backup_path, "n8n_workflows"), dirs_exist_ok=True)

        # 7. Backup n8n persistence
        n8n_persistence_src = "/mnt/archie_brain/persistence/n8n"
        if os.path.exists(n8n_persistence_src):
            n8n_persistence_dst = os.path.join(backup_path, "persistence/n8n")
            os.makedirs(os.path.dirname(n8n_persistence_dst), exist_ok=True)
            shutil.copytree(n8n_persistence_src, n8n_persistence_dst, dirs_exist_ok=True)

        # 8. Backup scripts — skip large binaries, caches, logs
        scripts_src = "/mnt/archie_brain/scripts"
        if os.path.exists(scripts_src):

            def _scripts_ignore(directory, contents):
                skip = set()
                for name in contents:
                    full = os.path.join(directory, name)
                    if name in ("__pycache__",) or name.endswith((".log", ".pyc")):
                        skip.add(name)
                    elif os.path.isfile(full) and os.path.getsize(full) > 10 * 1024 * 1024:
                        skip.add(name)  # skip binaries/large files >10 MB
                return skip

            shutil.copytree(
                scripts_src,
                os.path.join(backup_path, "scripts"),
                dirs_exist_ok=True,
                ignore=_scripts_ignore,
            )

        # 9. Backup nginx configuration
        nginx_src = "/mnt/archie_brain/nginx"
        if os.path.exists(nginx_src):
            shutil.copytree(nginx_src, os.path.join(backup_path, "nginx"), dirs_exist_ok=True)

        # 10. Backup root docker-compose (environment)
        root_compose = "/mnt/archie_brain/docker-compose.yml"
        if os.path.exists(root_compose):
            shutil.copy2(root_compose, os.path.join(backup_path, "docker-compose.yml"))

        # 11. Backup conversation logs (Claude Code hook transcripts)
        conversation_logs_src = "/mnt/archie_brain/conversation_logs"
        if os.path.exists(conversation_logs_src):
            shutil.copytree(
                conversation_logs_src,
                os.path.join(backup_path, "conversation_logs"),
                dirs_exist_ok=True,
            )
            print("  ✓ Conversation logs backup complete")

        # 12. Backup website portrait JPEGs
        for site_dir, site_label in (
            ("/mnt/archie_brain/website/kytranempowerment.com/assets/portraits", "kytranempowerment"),
            ("/mnt/archie_brain/website/creed-ai.org/assets/portraits", "creed-ai.org"),
        ):
            if os.path.exists(site_dir):
                dst = os.path.join(backup_path, f"website_portraits/{site_label}")
                shutil.copytree(site_dir, dst, dirs_exist_ok=True)
                portrait_count = len([f for f in os.listdir(dst) if f.endswith(".jpg")])
                print(f"  ✓ Portrait backup complete ({site_label}: {portrait_count} files)")

        # Calculate total backup size
        total_size = 0
        for root, dirs, files in os.walk(backup_path):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))

        # Copy to external storage if available.
        # ⚠️ EPHEMERAL (pre-deploy / repair-bay / drill) snapshots get ONE rolling
        # slot, not one copy each. Measured 2026-07-22 before this rule: the USB
        # tier held 10 pre-deploy dirs (24.6 GB) + 3 drills (6.3 GB) against a
        # single 2.7 GB daily — i.e. 92% of an off-site DR drive was pre-fix
        # scratch. These exist to roll back a self-heal seconds later; they are
        # not disaster-recovery material and must not crowd out the daily (#5126).
        external_result = {"success": False, "error": "External storage not mounted"}
        if _is_ephemeral_backup(description, backup_name):
            # Pre-deploy / repair-bay snapshots NEVER go off-site (#5128, owner call).
            # They exist ONLY to roll a self-heal back seconds later, and that rollback
            # reads the PRIMARY copy under /backups — which is still written. So the
            # off-site copy bought nothing while consuming ~2.4 GB per Repair Bay
            # proposal (10 had accumulated = 24.6 GB, 92% of the DR drive).
            # Previous rule kept ONE rolling copy; that still refilled after every
            # cleanup, so the copy is now skipped outright.
            _pruned = _prune_ephemeral_external(keep=0)  # sweep strays from older runs
            if _pruned:
                print(f"  Reclaimed {_pruned} stale pre-fix copy/copies from external")
            external_result = {"success": False, "error": "skipped — pre-fix snapshot is local-only"}
            print("  Skipping external copy (pre-fix snapshot — primary copy is the rollback point)")
        elif is_external_storage_available():
            print("  Copying to external storage...")
            external_result = copy_to_external_storage(backup_name, backup_path)
            if external_result["success"]:
                print(f"  ✓ External copy complete ({external_result.get('size_mb', 0)} MB)")
                # Cap drills AFTER a confirmed copy — pruning first could leave a
                # kind at zero if the copy then failed (#5127).
                if _is_drill_backup(description, backup_name):
                    _dpruned = _prune_drills_external(keep_per_kind=1)
                    if _dpruned:
                        print(f"  Reclaimed {_dpruned} superseded drill copy/copies from external")
            else:
                print(f"  ⚠ External copy failed: {external_result.get('error', 'unknown')}")

        # 12. Create metadata with auto-assigned build number
        new_build_number = get_next_build_number()
        metadata = {
            "name": backup_name,
            "timestamp": timestamp,
            "description": description,
            "created_by": created_by_username,
            "created_at": datetime.now().isoformat(),
            "platform_version": get_platform_version(),
            "build_number": new_build_number,
            "backup_type": "full",
            "proposal_id": proposal_id,
            "compression": "gzip" if compress else "none",
            "database_file": db_file_name,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "external_copy": external_result.get("success", False),
            "external_path": (external_result.get("external_path") if external_result.get("success") else None),
            "components": {
                "database": True,
                "platform_v2": True,
                "documentation": os.path.exists(docs_src),
                "ai_bridge": os.path.exists(ai_bridge_src),
                "database_migrations": os.path.exists(db_migrations_src),
                "n8n_workflows": os.path.exists(n8n_src),
                "n8n_persistence": os.path.exists(n8n_persistence_src),
                "scripts": os.path.exists(scripts_src),
                "nginx": os.path.exists(nginx_src),
                "environment": os.path.exists(root_compose),
                "conversation_logs": os.path.exists(conversation_logs_src),
            },
        }

        metadata_file = os.path.join(backup_path, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        # Generate rollback script (handles both compressed and uncompressed)
        rollback_script = os.path.join(backup_path, "rollback.sh")
        db_restore_cmd = (
            f"zcat {backup_path}/{db_file_name} | docker exec -i archie_database psql -U archie -d archie"
            if compress
            else f"docker exec -i archie_database psql -U archie -d archie < {backup_path}/database.sql"
        )
        with open(rollback_script, "w") as f:
            f.write(
                f"""#!/bin/bash
# A.R.C.H.I.E. Platform Rollback Script
# Backup: {backup_name}
# Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

set -e

echo "Starting rollback to backup: {backup_name}"
echo ""

# Stop platform
echo "Stopping platform..."
cd /mnt/archie_brain
docker-compose stop archie_platform

# Restore database
echo "Restoring database..."
docker exec -i archie_database psql -U archie -c "DROP DATABASE IF EXISTS archie;"
docker exec -i archie_database psql -U archie -c "CREATE DATABASE archie;"
{db_restore_cmd}

# Restore platform files
echo "Restoring platform files..."
cd /mnt/archie_brain/platform_v2
cp -r {platform_backup}/* ./

# Restart platform
echo "Restarting platform..."
cd /mnt/archie_brain
docker-compose up -d archie_platform

echo ""
echo "✓ Rollback complete!"
echo "Platform should be available at http://192.168.1.200:3000"
"""
            )
        os.chmod(rollback_script, 0o755)

        # Set this backup as the current build
        set_build_number(new_build_number)

        # Execute post-backup hooks
        post_results = execute_post_hooks(backup_name, metadata)
        metadata["hook_results"] = {"pre": pre_results, "post": post_results}

        # Update metadata with hook results
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        # Trigger webhooks
        webhook_results = trigger_webhooks(
            "backup_complete",
            {
                "event": "backup_complete",
                "backup_name": backup_name,
                "build_number": new_build_number,
                "platform_version": get_platform_version(),
                "components": list(metadata["components"].keys()),
                "size_bytes": total_size,
                "size_mb": metadata["total_size_mb"],
                "compression": metadata["compression"],
                "external_copy": external_result.get("success", False),
                "timestamp": datetime.now().isoformat(),
            },
        )

        # Release lock
        release_backup_lock()
        lock_acquired = False

        print(f"✓ Backup created successfully: {backup_name} (Build #{new_build_number})")

        # Record in backup_log. Until #5053 this path wrote NO row at all — only the UI
        # /create route did — so every programmatic backup was invisible to the Backups
        # tab, to backup_posture_monitor, and to any size/freshness accounting. The
        # self-heal pre-deploy snapshots are the worst case: 12 GB accumulated on disk
        # with ZERO rows, i.e. unmonitored while the system appeared monitored (the same
        # shape as #2366). Non-fatal: a logging failure must never fail a good backup.
        _components = ",".join(k for k, v in metadata.get("components", {}).items() if v)
        _log_sql = """INSERT INTO backup_log
                          (backup_type, file_path, size_bytes, status, tier,
                           component, notes, triggered_by, proposal_id,
                           build_number, platform_version, duration_ms, created_at)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())"""

        def _log_values(_pid):
            return (
                "full",
                backup_path,
                total_size,
                "success",
                "primary",
                _components,
                description or "",
                created_by_username,
                _pid,
                new_build_number,
                metadata.get("platform_version"),
                int((time.time() - _t0) * 1000),
            )

        try:
            with get_backup_db_cursor(commit=True) as (_c, _cur):
                _cur.execute(_log_sql, _log_values(proposal_id))
        except psycopg2.errors.ForeignKeyViolation:
            # backup_log.proposal_id is FK-constrained to improvement_proposals. A caller
            # passing an id that is not (or no longer) there would otherwise lose the row
            # entirely to the except below — a backup that exists on disk but is invisible
            # to monitoring, which is the very failure #5053 set out to fix. Keep the row,
            # drop only the link.
            logger.warning(
                "backup_log: proposal_id=%s not in improvement_proposals — logging without the link",
                proposal_id,
            )
            try:
                with get_backup_db_cursor(commit=True) as (_c, _cur):
                    _cur.execute(_log_sql, _log_values(None))
            except Exception as _retry_err:
                logger.warning("backup_log INSERT retry failed (non-fatal): %s", _retry_err)
        except Exception as _log_err:
            logger.warning("backup_log INSERT failed (non-fatal): %s", _log_err)

        return {
            "success": True,
            "backup_name": backup_name,
            "backup_path": backup_path,
            "build_number": new_build_number,
            "backup": metadata,
            "external_copy": external_result,
            "webhook_results": webhook_results,
        }

    except Exception as e:
        print(f"Backup creation failed: {str(e)}")

        # Trigger failure webhook
        try:
            trigger_webhooks(
                "backup_failed",
                {
                    "event": "backup_failed",
                    "description": description,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                },
            )
        except Exception:
            pass

        # Cleanup
        if backup_path and os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        if lock_acquired:
            release_backup_lock()

        return {"success": False, "error": str(e)}


# ai_bridge lives OUTSIDE PLATFORM_DIR, and the mount layout differs per container
# (platform vs scheduler) — the first existing root wins. Module-level so tests can
# point it at a scratch tree. (#5279 item 1 — ADR-009's named 68/172 coverage gap.)
_AI_BRIDGE_ROOTS = ("/app/ai_bridge", "/mnt/archie_brain/ai_bridge")


def _write_rollback_script(backup_path, restore_map):
    """Emit a self-contained rollback.sh into a module backup dir (#5279 / ADR-009).

    auto_rollback._execute_rollback() runs `bash rollback.sh` when the file exists —
    and NO backup ever shipped one, so every auto-rollback fell to needs_manual. With
    this script a module backup is the first pre-deploy artifact the rollback path can
    actually execute. Directory entries restore with `cp -a 'rel/.' 'dest/'` (overwrites
    changed files; files CREATED after the backup are deliberately left in place); file
    entries mkdir -p the destination first. Paths are single-quoted with quote-escaping
    and module names are charset-validated upstream, so nothing caller-controlled can
    break out of the command.
    """

    def q(s):
        return "'" + str(s).replace("'", "'\\''") + "'"

    lines = [
        "#!/bin/bash",
        "# Generated by backup_module() — restores this module backup over the live tree (#5279/ADR-009).",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
    ]
    n = 0
    for rel, dest in restore_map:
        src = os.path.join(backup_path, rel)
        if os.path.isdir(src):
            lines.append(f"mkdir -p {q(dest)}")
            lines.append(f"cp -a {q(rel + '/.')} {q(dest + '/')}")
        elif os.path.isfile(src):
            lines.append(f"mkdir -p {q(os.path.dirname(dest))}")
            lines.append(f"cp -p {q(rel)} {q(dest)}")
        else:
            continue
        n += 1
    lines.append(f'echo "rollback complete: {n} item(s) restored"')
    script = os.path.join(backup_path, "rollback.sh")
    with open(script, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(script, 0o755)


def backup_module(module_name, proposal_id=None, created_by_username="system", predeploy=False):
    """
    Backup a single module for isolated sandbox testing AND as the scoped
    pre-deploy restore point (#5279 / ADR-009: "roll back via a FRESH module
    backup; full snapshots become the safety net, not the per-fix default").

    Args:
        module_name: e.g., 'improvements', 'backup_manager', 'consciousness' —
            plus the WIDENED pseudo-modules 'ai_bridge' and 'services' (task
            #5279 item 1: the paths backup_module previously could not cover)
        proposal_id: Optional link to proposal
        created_by_username: Who created this backup
        predeploy: True when taken as a pre-deploy safety copy — stamps the
            backup_log notes with the 'Pre-deploy snapshot' prefix so the
            ephemeral classification + Backups-list exclusion both apply

    Returns:
        {
            'success': True,
            'backup_name': '20260114_150302_module_improvements',
            'backup_path': '/mnt/archie_brain/backups/modules/...',
            'files_backed_up': [...],
            'restore_map': [[backup_rel, live_abs], ...]
        }

    Every backup ships a generated rollback.sh + a restore_map in metadata.json,
    so the copy is provably restorable (task #5279 item 5 — a cheaper backup
    that cannot restore is strictly worse than an expensive one that can).
    """
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(module_name or "")):
            return {"success": False, "error": f"invalid module name: {module_name!r}"}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}_module_{module_name}"
        backup_path = os.path.join(BACKUP_DIR, "modules", backup_name)

        os.makedirs(backup_path, exist_ok=True)

        files_backed_up = []
        restore_map = []  # [backup-relative, live-absolute] pairs rollback.sh restores

        if module_name == "ai_bridge":
            # Widened pseudo-module (#5279 item 1): ai_bridge is outside PLATFORM_DIR.
            src = next((r for r in _AI_BRIDGE_ROOTS if os.path.isdir(r)), None)
            if not src:
                shutil.rmtree(backup_path, ignore_errors=True)
                return {"success": False, "error": "ai_bridge root not found in this container"}
            shutil.copytree(src, os.path.join(backup_path, "ai_bridge"), dirs_exist_ok=True)
            files_backed_up.append("ai_bridge/")
            restore_map.append(["ai_bridge", src])
        elif module_name == "services":
            # Widened pseudo-module (#5279 item 1): platform_v2/services/.
            src = os.path.join(PLATFORM_DIR, "services")
            if not os.path.isdir(src):
                shutil.rmtree(backup_path, ignore_errors=True)
                return {"success": False, "error": "services dir not found"}
            shutil.copytree(src, os.path.join(backup_path, "services"), dirs_exist_ok=True)
            files_backed_up.append("services/")
            restore_map.append(["services", src])
        else:
            # 1. Backup tool routes
            tool_src = os.path.join(PLATFORM_DIR, "tools", module_name)
            if os.path.exists(tool_src):
                tool_dst = os.path.join(backup_path, "tools", module_name)
                shutil.copytree(tool_src, tool_dst, dirs_exist_ok=True)
                files_backed_up.append(f"tools/{module_name}/")
                restore_map.append([f"tools/{module_name}", tool_src])

            # 2. Backup related templates
            templates_dir = os.path.join(PLATFORM_DIR, "templates", "tools")
            if os.path.exists(templates_dir):
                for f in os.listdir(templates_dir):
                    if module_name in f.lower() or f.startswith(module_name):
                        src = os.path.join(templates_dir, f)
                        dst = os.path.join(backup_path, "templates", "tools", f)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.isfile(src):
                            shutil.copy2(src, dst)
                        else:
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                        files_backed_up.append(f"templates/tools/{f}")
                        restore_map.append([f"templates/tools/{f}", src])

            # 3. Backup related static JS
            js_dir = os.path.join(PLATFORM_DIR, "static", "js", module_name)
            if os.path.exists(js_dir):
                js_dst = os.path.join(backup_path, "static", "js", module_name)
                shutil.copytree(js_dir, js_dst, dirs_exist_ok=True)
                files_backed_up.append(f"static/js/{module_name}/")
                restore_map.append([f"static/js/{module_name}", js_dir])

        # 4. Create metadata
        metadata = {
            "name": backup_name,
            "type": "module",
            "module_name": module_name,
            "timestamp": timestamp,
            "created_by": created_by_username,
            "proposal_id": proposal_id,
            "files_backed_up": files_backed_up,
            "restore_map": restore_map,
            "predeploy": bool(predeploy),
        }

        with open(os.path.join(backup_path, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        # 5. Self-contained rollback script — makes the module rung of the restore
        # ladder executable by auto_rollback (#5279 item 5).
        _write_rollback_script(backup_path, restore_map)

        # Record it. Module backups wrote NOTHING to backup_log until 2026-07-20, which
        # made them invisible to retention_prune, backup_posture_monitor, the Backups tab,
        # and to initiate_sandbox_restore (which selects by backup_log.id — so a module
        # backup could not be sandbox-tested at all). 79 existed on disk, all dated
        # 2026-05-07, and nothing anywhere knew. Non-fatal: a logging failure must not
        # discard a good backup. Mirrors the 'standalone' INSERT below.
        total_size = 0
        try:
            for root, _dirs, files in os.walk(backup_path):
                for fname in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, fname))
                    except OSError:
                        pass
            with get_backup_db_cursor(commit=True) as (conn, cur):
                # NOTE: backup_log.created_by is an INTEGER user id, NOT a username —
                # passing the name there raises InvalidTextRepresentation. The human/job
                # label goes in triggered_by (text).
                cur.execute(
                    "INSERT INTO backup_log "
                    "(file_path, backup_type, component, tier, size_bytes, status, "
                    " triggered_by, proposal_id, notes, created_at) "
                    "VALUES (%s, 'module', %s, 'module', %s, 'success', %s, %s, %s, NOW())",
                    (
                        backup_path,
                        module_name,
                        total_size,
                        created_by_username,
                        proposal_id,
                        # 'Pre-deploy snapshot' prefix is LOAD-BEARING for predeploy copies:
                        # routes_operations excludes `LIKE 'Pre-deploy snapshot%'` from the
                        # Backups list, and _is_ephemeral_backup matches 'pre-deploy'.
                        (
                            f"Pre-deploy snapshot (module) for proposal #{proposal_id}: {module_name}"
                            if predeploy
                            else f"module backup: {', '.join(files_backed_up)[:200]}"
                        ),
                    ),
                )
        except Exception as log_err:  # noqa: BLE001 — never fail a good backup on bookkeeping
            logger.warning("module backup_log INSERT failed (non-fatal) for %s: %s", module_name, log_err)

        return {
            "success": True,
            "backup_name": backup_name,
            "backup_path": backup_path,
            "files_backed_up": files_backed_up,
            "restore_map": restore_map,
            "size_bytes": total_size,
            "metadata": metadata,
        }

    except Exception as e:
        if "backup_path" in locals() and os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        return {"success": False, "error": str(e)}


def get_module_dependencies(module_name):
    """
    Get list of files a module depends on

    Returns dict of:
        - routes: tools/{module}/routes.py
        - templates: templates/tools/{module}*.html
        - static: static/js/{module}/
        - shared: shared imports (config.py, db.py, etc.)
    """
    dependencies = {"routes": [], "templates": [], "static": [], "shared": []}

    # Routes
    tool_dir = os.path.join(PLATFORM_DIR, "tools", module_name)
    if os.path.exists(tool_dir):
        for f in os.listdir(tool_dir):
            dependencies["routes"].append(f"tools/{module_name}/{f}")

    # Templates
    templates_dir = os.path.join(PLATFORM_DIR, "templates", "tools")
    if os.path.exists(templates_dir):
        for f in os.listdir(templates_dir):
            if module_name in f.lower():
                dependencies["templates"].append(f"templates/tools/{f}")

    # Static JS
    js_dir = os.path.join(PLATFORM_DIR, "static", "js", module_name)
    if os.path.exists(js_dir):
        for f in os.listdir(js_dir):
            dependencies["static"].append(f"static/js/{module_name}/{f}")

    # Common shared files (always needed)
    dependencies["shared"] = ["config.py", "app.py", "module_registry.py", "rbac.py"]

    return dependencies


# Alias for backward compatibility
create_backup = create_backup_programmatic


# =============================================================================
# FLASK ROUTES
# =============================================================================


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


# Configuration
# Path constants - must match Docker volume mounts in docker-compose.yml
# Host ./backups is mounted to /backups in container
# Host ./platform_v2 is mounted to /app in container
BACKUP_DIR = "/backups"
PLATFORM_DIR = "/app"

# External backup storage configuration
EXTERNAL_BACKUP_DIR = "/mnt/external-backup"

# Backup locking configuration
LOCK_FILE = os.path.join(BACKUP_DIR, ".backup_lock")
LOCK_TIMEOUT = 7200  # 2 hours

# Bytes read from the pg_dump pipe per iteration. This is what bounds peak memory now that
# the dump is produced by pg_dump rather than assembled in Python (#5080). The original OOM
# (#5014/#2365) came from holding dump CONTENT in the process; nothing here does.
_DUMP_CHUNK_BYTES = 1024 * 1024  # 1 MiB

# Floor below which a "successful" dump is not believable. A real pg_dump of this database
# is hundreds of MB; anything near-empty means pg_dump exited 0 having written nothing, and
# recording that as a restore point is the exact failure this module keeps hitting.
_MIN_DUMP_BYTES = 1024

# Hook directories
HOOKS_DIR = os.path.join(BACKUP_DIR, ".hooks")
PRE_HOOKS_DIR = os.path.join(HOOKS_DIR, "pre")
POST_HOOKS_DIR = os.path.join(HOOKS_DIR, "post")

# Ensure backup directory exists.
# Tolerate failure at IMPORT time: outside the container (tests, tooling, a dev shell)
# /backups is not writable, and an unimportable module cannot be unit-tested at all —
# which is part of why the dump defects in #5080 were only ever found in production.
# Anything that actually writes a backup creates its own directories and will still fail
# loudly there, where the error is meaningful.
try:
    os.makedirs(BACKUP_DIR, exist_ok=True)
except OSError:
    pass

# =============================================================================
# STANDALONE PRODUCTS REGISTRY
# =============================================================================

STANDALONE_PRODUCTS = [
    {
        "name": "kbs",
        "display_name": "Kytran Business Suite",
        "code_path": "/mnt/archie_brain/kytran-business-suite",
        "db_schema": None,  # own Postgres DB (kbs_app container)
        "backup_type": "full",
    },
    {
        "name": "media_hub",
        "display_name": "Media Hub",
        "code_path": "/mnt/archie_brain/standalone/media_hub",
        "db_schema": None,  # own Postgres DB (mediahub_app container)
        "backup_type": "config_only",
        "exclude_paths": ["/mnt/Plex", "/mnt/data2", "media/", "data/"],
        "exclude_extensions": [".mkv", ".mp4", ".avi", ".mov", ".m4v", ".iso"],
    },
    {
        "name": "creed",
        "display_name": "C.R.E.E.D. Governance",
        # /mnt/archie_brain/kytran-creed is a SYMLINK to this path and is not bound into
        # archie_platform, so it does not resolve in-container: every creed backup since
        # the beginning produced 0 files / 0 bytes (13 runs, measured 2026-07-20).
        # /mnt/standalone IS bound, and stat confirms both spellings are the same inode —
        # this is the same directory, just the reachable name for it.
        "code_path": "/mnt/standalone/kytran-creed",
        "db_schema": None,  # own SQLite DB
        "backup_type": "full",
    },
    {
        "name": "kso",
        "display_name": "Kytran System Operations",
        "code_path": "/mnt/archie_brain/kytran-server-manager",
        "db_schema": None,  # own DB
        "backup_type": "full",
    },
    {
        "name": "gov_watch",
        "display_name": "Gov Watch",
        "code_path": "/mnt/standalone/kytran-gov-watch",
        # LIVE DB = Postgres container `gov_watch_db` on boston-2 (migrated off
        # outpost-us 2026-06; outpost copy is gone — backups failed 06-10 until
        # this repoint). The old hub `gov_watch` schema is stale — do not dump it.
        "db_kind": "pg_container",
        "db_node": "100.64.0.10",  # boston-2 (mesh)
        "db_ssh_user": "root",
        "db_container": "gov_watch_db",
        "backup_type": "full",
    },
    {
        "name": "civic_watch",
        "display_name": "Civic Watch",
        "code_path": "/mnt/standalone/kytran-civic-watch",
        # LIVE DB = SQLite in the civic API container on boston-2 (watch.db —
        # civic.db is an empty legacy file). Migrated off outpost-us 2026-06.
        "db_kind": "sqlite",
        "db_node": "100.64.0.10",  # boston-2 (mesh)
        "db_ssh_user": "root",
        "db_container": "kytran_watch_api",
        "db_path": "/app/data/watch.db",
        "backup_type": "full",
    },
    {
        "name": "legal_watch",
        "display_name": "Legal Watch",
        "code_path": "/mnt/standalone/kytran-legal-watch",
        # LIVE DB = SQLite in the legal API container on boston-2 (migrated
        # 2026-06-02; DNS legal.kytranempowerment.com -> boston-2).
        "db_kind": "sqlite",
        "db_node": "100.64.0.10",  # boston-2 (mesh)
        "db_ssh_user": "root",
        "db_container": "kytran_legal_api",
        "db_path": "/app/data/legal.db",
        "backup_type": "full",
    },
    {
        "name": "market_watch",
        "display_name": "Market Watch",
        "code_path": "/mnt/standalone/kytran-market-watch",
        # LIVE DB = SQLite in the market API container on boston-2 (migrated
        # off outpost-us 2026-06).
        "db_kind": "sqlite",
        "db_node": "100.64.0.10",  # boston-2 (mesh)
        "db_ssh_user": "root",
        "db_container": "kytran_market_api",
        "db_path": "/app/data/market.db",
        "backup_type": "full",
    },
    {
        "name": "wtf",
        "display_name": "What The Fact",
        "code_path": "/mnt/archie_brain/what-the-fact",
        # WTF DB = real Postgres DB on the hub (schema "wtf" in DB "wtf").
        "db_kind": "hub_schema",
        "db_schema": "wtf",  # schema within the wtf database
        "db_name": "wtf",  # separate postgres DB — connect: psql -U archie -d wtf
        "backup_type": "full",
    },
]


# ---------------------------------------------------------------------------
# Remote-DB backup helpers (watch products). Their LIVE databases live in
# containers on fleet nodes, not on the hub. All traffic uses the Headscale
# mesh (100.64.0.x). The archie_platform container ships an ssh client + the
# hub key at /root/.ssh/id_ed25519, which is authorized on every node.
# ---------------------------------------------------------------------------
def _ssh_key_path():
    for k in ("/root/.ssh/id_ed25519", "/home/kytran/.ssh/id_ed25519"):
        if os.path.exists(k):
            return k
    return "/root/.ssh/id_ed25519"


def _ssh_cmd(user_host):
    return [
        "ssh",
        "-i",
        _ssh_key_path(),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        user_host,
    ]


def _backup_remote_sqlite(product, out_path):
    """Online .backup() of a SQLite DB inside a container on a fleet node,
    streamed off-box over the mesh. Consistent under live writes (unlike cp).
    Returns (size_bytes, error_or_None)."""
    import subprocess
    import sqlite3

    user_host = f"{product['db_ssh_user']}@{product['db_node']}"
    ctr = product["db_container"]
    dbp = product["db_path"]
    snap = "/tmp/_archie_bk.sqlite"
    inner = "import sqlite3;" f"b=sqlite3.connect('{snap}');" f"sqlite3.connect('{dbp}').backup(b);" "b.close()"
    remote = (
        f'docker exec {ctr} python3 -c "{inner}" && '
        f"docker exec {ctr} cat {snap} && "
        f"docker exec {ctr} rm -f {snap}"
    )
    try:
        with open(out_path, "wb") as fh:
            r = subprocess.run(
                _ssh_cmd(user_host) + [remote],
                stdout=fh,
                stderr=subprocess.PIPE,
                timeout=300,
            )
    except Exception as e:
        return 0, f"sqlite ssh error ({product['db_node']}): {e}"
    if r.returncode != 0:
        return 0, f"sqlite backup ({product['db_node']}): {r.stderr.decode()[:200]}"
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    if size < 1000:
        return size, f"sqlite backup too small ({size}B) — {product['db_node']}:{dbp}"
    try:
        ok = sqlite3.connect(out_path).execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            return size, f"sqlite integrity_check={ok} — {product['db_node']}:{dbp}"
    except Exception as e:
        return size, f"sqlite verify error: {e}"
    return size, None


def _backup_remote_pg_container(product, out_path):
    """pg_dump -Fc of a Postgres DB in a container on a fleet node, using the
    container's own POSTGRES_* env (no secret in code). Streams over the mesh.
    Returns (size_bytes, error_or_None)."""
    import subprocess

    user_host = f"{product['db_ssh_user']}@{product['db_node']}"
    ctr = product["db_container"]
    remote = f"docker exec {ctr} sh -c " "'PGPASSWORD=$POSTGRES_PASSWORD pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB'"
    try:
        with open(out_path, "wb") as fh:
            r = subprocess.run(
                _ssh_cmd(user_host) + [remote],
                stdout=fh,
                stderr=subprocess.PIPE,
                timeout=300,
            )
    except Exception as e:
        return 0, f"pg_dump ssh error ({product['db_node']}): {e}"
    if r.returncode != 0:
        return 0, f"pg_dump ({product['db_node']}/{ctr}): {r.stderr.decode()[:200]}"
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    if size < 100:
        return size, f"pg_dump too small ({size}B) — {product['db_node']}/{ctr}"
    return size, None


def backup_standalone(standalone_name):
    """Backup one standalone: live DB dump (mesh/SSH for node-hosted DBs) + code tar.gz.
    Returns {'success': bool, 'backup_name': str, 'errors': list}."""
    import subprocess
    import tarfile as _tarfile

    product = next((p for p in STANDALONE_PRODUCTS if p["name"] == standalone_name), None)
    if not product:
        return {
            "success": False,
            "error": f"Unknown standalone: {standalone_name}",
            "errors": [f"Unknown standalone: {standalone_name}"],
        }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"standalone_{standalone_name}_{timestamp}"
    dest_dir = os.path.join(BACKUP_DIR, "standalones", standalone_name)
    os.makedirs(dest_dir, exist_ok=True)
    backup_path = os.path.join(dest_dir, backup_name)
    os.makedirs(backup_path)

    errors = []
    warnings = []

    # 1. Database backup — handler depends on where the LIVE DB physically lives:
    #    hub_schema   → pg_dump a schema in the hub archie/wtf DB (e.g. wtf)
    #    sqlite       → online .backup() of a SQLite DB in a container on a node
    #    pg_container → pg_dump -Fc of a Postgres DB in a container on a node
    # Back-compat: products without db_kind fall back to legacy db_schema behaviour.
    db_kind = product.get("db_kind") or ("hub_schema" if product.get("db_schema") else None)
    db_dump_path = None
    db_size = 0

    if db_kind == "sqlite":
        db_dump_path = os.path.join(backup_path, f"{standalone_name}.db")
        db_size, _dberr = _backup_remote_sqlite(product, db_dump_path)
        if _dberr:
            errors.append(_dberr)
    elif db_kind == "pg_container":
        db_dump_path = os.path.join(backup_path, f"{standalone_name}.dump")
        db_size, _dberr = _backup_remote_pg_container(product, db_dump_path)
        if _dberr:
            errors.append(_dberr)
    elif db_kind == "hub_schema":
        db_dump_path = os.path.join(backup_path, f"{standalone_name}_schema.sql")
        pg_env = os.environ.copy()
        db_password = os.getenv("DB_PASSWORD") or ""
        if not db_password:
            secret_file = os.getenv("DB_PASSWORD_FILE", "")
            if secret_file and os.path.exists(secret_file):
                try:
                    with open(secret_file) as _sf:
                        db_password = _sf.read().strip()
                except Exception:
                    pass
        if db_password:
            pg_env["PGPASSWORD"] = db_password
        try:
            result = subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    os.getenv("DB_HOST", "192.168.1.200"),
                    "-U",
                    os.getenv("DB_USER", "archie"),
                    "-d",
                    product.get("db_name", os.getenv("DB_NAME", "archie")),
                    "-n",
                    product["db_schema"],
                    "-f",
                    db_dump_path,
                ],
                env=pg_env,
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                errors.append(f"pg_dump: {result.stderr.decode()[:200]}")
            else:
                db_size = os.path.getsize(db_dump_path) if os.path.exists(db_dump_path) else 0
        except Exception as e:
            errors.append(f"pg_dump error: {e}")
    else:
        warnings.append(f"no DB configured for {standalone_name} — code-only backup")

    # 2. Code tar.gz
    code_archive = os.path.join(backup_path, f"{standalone_name}_code.tar.gz")
    code_path = product["code_path"]
    exclude_paths = product.get("exclude_paths", [])
    exclude_exts = set(e.lower() for e in product.get("exclude_extensions", []))
    code_size = 0
    if os.path.exists(code_path):
        try:
            with _tarfile.open(code_archive, "w:gz") as tar:
                for dirpath, dirnames, filenames in os.walk(code_path):
                    dirnames[:] = [
                        d
                        for d in dirnames
                        if not any(excl.rstrip("/") in os.path.join(dirpath, d) for excl in exclude_paths)
                    ]
                    for fname in filenames:
                        if os.path.splitext(fname)[1].lower() in exclude_exts:
                            continue
                        fpath = os.path.join(dirpath, fname)
                        tar.add(fpath, arcname=os.path.relpath(fpath, code_path))
                        code_size += os.path.getsize(fpath)
        except Exception as e:
            errors.append(f"tar error: {e}")
    else:
        warnings.append(f"code_path not mounted: {code_path} (schema-only backup)")

    db_size = os.path.getsize(db_dump_path) if (db_dump_path and os.path.exists(db_dump_path)) else 0
    total_size = code_size + db_size
    if errors:
        status = "failed"
    elif warnings:
        status = "partial"
    else:
        status = "success"

    try:
        with get_backup_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO backup_log "
                "(file_path, backup_type, standalone_name, size_bytes, status, created_at) "
                "VALUES (%s, 'standalone', %s, %s, %s, NOW())",
                (backup_path, standalone_name, total_size, status),
            )
    except Exception as e:
        errors.append(f"DB log error: {e}")

    return {
        "success": not errors,
        "backup_name": backup_name,
        "backup_path": backup_path,
        "errors": errors,
        "warnings": warnings,
    }


# Ensure hook directories exist. Same import-time tolerance as BACKUP_DIR above: outside the
# container these are not creatable, and refusing to import makes the module untestable.
for d in [HOOKS_DIR, PRE_HOOKS_DIR, POST_HOOKS_DIR]:
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass

# =============================================================================
# RETENTION POLICY - Grandfather-Father-Son (7 daily + 4 weekly + 6 monthly)
# =============================================================================


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


def get_backup_retention_status():
    """
    Analyze all backups and determine which should be kept/deleted based on retention policy.

    Retention Policy (Industry Standard GFS):
    - Keep last 7 daily backups
    - Keep last 4 weekly backups (Sundays)
    - Keep last 6 monthly backups (1st of month)

    Returns:
        {
            'keep': [list of backup names to keep],
            'delete': [list of backup names to delete],
            'stats': {storage info}
        }
    """
    if not os.path.exists(BACKUP_DIR):
        return {"keep": [], "delete": [], "stats": {}}

    # Get all backups with their dates
    backups = []
    for item in os.listdir(BACKUP_DIR):
        backup_path = os.path.join(BACKUP_DIR, item)
        if os.path.isdir(backup_path) and item != "modules":
            # Skip Daily_Triage dirs — managed by scripts/backup_triage.sh with its own retention
            if item.endswith("_Daily_Triage"):
                continue
            # Parse timestamp from backup name (format: YYYYMMDD_HHMMSS_description)
            try:
                timestamp_str = item[:15]  # YYYYMMDD_HHMMSS
                backup_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")

                # Get backup size
                total_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, _, filenames in os.walk(backup_path)
                    for filename in filenames
                )

                backups.append(
                    {
                        "name": item,
                        "path": backup_path,
                        "date": backup_date,
                        "size": total_size,
                        "day_of_week": backup_date.weekday(),  # 0=Monday, 6=Sunday
                        "day_of_month": backup_date.day,
                    }
                )
            except (ValueError, IndexError):
                # Skip malformed backup names
                continue

    # Sort by date (newest first)
    backups.sort(key=lambda x: x["date"], reverse=True)

    cfg = get_retention_config()

    keep = set()

    # Rule 1: Keep last N daily backups (configurable, default 7)
    daily_kept = 0
    for backup in backups:
        if daily_kept < cfg["daily"]:
            keep.add(backup["name"])
            daily_kept += 1

    # Rule 2: Keep last N weekly backups (configurable, default 4)
    weeks_seen = set()
    for backup in backups:
        week_key = backup["date"].strftime("%Y-%W")  # Year-Week number
        if week_key not in weeks_seen and len(weeks_seen) < cfg["weekly"]:
            keep.add(backup["name"])
            weeks_seen.add(week_key)

    # Rule 3: Keep last N monthly backups (configurable, default 6)
    months_seen = set()
    for backup in backups:
        month_key = backup["date"].strftime("%Y-%m")  # Year-Month
        if month_key not in months_seen and len(months_seen) < cfg["monthly"]:
            keep.add(backup["name"])
            months_seen.add(month_key)

    # Determine which to delete
    delete = []
    keep_list = []
    total_size = 0
    delete_size = 0

    for backup in backups:
        total_size += backup["size"]
        if backup["name"] in keep:
            keep_list.append(backup["name"])
        else:
            delete.append(backup["name"])
            delete_size += backup["size"]

    return {
        "keep": keep_list,
        "delete": delete,
        "stats": {
            "total_backups": len(backups),
            "keep_count": len(keep_list),
            "delete_count": len(delete),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "delete_size_bytes": delete_size,
            "delete_size_mb": round(delete_size / (1024 * 1024), 2),
            "space_to_free_mb": round(delete_size / (1024 * 1024), 2),
        },
    }


def cleanup_old_backups(dry_run=True):
    """
    Delete old backups based on retention policy.

    Args:
        dry_run: If True, only report what would be deleted without actually deleting

    Returns:
        {
            'success': True,
            'dry_run': True/False,
            'deleted': [list of deleted backup names],
            'kept': [list of kept backup names],
            'space_freed_mb': float
        }
    """
    retention = get_backup_retention_status()

    deleted = []
    space_freed = 0

    if not dry_run:
        for backup_name in retention["delete"]:
            backup_path = os.path.join(BACKUP_DIR, backup_name)
            # Get size before deletion
            try:
                backup_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, _, filenames in os.walk(backup_path)
                    for filename in filenames
                )
            except Exception:
                backup_size = 0

            # DB delete FIRST — so a crash leaves orphan directory (recoverable) not orphan log entry
            # Match both container path (/backups/...) and host path (/mnt/data2/backups/...)
            # plus sub-component entries (file_path LIKE backup_path/%) for each variant.
            host_path = backup_path.replace(BACKUP_DIR, "/mnt/data2/backups")
            try:
                with get_backup_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "DELETE FROM backup_log WHERE file_path = %s OR file_path LIKE %s"
                        " OR file_path = %s OR file_path LIKE %s",
                        (backup_path, backup_path + "/%", host_path, host_path + "/%"),
                    )
            except Exception as db_err:
                logger.warning("cleanup_old_backups: failed to delete backup_log row for %s: %s", backup_name, db_err)
                # Skip rmtree if DB delete failed — don't create filesystem-DB drift
                continue

            try:
                shutil.rmtree(backup_path)
                deleted.append(backup_name)
                space_freed += backup_size
            except Exception as e:
                logger.warning("cleanup_old_backups: failed to delete dir %s: %s", backup_name, e)

    return {
        "success": True,
        "dry_run": dry_run,
        "deleted": deleted if not dry_run else retention["delete"],
        "kept": retention["keep"],
        "would_delete": retention["delete"] if dry_run else [],
        "space_freed_mb": (
            round(space_freed / (1024 * 1024), 2) if not dry_run else retention["stats"]["delete_size_mb"]
        ),
        "stats": retention["stats"],
    }


def get_current_build():
    """Get current build number from file"""
    current_build_file = os.path.join(BACKUP_DIR, ".current_build")
    if os.path.exists(current_build_file):
        try:
            with open(current_build_file, "r") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            return None
    return None


def get_next_build_number():
    """Get next build number (current + 1, or 1 if none exists)"""
    current = get_current_build()
    return (current or 0) + 1


def set_build_number(build_number):
    """Set the current build number"""
    current_build_file = os.path.join(BACKUP_DIR, ".current_build")
    with open(current_build_file, "w") as f:
        f.write(str(build_number))
    return build_number


def verify_backup_integrity(backup_name):
    """
    Verify integrity of a backup.

    Checks:
    - metadata.json exists and is valid JSON
    - database.sql exists and is > 1KB
    - platform_v2/ directory exists
    - rollback.sh exists

    Returns:
        {
            'valid': True/False,
            'backup_name': str,
            'checks': {check_name: True/False},
            'errors': [list of error messages]
        }
    """
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    checks = {}
    errors = []

    # Check backup directory exists
    if not os.path.isdir(backup_path):
        return {
            "valid": False,
            "backup_name": backup_name,
            "checks": {},
            "errors": ["Backup directory does not exist"],
        }

    # Check metadata.json
    metadata_file = os.path.join(backup_path, "metadata.json")
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, "r") as f:
                json.load(f)  # Validate JSON is parseable
            checks["metadata_valid"] = True
        except json.JSONDecodeError:
            checks["metadata_valid"] = False
            errors.append("metadata.json is not valid JSON")
    else:
        checks["metadata_valid"] = False
        errors.append("metadata.json missing")

    # Check database.sql or database.sql.gz
    db_file = os.path.join(backup_path, "database.sql.gz")
    db_compressed = True
    if not os.path.exists(db_file):
        db_file = os.path.join(backup_path, "database.sql")
        db_compressed = False

    if os.path.exists(db_file):
        db_size = os.path.getsize(db_file)
        # For compressed files, even 1KB compressed is valid (uncompressed ~95MB -> ~5MB compressed)
        min_size = 512 if db_compressed else 1024
        if db_size > min_size:
            checks["database_valid"] = True
            checks["database_compressed"] = db_compressed
            # Verify gzip can be opened if compressed
            if db_compressed:
                try:
                    with gzip.open(db_file, "rt", encoding="utf-8") as f:
                        f.read(100)  # Read first 100 chars to verify
                except Exception as e:
                    checks["database_valid"] = False
                    errors.append(f"database.sql.gz is corrupted: {str(e)}")
        else:
            checks["database_valid"] = False
            errors.append(f"database file too small ({db_size} bytes)")
    else:
        checks["database_valid"] = False
        errors.append("database.sql or database.sql.gz missing")

    # Check platform_v2 directory
    platform_dir = os.path.join(backup_path, "platform_v2")
    if os.path.isdir(platform_dir):
        # Check for key subdirectories
        has_tools = os.path.isdir(os.path.join(platform_dir, "tools"))
        has_templates = os.path.isdir(os.path.join(platform_dir, "templates"))
        checks["platform_valid"] = has_tools and has_templates
        if not has_tools:
            errors.append("platform_v2/tools directory missing")
        if not has_templates:
            errors.append("platform_v2/templates directory missing")
    else:
        checks["platform_valid"] = False
        errors.append("platform_v2 directory missing")

    # Check rollback.sh
    rollback_file = os.path.join(backup_path, "rollback.sh")
    if os.path.exists(rollback_file):
        checks["rollback_exists"] = True
    else:
        checks["rollback_exists"] = False
        errors.append("rollback.sh missing")

    # Overall validity
    valid = all(checks.values())

    return {
        "valid": valid,
        "backup_name": backup_name,
        "checks": checks,
        "errors": errors,
    }


def get_db_connection():
    """Get database connection using app config (DEPRECATED - use get_backup_db_cursor)"""
    db_host = os.environ.get("DB_HOST", "archie_db")
    db_name = os.environ.get("DB_NAME", "archie")
    db_user = os.environ.get("DB_USER", "archie")
    db_pass = _get_db_password()
    db_port = os.environ.get("DB_PORT", "5432")

    return psycopg2.connect(host=db_host, database=db_name, user=db_user, password=db_pass, port=db_port)


@contextmanager
def get_backup_db_cursor(commit=True, cursor_factory=None):
    """
    Context manager for safe database operations with automatic cleanup.

    Usage:
        with get_backup_db_cursor() as (conn, cur):
            cur.execute("SELECT ...")
            # Auto-commits on success, rollback on error, always closes

        # With RealDictCursor:
        from psycopg2.extras import RealDictCursor
        with get_backup_db_cursor(cursor_factory=RealDictCursor) as (conn, cur):
            cur.execute("SELECT ...")

    Args:
        commit: Whether to auto-commit on success (default: True)
        cursor_factory: Optional cursor factory (e.g., RealDictCursor)

    Yields:
        Tuple of (connection, cursor)
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=cursor_factory) if cursor_factory else conn.cursor()
        yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# =============================================================================
# EXTERNAL STORAGE FUNCTIONS
# =============================================================================


def is_external_storage_available():
    """Check if external backup storage is mounted and writable"""
    if not os.path.exists(EXTERNAL_BACKUP_DIR):
        return False
    # Check if it's a mount point
    try:
        return os.path.ismount(EXTERNAL_BACKUP_DIR) and os.access(EXTERNAL_BACKUP_DIR, os.W_OK)
    except Exception as e:
        current_app.logger.debug(f"External storage check failed: {e}")
        return False


def get_external_storage_stats():
    """Get external storage statistics"""
    if not is_external_storage_available():
        return {"available": False, "error": "External storage not mounted"}

    try:
        statvfs = os.statvfs(EXTERNAL_BACKUP_DIR)
        total_bytes = statvfs.f_frsize * statvfs.f_blocks
        free_bytes = statvfs.f_frsize * statvfs.f_bavail
        used_bytes = total_bytes - free_bytes

        # Count backups on external storage
        backup_count = 0
        backup_size = 0
        if os.path.exists(EXTERNAL_BACKUP_DIR):
            for item in os.listdir(EXTERNAL_BACKUP_DIR):
                item_path = os.path.join(EXTERNAL_BACKUP_DIR, item)
                if os.path.isdir(item_path):
                    backup_count += 1
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            backup_size += os.path.getsize(os.path.join(root, f))

        return {
            "available": True,
            "mount_point": EXTERNAL_BACKUP_DIR,
            "total_bytes": total_bytes,
            "total_gb": round(total_bytes / (1024**3), 2),
            "free_bytes": free_bytes,
            "free_gb": round(free_bytes / (1024**3), 2),
            "used_bytes": used_bytes,
            "used_gb": round(used_bytes / (1024**3), 2),
            "backup_count": backup_count,
            "backup_size_bytes": backup_size,
            "backup_size_gb": round(backup_size / (1024**3), 2),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


# Markers identifying a PRE-FIX / scratch snapshot rather than a DR restore point.
# `proposal_service.create_backup(description=f"Pre-deploy snapshot for proposal #...")`
# and the restorability drills are the two producers.
_EPHEMERAL_MARKERS = ("pre-deploy", "repair bay")


def _is_ephemeral_backup(description: str, backup_name: str) -> bool:
    """True for PRE-DEPLOY / REPAIR-BAY snapshots only.

    These are taken seconds before a self-heal purely so it can be rolled back.
    They are not disaster-recovery artifacts and must not accumulate off-site.

    Scope is deliberately narrow:
      • Restorability DRILLS are NOT matched. They are DR rehearsal evidence,
        a different thing from pre-fix scratch, and were not in scope. (3 dirs /
        6.3 GB on USB as of 2026-07-22 — raise separately if they should go too.)
      • Directory names use underscores (`Pre-deploy_snapshot_for_proposal_…`)
        while descriptions use spaces, so separators are normalised before
        matching — otherwise a marker written with a space silently never fires,
        which is exactly the bug this comment used to describe inaccurately.
    """
    haystack = f"{description or ''} {backup_name or ''}".lower().replace("_", " ").replace("-", "-")
    return any(marker in haystack for marker in _EPHEMERAL_MARKERS)


_DRILL_MARKER = "restorability drill"
# Drill dirs are named `<ts>_restorability_drill_<kind>`; kind mirrors the three
# Quick Backup types. Each kind is SEPARATE rehearsal evidence, so the cap is
# per-kind — collapsing them to one would silently destroy proof that the
# database (or critical, or full) restore path was exercised at all.
_DRILL_KINDS = ("database", "critical", "full")


def _is_drill_backup(description: str, backup_name: str) -> bool:
    """True for restorability-drill snapshots (DR rehearsals)."""
    haystack = f"{description or ''} {backup_name or ''}".lower().replace("_", " ")
    return _DRILL_MARKER in haystack


def _drill_kind(backup_name: str) -> str:
    """Which drill kind a directory represents ('database'/'critical'/'full'/'other')."""
    low = (backup_name or "").lower()
    for kind in _DRILL_KINDS:
        if low.endswith(kind) or f"drill_{kind}" in low or f"drill {kind}" in low:
            return kind
    return "other"


def _prune_drills_external(keep_per_kind: int = 1) -> int:
    """Cap restorability drills on external storage at `keep_per_kind` PER KIND.

    Called AFTER the new copy lands, so a failed copy can never leave a kind at
    zero. Same narrow guarantees as _prune_ephemeral_external: external tier
    only, name must match, newest-first, realpath containment re-asserted before
    an irreversible delete, failures swallowed (#5127).
    """
    removed = 0
    try:
        if not os.path.isdir(EXTERNAL_BACKUP_DIR):
            return 0
        by_kind: dict = {}
        for d in os.listdir(EXTERNAL_BACKUP_DIR):
            if os.path.isdir(os.path.join(EXTERNAL_BACKUP_DIR, d)) and _is_drill_backup("", d):
                by_kind.setdefault(_drill_kind(d), []).append(d)
        for _kind, dirs in by_kind.items():
            dirs.sort(reverse=True)  # YYYYMMDD_HHMMSS prefix → newest first
            for stale in dirs[max(keep_per_kind, 0) :]:
                target = os.path.join(EXTERNAL_BACKUP_DIR, stale)
                if os.path.realpath(target).startswith(os.path.realpath(EXTERNAL_BACKUP_DIR) + os.sep):
                    shutil.rmtree(target, ignore_errors=True)
                    removed += 1
    except Exception as exc:
        print(f"  ⚠ Drill external prune skipped: {exc}")
    return removed


def _prune_ephemeral_external(keep: int = 1) -> int:
    """Keep at most `keep` ephemeral snapshots on external storage; delete the rest.

    Returns the number of directories removed. Deliberately narrow:
      • only ever touches EXTERNAL_BACKUP_DIR (never the primary /backups),
      • only directories whose NAME matches an ephemeral marker — a daily,
        monthly, weekly or any unrecognised run dir is never a candidate,
      • newest-first, so the most recent rollback point is the one retained.
    """
    removed = 0
    try:
        if not os.path.isdir(EXTERNAL_BACKUP_DIR):
            return 0
        candidates = [
            d
            for d in os.listdir(EXTERNAL_BACKUP_DIR)
            if os.path.isdir(os.path.join(EXTERNAL_BACKUP_DIR, d)) and _is_ephemeral_backup("", d)
        ]
        candidates.sort(reverse=True)  # names are YYYYMMDD_HHMMSS_… → newest first
        for stale in candidates[max(keep, 0) :]:
            target = os.path.join(EXTERNAL_BACKUP_DIR, stale)
            # Re-assert containment before an irreversible delete.
            if os.path.realpath(target).startswith(os.path.realpath(EXTERNAL_BACKUP_DIR) + os.sep):
                shutil.rmtree(target, ignore_errors=True)
                removed += 1
    except Exception as exc:  # never let housekeeping break a backup run
        print(f"  ⚠ Ephemeral external prune skipped: {exc}")
    return removed


def copy_to_external_storage(backup_name, backup_path):
    """Copy backup to external USB storage for physical disaster recovery"""
    if not is_external_storage_available():
        return {"success": False, "error": "External storage not mounted"}

    external_path = os.path.join(EXTERNAL_BACKUP_DIR, backup_name)
    try:
        shutil.copytree(backup_path, external_path, dirs_exist_ok=True)
        # Calculate size of copied backup
        total_size = 0
        for root, dirs, files in os.walk(external_path):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))

        return {
            "success": True,
            "external_path": external_path,
            "size_bytes": total_size,
            "size_mb": round(total_size / (1024 * 1024), 2),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# BACKUP LOCKING FUNCTIONS
# =============================================================================


def _proc_start_time(pid):
    """Epoch seconds at which `pid` started, or None if it cannot be determined.

    /proc/<pid> directory ctime/mtime are NOT process start time (procfs reports "now"), so
    this reads /proc/<pid>/stat field 22 — starttime in clock ticks since system boot — and
    adds `btime` from /proc/stat. Both are host-relative inside a container and therefore
    mutually consistent. Verified 2026-07-20: pid 1 computed 15:37:09.83 against the
    container's actual StartedAt of 15:37:10Z.
    """
    try:
        btime = None
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    btime = float(line.split()[1])
                    break
        if btime is None:
            return None
        with open("/proc/%d/stat" % int(pid)) as f:
            data = f.read()
        # comm (field 2) may contain spaces and parens — split after the LAST ')'
        fields = data[data.rindex(")") + 2 :].split()
        return btime + float(fields[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def lock_owner_is_dead(lock_data, _exists=None, _start_time=None):
    """(is_dead, reason) — True ONLY when the lock's owner provably no longer exists.

    Asymmetric on purpose. Declaring a LIVE backup dead would run two backups concurrently
    over the same paths, which is far worse than waiting out LOCK_TIMEOUT. So every uncertain
    path returns False (keep the lock); only positive proof releases it.

    Two proofs, both observed for real on 2026-07-20 (#5012):
      1. the pid is simply gone — a `docker exec` wrapper was killed mid-backup (pid 1550).
      2. the pid exists but STARTED AFTER the lock was written — so it cannot be the owner.
         This is the container-restart case: a backup began at 15:35:57 as pid 1, the
         container restarted at 15:37:10, and pid 1 existed again. A bare "is pid 1 alive?"
         check says yes forever, which is why proof #1 alone is not enough.
    """
    exists = _exists or (lambda p: os.path.exists("/proc/%d" % int(p)))
    start_time = _start_time or _proc_start_time

    pid = lock_data.get("pid")
    if not pid:
        return False, "no pid recorded in lock"
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, "unreadable pid in lock"

    if not exists(pid):
        return True, f"owner pid {pid} no longer exists"

    started = start_time(pid)
    if started is None:
        return False, f"pid {pid} exists; start time unavailable"

    lock_ts = lock_data.get("timestamp")
    if not lock_ts:
        return False, f"pid {pid} exists; lock has no timestamp"

    # The owner necessarily started BEFORE it wrote the lock. A later start means this pid
    # belongs to a different process (restart or pid reuse). 2s tolerance for clock coarseness.
    if started > lock_ts + 2:
        return True, f"pid {pid} started after the lock was written — original owner is gone"

    return False, f"pid {pid} is alive and owns the lock"


def acquire_backup_lock(backup_name, created_by):
    """Acquire exclusive backup lock, returns (success, error_msg)"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                lock_data = json.load(f)
            lock_age = time.time() - lock_data.get("timestamp", 0)
            if lock_age < LOCK_TIMEOUT:
                # Before honouring it, check the owner is actually alive (#5012). Without
                # this, a backup killed mid-run (container restart, killed wrapper) leaves
                # an orphan that blocks EVERY backup — and therefore every medium-risk
                # deploy, since the W.A.R.D.E.N. gate needs a fresh one — for the full 2h
                # LOCK_TIMEOUT. That happened twice on 2026-07-20.
                dead, why = lock_owner_is_dead(lock_data)
                if not dead:
                    backup_name = lock_data.get("backup_name", "unknown")
                    created_by = lock_data.get("created_by", "unknown")
                    msg = f"Backup '{backup_name}' in progress by {created_by} (started {int(lock_age)}s ago)"
                    return (False, msg)
                try:
                    current_app.logger.warning(
                        "Releasing orphaned backup lock for '%s' (%s): %s",
                        lock_data.get("backup_name", "unknown"),
                        lock_data.get("created_by", "unknown"),
                        why,
                    )
                except Exception:
                    pass  # no app context (CLI/worker) — never block on logging
            # Stale or orphaned lock, remove it
            os.remove(LOCK_FILE)
        except (json.JSONDecodeError, IOError):
            # Corrupted lock file, remove it
            os.remove(LOCK_FILE)

    try:
        with open(LOCK_FILE, "w") as f:
            json.dump(
                {
                    "backup_name": backup_name,
                    "created_by": created_by,
                    "timestamp": time.time(),
                    "pid": os.getpid(),
                },
                f,
            )
        return True, None
    except Exception as e:
        return False, str(e)


def release_backup_lock():
    """Release backup lock"""
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except Exception as e:
            current_app.logger.warning(f"Failed to release backup lock file: {e}")


def check_backup_in_progress():
    """Check if backup is currently running"""
    if not os.path.exists(LOCK_FILE):
        return None
    try:
        with open(LOCK_FILE, "r") as f:
            lock_data = json.load(f)
        lock_age = time.time() - lock_data.get("timestamp", 0)
        if lock_age >= LOCK_TIMEOUT:
            return None  # Stale lock
        lock_data["age_seconds"] = int(lock_age)
        return lock_data
    except (json.JSONDecodeError, IOError):
        return None


# =============================================================================
# HOOK FUNCTIONS
# =============================================================================


def execute_hooks(hook_dir, backup_name, metadata=None):
    """Execute all scripts in hook directory"""
    results = []

    if not os.path.exists(hook_dir):
        return results

    try:
        scripts = sorted(os.listdir(hook_dir))
    except Exception as e:
        current_app.logger.warning(f"Failed to list hook scripts in {hook_dir}: {e}")
        return results

    for script in scripts:
        script_path = os.path.join(hook_dir, script)
        if not os.path.isfile(script_path) or not os.access(script_path, os.X_OK):
            continue

        env = os.environ.copy()
        env["ARCHIE_BACKUP_NAME"] = backup_name
        env["ARCHIE_BACKUP_DIR"] = BACKUP_DIR
        if metadata:
            env["ARCHIE_BACKUP_METADATA"] = json.dumps(metadata)

        try:
            result = subprocess.run(
                [script_path],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=env,
            )
            results.append(
                {
                    "script": script,
                    "success": result.returncode == 0,
                    "output": result.stdout[:1000] if result.stdout else "",
                    "error": (result.stderr[:500] if result.returncode != 0 and result.stderr else None),
                }
            )
        except subprocess.TimeoutExpired:
            results.append({"script": script, "success": False, "error": "Timeout after 5 minutes"})
        except Exception as e:
            results.append({"script": script, "success": False, "error": str(e)})

    return results


def execute_pre_hooks(backup_name):
    """Execute pre-backup hooks, fail backup if any hook fails"""
    results = execute_hooks(PRE_HOOKS_DIR, backup_name)
    failed = [r for r in results if not r["success"]]
    return len(failed) == 0, results


def execute_post_hooks(backup_name, metadata):
    """Execute post-backup hooks (failures logged but don't fail backup)"""
    return execute_hooks(POST_HOOKS_DIR, backup_name, metadata)


# =============================================================================
# WEBHOOK FUNCTIONS
# =============================================================================


def get_webhooks(event_type):
    """Get active webhooks for event type"""
    try:
        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, url, secret_key FROM backup_webhooks
                WHERE active = TRUE AND %s = ANY(event_types)
            """,
                (event_type,),
            )
            webhooks = cur.fetchall()
            return [{"id": w[0], "url": w[1], "secret_key": w[2]} for w in webhooks]
    except Exception as e:
        current_app.logger.error(f"Failed to fetch webhooks for event {event_type}: {e}")
        return []


def trigger_webhooks(event_type, payload):
    """Trigger all webhooks for an event"""
    webhooks = get_webhooks(event_type)
    results = []

    for webhook in webhooks:
        try:
            headers = {"Content-Type": "application/json"}
            if webhook.get("secret_key"):
                signature = hmac.new(
                    webhook["secret_key"].encode(),
                    json.dumps(payload).encode(),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Archie-Signature"] = signature

            response = requests.post(
                webhook["url"],
                json=payload,
                headers=headers,
                timeout=10,
            )
            results.append(
                {
                    "url": webhook["url"],
                    "status": response.status_code,
                    "success": 200 <= response.status_code < 300,
                }
            )

            # Update webhook last triggered
            try:
                with get_backup_db_cursor() as (conn, cur):
                    cur.execute(
                        "UPDATE backup_webhooks SET last_triggered = NOW(), last_status = %s WHERE id = %s",
                        (response.status_code, webhook["id"]),
                    )
            except Exception as e:
                current_app.logger.error(f"Failed to update webhook {webhook['id']} status: {e}")

        except Exception as e:
            results.append({"url": webhook["url"], "error": str(e), "success": False})

    return results


# =============================================================================
# RESTORE PREVIEW & SELECTIVE RESTORE FUNCTIONS
# =============================================================================


def preview_restore(backup_name):
    """Preview what would change during restore (dry-run).

    Supports two layouts:
    - Phase 1-6 pipeline: database/<ts>.dump + code/ + gitbundle(s)/ + config/ + volumes/
    - Legacy: database.sql.gz + platform_v2/ + ai_bridge/ + docs/ + scripts/ + nginx/ + n8n_workflows/
    """
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    if not os.path.exists(backup_path):
        return {"error": f"Backup {backup_name} not found"}

    preview = {
        "backup_name": backup_name,
        "components": [],
        "warnings": [],
        "database_tables": 0,
        "files_to_restore": 0,
        "total_size_bytes": 0,
    }

    # Detect pipeline — new pipeline has database/ subdir with .dump files.
    new_db_dir = os.path.join(backup_path, "database")
    is_new_pipeline = os.path.isdir(new_db_dir) and any(
        f.endswith(".dump") for f in (os.listdir(new_db_dir) if os.path.isdir(new_db_dir) else [])
    )

    if is_new_pipeline:
        # ---------- Phase 1-6 layout ----------
        # Database: pg_dump -Fc custom format. We report size + dump filename;
        # exact table count requires pg_restore --list which isn't available
        # in the app container. Metadata.json can tell us more if present.
        dumps = [f for f in os.listdir(new_db_dir) if f.endswith(".dump")]
        if dumps:
            # Prefer the archie dump (primary DB with knowledge_base). A bare sorted()[-1]
            # picks wtf/creed (alphabetically last) — the wrong-DB trap that caused #4050.
            dump_file = next((d for d in sorted(dumps) if d.startswith("archie_")), sorted(dumps)[-1])
            dump_path = os.path.join(new_db_dir, dump_file)
            dump_size = os.path.getsize(dump_path)
            preview["components"].append(
                {
                    "name": "database",
                    "file": f"database/{dump_file}",
                    "size_bytes": dump_size,
                    "compressed": True,
                    "format": "pg_dump custom (-Fc)",
                    "note": "Full DB dump; restore via pg_restore against a pgvector-capable postgres.",
                }
            )
            preview["total_size_bytes"] += dump_size
            # Real object/table count comes from metadata.json (written at backup time, #4049).
            _m = {}
            _mf = os.path.join(backup_path, "metadata.json")
            if os.path.exists(_mf):
                try:
                    with open(_mf) as _fh:
                        _m = json.load(_fh)
                except Exception:
                    _m = {}
            _dbmeta = next(
                (d for d in (_m.get("databases") or []) if str(d.get("file", "")).endswith(dump_file)),
                {},
            )
            if _dbmeta.get("table_count") is not None:
                preview["database_tables"] = _dbmeta["table_count"]
                preview["components"][-1]["object_count"] = _dbmeta.get("object_count")
                preview["components"][-1]["table_count"] = _dbmeta.get("table_count")
            else:
                preview["database_tables"] = "pg_dump archive — run restore_db.sh --into-scratch to verify"

        # Code: everything in code/ subdir (platform_v2 + ai_bridge + scripts + migrations)
        for comp_name in ("code", "gitbundles", "gitbundle", "config", "volumes"):
            comp_path = os.path.join(backup_path, comp_name)
            if not os.path.isdir(comp_path):
                continue
            file_count = sum(len(files) for _, _, files in os.walk(comp_path))
            size = sum(os.path.getsize(os.path.join(root, f)) for root, _, files in os.walk(comp_path) for f in files)
            entry = {
                "name": comp_name,
                "file_count": file_count,
                "size_bytes": size,
            }
            if comp_name == "config":
                entry["note"] = "Encrypted (AES-256-CBC) — restore with decrypt_restore.sh"
            preview["components"].append(entry)
            preview["files_to_restore"] += file_count
            preview["total_size_bytes"] += size

        # No legacy scan — skip straight to the metadata/version block.
        db_file = None
    else:
        # ---------- Legacy layout ----------
        db_file = os.path.join(backup_path, "database.sql.gz")
        if not os.path.exists(db_file):
            db_file = os.path.join(backup_path, "database.sql")

    # Fast-path: load metadata.json first for size/component info without expensive walks
    _meta = {}
    _meta_file = os.path.join(backup_path, "metadata.json")
    if os.path.exists(_meta_file):
        try:
            with open(_meta_file) as _f:
                _meta = json.load(_f)
        except Exception:
            pass

    if db_file and os.path.exists(db_file):
        db_size = os.path.getsize(db_file)
        preview["components"].append(
            {
                "name": "database",
                "file": os.path.basename(db_file),
                "size_bytes": db_size,
                "compressed": db_file.endswith(".gz"),
            }
        )
        preview["total_size_bytes"] += db_size

        # Get table count from metadata (fast) — avoid scanning large dump files
        table_count = _meta.get("database_table_count")
        if not table_count and not db_file.endswith(".gz"):
            # Only scan plain SQL (not gzip) — gzip scan is too slow for large files
            try:
                table_count = 0
                with open(db_file, "r", errors="replace") as f:
                    for line in f:
                        if "CREATE TABLE" in line:
                            table_count += 1
            except Exception:
                pass
        preview["database_tables"] = table_count or "see backup metadata"

    # Check platform and other directories — use os.stat (fast) not os.walk
    for dir_name in ["platform_v2", "ai_bridge", "docs", "scripts", "nginx", "n8n_workflows"]:
        dir_path = os.path.join(backup_path, dir_name)
        if not os.path.exists(dir_path):
            continue
        # Use du-style fast size via os.scandir rather than full os.walk
        try:
            dir_size = sum(
                entry.stat().st_size for entry in os.scandir(dir_path) if entry.is_file(follow_symlinks=False)
            )
            # Add a quick recursive estimate for subdirs (one level deep is enough for display)
            for entry in os.scandir(dir_path):
                if entry.is_dir(follow_symlinks=False):
                    try:
                        for sub in os.scandir(entry.path):
                            if sub.is_file(follow_symlinks=False):
                                dir_size += sub.stat().st_size
                    except Exception:
                        pass
            file_count = sum(1 for _ in os.scandir(dir_path))
        except Exception:
            dir_size = 0
            file_count = 0
        preview["components"].append(
            {
                "name": dir_name,
                "file_count": file_count,
                "size_bytes": dir_size,
            }
        )
        preview["files_to_restore"] += file_count
        preview["total_size_bytes"] += dir_size

    # Load metadata for version info
    metadata_file = os.path.join(backup_path, "metadata.json")
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            # TIMESTAMP SOURCE (#5121) — backup_log is THE source of truth
            # (.claude/rules/backup-manager.md), and the two writers disagree:
            # metadata.json on disk records NAIVE LOCAL (America/Toronto) while
            # backup_log.created_at records NAIVE UTC. Measured on backup_log 1910:
            #   metadata.json  2026-07-22T12:00:42.842740   (local)
            #   backup_log     2026-07-22T16:00:59.221632   (UTC, same event +16s)
            # Serving the manifest's already-local value made the client convert it a
            # SECOND time (ArchieTime treats it as UTC), so a 16:00 UTC backup rendered
            # as 08:00 in the Inspect modal while the row correctly showed 12:00 PM.
            # A wrong timestamp on the RESTORE path is a real hazard: "restore the 8 AM
            # backup" and "restore the noon backup" can select different artifacts.
            #
            # Prefer the ledger row; fall back to the manifest NORMALISED local->UTC so
            # the display layer's single conversion is correct either way.
            _created_at = metadata.get("created_at")
            _row_id = None
            try:
                with get_backup_db_cursor() as (_c, _cur):
                    _cur.execute(
                        "SELECT id, created_at FROM public.backup_log "
                        "WHERE file_path LIKE %s ORDER BY created_at DESC LIMIT 1",
                        (f"%{os.path.basename(backup_path)}%",),
                    )
                    _row = _cur.fetchone()
                # get_backup_db_cursor returns TUPLES, not dicts (backup-manager.md).
                if _row and _row[1]:
                    _row_id = _row[0]
                    _created_at = _row[1].isoformat()
            except Exception as _e:  # noqa: BLE001 - display path must never 500
                logger.warning("preview_restore: backup_log lookup failed (%s); normalising manifest ts", _e)
            if _row_id is None and _created_at:
                # No ledger row — the manifest value is naive LOCAL; convert to naive UTC.
                try:
                    from datetime import datetime as _dt
                    from datetime import timezone as _tz
                    from zoneinfo import ZoneInfo as _Z

                    # NB: datetime.timezone.utc, not ZoneInfo("UTC") — identical
                    # semantics, and it avoids a quoted literal that the timezone
                    # drift guardrail flags as a user-facing label (false positive
                    # on a tz constructor arg, but the stdlib form is cleaner anyway).
                    _naive = _dt.fromisoformat(str(_created_at))
                    if _naive.tzinfo is None:
                        _created_at = (
                            _naive.replace(tzinfo=_Z("America/Toronto")).astimezone(_tz.utc).replace(tzinfo=None)
                        ).isoformat()
                except Exception:  # noqa: BLE001 - leave the raw value rather than lose it
                    pass

            preview["backup_metadata"] = {
                "id": _row_id,
                "created_at": _created_at,
                "created_by": metadata.get("created_by"),
                "platform_version": metadata.get("platform_version"),
                "build_number": metadata.get("build_number"),
                "backup_type": metadata.get("backup_type"),
                "compression": metadata.get("compression"),
                "total_backup_size_bytes": metadata.get("total_size_bytes", 0),
                "total_backup_size_mb": metadata.get("total_size_mb", 0),
            }

            # Add info about non-restorable components (for user understanding).
            # Both pipelines' layouts are supported — restorable = everything
            # produced by either create_backup_programmatic (legacy) or
            # scripts/backup/run_backup.sh (phase-1-6).
            all_components = metadata.get("components", {})
            restorable = {
                # Legacy
                "database",
                "platform_v2",
                "ai_bridge",
                "docs",
                "scripts",
                "nginx",
                "n8n_workflows",
                "database_migrations",
                "n8n_persistence",
                "environment",
                "conversation_logs",
                # Phase 1-6
                "code",
                "gitbundle",
                "gitbundles",
                "config",
                "volumes",
                "convlogs",
                "kb_export",
                "vps_pull",
                "monthly_full",
            }
            non_restorable = [k for k, v in all_components.items() if v and k not in restorable]
            if non_restorable:
                preview["non_restorable_components"] = non_restorable

            # Check for version mismatch warning
            current_version = get_platform_version()
            backup_version = metadata.get("platform_version", "unknown")
            if current_version != backup_version:
                preview["warnings"].append(f"Version mismatch: current={current_version}, backup={backup_version}")
        except Exception:
            pass

    # Add estimated uncompressed size for database if compressed
    for comp in preview["components"]:
        if comp.get("name") == "database" and comp.get("compressed"):
            # Gzip typically achieves ~80% compression on SQL, so estimate 5x uncompressed
            comp["estimated_uncompressed_bytes"] = int(comp["size_bytes"] * 5)
            comp["estimated_uncompressed_mb"] = round(comp["size_bytes"] * 5 / (1024 * 1024), 1)

    preview["total_size_mb"] = round(preview["total_size_bytes"] / (1024 * 1024), 2)
    preview["restorable_size_bytes"] = preview["total_size_bytes"]
    preview["restorable_size_mb"] = preview["total_size_mb"]
    return preview


def _is_pg_custom_dump(path):
    """True if `path` is a pg_dump custom-format (-Fc) archive — binary, needs pg_restore (#4049)."""
    if path.endswith(".dump"):
        return True
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"PGDMP"
    except Exception:
        return False


def _db_from_dump_name(path):
    """Infer the logical DB name from a Phase 1-6 dump filename (archie_/wtf_/creed_<ts>.dump)."""
    base = os.path.basename(path)
    for db in ("archie", "wtf", "creed"):
        if base.startswith(db + "_"):
            return db
    return "archie"


HOST_BACKUP_DIR = "/mnt/data2/backups"  # host path operators use; BACKUP_DIR ("/backups") is the container mount


def _host_path(backup_path):
    """Translate an in-container backup path (/backups/...) to the host path operators run against.

    normpath() first so trailing/duplicate slashes (e.g. ``/backups//x/``) don't defeat the prefix
    match. The result is an informational command string, never executed by the platform. (#4049)
    """
    norm = os.path.normpath(backup_path)
    if norm == BACKUP_DIR or norm.startswith(BACKUP_DIR + os.sep):
        return HOST_BACKUP_DIR + norm[len(BACKUP_DIR) :]
    return backup_path


def _host_restore_command(backup_path, db="archie", force=False):
    """The exact host command an operator runs to restore a Phase 1-6 (-Fc) backup (KB #272184)."""
    flag = " --force" if force else ""
    return f"scripts/backup/restore_db.sh {_host_path(backup_path)} --db {db}{flag}"


def restore_database_from_backup(db_file_path):
    """Restore a database dump.

    Plain ``.sql`` / ``.sql.gz`` dumps are executed in-process. Binary pg_dump custom-format
    (``-Fc``, the Phase 1-6 ``database/*.dump`` layout) CANNOT be ``cur.execute()``'d — and the
    platform cannot DROP+restore its own live DB anyway — so we refuse and hand back the exact
    host command (``scripts/backup/restore_db.sh``). Runbook: KB #272184. (Task #4049.)
    """
    if not os.path.exists(db_file_path):
        return {"success": False, "error": f"Database file not found: {db_file_path}"}

    # Guard: never feed a binary -Fc archive to cur.execute() (silent corruption / failure).
    if _is_pg_custom_dump(db_file_path):
        db = _db_from_dump_name(db_file_path)
        backup_path = os.path.dirname(os.path.dirname(db_file_path))  # <dir>/database/x.dump -> <dir>
        return {
            "success": False,
            "requires_host_restore": True,
            "format": "pg_dump custom (-Fc)",
            "error": (
                "Binary pg_dump archive — restore via host script, not the UI (the platform "
                "cannot DROP+restore its own live DB). See runbook KB #272184."
            ),
            "host_command": _host_restore_command(backup_path, db=db, force=True),
            "verify_command": _host_restore_command(backup_path, db=db, force=False),
            "kb": "#272184",
        }

    try:
        # Read SQL content (legacy plain / gzip dumps only)
        if db_file_path.endswith(".gz"):
            with gzip.open(db_file_path, "rt", encoding="utf-8") as f:
                sql_content = f.read()
        else:
            with open(db_file_path, "r") as f:
                sql_content = f.read()

        # Execute SQL
        with get_backup_db_cursor() as (conn, cur):
            cur.execute(sql_content)

        return {"success": True}
    except Exception as e:
        current_app.logger.error(f"Database restore failed: {e}")
        return {"success": False, "error": str(e)}


def restore_components(backup_name, components):
    """Restore specific components from backup"""
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        return {"success": False, "error": f"Backup {backup_name} not found"}

    results = {"restored": [], "errors": [], "warnings": []}

    if "database" in components:
        try:
            # Phase 1-6 layout: database/<db>_<ts>.dump (pg_dump -Fc) — cannot restore in-process.
            new_db_dir = os.path.join(backup_path, "database")
            dumps = (
                sorted(f for f in os.listdir(new_db_dir) if f.endswith(".dump")) if os.path.isdir(new_db_dir) else []
            )
            if dumps:
                archie_dump = next((f for f in dumps if f.startswith("archie_")), dumps[0])
                guard = restore_database_from_backup(os.path.join(new_db_dir, archie_dump))
                # Expected: requires_host_restore — surface the host command, never a silent no-op.
                results["warnings"].append(
                    {
                        "component": "database",
                        "requires_host_restore": True,
                        "message": guard.get("error", "Restore the database via host script."),
                        "host_command": guard.get("host_command"),
                        "verify_command": guard.get("verify_command"),
                        "kb": guard.get("kb", "#272184"),
                    }
                )
            else:
                # Legacy layout: plain / gzip SQL is executed in-process.
                db_file = os.path.join(backup_path, "database.sql.gz")
                if not os.path.exists(db_file):
                    db_file = os.path.join(backup_path, "database.sql")

                if os.path.exists(db_file):
                    restore_result = restore_database_from_backup(db_file)
                    if restore_result["success"]:
                        results["restored"].append("database")
                    else:
                        results["errors"].append({"component": "database", "error": restore_result["error"]})
                else:
                    results["errors"].append(
                        {
                            "component": "database",
                            "error": "Database file not found in backup",
                        }
                    )
        except Exception as e:
            results["errors"].append({"component": "database", "error": str(e)})

    if "platform" in components:
        try:
            platform_src = os.path.join(backup_path, "platform_v2")
            if os.path.exists(platform_src):
                for subdir in ["tools", "templates", "static"]:
                    src = os.path.join(platform_src, subdir)
                    dst = os.path.join(PLATFORM_DIR, subdir)
                    if os.path.exists(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                results["restored"].append("platform")
            else:
                results["errors"].append(
                    {
                        "component": "platform",
                        "error": "Platform directory not found in backup",
                    }
                )
        except Exception as e:
            results["errors"].append({"component": "platform", "error": str(e)})

    # Restore other components
    component_paths = {
        "ai_bridge": ("/mnt/archie_brain/ai_bridge", "ai_bridge"),
        "docs": ("/mnt/archie_brain/docs", "docs"),
        "scripts": ("/mnt/archie_brain/scripts", "scripts"),
        "nginx": ("/mnt/archie_brain/nginx", "nginx"),
        "n8n_workflows": ("/mnt/archie_brain/n8n_workflows", "n8n_workflows"),
    }

    for comp_name, (dst_path, src_subdir) in component_paths.items():
        if comp_name in components:
            try:
                src = os.path.join(backup_path, src_subdir)
                if os.path.exists(src):
                    shutil.copytree(src, dst_path, dirs_exist_ok=True)
                    results["restored"].append(comp_name)
                else:
                    results["warnings"].append(f"{comp_name} not found in backup")
            except Exception as e:
                results["errors"].append({"component": comp_name, "error": str(e)})

    results["success"] = len(results["errors"]) == 0
    return results


# =============================================================================
# BACKUP COMPARISON FUNCTIONS
# =============================================================================


def get_all_files(directory):
    """Get list of all files relative to directory"""
    files = []
    for root, dirs, filenames in os.walk(directory):
        for f in filenames:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, directory)
            files.append(rel_path)
    return files


def file_hash(filepath):
    """Get SHA256 hash of file"""
    hasher = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def compare_backups(backup1_name, backup2_name):
    """Compare two backups and show differences"""
    backup1_path = os.path.join(BACKUP_DIR, backup1_name)
    backup2_path = os.path.join(BACKUP_DIR, backup2_name)

    if not os.path.exists(backup1_path):
        return {"error": f"Backup {backup1_name} not found"}
    if not os.path.exists(backup2_path):
        return {"error": f"Backup {backup2_name} not found"}

    comparison = {
        "backup1": backup1_name,
        "backup2": backup2_name,
        "metadata_diff": {},
        "file_changes": {
            "added": [],
            "removed": [],
            "modified": [],
        },
    }

    # Compare metadata
    try:
        with open(os.path.join(backup1_path, "metadata.json")) as f:
            meta1 = json.load(f)
        with open(os.path.join(backup2_path, "metadata.json")) as f:
            meta2 = json.load(f)

        comparison["metadata_diff"] = {
            "build_number": {
                "old": meta1.get("build_number"),
                "new": meta2.get("build_number"),
            },
            "platform_version": {
                "old": meta1.get("platform_version"),
                "new": meta2.get("platform_version"),
            },
            "created_at": {
                "old": meta1.get("created_at"),
                "new": meta2.get("created_at"),
            },
        }
    except Exception:
        pass

    # Compare file lists (exclude metadata.json and rollback.sh)
    exclude = {"metadata.json", "rollback.sh"}
    files1 = set(f for f in get_all_files(backup1_path) if f not in exclude)
    files2 = set(f for f in get_all_files(backup2_path) if f not in exclude)

    comparison["file_changes"]["added"] = sorted(list(files2 - files1))[:100]  # Limit to 100
    comparison["file_changes"]["removed"] = sorted(list(files1 - files2))[:100]

    # Check modified files (same name, different content) - limit to first 50 common files
    common_files = list(files1 & files2)[:50]
    for f in common_files:
        hash1 = file_hash(os.path.join(backup1_path, f))
        hash2 = file_hash(os.path.join(backup2_path, f))
        if hash1 and hash2 and hash1 != hash2:
            comparison["file_changes"]["modified"].append(f)

    comparison["summary"] = {
        "files_added": len(files2 - files1),
        "files_removed": len(files1 - files2),
        "files_modified": len(comparison["file_changes"]["modified"]),
        "files_unchanged": len(files1 & files2) - len(comparison["file_changes"]["modified"]),
    }

    return comparison


def _discard_partial_dump(path):
    """Remove a half-written dump. Never leave a plausible-looking unrestorable artifact."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:  # pragma: no cover - defensive
        try:
            current_app.logger.error(f"could not remove partial dump {path}: {exc}")
        except Exception:
            pass


def _pg_dump_env():
    """Environment for pg_dump, resolving the password from env or Docker secret."""
    env = os.environ.copy()
    pw = os.getenv("DB_PASSWORD") or ""
    if not pw:
        secret_file = os.getenv("DB_PASSWORD_FILE", "")
        if secret_file and os.path.exists(secret_file):
            try:
                with open(secret_file) as _sf:
                    pw = _sf.read().strip()
            except OSError:
                pass
    if pw:
        env["PGPASSWORD"] = pw
    return env


def get_cloud_backup_passphrase():
    """Owner-set passphrase used to encrypt the single Google Drive (cloud) backup zip.

    The cloud recovery copy is one zip, AES-encrypted with THIS passphrase, so a restore needs
    only the passphrase. It is an OWNER SECRET — set once, never handled by an assistant.

    IMPORTANT: the platform login password CANNOT be used as this key. Logins are stored one-way
    HASHED (werkzeug generate_password_hash); the plaintext is never available — not to a person,
    not to the nightly backup (which runs with no session). This is therefore a DEDICATED
    passphrase the owner sets once; they may choose it to be the same string as their password.

    Resolution order: BACKUP_CLOUD_PASSPHRASE env, then a Docker-secret file at
    BACKUP_CLOUD_PASSPHRASE_FILE. Returns None if unset — the cloud-encryption step MUST fail
    closed (refuse to upload an unencrypted backup) when this is None.
    """
    pw = os.getenv("BACKUP_CLOUD_PASSPHRASE") or ""
    if not pw:
        secret_file = os.getenv("BACKUP_CLOUD_PASSPHRASE_FILE", "")
        if secret_file and os.path.exists(secret_file):
            try:
                with open(secret_file) as _sf:
                    pw = _sf.read().strip()
            except OSError:
                pass
    return pw or None


def backup_database_python(output_file, compress=True):
    """Dump the database to a gzipped plain-SQL file using pg_dump.

    Despite the legacy name this no longer hand-rolls SQL. It used to, and the SQL it
    produced WAS NOT RESTORABLE (#5080):

      * Values went through a serializer whose fallback was `str(val).replace("'", "''")`.
        psycopg2 hands back a Python dict/list for json/jsonb, so a JSON column was written
        as a PYTHON REPR — single-quoted — and psql rejected it with
        `invalid input syntax for type json`. bytea became `<memory at 0x...>`, i.e. silent
        data loss rather than an error.
      * The CREATE TABLE text was built from `information_schema.columns.data_type`, which
        returns the literal string `ARRAY` for any array column, emitting `col ARRAY` and
        `syntax error at or near "ARRAY"`.

    Every UI/programmatic backup was therefore recorded `status='success'`, had a plausible
    size, was counted by the posture monitor — and could not be restored. Discovered only
    once #5036 made the sandbox restore path reach these files at all.

    pg_dump already solves this correctly (json, arrays, bytea, enums, sequences,
    constraints, encoding) and is present in the image, so the hand-rolled generator is gone.
    Output stays `<...>.sql.gz` = gzipped PLAIN SQL, which is exactly what the name always
    claimed and what the restore path (`gunzip | psql`) already expects — so callers and the
    restore ladder are unchanged.

    Memory stays bounded by streaming the pipe in fixed chunks; the OOM that motivated the
    previous rewrite (#5014/#2365) cannot recur because no dump content is held in Python.

    Args:
        output_file: Base output path (".gz" appended when compress=True)
        compress: gzip the output (default True)

    Returns:
        str: the path actually written
    """
    if compress and not output_file.endswith(".gz"):
        output_path = output_file + ".gz"
    else:
        output_path = output_file

    cmd = [
        "pg_dump",
        "-h",
        os.getenv("DB_HOST", "192.168.1.200"),
        "-p",
        str(os.getenv("DB_PORT", "5432")),
        "-U",
        os.getenv("DB_USER", "archie"),
        "-d",
        os.getenv("DB_NAME", "archie"),
        "--no-owner",
        "--no-privileges",
        "--format=plain",
    ]

    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_pg_dump_env())
        opener = gzip.open(output_path, "wb") if compress else open(output_path, "wb")
        with opener as fh:
            while True:
                chunk = proc.stdout.read(_DUMP_CHUNK_BYTES)
                if not chunk:
                    break
                fh.write(chunk)
        stderr = (proc.stderr.read() or b"").decode("utf-8", "replace")
        rc = proc.wait()
    except Exception as e:
        current_app.logger.error(f"Database backup failed: {str(e)}")
        _discard_partial_dump(output_path)
        raise
    finally:
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except OSError:
                    pass

    if rc != 0:
        # Delete the partial artifact. Leaving a truncated file behind is the precise
        # failure this whole class of bug is made of: something that looks like a backup,
        # is logged as one, and cannot be restored.
        _discard_partial_dump(output_path)
        raise RuntimeError(f"pg_dump exited {rc}: {stderr.strip()[-500:]}")

    # An empty/near-empty artifact means pg_dump "succeeded" while writing nothing.
    size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    if size < _MIN_DUMP_BYTES:
        _discard_partial_dump(output_path)
        raise RuntimeError(f"pg_dump produced an implausibly small dump ({size} bytes); refusing to record it")

    return output_path


# =============================================================================
# Cloud / deployment helpers (recovered from inter-route locations in monolith)
# =============================================================================


def get_platform_version():
    """Get current platform version — system_config is the single source of truth."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key='platform_version'")
            row = cur.fetchone()
            if row and row["value"]:
                return row["value"]
    except Exception:
        pass
    # Fallback: CHANGELOG.md
    try:
        import re

        changelog_path = "/mnt/archie_brain/docs/CHANGELOG.md"
        if os.path.exists(changelog_path):
            with open(changelog_path, "r") as f:
                for line in f:
                    if line.startswith("## [") or line.startswith("## v"):
                        match = re.search(r"[\d]+\.[\d]+\.[\d]+", line)
                        if match:
                            return match.group()
    except Exception:
        pass
    return "5.33.0"


def generate_deploy_script(package_name, components):
    """Generate the deploy.sh script for deployment packages"""
    version = get_platform_version()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. Deployment Script
# Package: {package_name}
# Version: {version}
# Generated: {timestamp}
# ============================================================================

set -e

# Colors
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
CYAN='\\033[0;36m'
NC='\\033[0m'

echo ""
echo -e "${{CYAN}}╔═══════════════════════════════════════════════════════════════════╗${{NC}}"
echo -e "${{CYAN}}║     A.R.C.H.I.E. Deployment Package Installer v{version}           ║${{NC}}"
echo -e "${{CYAN}}║   Autonomous Resource & Coordination Hub for                      ║${{NC}}"
echo -e "${{CYAN}}║              Intelligent Execution                                ║${{NC}}"
echo -e "${{CYAN}}╚═══════════════════════════════════════════════════════════════════╝${{NC}}"
echo ""

# Configuration
TARGET_DIR="${{1:-/mnt/archie_brain}}"
DB_PASSWORD="${{2:-$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)}}"
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

echo -e "${{YELLOW}}Target Directory:${{NC}} $TARGET_DIR"
echo -e "${{YELLOW}}Script Directory:${{NC}} $SCRIPT_DIR"
echo ""

# ============================================================================
# PREREQUISITES CHECK
# ============================================================================

echo -e "${{CYAN}}[1/6] Checking prerequisites...${{NC}}"

# Check root
if [ "$EUID" -ne 0 ]; then
    echo -e "${{RED}}Error: Please run as root (sudo)${{NC}}"
    exit 1
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${{RED}}Error: Docker not installed${{NC}}"
    echo "Install with: curl -fsSL https://get.docker.com | sh"
    exit 1
fi
echo "  ✓ Docker installed"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${{RED}}Error: Docker Compose not installed${{NC}}"
    exit 1
fi
echo "  ✓ Docker Compose installed"

# Check disk space (need at least 5GB)
AVAILABLE_GB=$(df -BG "${{TARGET_DIR%/*}}" 2>/dev/null | awk 'NR==2 {{print $4}}' | tr -d 'G')
if [ -n "$AVAILABLE_GB" ] && [ "$AVAILABLE_GB" -lt 5 ]; then
    echo -e "${{YELLOW}}Warning: Low disk space (${{AVAILABLE_GB}}GB available)${{NC}}"
fi
echo "  ✓ Disk space: ${{AVAILABLE_GB}}GB available"

# ============================================================================
# CREATE DIRECTORY STRUCTURE
# ============================================================================

echo ""
echo -e "${{CYAN}}[2/6] Creating directory structure...${{NC}}"

mkdir -p "$TARGET_DIR"
mkdir -p "$TARGET_DIR/backups"
mkdir -p "$TARGET_DIR/persistence/postgres"
mkdir -p "$TARGET_DIR/persistence/n8n"
mkdir -p "$TARGET_DIR/logs"

echo "  ✓ Created $TARGET_DIR"

# ============================================================================
# COPY FILES
# ============================================================================

echo ""
echo -e "${{CYAN}}[3/6] Copying platform files...${{NC}}"

# Copy all directories
for dir in platform_v2 ai_bridge docs database scripts nginx node_client; do
    if [ -d "$SCRIPT_DIR/$dir" ]; then
        cp -r "$SCRIPT_DIR/$dir" "$TARGET_DIR/"
        echo "  ✓ Copied $dir"
    fi
done

# Copy docker-compose.yml
if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    cp "$SCRIPT_DIR/docker-compose.yml" "$TARGET_DIR/"
    echo "  ✓ Copied docker-compose.yml"
fi

# ============================================================================
# CONFIGURE ENVIRONMENT
# ============================================================================

echo ""
echo -e "${{CYAN}}[4/6] Configuring environment...${{NC}}"

# Create .env file
cat > "$TARGET_DIR/.env" << ENVEOF
# A.R.C.H.I.E. Platform Configuration
# Generated by deployment script

# Database
DB_HOST=archie_database
DB_NAME=archie
DB_USER=archie
DB_PASSWORD=$DB_PASSWORD
DB_PORT=5432

# Platform
FLASK_ENV=production
SECRET_KEY=$(openssl rand -hex 32)
PLATFORM_PORT=3000

# Ollama (optional - can be local or remote)
OLLAMA_HOST=http://localhost:11434

# External APIs (optional - add your keys)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
ENVEOF

chmod 600 "$TARGET_DIR/.env"
echo "  ✓ Created .env configuration"

# ============================================================================
# START CONTAINERS
# ============================================================================

echo ""
echo -e "${{CYAN}}[5/6] Starting Docker containers...${{NC}}"

cd "$TARGET_DIR"

# Start database first
echo "  Starting database..."
docker-compose up -d archie_database
sleep 10

# Check database is ready
for i in {{1..30}}; do
    if docker exec archie_database pg_isready -U archie &>/dev/null; then
        echo "  ✓ Database ready"
        break
    fi
    sleep 1
done

# Restore database if backup exists
if [ -f "$SCRIPT_DIR/database.sql" ]; then
    echo "  Restoring database..."
    docker exec -i archie_database psql -U archie -d archie < "$SCRIPT_DIR/database.sql"
    echo "  ✓ Database restored"
fi

# Start platform
echo "  Starting platform..."
docker-compose up -d archie_platform
sleep 5

# ============================================================================
# VERIFY DEPLOYMENT
# ============================================================================

echo ""
echo -e "${{CYAN}}[6/6] Verifying deployment...${{NC}}"

# Wait for platform to be ready
for i in {{1..30}}; do
    if curl -s http://localhost:3000/health &>/dev/null; then
        echo "  ✓ Platform is responding"
        break
    fi
    sleep 2
done

# Final health check
HEALTH=$(curl -s http://localhost:3000/health 2>/dev/null || echo "failed")
if [[ "$HEALTH" == *"healthy"* ]] || [[ "$HEALTH" == *"ok"* ]]; then
    echo -e "${{GREEN}}  ✓ Health check passed${{NC}}"
else
    echo -e "${{YELLOW}}  ⚠ Health check returned: $HEALTH${{NC}}"
fi

# ============================================================================
# COMPLETE
# ============================================================================

echo ""
echo -e "${{GREEN}}╔═══════════════════════════════════════════════════════════════════╗${{NC}}"
echo -e "${{GREEN}}║              Deployment Complete!                                 ║${{NC}}"
echo -e "${{GREEN}}╚═══════════════════════════════════════════════════════════════════╝${{NC}}"
echo ""
echo -e "Access A.R.C.H.I.E. at: ${{CYAN}}http://$(hostname -I | awk '{{print $1}}'):3000${{NC}}"
echo ""
echo "Useful commands:"
echo "  cd $TARGET_DIR && docker-compose logs -f     # View logs"
echo "  cd $TARGET_DIR && docker-compose restart     # Restart services"
echo "  cd $TARGET_DIR && docker-compose down        # Stop services"
echo ""
echo -e "${{YELLOW}}IMPORTANT: Save this database password securely!${{NC}}"
echo -e "Database Password: ${{RED}}$DB_PASSWORD${{NC}}"
echo ""
"""


_cloud_progress = {}


CLOUD_EXCLUDE_DIRS = {
    "conversation_logs",
    "persistence",
    "docs",
}


def _cloud_tar_filter(tarinfo):
    """Exclude non-essential dirs from cloud backup tar."""
    parts = tarinfo.name.split("/")
    if len(parts) >= 2 and parts[1] in CLOUD_EXCLUDE_DIRS:
        return None
    return tarinfo


GDRIVE_PASSPHRASE_HASH_KEY = "backup:gdrive:passphrase_hash"


def _get_gdrive_passphrase_hash() -> str:
    """Read the operator passphrase hash — DB FIRST, env only as a fallback.

    ⚠️ This MUST NOT be stored in os.environ / .env (#5125). Two independent
    reasons, both observed live:

      1. archie_platform runs gunicorn with --workers 4. `_update_env_var` does
         `os.environ[key] = value`, which reaches only the ONE worker that
         handled the POST — the other three keep answering "incorrect
         passphrase", so setting a passphrase appears to fail at random.
      2. `_update_env_var` writes to /app/.env, and /app is the bind-mount of
         platform_v2/ — so it lands in platform_v2/.env, a file the container
         NEVER loads (docker-compose uses `env_file: .env`, the ROOT one, where
         this key exists with an EMPTY value). So it also does not survive a
         restart.

    platform_settings is shared by every worker and is durable, which is what a
    credential verifier needs. Only the SHA-256 hash is stored here, never the
    passphrase itself.
    """
    try:
        with get_backup_db_cursor() as (_conn, _cur):
            _cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s",
                (GDRIVE_PASSPHRASE_HASH_KEY,),
            )
            row = _cur.fetchone()  # NOTE: this cursor yields TUPLES, not dicts
            if row and row[0]:
                return str(row[0]).strip()
    except Exception:
        # Never let a settings-table hiccup take down the whole Cloud tab.
        pass
    return os.environ.get("GDRIVE_ENCRYPTION_PASSPHRASE_HASH", "")


def _set_gdrive_passphrase_hash(passphrase_hash: str) -> None:
    """Persist the passphrase hash so ALL gunicorn workers see it, durably."""
    with get_backup_db_cursor(commit=True) as (_conn, _cur):
        _cur.execute(
            "INSERT INTO platform_settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (GDRIVE_PASSPHRASE_HASH_KEY, passphrase_hash),
        )
    # Keep the current process consistent too; the DB row is the source of truth.
    os.environ["GDRIVE_ENCRYPTION_PASSPHRASE_HASH"] = passphrase_hash


def _get_cloud_config():
    """Read Google Drive configuration from environment."""
    return {
        "enabled": os.environ.get("GDRIVE_ENABLED", "false").lower() == "true",
        "service_account_path": os.environ.get(
            "GDRIVE_SERVICE_ACCOUNT_PATH",
            "/app/credentials/gdrive-service-account.json",
        ),
        "folder_id": os.environ.get("GDRIVE_BACKUP_FOLDER_ID", ""),
        "passphrase_hash": _get_gdrive_passphrase_hash(),
        # The secret that ACTUALLY protects every object currently in Drive.
        # scripts/backup/tier_sync_gdrive.py (host cron) encrypts with this;
        # GDRIVE_ENCRYPTION_PASSPHRASE_HASH is a hash of a DIFFERENT, older
        # passphrase and is not even present in the container (it lives only in
        # platform_v2/.env, which archie_platform does not load — it uses root
        # .env). Gating recovery on the hash alone made the Cloud tab hide
        # itself while 37 perfectly good off-site backups sat there (#5124).
        "server_passphrase": os.environ.get("BACKUP_GDRIVE_PASSPHRASE", ""),
        # The config tier is encrypted UPSTREAM by scripts/backup/component_config.sh
        # under its own secret, and tier_sync_gdrive.py uploads an already-.enc file
        # without re-encrypting it — so `<run>/config/*.enc` in Drive needs THIS key,
        # not the gdrive one. Verified against live objects 2026-07-22.
        "config_passphrase": os.environ.get("BACKUP_CONFIG_PASSPHRASE", ""),
    }


def _gdrive_is_fully_configured() -> tuple[bool, str]:
    """
    Return (True, "") when GDrive is enabled AND at least one credential path
    is present (OAuth token file, Work Suite google_accounts row, or service
    account JSON).  Return (False, reason) otherwise so callers can write a
    clean 'skipped' log entry instead of crashing.
    """
    config = _get_cloud_config()
    if not config["enabled"]:
        return False, "GDRIVE_ENABLED is not set to true"

    # Service account file present?
    if os.path.exists(config["service_account_path"]):
        return True, ""

    # Dedicated OAuth token file present?
    token_path = os.environ.get("GDRIVE_TOKEN_PATH", "/app/credentials/gdrive-oauth-token.json")
    if os.path.exists(token_path):
        return True, ""

    # Work Suite google_accounts row with Drive scope?
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT id FROM google_accounts "
                "WHERE (scopes IS NULL OR scopes ILIKE %s) AND refresh_token IS NOT NULL "
                "LIMIT 1",
                ("%drive%",),
            )
            if cur.fetchone():
                return True, ""
    except Exception as _db_err:
        logger.warning("DB unavailable checking google_accounts: %s", _db_err)
        return False, "DB unavailable — could not verify GDrive credentials"

    return (
        False,
        "GDrive enabled but no credentials found — connect via "
        "/tools/google-work-suite or upload a service account JSON",
    )


def _update_env_var(key, value):
    """Update an environment variable in memory and in the .env file."""
    os.environ[key] = value
    env_path = "/app/.env"
    if not os.path.exists(env_path):
        return
    lines = []
    found = False
    with open(env_path, "r") as f:
        for line in f:
            if line.strip().startswith(f"{key}="):
                lines.append(f"{key}={value}\n")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
