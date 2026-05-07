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

from flask import Blueprint, render_template, jsonify, request, send_file, current_app
from functools import wraps
from flask_login import current_user
import logging
import os

logger = logging.getLogger(__name__)
from database import _get_db_password
import subprocess
import json
from datetime import datetime, timedelta
import shutil
import tarfile
import tempfile
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
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

    try:
        # Generate backup name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}_{description.replace(' ', '_')}"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

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

        # Copy to external storage if available
        external_result = {"success": False, "error": "External storage not mounted"}
        if is_external_storage_available():
            print("  Copying to external storage...")
            external_result = copy_to_external_storage(backup_name, backup_path)
            if external_result["success"]:
                print(f"  ✓ External copy complete ({external_result.get('size_mb', 0)} MB)")
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


def backup_module(module_name, proposal_id=None, created_by_username="system"):
    """
    Backup a single module for isolated sandbox testing

    Args:
        module_name: e.g., 'improvements', 'backup_manager', 'consciousness'
        proposal_id: Optional link to proposal
        created_by_username: Who created this backup

    Returns:
        {
            'success': True,
            'backup_name': '20260114_150302_module_improvements',
            'backup_path': '/mnt/archie_brain/backups/modules/...',
            'files_backed_up': [...]
        }
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}_module_{module_name}"
        backup_path = os.path.join(BACKUP_DIR, "modules", backup_name)

        os.makedirs(backup_path, exist_ok=True)

        files_backed_up = []

        # 1. Backup tool routes
        tool_src = os.path.join(PLATFORM_DIR, "tools", module_name)
        if os.path.exists(tool_src):
            tool_dst = os.path.join(backup_path, "tools", module_name)
            shutil.copytree(tool_src, tool_dst, dirs_exist_ok=True)
            files_backed_up.append(f"tools/{module_name}/")

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

        # 3. Backup related static JS
        js_dir = os.path.join(PLATFORM_DIR, "static", "js", module_name)
        if os.path.exists(js_dir):
            js_dst = os.path.join(backup_path, "static", "js", module_name)
            shutil.copytree(js_dir, js_dst, dirs_exist_ok=True)
            files_backed_up.append(f"static/js/{module_name}/")

        # 4. Create metadata
        metadata = {
            "name": backup_name,
            "type": "module",
            "module_name": module_name,
            "timestamp": timestamp,
            "created_by": created_by_username,
            "proposal_id": proposal_id,
            "files_backed_up": files_backed_up,
        }

        with open(os.path.join(backup_path, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        return {
            "success": True,
            "backup_name": backup_name,
            "backup_path": backup_path,
            "files_backed_up": files_backed_up,
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

# Hook directories
HOOKS_DIR = os.path.join(BACKUP_DIR, ".hooks")
PRE_HOOKS_DIR = os.path.join(HOOKS_DIR, "pre")
POST_HOOKS_DIR = os.path.join(HOOKS_DIR, "post")

# Ensure backup directory exists
os.makedirs(BACKUP_DIR, exist_ok=True)

# =============================================================================
# STANDALONE PRODUCTS REGISTRY
# =============================================================================

STANDALONE_PRODUCTS = [
    {
        "name": "kbs",
        "display_name": "Kytran Business Suite",
        "code_path": "/mnt/archie_brain/kytran-business-suite",
        "db_schema": "kbs",
        "backup_type": "full",
    },
    {
        "name": "media_hub",
        "display_name": "Media Hub",
        "code_path": "/mnt/archie_brain/standalone/media_hub",
        "db_schema": "media_hub",
        "backup_type": "config_only",
        "exclude_paths": ["/mnt/Plex", "/mnt/data2", "media/", "data/"],
        "exclude_extensions": [".mkv", ".mp4", ".avi", ".mov", ".m4v", ".iso"],
    },
    {
        "name": "creed",
        "display_name": "C.R.E.E.D. Governance",
        "code_path": "/mnt/archie_brain/kytran-creed",
        "db_schema": "creed",
        "backup_type": "full",
    },
    {
        "name": "kso",
        "display_name": "Kytran System Operations",
        "code_path": "/mnt/archie_brain/kytran-server-manager",
        "db_schema": "kso",
        "backup_type": "full",
    },
    {
        "name": "gov_watch",
        "display_name": "Gov Watch",
        "code_path": "/mnt/standalone/kytran-gov-watch",
        "db_schema": "gov_watch",
        "backup_type": "full",
    },
    {
        "name": "civic_watch",
        "display_name": "Civic Watch",
        "code_path": "/mnt/standalone/kytran-civic-watch",
        "db_schema": "civic_watch",
        "backup_type": "full",
    },
    {
        "name": "legal_watch",
        "display_name": "Legal Watch",
        "code_path": "/mnt/standalone/kytran-legal-watch",
        "db_schema": "legal_watch",
        "backup_type": "full",
    },
    {
        "name": "market_watch",
        "display_name": "Market Watch",
        "code_path": "/mnt/standalone/kytran-market-watch",
        "db_schema": "market_watch",
        "backup_type": "full",
    },
    {
        "name": "wtf",
        "display_name": "What The Fact",
        "code_path": "/mnt/archie_brain/what-the-fact",
        "db_schema": "wtf",
        "backup_type": "full",
    },
]


def backup_standalone(standalone_name):
    """Backup one standalone: pg_dump of its schema + code tar.gz.
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

    # 1. pg_dump of schema
    db_dump_path = os.path.join(backup_path, f"{standalone_name}_schema.sql")
    pg_env = os.environ.copy()
    if os.getenv("DB_PASSWORD"):
        pg_env["PGPASSWORD"] = os.getenv("DB_PASSWORD", "")
    try:
        result = subprocess.run(
            [
                "pg_dump",
                "-h",
                os.getenv("DB_HOST", "192.168.1.200"),
                "-U",
                os.getenv("DB_USER", "archie"),
                "-d",
                os.getenv("DB_NAME", "archie"),
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
        errors.append(f"code_path not found: {code_path}")

    db_size = os.path.getsize(db_dump_path) if os.path.exists(db_dump_path) else 0
    total_size = code_size + db_size
    status = "success" if not errors else "failed"

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

    return {"success": not errors, "backup_name": backup_name, "backup_path": backup_path, "errors": errors}


# Ensure hook directories exist
for d in [HOOKS_DIR, PRE_HOOKS_DIR, POST_HOOKS_DIR]:
    os.makedirs(d, exist_ok=True)

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
            try:
                with get_backup_db_cursor(commit=True) as (conn, cur):
                    cur.execute("DELETE FROM backup_log WHERE file_path = %s", (backup_path,))
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


def acquire_backup_lock(backup_name, created_by):
    """Acquire exclusive backup lock, returns (success, error_msg)"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                lock_data = json.load(f)
            lock_age = time.time() - lock_data.get("timestamp", 0)
            if lock_age < LOCK_TIMEOUT:
                backup_name = lock_data.get("backup_name", "unknown")
                created_by = lock_data.get("created_by", "unknown")
                msg = f"Backup '{backup_name}' in progress by {created_by} (started {int(lock_age)}s ago)"
                return (False, msg)
            # Stale lock, remove it
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
            dump_file = sorted(dumps)[-1]
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
            preview["database_tables"] = "pg_dump archive (see metadata.json for table count)"

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
            preview["backup_metadata"] = {
                "created_at": metadata.get("created_at"),
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


def restore_database_from_backup(db_file_path):
    """Restore database from SQL file (handles both .sql and .sql.gz)"""
    if not os.path.exists(db_file_path):
        return {"success": False, "error": f"Database file not found: {db_file_path}"}

    try:
        # Read SQL content
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


def _safe_serialize_val(val):
    """Serialize a DB value to a SQL literal, guarding against out-of-range datetimes."""
    import datetime as _dt

    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (_dt.datetime, _dt.date)):
        try:
            return f"'{val.isoformat()}'"
        except (ValueError, OverflowError):
            return "NULL  -- original value had out-of-range year"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


def backup_database_python(output_file, compress=True):
    """Backup database using psycopg2 (Python-based, no pg_dump needed)

    Args:
        output_file: Base output file path (without .gz extension if compress=True)
        compress: If True, compress with gzip (adds .gz extension)

    Returns:
        str: Actual output file path (with .gz if compressed)
    """
    try:
        sql_lines = []

        with get_backup_db_cursor(commit=False) as (conn, cursor):
            # Generate SQL content
            sql_lines.append("-- A.R.C.H.I.E. Platform Database Backup\n")
            sql_lines.append(f"-- Generated: {datetime.now().isoformat()}\n")
            sql_lines.append(f"-- Compression: {'gzip' if compress else 'none'}\n\n")

            # Get all tables
            cursor.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename;
            """
            )
            tables = cursor.fetchall()

            for (table_name,) in tables:
                sql_lines.append(f"\n-- Table: {table_name}\n")
                sql_lines.append(f"DROP TABLE IF EXISTS {table_name} CASCADE;\n")

                # Get CREATE TABLE statement
                cursor.execute(
                    """
                    SELECT
                        'CREATE TABLE ' || quote_ident(table_name) || ' (' ||
                        string_agg(
                            quote_ident(column_name) || ' ' ||
                            data_type ||
                            CASE
                                WHEN character_maximum_length IS NOT NULL
                                THEN '(' || character_maximum_length || ')'
                                ELSE ''
                            END ||
                            CASE
                                WHEN is_nullable = 'NO' THEN ' NOT NULL'
                                ELSE ''
                            END,
                            ', '
                        ) || ');'
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = %s
                    GROUP BY table_name;
                """,
                    (table_name,),
                )

                create_stmt = cursor.fetchone()
                if create_stmt:
                    sql_lines.append(create_stmt[0] + "\n\n")

                # Get data - cast timestamp columns to TEXT so psycopg2 never
                # raises ValueError on out-of-range years (e.g. year 58317).
                cursor.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (table_name,),
                )
                col_meta = cursor.fetchall()
                _ts_types = {
                    "timestamp with time zone",
                    "timestamp without time zone",
                    "date",
                    "time with time zone",
                    "time without time zone",
                }
                select_parts = []
                for col_name, data_type in col_meta:
                    ident = sql.Identifier(col_name)
                    if data_type in _ts_types:
                        select_parts.append(sql.SQL("{col}::text AS {alias}").format(col=ident, alias=ident))
                    else:
                        select_parts.append(ident)

                if select_parts:
                    select_query = sql.SQL("SELECT {cols} FROM {tbl}").format(
                        cols=sql.SQL(", ").join(select_parts),
                        tbl=sql.Identifier(table_name),
                    )
                else:
                    select_query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(table_name))
                cursor.execute(select_query)
                rows = cursor.fetchall()

                if rows:
                    # Get column names
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                        ORDER BY ordinal_position;
                    """,
                        (table_name,),
                    )
                    columns = [col[0] for col in cursor.fetchall()]

                    sql_lines.append(f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES\n")

                    for i, row in enumerate(rows):
                        # Format values
                        values = []
                        for val in row:
                            values.append(_safe_serialize_val(val))

                        if i < len(rows) - 1:
                            sql_lines.append(f"  ({', '.join(values)}),\n")
                        else:
                            sql_lines.append(f"  ({', '.join(values)});\n")

                    sql_lines.append("\n")

        # Write to file (compressed or uncompressed)
        sql_content = "".join(sql_lines)

        if compress:
            output_path = output_file + ".gz" if not output_file.endswith(".gz") else output_file
            with gzip.open(output_path, "wt", encoding="utf-8") as f:
                f.write(sql_content)
            return output_path
        else:
            with open(output_file, "w") as f:
                f.write(sql_content)
            return output_file

    except Exception as e:
        current_app.logger.error(f"Database backup failed: {str(e)}")
        raise


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


def _get_cloud_config():
    """Read Google Drive configuration from environment."""
    return {
        "enabled": os.environ.get("GDRIVE_ENABLED", "false").lower() == "true",
        "service_account_path": os.environ.get(
            "GDRIVE_SERVICE_ACCOUNT_PATH",
            "/app/credentials/gdrive-service-account.json",
        ),
        "folder_id": os.environ.get("GDRIVE_BACKUP_FOLDER_ID", ""),
        "passphrase_hash": os.environ.get("GDRIVE_ENCRYPTION_PASSPHRASE_HASH", ""),
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
