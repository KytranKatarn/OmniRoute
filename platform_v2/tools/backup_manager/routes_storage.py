"""Backup Manager — cloud / external USB / deployment packages / module storage routes.

Split from the original backup_manager_routes.py monolith (Task #2699).
All routes are registered via register_storage_routes(bp, admin_required).
"""

from flask import jsonify, request, send_file, render_template, current_app
from flask_login import current_user
import os
import json
import shutil
import subprocess
import tempfile
import tarfile
import gzip
import time
import hashlib
import hmac
import requests
from datetime import datetime, timedelta
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from database import _get_db_password

# Pull every shared helper / constant / programmatic function into module scope
from ._shared import (
    BACKUP_DIR,
    CLOUD_EXCLUDE_DIRS,
    EXTERNAL_BACKUP_DIR,
    PLATFORM_DIR,
    _cloud_progress,
    _cloud_tar_filter,
    _gdrive_is_fully_configured,
    _get_cloud_config,
    _update_env_var,
    admin_required,
    backup_database_python,
    copy_to_external_storage,
    file_hash,
    generate_deploy_script,
    get_backup_db_cursor,
    get_backup_retention_status,
    get_external_storage_stats,
    get_platform_version,
    is_external_storage_available,
)


def enqueue_deployment_package_job(version_tag, description="W.A.R.D.E.N. auto-package"):
    """Insert a deployment_package_jobs row and launch the background build thread.
    Importable from agent_jobs.py for scheduler-context calls (no HTTP needed)."""
    import threading

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_version = version_tag.replace(".", "_").replace(" ", "_")
    package_name = f"archie-deployment-{safe_version}-{timestamp}"

    with get_backup_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO deployment_package_jobs (package_name, status, progress_pct) "
            "VALUES (%s, 'queued', 0) RETURNING id",
            (package_name,),
        )
        job_id = cur.fetchone()[0]

    t = threading.Thread(
        target=_build_deployment_package_bg,
        args=(job_id, package_name, description, version_tag, None, "linux"),
        daemon=True,
    )
    t.start()
    return job_id


