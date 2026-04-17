"""
A.R.C.H.I.E. Platform - Backup Manager Routes
==============================================

Provides comprehensive backup, restore, and disaster recovery functionality
for the A.R.C.H.I.E. platform. Uses psycopg2 for database backup (no pg_dump needed).

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
import os
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


backup_manager_bp = Blueprint("backup_manager", __name__, url_prefix="/tools/backup-manager")

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

        # 8. Backup scripts
        scripts_src = "/mnt/archie_brain/scripts"
        if os.path.exists(scripts_src):
            shutil.copytree(scripts_src, os.path.join(backup_path, "scripts"), dirs_exist_ok=True)

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

# Ensure hook directories exist
for d in [HOOKS_DIR, PRE_HOOKS_DIR, POST_HOOKS_DIR]:
    os.makedirs(d, exist_ok=True)

# =============================================================================
# RETENTION POLICY - Grandfather-Father-Son (7 daily + 4 weekly + 6 monthly)
# =============================================================================


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

    keep = set()

    # Rule 1: Keep last 7 daily backups
    daily_kept = 0
    for backup in backups:
        if daily_kept < 7:
            keep.add(backup["name"])
            daily_kept += 1

    # Rule 2: Keep last 4 weekly backups (prefer Sundays, but take latest each week)
    weeks_seen = set()
    for backup in backups:
        week_key = backup["date"].strftime("%Y-%W")  # Year-Week number
        if week_key not in weeks_seen and len(weeks_seen) < 4:
            keep.add(backup["name"])
            weeks_seen.add(week_key)

    # Rule 3: Keep last 6 monthly backups (prefer 1st of month, but take latest each month)
    months_seen = set()
    for backup in backups:
        month_key = backup["date"].strftime("%Y-%m")  # Year-Month
        if month_key not in months_seen and len(months_seen) < 6:
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
            try:
                # Get size before deletion
                backup_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, _, filenames in os.walk(backup_path)
                    for filename in filenames
                )

                shutil.rmtree(backup_path)
                deleted.append(backup_name)
                space_freed += backup_size
            except Exception as e:
                print(f"Error deleting {backup_name}: {e}")

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
    """Preview what would change during restore (dry-run)"""
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

    # Check database
    db_file = os.path.join(backup_path, "database.sql.gz")
    if not os.path.exists(db_file):
        db_file = os.path.join(backup_path, "database.sql")

    if os.path.exists(db_file):
        preview["components"].append(
            {
                "name": "database",
                "file": os.path.basename(db_file),
                "size_bytes": os.path.getsize(db_file),
                "compressed": db_file.endswith(".gz"),
            }
        )
        preview["total_size_bytes"] += os.path.getsize(db_file)

        # Count tables by parsing SQL
        try:
            if db_file.endswith(".gz"):
                with gzip.open(db_file, "rt", encoding="utf-8") as f:
                    content = f.read()
            else:
                with open(db_file, "r") as f:
                    content = f.read()
            preview["database_tables"] = content.count("CREATE TABLE")
        except Exception:
            pass

    # Check platform files
    platform_dir = os.path.join(backup_path, "platform_v2")
    if os.path.exists(platform_dir):
        file_count = 0
        dir_size = 0
        for root, dirs, files in os.walk(platform_dir):
            file_count += len(files)
            for f in files:
                dir_size += os.path.getsize(os.path.join(root, f))

        preview["components"].append(
            {
                "name": "platform_v2",
                "file_count": file_count,
                "size_bytes": dir_size,
            }
        )
        preview["files_to_restore"] += file_count
        preview["total_size_bytes"] += dir_size

    # Check other directories
    for dir_name in ["ai_bridge", "docs", "scripts", "nginx", "n8n_workflows"]:
        dir_path = os.path.join(backup_path, dir_name)
        if os.path.exists(dir_path):
            file_count = sum(len(files) for _, _, files in os.walk(dir_path))
            dir_size = sum(
                os.path.getsize(os.path.join(root, f)) for root, _, files in os.walk(dir_path) for f in files
            )
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

            # Add info about non-restorable components (for user understanding)
            all_components = metadata.get("components", {})
            restorable = {
                "database",
                "platform_v2",
                "ai_bridge",
                "docs",
                "scripts",
                "nginx",
                "n8n_workflows",
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

                # Get data - use sql.Identifier for safe table name in FROM clause
                cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table_name)))
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
                            if val is None:
                                values.append("NULL")
                            elif isinstance(val, str):
                                # Escape single quotes
                                escaped = val.replace("'", "''")
                                values.append(f"'{escaped}'")
                            elif isinstance(val, (int, float)):
                                values.append(str(val))
                            elif isinstance(val, datetime):
                                values.append(f"'{val.isoformat()}'")
                            else:
                                values.append(f"'{str(val)}'")

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


@backup_manager_bp.route("/")
@admin_required
def index():
    """Backup manager main page"""
    return render_template("tools/backup_manager.html")


@backup_manager_bp.route("/list")
@admin_required
def list_backups():
    """List all available backups"""
    try:
        backups = []

        if os.path.exists(BACKUP_DIR):
            for item in os.listdir(BACKUP_DIR):
                backup_path = os.path.join(BACKUP_DIR, item)
                if os.path.isdir(backup_path):
                    metadata_file = os.path.join(backup_path, "metadata.json")
                    if os.path.exists(metadata_file):
                        with open(metadata_file, "r") as f:
                            metadata = json.load(f)

                            # Calculate size
                            total_size = 0
                            for root, dirs, files in os.walk(backup_path):
                                for file in files:
                                    filepath = os.path.join(root, file)
                                    total_size += os.path.getsize(filepath)

                            metadata["size"] = total_size
                            backups.append(metadata)

        # Sort by timestamp descending
        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return jsonify({"success": True, "backups": backups, "current_build": get_current_build()})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/current-build")
@admin_required
def api_current_build():
    """Get current build number"""
    return jsonify({"success": True, "current_build": get_current_build()})


@backup_manager_bp.route("/health")
@admin_required
def backup_health():
    """Return backup system health status"""
    try:
        alerts = []
        healthy = True

        # Count backups
        backups = []
        total_size = 0
        if os.path.exists(BACKUP_DIR):
            for item in os.listdir(BACKUP_DIR):
                backup_path = os.path.join(BACKUP_DIR, item)
                if os.path.isdir(backup_path):
                    metadata_file = os.path.join(backup_path, "metadata.json")
                    if os.path.exists(metadata_file):
                        with open(metadata_file, "r") as f:
                            metadata = json.load(f)
                            # Calculate size
                            backup_size = 0
                            for root, dirs, files in os.walk(backup_path):
                                for file in files:
                                    filepath = os.path.join(root, file)
                                    backup_size += os.path.getsize(filepath)
                            metadata["size"] = backup_size
                            total_size += backup_size
                            backups.append(metadata)

        # Sort by timestamp descending
        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        backup_count = len(backups)

        # Check: No backups
        if backup_count == 0:
            healthy = False
            alerts.append(
                {
                    "level": "critical",
                    "message": "No backups found - system is unprotected",
                }
            )

        # Check: Latest backup age
        latest_backup = None
        latest_age_hours = None
        if backups:
            latest_backup = backups[0]
            created_at = latest_backup.get("created_at")
            if created_at:
                try:
                    backup_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    age = datetime.now() - backup_time.replace(tzinfo=None)
                    latest_age_hours = age.total_seconds() / 3600

                    if latest_age_hours > 48:
                        healthy = False
                        alerts.append(
                            {
                                "level": "warning",
                                "message": f"Latest backup is {latest_age_hours:.1f} hours old (>48h)",
                            }
                        )
                    elif latest_age_hours > 24:
                        alerts.append(
                            {
                                "level": "info",
                                "message": f"Latest backup is {latest_age_hours:.1f} hours old",
                            }
                        )
                except Exception:
                    pass

        # Check: Backup integrity (database.sql or database.sql.gz exists)
        if latest_backup:
            backup_path = os.path.join(BACKUP_DIR, latest_backup.get("name", ""))
            db_file = os.path.join(backup_path, "database.sql.gz")
            db_compressed = True
            if not os.path.exists(db_file):
                db_file = os.path.join(backup_path, "database.sql")
                db_compressed = False

            if os.path.exists(db_file):
                db_size = os.path.getsize(db_file)
                # For compressed files, even 512B is valid
                min_size = 512 if db_compressed else 1024
                if db_size < min_size:
                    healthy = False
                    alerts.append(
                        {
                            "level": "critical",
                            "message": f"Latest backup database file is too small ({db_size} bytes)",
                        }
                    )
            else:
                healthy = False
                alerts.append(
                    {
                        "level": "critical",
                        "message": "Latest backup missing database.sql or database.sql.gz",
                    }
                )

        # Check: Disk space (warning if backups > 10GB)
        if total_size > 10 * 1024 * 1024 * 1024:  # 10GB
            alerts.append(
                {
                    "level": "warning",
                    "message": f"Backup storage exceeds 10GB ({total_size / (1024*1024*1024):.1f}GB)",
                }
            )

        # Phase 5 / Task 20: per-tier freshness from backup_log.
        # Newest row per (component, tier) — feeds the LCARS tier-health card.
        tiers: dict = {}
        try:
            with get_backup_db_cursor(commit=False) as (_tconn, _tcur):
                _tcur.execute(
                    """
                    SELECT DISTINCT ON (component, tier)
                           component, tier, status, created_at, size_bytes,
                           verification_status
                      FROM backup_log
                     WHERE component IS NOT NULL AND tier IS NOT NULL
                     ORDER BY component, tier, created_at DESC
                    """
                )
                for row in _tcur.fetchall():
                    tiers.setdefault(row["tier"], []).append(
                        {
                            "component": row["component"],
                            "status": row["status"],
                            "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
                            "size_bytes": row["size_bytes"] or 0,
                            "verification_status": row["verification_status"],
                        }
                    )
        except Exception as _tier_err:
            tiers = {"_error": str(_tier_err)}

        return jsonify(
            {
                "healthy": healthy,
                "total_backups": backup_count,
                "latest_backup": latest_backup.get("name") if latest_backup else None,
                "latest_age_hours": (round(latest_age_hours, 1) if latest_age_hours else None),
                "total_storage_bytes": total_size,
                "total_storage_formatted": f"{total_size / (1024*1024):.1f} MB",
                "platform_version": get_platform_version(),
                "current_build": get_current_build(),
                "alerts": alerts,
                "tiers": tiers,
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "healthy": False,
                    "error": str(e),
                    "alerts": [
                        {
                            "level": "critical",
                            "message": f"Health check failed: {str(e)}",
                        }
                    ],
                }
            ),
            500,
        )


@backup_manager_bp.route("/verify/<backup_name>")
@admin_required
def verify_backup(backup_name):
    """Verify integrity of a specific backup"""
    try:
        result = verify_backup_integrity(backup_name)
        return jsonify(result)
    except Exception as e:
        return (
            jsonify({"valid": False, "backup_name": backup_name, "error": str(e)}),
            500,
        )


@backup_manager_bp.route("/create", methods=["POST"])
@admin_required
def api_create_backup():
    """Create a new backup (API route - use create_backup_programmatic for code)"""
    try:
        data = request.get_json() or {}
        description = data.get("description", "Manual backup")
        backup_type = data.get("backup_type", "full")
        custom_components = data.get("components", [])

        # Define component sets for each backup type
        ALL_COMPONENTS = [
            "database",
            "platform",
            "documentation",
            "ai_bridge",
            "migrations",
            "n8n_workflows",
            "n8n_persistence",
            "scripts",
            "nginx",
            "environment",
            "conversation_logs",
        ]
        CRITICAL_COMPONENTS = ["database", "platform", "documentation", "environment"]
        DATABASE_COMPONENTS = ["database"]

        # Determine which components to backup based on type
        if backup_type == "full":
            components_to_backup = ALL_COMPONENTS
        elif backup_type == "critical":
            components_to_backup = CRITICAL_COMPONENTS
        elif backup_type == "database":
            components_to_backup = DATABASE_COMPONENTS
        elif backup_type == "custom":
            components_to_backup = custom_components if custom_components else ALL_COMPONENTS
        else:
            components_to_backup = ALL_COMPONENTS
            backup_type = "full"

        current_app.logger.info(f"Creating {backup_type} backup with components: {components_to_backup}")

        # Generate backup name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}_{description.replace(' ', '_')}"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        # Acquire backup lock
        lock_acquired, lock_error = acquire_backup_lock(backup_name, current_user.username)
        if not lock_acquired:
            return jsonify({"success": False, "error": lock_error}), 409

        # Execute pre-backup hooks
        pre_ok, pre_results = execute_pre_hooks(backup_name)
        if not pre_ok:
            release_backup_lock()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Pre-backup hook failed",
                        "hook_results": pre_results,
                    }
                ),
                500,
            )

        os.makedirs(backup_path, exist_ok=True)

        # Track which components were backed up
        backed_up = {}
        db_file_name = "database.sql.gz"  # Default to compressed

        # 1. Backup database (with compression)
        if "database" in components_to_backup:
            current_app.logger.info("Backing up database (compressed)...")
            db_file = os.path.join(backup_path, "database.sql")
            actual_db_file = backup_database_python(db_file, compress=True)
            db_file_name = os.path.basename(actual_db_file)
            backed_up["database"] = True
            current_app.logger.info(f"Database backup complete ({db_file_name})")

        # 2. Backup platform files (configs, tools, templates)
        if "platform" in components_to_backup:
            current_app.logger.info("Backing up platform files...")
            platform_backup = os.path.join(backup_path, "platform_v2")
            platform_dirs = [
                "tools",
                "templates",
                "static",
                "consciousness",
                "migrations",
            ]
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
            ]
            for file_name in important_files:
                src = os.path.join(PLATFORM_DIR, file_name)
                if os.path.exists(src):
                    dst = os.path.join(platform_backup, file_name)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
            backed_up["platform"] = True
            current_app.logger.info("Platform files backup complete")

        # 3. Backup documentation
        docs_src = "/mnt/archie_brain/docs"
        if "documentation" in components_to_backup and os.path.exists(docs_src):
            current_app.logger.info("Backing up documentation...")
            docs_dst = os.path.join(backup_path, "docs")
            shutil.copytree(docs_src, docs_dst, dirs_exist_ok=True)
            backed_up["documentation"] = True
            current_app.logger.info(f"Documentation backup complete - {len(os.listdir(docs_dst))} files")

        # 4. Backup AI bridge code
        ai_bridge_src = "/mnt/archie_brain/ai_bridge"
        if "ai_bridge" in components_to_backup and os.path.exists(ai_bridge_src):
            current_app.logger.info("Backing up AI bridge...")
            ai_bridge_dst = os.path.join(backup_path, "ai_bridge")
            shutil.copytree(ai_bridge_src, ai_bridge_dst, dirs_exist_ok=True)
            backed_up["ai_bridge"] = True
            current_app.logger.info("AI bridge backup complete")

        # 5. Backup database migrations
        db_migrations_src = "/mnt/archie_brain/database/migrations"
        if "migrations" in components_to_backup and os.path.exists(db_migrations_src):
            current_app.logger.info("Backing up database migrations...")
            db_migrations_dst = os.path.join(backup_path, "database/migrations")
            os.makedirs(os.path.dirname(db_migrations_dst), exist_ok=True)
            shutil.copytree(db_migrations_src, db_migrations_dst, dirs_exist_ok=True)
            backed_up["migrations"] = True
            current_app.logger.info("Database migrations backup complete")

        # 6. Backup n8n workflows
        n8n_workflows_src = "/mnt/archie_brain/n8n_workflows"
        if "n8n_workflows" in components_to_backup and os.path.exists(n8n_workflows_src):
            current_app.logger.info("Backing up n8n workflows...")
            n8n_workflows_dst = os.path.join(backup_path, "n8n_workflows")
            shutil.copytree(n8n_workflows_src, n8n_workflows_dst, dirs_exist_ok=True)
            backed_up["n8n_workflows"] = True
            current_app.logger.info(f"n8n workflows backup complete - {len(os.listdir(n8n_workflows_dst))} files")

        # 7. Backup n8n persistence data
        n8n_persistence_src = "/mnt/archie_brain/persistence/n8n"
        if "n8n_persistence" in components_to_backup and os.path.exists(n8n_persistence_src):
            current_app.logger.info("Backing up n8n persistence data...")
            n8n_persistence_dst = os.path.join(backup_path, "persistence/n8n")
            os.makedirs(os.path.dirname(n8n_persistence_dst), exist_ok=True)
            shutil.copytree(n8n_persistence_src, n8n_persistence_dst, dirs_exist_ok=True)
            backed_up["n8n_persistence"] = True
            current_app.logger.info("n8n persistence backup complete")

        # 8. Backup deployment scripts
        scripts_src = "/mnt/archie_brain/scripts"
        if "scripts" in components_to_backup and os.path.exists(scripts_src):
            current_app.logger.info("Backing up deployment scripts...")
            scripts_dst = os.path.join(backup_path, "scripts")
            shutil.copytree(scripts_src, scripts_dst, dirs_exist_ok=True)
            backed_up["scripts"] = True
            current_app.logger.info(f"Scripts backup complete - {len(os.listdir(scripts_dst))} files")

        # 9. Backup nginx configuration
        nginx_src = "/mnt/archie_brain/nginx"
        if "nginx" in components_to_backup and os.path.exists(nginx_src):
            current_app.logger.info("Backing up nginx configuration...")
            nginx_dst = os.path.join(backup_path, "nginx")
            shutil.copytree(nginx_src, nginx_dst, dirs_exist_ok=True)
            backed_up["nginx"] = True
            current_app.logger.info("nginx configuration backup complete")

        # 10. Backup docker-compose.yml from root (environment)
        root_compose_src = "/mnt/archie_brain/docker-compose.yml"
        if "environment" in components_to_backup and os.path.exists(root_compose_src):
            current_app.logger.info("Backing up root docker-compose.yml...")
            root_compose_dst = os.path.join(backup_path, "docker-compose.yml")
            shutil.copy2(root_compose_src, root_compose_dst)
            backed_up["environment"] = True
            current_app.logger.info("Root docker-compose.yml backup complete")

        # 11. Backup conversation logs (Claude Code hook transcripts)
        conversation_logs_src = "/mnt/archie_brain/conversation_logs"
        if "conversation_logs" in components_to_backup and os.path.exists(conversation_logs_src):
            current_app.logger.info("Backing up conversation logs...")
            conversation_logs_dst = os.path.join(backup_path, "conversation_logs")
            shutil.copytree(conversation_logs_src, conversation_logs_dst, dirs_exist_ok=True)
            backed_up["conversation_logs"] = True
            current_app.logger.info("Conversation logs backup complete")

        # Calculate total backup size
        total_size = 0
        for root, dirs, files in os.walk(backup_path):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))

        # Copy to external storage if available
        external_result = {"success": False, "error": "External storage not mounted"}
        if is_external_storage_available():
            current_app.logger.info("Copying to external storage...")
            external_result = copy_to_external_storage(backup_name, backup_path)
            if external_result["success"]:
                current_app.logger.info(f"External copy complete ({external_result.get('size_mb', 0)} MB)")

        # 12. Create metadata with auto-assigned build number
        new_build_number = get_next_build_number()
        metadata = {
            "name": backup_name,
            "timestamp": timestamp,
            "description": description,
            "created_by": current_user.username,
            "created_at": datetime.now().isoformat(),
            "platform_version": get_platform_version(),
            "build_number": new_build_number,
            "backup_type": backup_type,
            "compression": "gzip",
            "database_file": db_file_name,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "external_copy": external_result.get("success", False),
            "components": backed_up,
        }

        metadata_file = os.path.join(backup_path, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        # Generate rollback script (handles compressed database)
        db_restore_cmd = (
            f"zcat {backup_path}/{db_file_name} | docker exec -i archie_db psql -U archie -d archie"
            if db_file_name.endswith(".gz")
            else f"docker exec -i archie_db psql -U archie -d archie < {backup_path}/database.sql"
        )
        rollback_script = os.path.join(backup_path, "rollback.sh")
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
docker exec -i archie_db psql -U archie -c "DROP DATABASE IF EXISTS archie;"
docker exec -i archie_db psql -U archie -c "CREATE DATABASE archie;"
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
                "backup_type": backup_type,
                "size_bytes": total_size,
                "compression": "gzip",
                "external_copy": external_result.get("success", False),
                "timestamp": datetime.now().isoformat(),
            },
        )

        # Release lock
        release_backup_lock()

        current_app.logger.info(f"Backup created successfully: {backup_name} (Build #{new_build_number})")

        return jsonify(
            {
                "success": True,
                "message": f"Backup created successfully (Build #{new_build_number})",
                "backup": metadata,
                "external_copy": external_result,
                "webhook_results": webhook_results,
            }
        )

    except Exception as e:
        current_app.logger.error(f"Backup creation failed: {str(e)}")

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

        # Clean up failed backup
        if "backup_path" in locals() and os.path.exists(backup_path):
            shutil.rmtree(backup_path)

        # Release lock if acquired
        if "lock_acquired" in locals() and lock_acquired:
            release_backup_lock()

        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/restore/<backup_name>", methods=["POST"])
@admin_required
def restore_backup(backup_name):
    """Restore a backup"""
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        if not os.path.exists(backup_path):
            return jsonify({"success": False, "error": "Backup not found"}), 404

        rollback_script = os.path.join(backup_path, "rollback.sh")

        if not os.path.exists(rollback_script):
            return (
                jsonify({"success": False, "error": "Rollback script not found"}),
                404,
            )

        # Execute rollback script
        result = subprocess.run(["bash", rollback_script], capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Rollback failed: {result.stderr}")

        return jsonify(
            {
                "success": True,
                "message": "Backup restored successfully. Platform is restarting...",
                "output": result.stdout,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/download/<backup_name>")
@admin_required
def download_backup(backup_name):
    """Download a backup as tar.gz"""
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        if not os.path.exists(backup_path):
            return jsonify({"success": False, "error": "Backup not found"}), 404

        # Create tar.gz archive using tempfile for proper cleanup
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            archive_path = tmp.name

        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(backup_path, arcname=backup_name)

            response = send_file(
                archive_path,
                as_attachment=True,
                download_name=f"{backup_name}.tar.gz",
                mimetype="application/gzip",
            )

            # Schedule cleanup after response is sent
            @response.call_on_close
            def cleanup():
                try:
                    if os.path.exists(archive_path):
                        os.unlink(archive_path)
                except Exception:
                    pass

            return response
        except Exception:
            # Cleanup on error
            if os.path.exists(archive_path):
                os.unlink(archive_path)
            raise

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/delete/<backup_name>", methods=["DELETE"])
@admin_required
def delete_backup(backup_name):
    """Delete a backup"""
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        if not os.path.exists(backup_path):
            return jsonify({"success": False, "error": "Backup not found"}), 404

        # Safety check: don't delete if it's the only/newest backup
        all_backups = [d for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, d))]

        if len(all_backups) == 1:
            return (
                jsonify({"success": False, "error": "Cannot delete the only backup"}),
                400,
            )

        # Delete backup directory
        shutil.rmtree(backup_path)

        return jsonify({"success": True, "message": "Backup deleted successfully"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# RETENTION POLICY ROUTES
# =============================================================================


@backup_manager_bp.route("/retention-status")
@admin_required
def retention_status():
    """
    Get current retention policy status showing which backups would be kept/deleted.

    Returns:
        {
            'keep': [list of backup names to keep],
            'delete': [list of backup names that can be deleted],
            'stats': {
                'total_backups': int,
                'keep_count': int,
                'delete_count': int,
                'total_size_mb': float,
                'space_to_free_mb': float
            }
        }
    """
    try:
        status = get_backup_retention_status()
        return jsonify(
            {
                "success": True,
                "retention_policy": "7 daily + 4 weekly + 6 monthly",
                **status,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/cleanup", methods=["POST"])
@admin_required
def cleanup_backups():
    """
    Delete old backups based on retention policy.

    Request body (optional):
        {
            'dry_run': true/false (default: true)
        }

    Returns:
        {
            'success': True,
            'dry_run': True/False,
            'deleted': [list of deleted backup names],
            'kept': [list of kept backup names],
            'space_freed_mb': float
        }
    """
    try:
        data = request.get_json() or {}
        dry_run = data.get("dry_run", True)  # Default to dry run for safety

        result = cleanup_old_backups(dry_run=dry_run)

        if not dry_run:
            current_app.logger.info(
                f"Retention cleanup: deleted {len(result['deleted'])} backups, freed {result['space_freed_mb']} MB"
            )

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Cleanup failed: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/storage-stats")
@admin_required
def storage_stats():
    """
    Get storage statistics for backups.

    Returns:
        {
            'total_backups': int,
            'total_size_mb': float,
            'oldest_backup': str,
            'newest_backup': str,
            'retention_summary': {...}
        }
    """
    try:
        retention = get_backup_retention_status()

        # Get oldest and newest backup names
        backups = []
        for item in os.listdir(BACKUP_DIR):
            backup_path = os.path.join(BACKUP_DIR, item)
            if os.path.isdir(backup_path) and item != "modules":
                try:
                    timestamp_str = item[:15]
                    backup_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    backups.append({"name": item, "date": backup_date})
                except (ValueError, IndexError):
                    continue

        backups.sort(key=lambda x: x["date"])

        return jsonify(
            {
                "success": True,
                "total_backups": retention["stats"]["total_backups"],
                "total_size_mb": retention["stats"]["total_size_mb"],
                "oldest_backup": backups[0]["name"] if backups else None,
                "newest_backup": backups[-1]["name"] if backups else None,
                "retention_summary": {
                    "keep_count": retention["stats"]["keep_count"],
                    "delete_count": retention["stats"]["delete_count"],
                    "space_to_free_mb": retention["stats"]["space_to_free_mb"],
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/deploy-to-sandbox", methods=["POST"])
@admin_required
def deploy_backup_to_sandbox():
    """
    Deploy a backup to a sandbox for testing restore functionality.

    Request body:
        {
            'backup_name': 'backup_20250105_123456',
            'sandbox_id': 1
        }

    Returns:
        {
            'success': True,
            'sandbox_id': 1,
            'sandbox_type': 'schema_separation',
            'components_deployed': ['database', 'platform_code'],
            'deployment_log': '...'
        }
    """
    try:
        data = request.get_json()
        backup_name = data.get("backup_name")
        sandbox_id = data.get("sandbox_id")

        if not backup_name or not sandbox_id:
            return (
                jsonify({"success": False, "error": "backup_name and sandbox_id required"}),
                400,
            )

        # Get backup path
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            return (
                jsonify({"success": False, "error": f"Backup {backup_name} not found"}),
                404,
            )

        # Get sandbox details
        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, proposal_id, sandbox_type, schema_name, container_id, status
                FROM sandbox_instances
                WHERE id = %s
                AND destroyed_at IS NULL
            """,
                (sandbox_id,),
            )
            sandbox = cur.fetchone()

        if not sandbox:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Sandbox #{sandbox_id} not found or destroyed",
                    }
                ),
                404,
            )

        sandbox_type = sandbox[2]
        schema_name = sandbox[3]
        container_id = sandbox[4]

        deployment_log = []
        components_deployed = []

        # Deploy based on sandbox type
        if sandbox_type == "schema_separation":
            # Deploy to schema-based sandbox
            deployment_log.append(f"Deploying to schema: {schema_name}")

            # 1. Restore database backup to sandbox schema
            db_backup_path = os.path.join(backup_path, "database.sql")
            if os.path.exists(db_backup_path):
                deployment_log.append("Found database backup, restoring to sandbox schema...")

                # Modify SQL to use sandbox schema instead of public
                with open(db_backup_path, "r") as f:
                    sql_content = f.read()

                # Replace schema references (simple approach - for production you'd want more robust handling)
                sql_content = sql_content.replace("SET search_path = public", f"SET search_path = {schema_name}")

                # Write modified SQL to temp file
                import tempfile

                with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as tmp:
                    tmp.write(sql_content)
                    tmp_path = tmp.name

                try:
                    # Execute SQL in sandbox schema
                    result = subprocess.run(
                        [
                            "docker",
                            "exec",
                            "-i",
                            "archie_database",
                            "psql",
                            "-U",
                            "archie",
                            "-d",
                            "archie",
                            "-c",
                            f"SET search_path TO {schema_name}; \\i {tmp_path}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )

                    if result.returncode == 0:
                        deployment_log.append("✓ Database restored to sandbox schema")
                        components_deployed.append("database")
                    else:
                        deployment_log.append(f"⚠ Database restore warning: {result.stderr}")
                finally:
                    os.unlink(tmp_path)

            # 2. Note: Platform code would be applied to production, not sandbox
            #    (schema sandboxes share the same codebase)
            deployment_log.append("Note: Platform code shared with production (schema isolation only)")

        elif sandbox_type == "docker_container":
            # Deploy to Docker container sandbox
            deployment_log.append(f"Deploying to Docker container: {container_id}")

            # 1. Copy platform code files
            platform_backup_path = os.path.join(backup_path, "platform_v2")
            if os.path.exists(platform_backup_path):
                deployment_log.append("Found platform code, copying to container...")

                result = subprocess.run(
                    [
                        "docker",
                        "cp",
                        platform_backup_path + "/.",
                        f"{container_id}:/app/",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode == 0:
                    deployment_log.append("✓ Platform code deployed to container")
                    components_deployed.append("platform_code")
                else:
                    deployment_log.append(f"⚠ Platform copy warning: {result.stderr}")

            # 2. Restore database to container's database
            db_backup_path = os.path.join(backup_path, "database.sql")
            if os.path.exists(db_backup_path):
                deployment_log.append("Found database backup, restoring to container database...")

                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        container_id,
                        "psql",
                        "-U",
                        "archie",
                        "-d",
                        "archie",
                        "-f",
                        db_backup_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if result.returncode == 0:
                    deployment_log.append("✓ Database restored to container")
                    components_deployed.append("database")
                else:
                    deployment_log.append(f"⚠ Database restore warning: {result.stderr}")

        # Update sandbox metadata
        cur.execute(
            """
            UPDATE sandbox_instances
            SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
            WHERE id = %s
        """,
            (
                json.dumps(
                    {
                        "last_backup_deployed": backup_name,
                        "deployment_time": datetime.now().isoformat(),
                        "components_deployed": components_deployed,
                        "deployment_log": deployment_log,
                    }
                ),
                sandbox_id,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "sandbox_id": sandbox_id,
                "sandbox_type": sandbox_type,
                "components_deployed": components_deployed,
                "deployment_log": "\n".join(deployment_log),
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/set-current/<int:build_number>", methods=["POST"])
@admin_required
def set_current_build(build_number):
    """Set current running build number"""
    try:
        current_build_file = "/backups/.current_build"
        with open(current_build_file, "w") as f:
            f.write(str(build_number))

        return jsonify(
            {
                "success": True,
                "current_build": build_number,
                "message": f"Current build set to #{build_number}",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# MODULE-LEVEL BACKUP ROUTES (NEW)
# =============================================================================


@backup_manager_bp.route("/backup-module", methods=["POST"])
@admin_required
def api_backup_module():
    """
    Backup a single module for isolated sandbox testing

    Request body:
        {
            'module_name': 'improvements',
            'proposal_id': 45  (optional)
        }

    Returns:
        {
            'success': True,
            'backup_name': '20260114_150302_module_improvements',
            'backup_path': '/mnt/archie_brain/backups/modules/...',
            'files_backed_up': [...]
        }
    """
    try:
        data = request.get_json() or {}
        module_name = data.get("module_name")
        proposal_id = data.get("proposal_id")

        if not module_name:
            return jsonify({"success": False, "error": "module_name is required"}), 400

        result = backup_module(
            module_name=module_name,
            proposal_id=proposal_id,
            created_by_username=current_user.username,
        )

        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/module-dependencies/<module_name>")
@admin_required
def api_module_dependencies(module_name):
    """
    Get list of files a module depends on

    Returns:
        {
            'success': True,
            'module_name': 'improvements',
            'dependencies': {
                'routes': ['tools/improvements/routes.py', ...],
                'templates': ['templates/tools/improvements_lab.html', ...],
                'static': ['static/js/improvements_lab/api.js', ...],
                'shared': ['config.py', 'app.py', ...]
            }
        }
    """
    try:
        dependencies = get_module_dependencies(module_name)

        return jsonify({"success": True, "module_name": module_name, "dependencies": dependencies})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/modules/list")
@admin_required
def list_module_backups():
    """List all module-level backups"""
    try:
        module_backup_dir = os.path.join(BACKUP_DIR, "modules")
        backups = []

        if os.path.exists(module_backup_dir):
            for item in os.listdir(module_backup_dir):
                backup_path = os.path.join(module_backup_dir, item)
                if os.path.isdir(backup_path):
                    metadata_file = os.path.join(backup_path, "metadata.json")
                    if os.path.exists(metadata_file):
                        with open(metadata_file, "r") as f:
                            metadata = json.load(f)

                            # Calculate size
                            total_size = 0
                            for root, dirs, files in os.walk(backup_path):
                                for file in files:
                                    filepath = os.path.join(root, file)
                                    total_size += os.path.getsize(filepath)

                            metadata["size"] = total_size
                            backups.append(metadata)

        # Sort by timestamp descending
        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return jsonify({"success": True, "backups": backups})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/restore-module/<backup_name>", methods=["POST"])
@admin_required
def restore_module_backup(backup_name):
    """Restore a module backup to the platform"""
    try:
        backup_path = os.path.join(BACKUP_DIR, "modules", backup_name)

        if not os.path.exists(backup_path):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Module backup {backup_name} not found",
                    }
                ),
                404,
            )

        # Read metadata
        metadata_file = os.path.join(backup_path, "metadata.json")
        if not os.path.exists(metadata_file):
            return (
                jsonify({"success": False, "error": "Backup metadata not found"}),
                400,
            )

        with open(metadata_file, "r") as f:
            metadata = json.load(f)

        files_restored = []

        # Restore tools directory
        tools_backup = os.path.join(backup_path, "tools")
        if os.path.exists(tools_backup):
            for item in os.listdir(tools_backup):
                src = os.path.join(tools_backup, item)
                dst = os.path.join(PLATFORM_DIR, "tools", item)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                    files_restored.append(f"tools/{item}/")

        # Restore templates
        templates_backup = os.path.join(backup_path, "templates", "tools")
        if os.path.exists(templates_backup):
            for item in os.listdir(templates_backup):
                src = os.path.join(templates_backup, item)
                dst = os.path.join(PLATFORM_DIR, "templates", "tools", item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                else:
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                files_restored.append(f"templates/tools/{item}")

        # Restore static JS
        static_backup = os.path.join(backup_path, "static", "js")
        if os.path.exists(static_backup):
            for item in os.listdir(static_backup):
                src = os.path.join(static_backup, item)
                dst = os.path.join(PLATFORM_DIR, "static", "js", item)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                    files_restored.append(f"static/js/{item}/")

        return jsonify(
            {
                "success": True,
                "message": f'Module {metadata.get("module_name", "unknown")} restored successfully',
                "files_restored": files_restored,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/modules/available")
@admin_required
def list_available_modules():
    """List all available modules that can be backed up"""
    try:
        tools_dir = os.path.join(PLATFORM_DIR, "tools")
        modules = []

        # Modules to exclude (not real modules)
        exclude = {"__pycache__", "admin", "_deprecated"}

        if os.path.exists(tools_dir):
            for item in sorted(os.listdir(tools_dir)):
                if item in exclude or item.startswith(".") or item.startswith("_"):
                    continue

                module_path = os.path.join(tools_dir, item)
                if os.path.isdir(module_path):
                    # Check if it has routes.py (actual module)
                    has_routes = os.path.exists(os.path.join(module_path, "routes.py"))

                    # Count files
                    file_count = sum(1 for f in os.listdir(module_path) if os.path.isfile(os.path.join(module_path, f)))

                    # Check for related templates
                    templates_dir = os.path.join(PLATFORM_DIR, "templates", "tools")
                    template_count = 0
                    if os.path.exists(templates_dir):
                        template_count = sum(1 for f in os.listdir(templates_dir) if item in f.lower())

                    # Calculate size
                    total_size = 0
                    for root, dirs, files in os.walk(module_path):
                        for f in files:
                            total_size += os.path.getsize(os.path.join(root, f))

                    modules.append(
                        {
                            "name": item,
                            "has_routes": has_routes,
                            "file_count": file_count,
                            "template_count": template_count,
                            "size_bytes": total_size,
                            "size_kb": round(total_size / 1024, 1),
                        }
                    )

        return jsonify({"success": True, "modules": modules, "total_count": len(modules)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# MODULE REGISTRY SYNC / VERIFICATION
# =============================================================================


@backup_manager_bp.route("/verify-modules")
@admin_required
def verify_modules_coverage():
    """
    Verify all registered modules are covered by backups.

    Checks:
    1. All modules from module_registry exist in backup paths
    2. Each module has routes, templates, and static files where expected
    3. Reports any missing or orphaned modules

    Returns:
        {
            'success': True,
            'total_modules': 33,
            'covered_modules': [...],
            'missing_modules': [...],
            'coverage_percentage': 100.0
        }
    """
    try:
        # Import module registry
        try:
            from module_registry import get_all_modules

            modules = get_all_modules()
        except ImportError:
            return (
                jsonify({"success": False, "error": "Could not import module_registry"}),
                500,
            )

        covered = []
        missing = []

        for module in modules:
            module_id = module.id
            module_name = module.name

            # Check if module has files in expected locations
            tool_dir = os.path.join(PLATFORM_DIR, "tools", module_id)
            has_routes = os.path.exists(tool_dir)

            # Check for templates
            templates_dir = os.path.join(PLATFORM_DIR, "templates", "tools")
            has_templates = (
                any(
                    f.startswith(module_id) or f.startswith(module_id.replace("_", ""))
                    for f in os.listdir(templates_dir)
                    if f.endswith(".html")
                )
                if os.path.exists(templates_dir)
                else False
            )

            # Module status
            module_info = {
                "id": module_id,
                "name": module_name,
                "category": (module.category.value if hasattr(module.category, "value") else str(module.category)),
                "has_routes": has_routes,
                "has_templates": has_templates,
                "enabled": module.enabled,
                "status": "live" if not module.coming_soon else "coming_soon",
            }

            if has_routes:
                covered.append(module_info)
            else:
                # Check if it's a placeholder module (expected to not have files yet)
                if module.coming_soon:
                    module_info["note"] = "Placeholder module - not yet implemented"
                    covered.append(module_info)  # Still count as covered (intentionally missing)
                else:
                    missing.append(module_info)

        coverage_pct = (len(covered) / len(modules) * 100) if modules else 0

        return jsonify(
            {
                "success": True,
                "total_modules": len(modules),
                "covered_count": len(covered),
                "missing_count": len(missing),
                "coverage_percentage": round(coverage_pct, 1),
                "covered_modules": covered,
                "missing_modules": missing,
                "backup_paths": {
                    "tools_dir": os.path.join(PLATFORM_DIR, "tools"),
                    "templates_dir": os.path.join(PLATFORM_DIR, "templates", "tools"),
                    "static_dir": os.path.join(PLATFORM_DIR, "static"),
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# DEPLOYMENT BACKUPS API
# =============================================================================


@backup_manager_bp.route("/api/deployment-backups")
@admin_required
def get_deployment_backups():
    """
    Get all deployment backups from improvement_deployments table.
    Shows backups automatically created before deploying proposals.
    """
    try:
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (
            conn,
            cur,
        ):
            cur.execute(
                """
                SELECT
                    id.id,
                    id.proposal_id,
                    id.module_id,
                    id.deployed_by,
                    id.deployed_at,
                    id.backup_name,
                    id.deployment_type,
                    id.status,
                    id.health_check_passed,
                    id.health_check_details,
                    id.deployment_duration_ms,
                    ip.title as proposal_title
                FROM improvement_deployments id
                LEFT JOIN improvement_proposals ip ON id.proposal_id = ip.id
                WHERE id.backup_name IS NOT NULL
                ORDER BY id.deployed_at DESC
                LIMIT 100
            """
            )
            deployments = cur.fetchall()

        return jsonify({"success": True, "deployments": [dict(d) for d in deployments]})

    except Exception as e:
        current_app.logger.error(f"Failed to load deployment backups: {e}")
        return jsonify(
            {
                "success": True,
                "deployments": [],
                "note": f"Error loading deployment backups: {str(e)}",
            }
        )


# =============================================================================
# DEPLOYMENT PACKAGE API (Phase 31.1)
# =============================================================================


def get_platform_version():
    """Get current platform version from CHANGELOG or default"""
    try:
        changelog_path = "/mnt/archie_brain/docs/CHANGELOG.md"
        if os.path.exists(changelog_path):
            with open(changelog_path, "r") as f:
                for line in f:
                    if line.startswith("## [") or line.startswith("## v"):
                        # Extract version from line like "## [5.33.0]" or "## v5.33.0"
                        import re

                        match = re.search(r"[\d]+\.[\d]+\.[\d]+", line)
                        if match:
                            return match.group()
        return "5.0.0"
    except Exception:
        return "5.0.0"


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


@backup_manager_bp.route("/api/deployment-packages")
@admin_required
def list_deployment_packages():
    """List all deployment packages"""
    try:
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (
            conn,
            cur,
        ):
            cur.execute(
                """
                SELECT
                    dp.id,
                    dp.package_name,
                    dp.version_tag,
                    dp.description,
                    dp.backup_source,
                    dp.file_path,
                    dp.file_size,
                    dp.checksum,
                    dp.components,
                    dp.target_platform,
                    dp.download_count,
                    dp.created_at,
                    dp.last_downloaded_at,
                    u.username as created_by
                FROM deployment_packages dp
                LEFT JOIN users u ON dp.created_by = u.id
                ORDER BY dp.created_at DESC
            """
            )
            packages = cur.fetchall()

        return jsonify({"success": True, "packages": [dict(p) for p in packages]})

    except Exception as e:
        current_app.logger.error(f"Failed to list deployment packages: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/create-deployment-package", methods=["POST"])
@admin_required
def create_deployment_package():
    """
    Create a self-contained deployment package

    Request body:
        {
            'description': 'Production release v5.33',
            'version_tag': 'v5.33.0',
            'from_backup': 'backup_name' (optional - create from existing backup),
            'target_platform': 'linux' | 'docker' | 'all'
        }
    """
    from psycopg2.extras import RealDictCursor
    import hashlib

    try:
        data = request.get_json() or {}
        description = data.get("description", "Deployment package")
        version_tag = data.get("version_tag", get_platform_version())
        from_backup = data.get("from_backup")
        target_platform = data.get("target_platform", "linux")

        # Generate package name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_version = version_tag.replace(".", "_").replace(" ", "_")
        package_name = f"archie-deployment-{safe_version}-{timestamp}"

        # Create package directory
        package_dir = os.path.join("/tmp", package_name)
        os.makedirs(package_dir, exist_ok=True)

        current_app.logger.info(f"Creating deployment package: {package_name}")

        components_included = []

        # If creating from backup, use that as source
        if from_backup:
            backup_path = os.path.join(BACKUP_DIR, from_backup)
            if not os.path.exists(backup_path):
                return (
                    jsonify({"success": False, "error": f"Backup {from_backup} not found"}),
                    404,
                )

            # Copy backup contents
            for item in os.listdir(backup_path):
                src = os.path.join(backup_path, item)
                dst = os.path.join(package_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
            components_included.append("backup_contents")

        else:
            # Create fresh from current system

            # 1. Database dump
            current_app.logger.info("  Dumping database...")
            db_file = os.path.join(package_dir, "database.sql")
            backup_database_python(db_file)
            components_included.append("database")

            # 2. Platform code
            current_app.logger.info("  Copying platform code...")
            platform_dst = os.path.join(package_dir, "platform_v2")
            platform_dirs = [
                "tools",
                "templates",
                "static",
                "consciousness",
                "migrations",
            ]
            for dir_name in platform_dirs:
                src = os.path.join(PLATFORM_DIR, dir_name)
                if os.path.exists(src):
                    dst = os.path.join(platform_dst, dir_name)
                    shutil.copytree(src, dst, dirs_exist_ok=True)

            # Copy important platform files
            important_files = [
                "app.py",
                "requirements.txt",
                "config.py",
                "module_registry.py",
                "rbac.py",
            ]
            for file_name in important_files:
                src = os.path.join(PLATFORM_DIR, file_name)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(platform_dst, file_name))
            components_included.append("platform_v2")

            # 3. AI Bridge
            ai_bridge_src = "/mnt/archie_brain/ai_bridge"
            if os.path.exists(ai_bridge_src):
                shutil.copytree(
                    ai_bridge_src,
                    os.path.join(package_dir, "ai_bridge"),
                    dirs_exist_ok=True,
                )
                components_included.append("ai_bridge")

            # 4. Documentation
            docs_src = "/mnt/archie_brain/docs"
            if os.path.exists(docs_src):
                shutil.copytree(docs_src, os.path.join(package_dir, "docs"), dirs_exist_ok=True)
                components_included.append("docs")

            # 5. Database migrations
            migrations_src = "/mnt/archie_brain/database/migrations"
            if os.path.exists(migrations_src):
                migrations_dst = os.path.join(package_dir, "database/migrations")
                os.makedirs(os.path.dirname(migrations_dst), exist_ok=True)
                shutil.copytree(migrations_src, migrations_dst, dirs_exist_ok=True)
                components_included.append("migrations")

            # 6. Scripts
            scripts_src = "/mnt/archie_brain/scripts"
            if os.path.exists(scripts_src):
                shutil.copytree(
                    scripts_src,
                    os.path.join(package_dir, "scripts"),
                    dirs_exist_ok=True,
                )
                components_included.append("scripts")

            # 7. Nginx config
            nginx_src = "/mnt/archie_brain/nginx"
            if os.path.exists(nginx_src):
                shutil.copytree(nginx_src, os.path.join(package_dir, "nginx"), dirs_exist_ok=True)
                components_included.append("nginx")

            # 8. Node client
            node_client_src = "/mnt/archie_brain/node_client"
            if os.path.exists(node_client_src):
                shutil.copytree(
                    node_client_src,
                    os.path.join(package_dir, "node_client"),
                    dirs_exist_ok=True,
                )
                components_included.append("node_client")

            # 9. Docker compose
            compose_src = "/mnt/archie_brain/docker-compose.yml"
            if os.path.exists(compose_src):
                shutil.copy2(compose_src, os.path.join(package_dir, "docker-compose.yml"))
                components_included.append("docker-compose")

        # Generate deploy.sh
        deploy_script = generate_deploy_script(package_name, components_included)
        deploy_script_path = os.path.join(package_dir, "deploy.sh")
        with open(deploy_script_path, "w") as f:
            f.write(deploy_script)
        os.chmod(deploy_script_path, 0o755)

        # Create README
        readme_content = f"""# A.R.C.H.I.E. Deployment Package

**Package**: {package_name}
**Version**: {version_tag}
**Created**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Components Included
{chr(10).join('- ' + c for c in components_included)}

## Quick Start

1. Extract the package:
   ```bash
   tar -xzf {package_name}.tar.gz
   cd {package_name}
   ```

2. Run the deployment script:
   ```bash
   sudo ./deploy.sh [target_directory] [db_password]
   ```

   Example:
   ```bash
   sudo ./deploy.sh /mnt/archie_brain
   ```

3. Access A.R.C.H.I.E. at `http://your-server:3000`

## Requirements

- Ubuntu 22.04/24.04 or Debian 11+
- Docker and Docker Compose
- At least 4GB RAM
- At least 10GB free disk space
- Root/sudo access

## Manual Installation

If the automated script fails, you can:

1. Copy files to target directory
2. Create `.env` file with database credentials
3. Run `docker-compose up -d`
4. Restore database with `docker exec -i archie_database psql -U archie -d archie < database.sql`

## Support

- Documentation: /docs folder
- Issues: https://github.com/KytranKatarn/archie-platform/issues
"""
        with open(os.path.join(package_dir, "README.md"), "w") as f:
            f.write(readme_content)

        # Create checksums file
        checksums = []
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                filepath = os.path.join(root, file)
                relpath = os.path.relpath(filepath, package_dir)
                with open(filepath, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                checksums.append(f"{file_hash}  {relpath}")

        with open(os.path.join(package_dir, "checksums.sha256"), "w") as f:
            f.write("\n".join(checksums))

        # Create tar.gz archive
        archive_path = os.path.join(BACKUP_DIR, f"{package_name}.tar.gz")
        current_app.logger.info(f"  Creating archive: {archive_path}")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(package_dir, arcname=package_name)

        # Get archive size and checksum
        archive_size = os.path.getsize(archive_path)
        with open(archive_path, "rb") as f:
            archive_checksum = hashlib.sha256(f.read()).hexdigest()

        # Clean up temp directory
        shutil.rmtree(package_dir)

        # Save to database
        with get_backup_db_cursor(cursor_factory=RealDictCursor) as (conn, cur):
            cur.execute(
                """
                INSERT INTO deployment_packages
                (package_name, version_tag, description, backup_source, file_path,
                 file_size, checksum, components, target_platform, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, package_name, version_tag, file_size, created_at
            """,
                (
                    package_name,
                    version_tag,
                    description,
                    from_backup,
                    archive_path,
                    archive_size,
                    archive_checksum,
                    json.dumps(components_included),
                    target_platform,
                    current_user.id if current_user.is_authenticated else None,
                ),
            )
            package = cur.fetchone()

        current_app.logger.info(f"Deployment package created: {package_name} ({archive_size / 1024 / 1024:.1f} MB)")

        return jsonify(
            {
                "success": True,
                "message": "Deployment package created successfully",
                "package": {
                    "name": package_name,
                    "version": version_tag,
                    "size_mb": round(archive_size / 1024 / 1024, 2),
                    "checksum": archive_checksum,
                    "components": components_included,
                    "download_url": f"/tools/backup-manager/api/download-deployment/{package_name}",
                },
            }
        )

    except Exception as e:
        current_app.logger.error(f"Deployment package creation failed: {str(e)}")
        # Cleanup on failure
        if "package_dir" in locals() and os.path.exists(package_dir):
            shutil.rmtree(package_dir)
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/download-deployment/<package_name>")
@admin_required
def download_deployment_package(package_name):
    """Download a deployment package"""
    try:
        # Find package and update download count in database
        with get_backup_db_cursor(cursor_factory=RealDictCursor) as (conn, cur):
            cur.execute(
                """
                SELECT file_path FROM deployment_packages
                WHERE package_name = %s
            """,
                (package_name,),
            )
            package = cur.fetchone()

            if not package:
                return jsonify({"success": False, "error": "Package not found"}), 404

            file_path = package["file_path"]

            # Update download count
            cur.execute(
                """
                UPDATE deployment_packages
                SET download_count = download_count + 1,
                    last_downloaded_at = NOW()
                WHERE package_name = %s
            """,
                (package_name,),
            )

        if not os.path.exists(file_path):
            return jsonify({"success": False, "error": "Package file not found"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"{package_name}.tar.gz",
            mimetype="application/gzip",
        )

    except Exception as e:
        current_app.logger.error(f"Failed to download deployment package {package_name}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/delete-deployment/<package_name>", methods=["DELETE"])
@admin_required
def delete_deployment_package(package_name):
    """Delete a deployment package"""
    try:
        with get_backup_db_cursor(cursor_factory=RealDictCursor) as (conn, cur):
            # Get file path
            cur.execute(
                """
                SELECT file_path FROM deployment_packages
                WHERE package_name = %s
            """,
                (package_name,),
            )
            package = cur.fetchone()

            if not package:
                return jsonify({"success": False, "error": "Package not found"}), 404

            # Delete file
            if package["file_path"] and os.path.exists(package["file_path"]):
                os.remove(package["file_path"])

            # Delete from database
            cur.execute(
                """
                DELETE FROM deployment_packages
                WHERE package_name = %s
            """,
                (package_name,),
            )

        return jsonify({"success": True, "message": f"Package {package_name} deleted"})

    except Exception as e:
        current_app.logger.error(f"Failed to delete deployment package {package_name}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# EXTERNAL STORAGE API ROUTES
# =============================================================================


@backup_manager_bp.route("/external-status")
@admin_required
def external_storage_status():
    """Get external storage status and statistics"""
    try:
        stats = get_external_storage_stats()
        return jsonify({"success": True, **stats})
    except Exception as e:
        current_app.logger.error(f"Failed to get external storage status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/external-list")
@admin_required
def list_external_backups():
    """List backups on external storage"""
    try:
        if not is_external_storage_available():
            return jsonify({"success": False, "error": "External storage not mounted"})

        backups = []
        for item in os.listdir(EXTERNAL_BACKUP_DIR):
            item_path = os.path.join(EXTERNAL_BACKUP_DIR, item)
            if os.path.isdir(item_path):
                metadata_file = os.path.join(item_path, "metadata.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, "r") as f:
                            metadata = json.load(f)
                        # Calculate size
                        total_size = sum(
                            os.path.getsize(os.path.join(root, f))
                            for root, _, files in os.walk(item_path)
                            for f in files
                        )
                        metadata["size"] = total_size
                        metadata["size_mb"] = round(total_size / (1024 * 1024), 2)
                        backups.append(metadata)
                    except Exception:
                        # Backup without valid metadata
                        backups.append(
                            {
                                "name": item,
                                "error": "Invalid metadata",
                            }
                        )

        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return jsonify({"success": True, "backups": backups})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/sync-to-external/<backup_name>", methods=["POST"])
@admin_required
def sync_backup_to_external(backup_name):
    """Manually copy a specific backup to external storage"""
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            return (
                jsonify({"success": False, "error": f"Backup {backup_name} not found"}),
                404,
            )

        result = copy_to_external_storage(backup_name, backup_path)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# BACKUP LOCKING API ROUTES
# =============================================================================


@backup_manager_bp.route("/lock-status")
@admin_required
def get_lock_status():
    """Check if backup is currently in progress"""
    try:
        lock_info = check_backup_in_progress()
        return jsonify(
            {
                "success": True,
                "locked": lock_info is not None,
                "lock_info": lock_info,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# RESTORE PREVIEW & SELECTIVE RESTORE API ROUTES
# =============================================================================


@backup_manager_bp.route("/preview-restore/<backup_name>")
@admin_required
def api_preview_restore(backup_name):
    """Preview what would be restored from a backup (dry-run)"""
    try:
        preview = preview_restore(backup_name)
        if "error" in preview:
            return jsonify({"success": False, "error": preview["error"]}), 404
        return jsonify({"success": True, **preview})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/restore-selective/<backup_name>", methods=["POST"])
@admin_required
def api_restore_selective(backup_name):
    """Restore specific components from a backup"""
    try:
        data = request.get_json() or {}
        components = data.get("components", [])

        if not components:
            return jsonify({"success": False, "error": "No components specified"}), 400

        result = restore_components(backup_name, components)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# BACKUP COMPARISON API ROUTES
# =============================================================================


@backup_manager_bp.route("/compare/<backup1>/<backup2>")
@admin_required
def api_compare_backups(backup1, backup2):
    """Compare two backups and show differences"""
    try:
        result = compare_backups(backup1, backup2)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 404
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# WEBHOOK API ROUTES
# =============================================================================


@backup_manager_bp.route("/api/webhooks")
@admin_required
def list_webhooks():
    """List all configured webhooks"""
    try:
        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, url, event_types, active, created_at, last_triggered, last_status
                FROM backup_webhooks
                ORDER BY created_at DESC
            """
            )
            webhooks = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "webhooks": [
                    {
                        "id": w[0],
                        "url": w[1],
                        "event_types": w[2],
                        "active": w[3],
                        "created_at": w[4].isoformat() if w[4] else None,
                        "last_triggered": w[5].isoformat() if w[5] else None,
                        "last_status": w[6],
                    }
                    for w in webhooks
                ],
            }
        )
    except Exception as e:
        # Table might not exist yet
        current_app.logger.warning(f"Failed to list webhooks (table may not exist): {e}")
        return jsonify({"success": True, "webhooks": [], "note": str(e)})


@backup_manager_bp.route("/api/webhooks", methods=["POST"])
@admin_required
def create_webhook():
    """Create a new webhook"""
    try:
        data = request.get_json() or {}
        url = data.get("url")
        event_types = data.get("event_types", ["backup_complete", "backup_failed"])
        secret_key = data.get("secret_key")

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        with get_backup_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO backup_webhooks (url, event_types, secret_key, active)
                VALUES (%s, %s, %s, TRUE)
                RETURNING id
            """,
                (url, event_types, secret_key),
            )
            webhook_id = cur.fetchone()[0]

        return jsonify({"success": True, "webhook_id": webhook_id})

    except Exception as e:
        current_app.logger.error(f"Failed to create webhook: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/webhooks/<int:webhook_id>", methods=["DELETE"])
@admin_required
def delete_webhook(webhook_id):
    """Delete a webhook"""
    try:
        with get_backup_db_cursor() as (conn, cur):
            cur.execute("DELETE FROM backup_webhooks WHERE id = %s", (webhook_id,))

        return jsonify({"success": True, "message": f"Webhook {webhook_id} deleted"})

    except Exception as e:
        current_app.logger.error(f"Failed to delete webhook {webhook_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/webhooks/<int:webhook_id>/test", methods=["POST"])
@admin_required
def test_webhook(webhook_id):
    """Send a test webhook"""
    try:
        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT url, secret_key FROM backup_webhooks WHERE id = %s",
                (webhook_id,),
            )
            webhook = cur.fetchone()

        if not webhook:
            return jsonify({"success": False, "error": "Webhook not found"}), 404

        url, secret_key = webhook

        payload = {
            "event": "test",
            "message": "This is a test webhook from A.R.C.H.I.E. Backup Manager",
            "timestamp": datetime.now().isoformat(),
        }

        headers = {"Content-Type": "application/json"}
        if secret_key:
            signature = hmac.new(
                secret_key.encode(),
                json.dumps(payload).encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Archie-Signature"] = signature

        response = requests.post(url, json=payload, headers=headers, timeout=10)

        return jsonify(
            {
                "success": True,
                "status_code": response.status_code,
                "response": response.text[:500] if response.text else None,
            }
        )

    except Exception as e:
        current_app.logger.error(f"Failed to test webhook {webhook_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# HOOK API ROUTES
# =============================================================================


@backup_manager_bp.route("/api/hooks")
@admin_required
def list_hooks():
    """List installed pre and post hooks"""
    try:
        hooks = {"pre": [], "post": []}

        for hook_type, hook_dir in [("pre", PRE_HOOKS_DIR), ("post", POST_HOOKS_DIR)]:
            if os.path.exists(hook_dir):
                for script in sorted(os.listdir(hook_dir)):
                    script_path = os.path.join(hook_dir, script)
                    if os.path.isfile(script_path):
                        hooks[hook_type].append(
                            {
                                "name": script,
                                "executable": os.access(script_path, os.X_OK),
                                "size": os.path.getsize(script_path),
                                "modified": datetime.fromtimestamp(os.path.getmtime(script_path)).isoformat(),
                            }
                        )

        return jsonify({"success": True, "hooks": hooks, "hooks_dir": HOOKS_DIR})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/hooks/<hook_type>", methods=["POST"])
@admin_required
def upload_hook(hook_type):
    """Upload a new hook script"""
    try:
        if hook_type not in ["pre", "post"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid hook type (use 'pre' or 'post')",
                    }
                ),
                400,
            )

        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"success": False, "error": "No file selected"}), 400

        hook_dir = PRE_HOOKS_DIR if hook_type == "pre" else POST_HOOKS_DIR
        script_path = os.path.join(hook_dir, file.filename)

        file.save(script_path)
        os.chmod(script_path, 0o755)

        return jsonify(
            {
                "success": True,
                "message": f"Hook {file.filename} uploaded to {hook_type} hooks",
                "path": script_path,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/api/hooks/<hook_type>/<name>", methods=["DELETE"])
@admin_required
def delete_hook(hook_type, name):
    """Delete a hook script"""
    try:
        if hook_type not in ["pre", "post"]:
            return jsonify({"success": False, "error": "Invalid hook type"}), 400

        hook_dir = PRE_HOOKS_DIR if hook_type == "pre" else POST_HOOKS_DIR
        script_path = os.path.join(hook_dir, name)

        if not os.path.exists(script_path):
            return jsonify({"success": False, "error": f"Hook {name} not found"}), 404

        os.remove(script_path)
        return jsonify({"success": True, "message": f"Hook {name} deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# GOOGLE DRIVE CLOUD BACKUP ROUTES
# =============================================================================

# In-memory progress tracking for cloud operations
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


@backup_manager_bp.route("/cloud/status", methods=["GET"])
@admin_required
def cloud_status():
    """Get Google Drive cloud backup status."""
    config = _get_cloud_config()

    from tools.backup_manager.gdrive_service import is_oauth_configured

    result = {
        "enabled": config["enabled"],
        "has_service_account": os.path.exists(config["service_account_path"]),
        "has_oauth": is_oauth_configured(),
        "has_folder_id": bool(config["folder_id"]),
        "has_passphrase": bool(config["passphrase_hash"]),
        "connected": False,
        "storage": None,
        "email": None,
        "auth_type": None,
    }

    if config["enabled"]:
        try:
            from tools.backup_manager.gdrive_service import (
                get_drive_service,
                test_connection,
                get_storage_quota,
            )

            svc = get_drive_service(config["service_account_path"])
            conn = test_connection(svc)
            if conn["success"]:
                result["connected"] = True
                result["email"] = conn.get("email")
                result["auth_type"] = conn.get("auth_type")
                result["storage"] = get_storage_quota(svc)
        except Exception as e:
            result["connection_error"] = str(e)

    return jsonify({"success": True, **result})


@backup_manager_bp.route("/cloud/setup", methods=["POST"])
@admin_required
def cloud_setup():
    """Test service account and create/find backup folder."""
    config = _get_cloud_config()

    if not os.path.exists(config["service_account_path"]):
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Service account key not found at {config['service_account_path']}",
                }
            ),
            400,
        )

    try:
        from tools.backup_manager.gdrive_service import (
            get_drive_service,
            test_connection,
            ensure_backup_folder,
        )

        svc = get_drive_service(config["service_account_path"])
        conn = test_connection(svc)
        if not conn["success"]:
            return jsonify({"success": False, "error": conn["error"]}), 400

        folder_id = ensure_backup_folder(svc, config["folder_id"])

        # Save folder ID and enable
        _update_env_var("GDRIVE_BACKUP_FOLDER_ID", folder_id)
        _update_env_var("GDRIVE_ENABLED", "true")

        return jsonify(
            {
                "success": True,
                "email": conn.get("email"),
                "folder_id": folder_id,
                "message": "Google Drive connected and backup folder ready",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/cloud/oauth/start", methods=["POST"])
@admin_required
def cloud_oauth_start():
    """Start OAuth flow — returns the Google authorization URL."""
    try:
        from tools.backup_manager.gdrive_service import get_oauth_flow

        flow = get_oauth_flow()
        flow.redirect_uri = "http://localhost:8085"

        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )

        return jsonify({"success": True, "auth_url": auth_url})
    except FileNotFoundError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/cloud/oauth/exchange", methods=["POST"])
@admin_required
def cloud_oauth_exchange():
    """Exchange an authorization code for OAuth tokens."""
    try:
        from tools.backup_manager.gdrive_service import get_oauth_flow, save_oauth_token

        data = request.get_json() or {}
        code = data.get("code", "").strip()
        if not code:
            return (
                jsonify({"success": False, "error": "Authorization code required"}),
                400,
            )

        flow = get_oauth_flow()
        flow.redirect_uri = "http://localhost:8085"
        flow.fetch_token(code=code)
        save_oauth_token(flow.credentials)

        # Auto-setup: enable and create backup folder
        from tools.backup_manager.gdrive_service import (
            get_drive_service,
            ensure_backup_folder,
        )

        svc = get_drive_service()
        folder_id = ensure_backup_folder(svc)
        _update_env_var("GDRIVE_BACKUP_FOLDER_ID", folder_id)
        _update_env_var("GDRIVE_ENABLED", "true")

        from tools.backup_manager.gdrive_service import test_connection

        conn = test_connection(svc)

        return jsonify(
            {
                "success": True,
                "message": "Google Drive connected via OAuth",
                "email": conn.get("email"),
                "folder_id": folder_id,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/cloud/set-passphrase", methods=["POST"])
@admin_required
def cloud_set_passphrase():
    """Set or update the encryption passphrase."""
    data = request.get_json()
    passphrase = data.get("passphrase", "").strip() if data else ""

    if len(passphrase) < 8:
        return (
            jsonify({"success": False, "error": "Passphrase must be at least 8 characters"}),
            400,
        )

    from tools.backup_manager.gdrive_crypto import hash_passphrase

    ph = hash_passphrase(passphrase)
    _update_env_var("GDRIVE_ENCRYPTION_PASSPHRASE_HASH", ph)

    return jsonify({"success": True, "message": "Encryption passphrase set"})


@backup_manager_bp.route("/cloud/verify-passphrase", methods=["POST"])
@admin_required
def cloud_verify_passphrase():
    """Verify the passphrase matches the stored hash."""
    data = request.get_json()
    passphrase = data.get("passphrase", "").strip() if data else ""
    config = _get_cloud_config()

    if not config["passphrase_hash"]:
        return (
            jsonify({"success": False, "error": "No passphrase has been set yet"}),
            400,
        )

    from tools.backup_manager.gdrive_crypto import verify_passphrase

    if verify_passphrase(passphrase, config["passphrase_hash"]):
        return jsonify({"success": True, "message": "Passphrase verified"})
    return jsonify({"success": False, "error": "Incorrect passphrase"}), 401


@backup_manager_bp.route("/cloud/upload/<backup_name>", methods=["POST"])
@admin_required
def cloud_upload(backup_name):
    """Encrypt and upload a local backup to Google Drive."""
    data = request.get_json() or {}
    passphrase = data.get("passphrase", "").strip()
    config = _get_cloud_config()

    if not config["enabled"]:
        return jsonify({"success": False, "error": "Google Drive not enabled"}), 400
    if not config["passphrase_hash"]:
        return jsonify({"success": False, "error": "No passphrase configured"}), 400

    from tools.backup_manager.gdrive_crypto import verify_passphrase

    if not verify_passphrase(passphrase, config["passphrase_hash"]):
        return jsonify({"success": False, "error": "Incorrect passphrase"}), 401

    # Find the local backup
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.isdir(backup_path):
        return (
            jsonify({"success": False, "error": f"Backup {backup_name} not found"}),
            404,
        )

    import threading

    op_id = f"upload_{backup_name}_{int(time.time())}"
    _cloud_progress[op_id] = {
        "stage": "starting",
        "percent": 0,
        "error": None,
        "result": None,
    }

    def _do_upload():
        temp_tar = None
        temp_enc = None
        try:
            import tarfile as _tarfile
            from tools.backup_manager.gdrive_crypto import encrypt_file
            from tools.backup_manager.gdrive_service import (
                get_drive_service,
                upload_file,
                ensure_backup_folder,
            )

            _cloud_progress[op_id]["stage"] = "compressing (cloud-optimized)"
            _cloud_progress[op_id]["percent"] = 5

            # Create tar.gz of backup directory
            temp_tar = os.path.join(BACKUP_DIR, f".cloud_tmp_{backup_name}.tar.gz")
            with _tarfile.open(temp_tar, "w:gz") as tar:
                tar.add(backup_path, arcname=backup_name, filter=_cloud_tar_filter)

            _cloud_progress[op_id]["stage"] = "encrypting"
            _cloud_progress[op_id]["percent"] = 15

            # Encrypt
            temp_enc = temp_tar + ".enc"

            def enc_progress(done, total):
                pct = 15 + int((done / total) * 25) if total else 15
                _cloud_progress[op_id]["percent"] = pct

            encrypt_file(temp_tar, temp_enc, passphrase, on_progress=enc_progress)

            # Clean up tar (keep only encrypted)
            os.remove(temp_tar)
            temp_tar = None

            _cloud_progress[op_id]["stage"] = "uploading"
            _cloud_progress[op_id]["percent"] = 40

            # Upload
            svc = get_drive_service(config["service_account_path"])
            folder_id = ensure_backup_folder(svc, config["folder_id"])

            def upload_progress(done, total):
                pct = 40 + int((done / total) * 55) if total else 40
                _cloud_progress[op_id]["percent"] = pct

            result = upload_file(
                svc,
                temp_enc,
                folder_id,
                filename=f"{backup_name}.tar.gz.enc",
                on_progress=upload_progress,
            )

            # Cleanup
            os.remove(temp_enc)
            temp_enc = None

            _cloud_progress[op_id]["stage"] = "complete"
            _cloud_progress[op_id]["percent"] = 100
            _cloud_progress[op_id]["result"] = result

        except Exception as e:
            _cloud_progress[op_id]["stage"] = "error"
            _cloud_progress[op_id]["error"] = str(e)
        finally:
            if temp_tar and os.path.exists(temp_tar):
                os.remove(temp_tar)
            if temp_enc and os.path.exists(temp_enc):
                os.remove(temp_enc)

    thread = threading.Thread(target=_do_upload, daemon=True)
    thread.start()

    return jsonify({"success": True, "operation_id": op_id, "message": "Upload started"})


@backup_manager_bp.route("/cloud/download/<file_id>", methods=["POST"])
@admin_required
def cloud_download(file_id):
    """Download and decrypt a backup from Google Drive."""
    data = request.get_json() or {}
    passphrase = data.get("passphrase", "").strip()
    config = _get_cloud_config()

    if not config["enabled"]:
        return jsonify({"success": False, "error": "Google Drive not enabled"}), 400
    if not config["passphrase_hash"]:
        return jsonify({"success": False, "error": "No passphrase configured"}), 400

    from tools.backup_manager.gdrive_crypto import verify_passphrase

    if not verify_passphrase(passphrase, config["passphrase_hash"]):
        return jsonify({"success": False, "error": "Incorrect passphrase"}), 401

    import threading

    op_id = f"download_{file_id}_{int(time.time())}"
    _cloud_progress[op_id] = {
        "stage": "starting",
        "percent": 0,
        "error": None,
        "result": None,
    }

    def _do_download():
        temp_enc = None
        temp_tar = None
        try:
            from tools.backup_manager.gdrive_service import (
                get_drive_service,
                download_file as gdrive_download,
            )
            from tools.backup_manager.gdrive_crypto import decrypt_file

            _cloud_progress[op_id]["stage"] = "downloading"
            _cloud_progress[op_id]["percent"] = 5

            svc = get_drive_service(config["service_account_path"])

            # Get filename
            file_meta = svc.files().get(fileId=file_id, fields="name").execute()
            orig_name = file_meta.get("name", "backup.tar.gz.enc")

            temp_enc = os.path.join(BACKUP_DIR, f".cloud_dl_{orig_name}")

            def dl_progress(done, total):
                pct = 5 + int((done / total) * 45) if total else 5
                _cloud_progress[op_id]["percent"] = pct

            gdrive_download(svc, file_id, temp_enc, on_progress=dl_progress)

            _cloud_progress[op_id]["stage"] = "decrypting"
            _cloud_progress[op_id]["percent"] = 50

            # Decrypt
            temp_tar = temp_enc.replace(".enc", "")
            if temp_tar == temp_enc:
                temp_tar = temp_enc + ".decrypted"

            def dec_progress(done, total):
                pct = 50 + int((done / total) * 30) if total else 50
                _cloud_progress[op_id]["percent"] = pct

            decrypt_file(temp_enc, temp_tar, passphrase, on_progress=dec_progress)
            os.remove(temp_enc)
            temp_enc = None

            _cloud_progress[op_id]["stage"] = "extracting"
            _cloud_progress[op_id]["percent"] = 85

            # Extract tar.gz
            import tarfile as _tarfile

            with _tarfile.open(temp_tar, "r:gz") as tar:
                # Security: check for path traversal
                for member in tar.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        raise ValueError(f"Unsafe path in archive: {member.name}")
                tar.extractall(path=BACKUP_DIR)

            # Determine extracted backup name
            backup_name = orig_name.replace(".tar.gz.enc", "")
            os.remove(temp_tar)
            temp_tar = None

            _cloud_progress[op_id]["stage"] = "complete"
            _cloud_progress[op_id]["percent"] = 100
            _cloud_progress[op_id]["result"] = {"backup_name": backup_name}

        except Exception as e:
            _cloud_progress[op_id]["stage"] = "error"
            _cloud_progress[op_id]["error"] = str(e)
        finally:
            if temp_enc and os.path.exists(temp_enc):
                os.remove(temp_enc)
            if temp_tar and os.path.exists(temp_tar):
                os.remove(temp_tar)

    thread = threading.Thread(target=_do_download, daemon=True)
    thread.start()

    return jsonify({"success": True, "operation_id": op_id, "message": "Download started"})


@backup_manager_bp.route("/cloud/list", methods=["GET"])
@admin_required
def cloud_list():
    """List all cloud backups.

    Returns 200 with ``enabled=false`` if Google Drive integration isn't
    configured, and 200 with ``oauth_valid=false`` if OAuth credentials are
    stale (``invalid_grant``) so the UI can render a "reconnect" prompt
    instead of a 500. Other exceptions still return 500 for real bugs.
    """
    config = _get_cloud_config()
    if not config["enabled"]:
        return jsonify({"success": True, "enabled": False, "backups": [], "reason": "Google Drive not enabled"})

    try:
        from tools.backup_manager.gdrive_service import (
            get_drive_service,
            list_backups,
            ensure_backup_folder,
        )

        svc = get_drive_service(config["service_account_path"])
        folder_id = ensure_backup_folder(svc, config["folder_id"])
        backups = list_backups(svc, folder_id)
        return jsonify({"success": True, "enabled": True, "oauth_valid": True, "backups": backups})
    except Exception as e:
        err = str(e)
        if "invalid_grant" in err.lower():
            return jsonify(
                {
                    "success": False,
                    "enabled": True,
                    "oauth_valid": False,
                    "backups": [],
                    "error": "Google Drive OAuth credentials are stale — reconnect required.",
                }
            )
        return jsonify({"success": False, "error": err}), 500


@backup_manager_bp.route("/cloud/delete/<file_id>", methods=["DELETE"])
@admin_required
def cloud_delete(file_id):
    """Delete a cloud backup."""
    config = _get_cloud_config()
    if not config["enabled"]:
        return jsonify({"success": False, "error": "Google Drive not enabled"}), 400

    try:
        from tools.backup_manager.gdrive_service import get_drive_service, delete_backup

        svc = get_drive_service(config["service_account_path"])
        delete_backup(svc, file_id)
        return jsonify({"success": True, "message": "Cloud backup deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@backup_manager_bp.route("/cloud/progress", methods=["GET"])
@admin_required
def cloud_progress():
    """Poll endpoint for cloud operation progress.

    Called with no ``operation_id`` (e.g. from a dashboard widget checking
    "anything in flight?") returns 200 + ``idle=true`` instead of 404 so
    health pollers don't false-alarm. An explicit-but-unknown id still
    returns 404 (real client error).
    """
    op_id = request.args.get("operation_id", "")
    if not op_id:
        return jsonify({"success": True, "idle": True})
    if op_id not in _cloud_progress:
        return jsonify({"success": False, "error": "Operation not found"}), 404

    progress = _cloud_progress[op_id]

    # Clean up completed/errored operations after reading
    if progress["stage"] in ("complete", "error"):
        result = dict(progress)
        import threading

        def cleanup():
            _cloud_progress.pop(op_id, None)

        threading.Timer(60, cleanup).start()
        return jsonify({"success": True, **result})

    return jsonify({"success": True, **progress})