def _update_pkg_job(job_id, status, progress_pct, error=None):
    """Update deployment_package_jobs row. Called from background thread."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE deployment_package_jobs SET status=%s, progress_pct=%s, error=%s, "
                "completed_at = CASE WHEN %s IN ('ready','failed') THEN NOW() ELSE NULL END "
                "WHERE id=%s",
                (status, progress_pct, error, status, job_id),
            )
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to update pkg job %s: %s", job_id, e)


def _build_deployment_package_bg(job_id, package_name, description, version_tag, from_backup, target_platform):
    """Background thread: run deployment package creation with progress updates."""
    import logging

    logger = logging.getLogger(__name__)
    package_dir = os.path.join("/tmp", package_name)

    try:
        _update_pkg_job(job_id, "building", 10)

        os.makedirs(package_dir, exist_ok=True)
        logger.info("Creating deployment package: %s", package_name)
        components_included = []

        if from_backup:
            backup_path = os.path.join(BACKUP_DIR, from_backup)
            if not os.path.exists(backup_path):
                _update_pkg_job(job_id, "failed", 0, error=f"Backup {from_backup} not found")
                return
            for item in os.listdir(backup_path):
                src = os.path.join(backup_path, item)
                dst = os.path.join(package_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
            components_included.append("backup_contents")
        else:
            # 1. Database dump
            logger.info("  Dumping database...")
            db_file = os.path.join(package_dir, "database.sql")
            backup_database_python(db_file)
            components_included.append("database")
            _update_pkg_job(job_id, "building", 30)

            # 2. Platform code
            logger.info("  Copying platform code...")
            platform_dst = os.path.join(package_dir, "platform_v2")
            platform_dirs = ["tools", "templates", "static", "consciousness", "migrations"]
            for dir_name in platform_dirs:
                src = os.path.join(PLATFORM_DIR, dir_name)
                if os.path.exists(src):
                    dst = os.path.join(platform_dst, dir_name)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
            important_files = ["app.py", "requirements.txt", "config.py", "module_registry.py", "rbac.py"]
            for file_name in important_files:
                src = os.path.join(PLATFORM_DIR, file_name)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(platform_dst, file_name))
            components_included.append("platform_v2")
            _update_pkg_job(job_id, "building", 60)

            # 3. AI Bridge
            ai_bridge_src = "/mnt/archie_brain/ai_bridge"
            if os.path.exists(ai_bridge_src):
                shutil.copytree(ai_bridge_src, os.path.join(package_dir, "ai_bridge"), dirs_exist_ok=True)
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
                shutil.copytree(scripts_src, os.path.join(package_dir, "scripts"), dirs_exist_ok=True)
                components_included.append("scripts")

            # 7. Nginx config
            nginx_src = "/mnt/archie_brain/nginx"
            if os.path.exists(nginx_src):
                shutil.copytree(nginx_src, os.path.join(package_dir, "nginx"), dirs_exist_ok=True)
                components_included.append("nginx")

            # 8. Node client
            node_client_src = "/mnt/archie_brain/node_client"
            if os.path.exists(node_client_src):
                shutil.copytree(node_client_src, os.path.join(package_dir, "node_client"), dirs_exist_ok=True)
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
        _update_pkg_job(job_id, "building", 90)
        checksums = []
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                filepath = os.path.join(root, file)
                relpath = os.path.relpath(filepath, package_dir)
                with open(filepath, "rb") as f:
                    file_hash_val = hashlib.sha256(f.read()).hexdigest()
                checksums.append(f"{file_hash_val}  {relpath}")
        with open(os.path.join(package_dir, "checksums.sha256"), "w") as f:
            f.write("\n".join(checksums))

        # Create tar.gz archive
        archive_path = os.path.join(BACKUP_DIR, f"{package_name}.tar.gz")
        logger.info("  Creating archive: %s", archive_path)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(package_dir, arcname=package_name)

        # Get archive size and checksum
        archive_size = os.path.getsize(archive_path)
        with open(archive_path, "rb") as f:
            archive_checksum = hashlib.sha256(f.read()).hexdigest()

        # Clean up temp directory
        shutil.rmtree(package_dir)

        # Save to deployment_packages table
        with get_backup_db_cursor(cursor_factory=RealDictCursor) as (conn, cur):
            cur.execute(
                """
                INSERT INTO deployment_packages
                (package_name, version_tag, description, backup_source, file_path,
                 file_size, checksum, components, target_platform)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                ),
            )

        logger.info("Deployment package created: %s (%.1f MB)", package_name, archive_size / 1024 / 1024)
        _update_pkg_job(job_id, "ready", 100)

    except Exception as e:
        logger.error("Deployment package build failed for job %s: %s", job_id, e)
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir)
        _update_pkg_job(job_id, "failed", 0, error=str(e)[:500])


def register_storage_routes(bp, admin_required):  # noqa: F811
    """Register cloud / external USB / deployment packages / module storage routes onto the supplied blueprint."""

    @bp.route("/download/<backup_name>")
    @admin_required
    def download_backup(backup_name):
        """Download a backup as tar.gz"""
        try:
            backup_path = os.path.join(BACKUP_DIR, backup_name)

            if not os.path.exists(backup_path):
                return jsonify({"success": False, "error": "Backup not found"}), 404

            # Stage the archive on the persistent backups volume — /tmp is a 512 MB
            # tmpfs inside the container and backups of 700 MB+ overflow it with
            # "No space left on device". BACKUP_DIR lives on /mnt/data2 (~361 GB free).
            staging_dir = os.path.join(BACKUP_DIR, ".downloads")
            os.makedirs(staging_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False, dir=staging_dir) as tmp:
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

    @bp.route("/delete/<backup_name>", methods=["DELETE"])
    @admin_required
    def delete_backup(backup_name):
        """Delete a backup"""
        try:
            # Look up actual path from backup_log — automated backups may be stored
            # at a host path (e.g. /mnt/data2/backups/) that differs from BACKUP_DIR.
            actual_path = None
            log_ids = []
            try:
                from database import get_db_cursor as _gdc

                with _gdc(commit=False) as (_c, _cur):
                    _cur.execute(
                        "SELECT id, file_path FROM backup_log WHERE file_path LIKE %s",
                        (f"%/{backup_name}",),
                    )
                    for _row in _cur.fetchall():
                        log_ids.append(_row["id"])
                        if actual_path is None and _row["file_path"]:
                            actual_path = _row["file_path"]
            except Exception as _e:
                current_app.logger.warning("backup_log lookup: %s", _e)

            # Resolve filesystem path: prefer DB-recorded path if accessible,
            # fall back to BACKUP_DIR + name for backups created via the web UI.
            fallback_path = os.path.join(BACKUP_DIR, backup_name)
            if actual_path and os.path.exists(actual_path):
                backup_path = actual_path
            elif os.path.exists(fallback_path):
                backup_path = fallback_path
            elif log_ids:
                # Backup exists in DB but its path is on host storage not mounted
                # in this container — remove the log record so the UI is cleaned up.
                backup_path = None
            else:
                return jsonify({"success": False, "error": "Backup not found"}), 404

            files_deleted = False
            if backup_path:
                parent_dir = os.path.dirname(backup_path)
                all_backups = [d for d in os.listdir(parent_dir) if os.path.isdir(os.path.join(parent_dir, d))]
                if len(all_backups) == 1:
                    return (
                        jsonify({"success": False, "error": "Cannot delete the only backup"}),
                        400,
                    )

                if os.path.isdir(backup_path):
                    shutil.rmtree(backup_path)
                else:
                    os.remove(backup_path)
                files_deleted = True

            # Clean up backup_log records
            try:
                from database import get_db_cursor

                with get_db_cursor(commit=True) as (_c, _cur):
                    if log_ids:
                        _cur.execute(
                            "DELETE FROM backup_log WHERE id = ANY(%s)",
                            (log_ids,),
                        )
                    else:
                        container_path = "/backups/" + backup_name
                        _cur.execute(
                            "DELETE FROM backup_log WHERE file_path = %s OR file_path = %s",
                            (fallback_path, container_path),
                        )
            except Exception as _db_err:
                current_app.logger.warning("backup_log cleanup failed (non-fatal): %s", _db_err)

            msg = (
                "Backup deleted successfully"
                if files_deleted
                else "Backup record removed (files on host storage were not deleted)"
            )
            return jsonify({"success": True, "message": msg})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/storage-stats")
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

    @bp.route("/modules/list")
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

                                # Prefer the cached size from metadata.json — walking
                                # 14+ backup dirs each cycle turned a <1s endpoint into
                                # a 4s+ endpoint as retention grew. Fall back to os.walk
                                # only when metadata is missing a size field.
                                cached = metadata.get("total_size_bytes") or metadata.get("size")
                                if cached:
                                    metadata["size"] = cached
                                else:
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

    @bp.route("/modules/available")
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
                        # Only real modules — a Flask module dir has routes.py OR __init__.py.
                        # Skips non-module dirs like static/ (the "static leak") so the count
                        # matches module_registry (34), not the raw tools/ dir listing. (#4051)
                        is_module = os.path.exists(os.path.join(module_path, "routes.py")) or os.path.exists(
                            os.path.join(module_path, "__init__.py")
                        )
                        if not is_module:
                            continue
                        # Check if it has routes.py (actual module)
                        has_routes = os.path.exists(os.path.join(module_path, "routes.py"))

                        # Count files
                        file_count = sum(
                            1 for f in os.listdir(module_path) if os.path.isfile(os.path.join(module_path, f))
                        )

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

    @bp.route("/api/deployment-backups")
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

                # The overview tile renders `deployments.length`, which is CAPPED by the
                # LIMIT above — at 58 rows today it happens to be right, but it would
                # freeze at 100 and under-report silently from then on. Serve a real
                # unbounded count so the tile never depends on the page size. (#5138)
                cur.execute(
                    """SELECT COUNT(*) AS total
                       FROM improvement_deployments
                       WHERE backup_name IS NOT NULL"""
                )
                total = (cur.fetchone() or {}).get("total") or 0

            # Flag whether each pre-deploy snapshot still EXISTS on disk. Retention prunes the
            # snapshot directory but leaves the improvement_deployments row, so most historical
            # rows point at a backup that is gone (measured 55 of 64 / 86% pruned). The Deployment
            # tab used to render a Restore button on ALL of them → those 404'd. The UI now disables
            # Restore when this is False. This is the SOLE pre-deploy-snapshot UI since #2439 (#5142 f/u).
            result = []
            for d in deployments:
                row = dict(d)
                bn = row.get("backup_name")
                row["snapshot_exists"] = bool(bn) and os.path.exists(os.path.join(BACKUP_DIR, bn))
                result.append(row)

            return jsonify(
                {
                    "success": True,
                    "deployments": result,
                    "total": total,
                }
            )

        except Exception as e:
            current_app.logger.error(f"Failed to load deployment backups: {e}")
            return jsonify(
                {
                    "success": True,
                    "deployments": [],
                    "note": f"Error loading deployment backups: {str(e)}",
                }
            )

    @bp.route("/api/deployment-packages")
    @admin_required
    def list_deployment_packages():
        """List deployment packages — default: last 30 days. Pass ?all=true to show all."""
        try:
            show_all = request.args.get("all", "").lower() in ("1", "true", "yes")
            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (
                conn,
                cur,
            ):
                if show_all:
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
                else:
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
                        WHERE dp.created_at >= NOW() - INTERVAL '30 days'
                        ORDER BY dp.created_at DESC
                        """
                    )
                packages = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "packages": [dict(p) for p in packages],
                    "filtered": not show_all,
                    "retention_days": None if show_all else 30,
                }
            )

        except Exception as e:
            current_app.logger.error(f"Failed to list deployment packages: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/create-deployment-package", methods=["POST"])
    @admin_required
    def create_deployment_package():
        """Create a deployment package asynchronously. Returns job_id immediately."""
        import threading

        data = request.get_json() or {}
        description = data.get("description", "Deployment package")
        version_tag = data.get("version_tag", get_platform_version())
        from_backup = data.get("from_backup")
        target_platform = data.get("target_platform", "linux")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_version = version_tag.replace(".", "_").replace(" ", "_")
        package_name = f"archie-deployment-{safe_version}-{timestamp}"

        try:
            with get_backup_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO deployment_package_jobs (package_name, status, progress_pct) "
                    "VALUES (%s, 'queued', 0) RETURNING id",
                    (package_name,),
                )
                job_id = cur.fetchone()[0]
        except Exception as e:
            current_app.logger.error("Failed to create deployment_package_jobs row: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

        def _build():
            _build_deployment_package_bg(job_id, package_name, description, version_tag, from_backup, target_platform)

        t = threading.Thread(target=_build, daemon=True)
        t.start()

        return jsonify({"success": True, "job_id": job_id, "package_name": package_name, "status": "queued"})

    @bp.route("/api/deployment-package-status/<int:job_id>")
    @admin_required
    def get_deployment_package_status(job_id):
        """Poll the build status of an async deployment package job."""
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
            cur.execute(
                "SELECT id, package_name, status, progress_pct, error, created_at, completed_at "
                "FROM deployment_package_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Job not found"}), 404
        return jsonify(
            {
                "success": True,
                **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(row).items()},
            }
        )

    @bp.route("/api/download-deployment/<package_name>")
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

    @bp.route("/api/delete-deployment/<package_name>", methods=["DELETE"])
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

    @bp.route("/external-status")
    @admin_required
    def external_storage_status():
        """Get external storage status and statistics"""
        try:
            stats = get_external_storage_stats()
            return jsonify({"success": True, **stats})
        except Exception as e:
            current_app.logger.error(f"Failed to get external storage status: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/external-list")
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
                    metadata = {}
                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, "r") as f:
                                metadata = json.load(f)
                            if not isinstance(metadata, dict):
                                metadata = {}
                        except Exception:
                            metadata = {}

                    # ⚠️ A MISSING metadata.json USED TO SKIP THE ROW ENTIRELY (no else
                    # branch), so the External tab listed 1 of 14 USB backups and hid
                    # 30.9 GB of real restore points — measured 2026-07-22 (#5122).
                    # `sync-to-external` copies a run dir verbatim and only the nightly
                    # triage writes a metadata.json, so ABSENT metadata is the NORMAL
                    # case on this tier, not corruption. Always emit a row and derive
                    # what the folder name already tells us.
                    total_size = metadata.get("total_size_bytes") or metadata.get("size")
                    if not total_size:
                        # Stat-only walk (no file reads) — 14 dirs / 33 GB measured fast.
                        try:
                            total_size = sum(
                                os.path.getsize(os.path.join(root, f))
                                for root, _, files in os.walk(item_path)
                                for f in files
                            )
                        except OSError:
                            total_size = 0

                    # Folder names are `YYYYMMDD_HHMMSS_<description>`.
                    ts_part, rest = "", item
                    if len(item) >= 15 and item[8] == "_" and item[:8].isdigit() and item[9:15].isdigit():
                        ts_part, rest = item[:15], item[16:]

                    low = rest.lower()
                    if "daily_triage" in low:
                        derived_type = "daily_triage"
                    elif low.startswith("pre-deploy") or "pre-deploy" in low:
                        derived_type = "predeploy"
                    elif "drill" in low:
                        derived_type = "drill"
                    else:
                        derived_type = "backup"

                    metadata["size"] = total_size
                    metadata["size_mb"] = round(total_size / (1024 * 1024), 2)
                    metadata["backup_name"] = item
                    metadata.setdefault("name", item)
                    metadata.setdefault("timestamp", metadata.get("ts", "") or ts_part)
                    metadata.setdefault("display_type", metadata.get("backup_type") or derived_type)
                    if not metadata.get("description") and rest:
                        metadata["description"] = rest.replace("_", " ")
                    # ISO form so the UI can render a real local time (ArchieTime).
                    if not metadata.get("created_at") and ts_part:
                        metadata["created_at"] = (
                            f"{ts_part[0:4]}-{ts_part[4:6]}-{ts_part[6:8]}"
                            f"T{ts_part[9:11]}:{ts_part[11:13]}:{ts_part[13:15]}"
                        )
                    metadata["tier"] = "usb"
                    backups.append(metadata)

            backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return jsonify({"success": True, "backups": backups})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/sync-to-external/<backup_name>", methods=["POST"])
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

    @bp.route("/external/delete/<backup_name>", methods=["DELETE"])
    @admin_required
    def delete_external_backup(backup_name):
        """Delete a backup from external storage."""
        try:
            safe_name = os.path.basename(backup_name)
            backup_path = os.path.join(EXTERNAL_BACKUP_DIR, safe_name)
            if not os.path.exists(backup_path):
                return jsonify({"success": False, "error": "Backup not found on external storage"}), 404
            if os.path.isdir(backup_path):
                import shutil as _shutil

                _shutil.rmtree(backup_path)
            else:
                os.remove(backup_path)
            current_app.logger.info("Deleted external backup: %s", safe_name)
            return jsonify({"success": True, "deleted": safe_name})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/packages/prune", methods=["POST"])
    @admin_required
    def prune_old_packages():
        """Delete deployment packages older than retention_days (default 30).

        Removes both the DB row and the on-disk file (if it exists).
        Request body (JSON, all optional):
            { "retention_days": 30 }
        """
        import shutil as _shutil

        try:
            retention_days = (request.get_json() or {}).get("retention_days", 30)
            cutoff = datetime.now() - timedelta(days=int(retention_days))

            pruned_db = 0
            pruned_fs = 0
            errors = []

            with get_backup_db_cursor(commit=True, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    "SELECT id, package_name, file_path FROM deployment_packages WHERE created_at < %s",
                    (cutoff,),
                )
                old_rows = cur.fetchall()

                for row in old_rows:
                    # Remove on-disk file/dir first (best-effort)
                    fp = row.get("file_path") or ""
                    if fp and os.path.exists(fp):
                        try:
                            if os.path.isdir(fp):
                                _shutil.rmtree(fp, ignore_errors=True)
                            else:
                                os.remove(fp)
                            pruned_fs += 1
                        except Exception as fe:
                            errors.append(f"fs:{row['package_name']}:{fe}")

                    # Remove DB row
                    cur.execute("DELETE FROM deployment_packages WHERE id = %s", (row["id"],))
                    pruned_db += 1

            return jsonify(
                {
                    "success": True,
                    "pruned": pruned_db,
                    "pruned_fs": pruned_fs,
                    "retention_days": retention_days,
                    "cutoff": cutoff.isoformat(),
                    "errors": errors,
                }
            )

        except Exception as e:
            current_app.logger.error(f"Failed to prune packages: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/cloud/status", methods=["GET"])
    @admin_required
    def cloud_status():
        """Get Google Drive cloud backup status.

        Every call that touches the OAuth token layer is wrapped so a stale
        refresh token ("invalid_grant") degrades to ``oauth_valid=false`` instead
        of bubbling up to the global exception handler (which redirects to
        /dashboard and strands the UI).
        """
        config = _get_cloud_config()

        result = {
            "enabled": config["enabled"],
            "has_service_account": os.path.exists(config["service_account_path"]),
            "has_oauth": False,
            "oauth_valid": False,
            "has_folder_id": bool(config["folder_id"]),
            # True when EITHER an operator-set passphrase hash exists OR the
            # server holds the nightly passphrase that actually decrypts what is
            # in Drive. Gating on the hash alone hid the whole Cloud section
            # (display:none, no explanation) while 37 real backups sat there.
            "has_passphrase": bool(config["passphrase_hash"] or config["server_passphrase"]),
            # Lets the UI say WHICH credential is in play instead of guessing.
            "passphrase_source": (
                "user" if config["passphrase_hash"] else ("server" if config["server_passphrase"] else "none")
            ),
            "connected": False,
            "storage": None,
            "email": None,
            "auth_type": None,
        }

        # OAuth presence + validity. If the stored refresh token is revoked,
        # is_oauth_configured() raises RefreshError — catch it so the UI can
        # render a "reconnect required" prompt instead of being redirected away.
        try:
            from tools.backup_manager.gdrive_service import is_oauth_configured

            result["has_oauth"] = is_oauth_configured()
            result["oauth_valid"] = result["has_oauth"]
        except Exception as e:  # noqa: BLE001 — includes google.auth RefreshError
            err = str(e)
            result["has_oauth"] = True  # token exists but can't refresh
            result["oauth_valid"] = False
            result["oauth_error"] = err
            if "invalid_grant" in err.lower():
                result["reconnect_required"] = True

        # Live connection probe. Try as long as ANY auth path is plausible —
        # backup_get_drive_service falls back to service account when OAuth is
        # missing/invalid, so gating purely on oauth_valid missed service-
        # account-only setups (observed 2026-04-17 after stale OAuth token
        # was moved aside and the service account turned out to be working).
        if config["enabled"] and (result["oauth_valid"] or result["has_service_account"]):
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
            except Exception as e:  # noqa: BLE001
                result["connection_error"] = str(e)

        # Simplified summary shape — used by monitoring endpoints and the
        # `/api/cloud/status` contract documented in the backup governance spec.
        configured, _why = _gdrive_is_fully_configured()
        result["configured"] = configured
        if not configured:
            result["not_configured_reason"] = _why

        # last_run + status from backup_log
        try:
            from database import get_db_cursor

            with get_db_cursor() as (_, _cur):
                _cur.execute(
                    "SELECT status, created_at FROM backup_log "
                    "WHERE tier = 'gdrive' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
                _row = _cur.fetchone()
            if _row:
                result["last_run"] = _row["created_at"].isoformat()
                result["last_run_status"] = _row["status"]
            else:
                result["last_run"] = None
                result["last_run_status"] = None
        except Exception as _le:
            result["last_run"] = None
            result["last_run_status"] = None
            result["last_run_error"] = str(_le)

        # Top-level `status` string for quick health checks
        if not configured:
            result["status"] = "not_configured"
        elif result.get("connected"):
            result["status"] = "ok"
        elif result.get("reconnect_required"):
            result["status"] = "reconnect_required"
        else:
            result["status"] = "error"

        return jsonify({"success": True, **result})

    @bp.route("/cloud/setup", methods=["POST"])
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

    @bp.route("/cloud/oauth/start", methods=["POST"])
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

    @bp.route("/cloud/oauth/exchange", methods=["POST"])
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

    @bp.route("/cloud/set-passphrase", methods=["POST"])
    @admin_required
    def cloud_set_passphrase():
        """Set or update the encryption passphrase.

        Overwriting an existing passphrase requires proving the caller knows the
        current one via `current_passphrase` in the request body. Without this
        guard, a typo-by-typo overwrite silently locks the user out of every
        existing encrypted backup — which happened once in practice 2026-04-17.
        """
        data = request.get_json() or {}
        passphrase = (data.get("passphrase") or "").strip()
        current = (data.get("current_passphrase") or "").strip()

        if len(passphrase) < 8:
            return (
                jsonify({"success": False, "error": "Passphrase must be at least 8 characters"}),
                400,
            )

        from tools.backup_manager.gdrive_crypto import hash_passphrase, verify_passphrase

        existing_hash = _get_cloud_config()["passphrase_hash"]
        if existing_hash:
            # A passphrase is already set — confirm the caller knows it.
            if not current:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "A passphrase is already set. Provide current_passphrase to overwrite it.",
                        }
                    ),
                    400,
                )
            if not verify_passphrase(current, existing_hash):
                return (
                    jsonify({"success": False, "error": "Current passphrase incorrect — cannot overwrite."}),
                    401,
                )

        ph = hash_passphrase(passphrase)
        # Persist to platform_settings, NOT the env: _update_env_var only reaches
        # one of four gunicorn workers and writes to platform_v2/.env, which the
        # container never loads — so a set passphrase failed on ~3 of 4 requests
        # and vanished on restart (#5125).
        from tools.backup_manager._shared import _set_gdrive_passphrase_hash

        _set_gdrive_passphrase_hash(ph)

        return jsonify({"success": True, "message": "Encryption passphrase set"})

    @bp.route("/cloud/verify-passphrase", methods=["POST"])
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

    @bp.route("/cloud/upload/<backup_name>", methods=["POST"])
    @admin_required
    def cloud_upload(backup_name):
        """Encrypt and upload a local backup to Google Drive."""
        data = request.get_json() or {}
        passphrase = data.get("passphrase", "").strip()
        config = _get_cloud_config()

        if not config["enabled"]:
            return jsonify({"success": False, "error": "Google Drive not enabled"}), 400

        # Pre-fix scratch never belongs off-site. Drive is a 15 GB FREE-TIER
        # account that filled once and silently killed off-site DB backups for
        # ~3 weeks; a 2.4 GB pre-deploy snapshot is the fastest way to refill it.
        # Cloud is currently clean (0 such objects) — this keeps it that way (#5126).
        from tools.backup_manager._shared import _is_drill_backup, _is_ephemeral_backup

        if _is_ephemeral_backup("", backup_name) or _is_drill_backup("", backup_name):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": (
                            "Pre-deploy / repair-bay snapshots and restorability drills are not "
                            "uploaded to cloud storage — they are short-lived rollback points and "
                            "local rehearsal evidence, not off-site restore points."
                        ),
                    }
                ),
                400,
            )

        from tools.backup_manager.gdrive_crypto import verify_passphrase

        if config["passphrase_hash"]:
            # An operator-set passphrase exists — keep proving the caller knows it.
            if not verify_passphrase(passphrase, config["passphrase_hash"]):
                return jsonify({"success": False, "error": "Incorrect passphrase"}), 401
        elif config["server_passphrase"]:
            # No operator passphrase, but the server holds the nightly one — the
            # secret every object in Drive is already encrypted under. Use it
            # rather than refusing, otherwise the ONLY off-site restore path is
            # blocked outright and new uploads would use a second, divergent key.
            # Trade-off accepted deliberately: these routes are @admin_required
            # and the plaintext is handled server-side either way, so making the
            # admin retype a 64-char generated secret buys nothing.
            passphrase = config["server_passphrase"]
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No passphrase available — set one in the Cloud tab, or set BACKUP_GDRIVE_PASSPHRASE.",
                    }
                ),
                400,
            )

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
                # Pre-flight: skip gracefully if credentials are not in place.
                _configured, _reason = _gdrive_is_fully_configured()
                if not _configured:
                    _cloud_progress[op_id]["stage"] = "skipped"
                    _cloud_progress[op_id]["error"] = _reason
                    try:
                        from database import get_db_cursor

                        with get_db_cursor(commit=True) as (_, _cur):
                            _cur.execute(
                                "INSERT INTO backup_log (tier, status, error_message) "
                                "VALUES ('gdrive', 'skipped', %s)",
                                (_reason,),
                            )
                    except Exception as _db_err:
                        current_app.logger.warning("backup_log INSERT failed for skipped gdrive upload: %s", _db_err)
                    return

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

    @bp.route("/cloud/download/<file_id>", methods=["POST"])
    @admin_required
    def cloud_download(file_id):
        """Download and decrypt a backup from Google Drive."""
        data = request.get_json() or {}
        passphrase = data.get("passphrase", "").strip()
        config = _get_cloud_config()

        if not config["enabled"]:
            return jsonify({"success": False, "error": "Google Drive not enabled"}), 400

        from tools.backup_manager.gdrive_crypto import verify_passphrase

        if config["passphrase_hash"]:
            # An operator-set passphrase exists — keep proving the caller knows it.
            if not verify_passphrase(passphrase, config["passphrase_hash"]):
                return jsonify({"success": False, "error": "Incorrect passphrase"}), 401
        elif config["server_passphrase"]:
            # No operator passphrase, but the server holds the nightly one — the
            # secret every object in Drive is already encrypted under. Use it
            # rather than refusing, otherwise the ONLY off-site restore path is
            # blocked outright and new uploads would use a second, divergent key.
            # Trade-off accepted deliberately: these routes are @admin_required
            # and the plaintext is handled server-side either way, so making the
            # admin retype a 64-char generated secret buys nothing.
            passphrase = config["server_passphrase"]
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No passphrase available — set one in the Cloud tab, or set BACKUP_GDRIVE_PASSPHRASE.",
                    }
                ),
                400,
            )

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
                from tools.backup_manager.gdrive_crypto import decrypt_with_candidates

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

                # Try the passphrase most likely to fit this object FIRST — the
                # Drive tier is not single-key (config/* is encrypted upstream
                # under BACKUP_CONFIG_PASSPHRASE). Verified against live objects.
                _is_config_obj = "/config/" in (orig_name or "")
                _candidates = [("user/explicit", passphrase)] if passphrase else []
                _cfg_pair = ("config", config.get("config_passphrase", ""))
                _gd_pair = ("gdrive", config.get("server_passphrase", ""))
                _candidates += [_cfg_pair, _gd_pair] if _is_config_obj else [_gd_pair, _cfg_pair]
                _used = decrypt_with_candidates(temp_enc, temp_tar, _candidates)
                _cloud_progress[op_id]["passphrase_used"] = _used
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

    @bp.route("/cloud/list", methods=["GET"])
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

    @bp.route("/cloud/delete/<file_id>", methods=["DELETE"])
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

    @bp.route("/cloud/progress", methods=["GET"])
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
