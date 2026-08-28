"""Backup Manager — core operations (create, list, status, health, lock, verify, retention) routes.

Split from the original backup_manager_routes.py monolith (Task #2699).
All routes are registered via register_operations_routes(bp, admin_required).
"""

from flask import jsonify, request, render_template, current_app
from flask_login import current_user
import os
import json
import shutil
import subprocess
import time
from datetime import datetime
from psycopg2.extras import RealDictCursor

# get_db_cursor (RealDictCursor) — NOT _shared's get_backup_db_cursor, which yields
# TUPLES and would break the row["backup_type"] access in api_quick_backup_stats.
from database import get_db_cursor

# Pull every shared helper / constant / programmatic function into module scope
from ._shared import (
    BACKUP_DIR,
    PLATFORM_DIR,
    acquire_backup_lock,
    backup_database_python,
    check_backup_in_progress,
    copy_to_external_storage,
    execute_post_hooks,
    execute_pre_hooks,
    get_backup_db_cursor,
    get_current_build,
    get_next_build_number,
    get_platform_version,
    is_external_storage_available,
    release_backup_lock,
    set_build_number,
    trigger_webhooks,
    verify_backup_integrity,
)


def register_operations_routes(bp, admin_required):  # noqa: F811
    """Register core operations (create, list, status, health, lock, verify, retention) routes onto the supplied blueprint."""

    @bp.route("/")
    @admin_required
    def index():
        """Backup manager main page"""
        return render_template("tools/backup_manager.html")

    @bp.route("/list")
    @admin_required
    def list_backups():
        """List all available backups — reads from backup_log DB table (source of truth)"""
        try:
            backups = []

            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, backup_type, file_path, file_size_bytes, size_bytes,
                           status, created_by, created_at, completed_at,
                           error_message, component, tier, duration_ms,
                           verification_status, notes,
                           git_commit, git_branch, triggered_by, proposal_id, pr_number,
                           build_number, platform_version
                    FROM backup_log
                    -- Pre-filter in SQL to non-empty, non-standalone, top-level rows (the
                    -- Python pass below still applies the same rules + the on-disk check).
                    -- Without this, LIMIT truncated the fetch and UNDERCOUNTED: an existing
                    -- backup can be old (retention keeps ~48) while thousands of noise rows
                    -- (verify, retention, per-component, per-tier) pile above it, pushing it
                    -- past the row window. The cap is a safety ceiling, not a display limit —
                    -- the on-disk filter is what bounds the output to what exists.
                    WHERE COALESCE(size_bytes, file_size_bytes, 0) > 0
                      AND COALESCE(backup_type, '') <> 'standalone'
                      -- Pre-deploy snapshots (Repair Bay safety copies taken before a proposal
                      -- deploy) are owned by the DEPLOYMENT tab (improvement_deployments). They
                      -- were also flooding the TOP of this list (newest build numbers), burying
                      -- the real nightly/weekly/manual restore points. Exclude them here so each
                      -- tab owns its own content — nothing is lost, they remain in Deployment (#5142).
                      AND COALESCE(notes, '') NOT LIKE 'Pre-deploy snapshot%'
                      AND (file_path IS NULL
                           OR file_path !~ '^/(backups|mnt/data2/backups|mnt/archie_brain/backups)/[^/]+/.+')
                    ORDER BY created_at DESC
                    LIMIT 5000
                    """,
                )
                rows = cur.fetchall()

            def _is_top_level(file_path, backup_type=None):
                # Standalones have their own tab — exclude from the main backup list
                if backup_type == "standalone":
                    return False
                if not file_path:
                    return True
                p = file_path.rstrip("/")
                for root in ("/backups/", "/mnt/data2/backups/", "/mnt/archie_brain/backups/"):
                    if p.startswith(root):
                        # Sub-components have an additional slash after the backup dir name
                        return "/" not in p[len(root) :]
                return True

            def _backup_present(file_path):
                """True only if the backup dir still exists on disk.

                backup_log is APPEND-ONLY: retention deletes the DIRECTORY but leaves the
                row. Without this check the list shows backups you can no longer restore,
                and the overview COUNT/SUM reflect the entire HISTORY (e.g. 1017 rows /
                550 GB) instead of what exists (~56 rows / ~90 GB). Normalise the equivalent
                host roots (/mnt/data2/backups, /mnt/archie_brain/backups) to the container
                mount before stat-ing; a non-local path (e.g. a boston-2: DR ref) simply
                fails the check, which is correct — it is not on this host.
                """
                if not file_path:
                    return False
                p = file_path.rstrip("/")
                for root in ("/mnt/data2/backups/", "/mnt/archie_brain/backups/"):
                    if p.startswith(root):
                        p = "/backups/" + p[len(root) :]
                        break
                try:
                    return os.path.exists(p)
                except OSError:
                    return False

            # Show only genuine, restorable backups: top-level (not a sub-component),
            # still on disk, and non-empty. The 0-byte rows are not backups — they are
            # failed weekly `verify`-job records mis-logged against the /backups root, and
            # they never gain a size. Dropping them here also drops them from the totals.
            rows = [
                r
                for r in rows
                if _is_top_level(r.get("file_path") or "", r.get("backup_type"))
                and _backup_present(r.get("file_path") or "")
                and (r.get("size_bytes") or r.get("file_size_bytes") or 0) > 0
            ]

            for row in rows:
                # Derive a human-readable name from file_path (last path component)
                raw_path = row.get("file_path") or ""
                name = os.path.basename(raw_path.rstrip("/")) or f"backup-{row['id']}"

                # Normalise size: prefer size_bytes, fall back to file_size_bytes
                size = row.get("size_bytes") or row.get("file_size_bytes") or 0
                total_size_mb = round(size / 1024 / 1024, 2) if size else 0

                # created_at as ISO string for UI
                created_at = row["created_at"].isoformat() if row.get("created_at") else None
                # timestamp in YYYYMMDD_HHMMSS format for legacy UI consumers
                timestamp = row["created_at"].strftime("%Y%m%d_%H%M%S") if row.get("created_at") else None

                backups.append(
                    {
                        # Identity
                        "id": row["id"],
                        "name": name,
                        "timestamp": timestamp,
                        # Type & status
                        "backup_type": row.get("backup_type") or "backup",
                        # Display-only: automated/component rows (nightly triage, retention, git
                        # bundles, per-component db/config/code/vps backups) carry no backup_type,
                        # so the list badge falls back to the component name to render a meaningful
                        # emoji + label instead of a generic "AUTO". Never used for restore/logic.
                        "display_type": (row.get("backup_type") or row.get("component") or "backup"),
                        "component": row.get("component"),
                        "tier": row.get("tier"),
                        "status": row.get("status"),
                        "verification_status": row.get("verification_status"),
                        # Size
                        "size": size,
                        "total_size_mb": total_size_mb,
                        # Timestamps
                        "created_at": created_at,
                        "completed_at": (row["completed_at"].isoformat() if row.get("completed_at") else None),
                        "duration_ms": row.get("duration_ms"),
                        # Authorship / notes
                        "created_by": row.get("created_by") or "system",
                        "description": row.get("notes") or "",
                        "error_message": row.get("error_message"),
                        # Path (for restore / download lookups)
                        "path": raw_path,
                        # Build number + version from backup_log (migrations 373/375)
                        "build_number": row.get("build_number"),
                        "platform_version": row.get("platform_version"),
                        "compression": None,
                        "external_copy": False,
                        # Version tracking (migration 373)
                        "git_commit": row.get("git_commit"),
                        "git_branch": row.get("git_branch"),
                        "triggered_by": row.get("triggered_by"),
                        "proposal_id": row.get("proposal_id"),
                        "pr_number": row.get("pr_number"),
                    }
                )

            # Totals describe EXACTLY the backups shown above (existing, non-empty, top-level)
            # so the overview cards and the list always agree. The old code ran
            # COUNT(*)/SUM(size_bytes) over the whole append-only backup_log, which counted
            # every backup ever made — including ~721 that retention had already deleted from
            # disk plus 0-byte verify rows — and reported 1017 backups / 550 GB when only
            # ~46 backups / ~96 GB actually exist.
            total_count = len(backups)
            total_size_bytes = sum(int(b.get("size") or 0) for b in backups)

            return jsonify(
                {
                    "success": True,
                    "backups": backups,
                    "current_build": get_current_build(),
                    "total_count": total_count,
                    "total_size_bytes": total_size_bytes,
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/current-build")
    @admin_required
    def api_current_build():
        """Get current build number"""
        return jsonify({"success": True, "current_build": get_current_build()})

    @bp.route("/health")
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
                        metadata = None
                        if os.path.exists(metadata_file):
                            try:
                                with open(metadata_file, "r") as f:
                                    metadata = json.load(f)
                            except Exception:
                                metadata = None
                        # Phase 1-6 host-cron backups (Daily_Triage / daily / weekly)
                        # write component dirs (database/, code/, gitbundles/, ...)
                        # and NO metadata.json — synthesize a record so /health
                        # counts them instead of reporting 0 backups (#4051).
                        if metadata is None and any(
                            os.path.isdir(os.path.join(backup_path, d))
                            for d in ("database", "code", "gitbundles", "config", "volumes")
                        ):
                            metadata = {"name": item, "timestamp": item[:15], "synthesized": True}
                        if metadata is not None:
                            backup_size = 0
                            for root, dirs, files in os.walk(backup_path):
                                for file in files:
                                    filepath = os.path.join(root, file)
                                    try:
                                        backup_size += os.path.getsize(filepath)
                                    except OSError:
                                        pass
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

    @bp.route("/verify/<backup_name>")
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

    @bp.route("/quick-stats", methods=["GET"])
    @admin_required
    def api_quick_backup_stats():
        """Last SUCCESSFUL run per Quick Backup type — size, duration, age.

        The three button captions used to hard-code size ranges ("~850-900 MB"). Those
        drifted badly: BRAIN BACKUP advertised ~440-460 MB while a database dump had
        grown to 1,543 MB, and COMPLETE ARCHIVE claimed a figure smaller than what
        FULL RESTORE actually produced. Serving the measured last run instead means the
        caption cannot go stale again.

        Reports the newest status='success' row only — a failed attempt must never be
        presented as "last run", for the same reason backup freshness gates on
        last_success rather than the newest attempt (#5013).
        """
        stats = {}
        try:
            with get_db_cursor(commit=False) as (_c, _cur):
                _cur.execute(
                    """
                    SELECT DISTINCT ON (backup_type)
                           backup_type, size_bytes, duration_ms, created_at
                    FROM backup_log
                    WHERE backup_type IN ('full', 'critical', 'database')
                      AND status = 'success'
                    ORDER BY backup_type, created_at DESC
                    """
                )
                for row in _cur.fetchall() or []:
                    dur = row.get("duration_ms") or 0
                    stats[row["backup_type"]] = {
                        "size_mb": round((row.get("size_bytes") or 0) / 1048576.0),
                        # 0 = pre-instrumentation row (duration_ms was never written
                        # before 2026-07-20); surface null so the UI shows "—" rather
                        # than claiming a backup finished instantly.
                        "duration_s": round(dur / 1000.0) if dur else None,
                        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                    }
        except Exception as e:
            current_app.logger.warning("quick-stats failed (non-fatal): %s", e)
            return jsonify({"success": True, "stats": {}, "error": str(e)})
        return jsonify({"success": True, "stats": stats})

    @bp.route("/create", methods=["POST"])
    @admin_required
    def api_create_backup():
        """Create a new backup (API route - use create_backup_programmatic for code)"""
        # Wall-clock for backup_log.duration_ms. The column has existed all along but
        # this INSERT never populated it, so every UI-triggered backup recorded 0 and
        # the Backups tab had no timing to show. Started before any work so the number
        # covers the whole request, including the DB dump.
        _t0 = time.time()
        try:
            data = request.get_json() or {}
            description = data.get("description", "Manual backup")
            backup_type = data.get("backup_type", "full")
            custom_components = data.get("components", [])

            # Capture git context (fail-safe — never crash the backup if git is unavailable)
            def _git(cmd):
                try:
                    return (
                        subprocess.run(
                            ["git", "-C", "/mnt/archie_brain", "-c", "safe.directory=/mnt/archie_brain"] + cmd,
                            capture_output=True,
                            text=True,
                            timeout=5,
                        ).stdout.strip()
                        or None
                    )
                except Exception:
                    return None

            _git_commit = _git(["rev-parse", "HEAD"])
            _git_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
            _triggered_by = data.get("triggered_by", "manual") if data else "manual"
            _proposal_id = data.get("proposal_id") if data else None
            _pr_number = data.get("pr_number") if data else None

            # Define component sets for each backup type
            ALL_COMPONENTS = [
                "database",
                "platform",
                "documentation",
                "ai_bridge",
                "migrations",
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
            platform_backup = os.path.join(backup_path, "platform_v2")  # default path even if not backed up
            if "platform" in components_to_backup:
                current_app.logger.info("Backing up platform files...")
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

            # (n8n workflow + persistence backup removed 2026-07-20. n8n was
            # decommissioned platform-wide on 2026-06-26, PRs #1931/#1932 — the module,
            # the compose services and the volumes are all gone, and
            # /mnt/archie_brain/n8n_workflows no longer exists. The blocks survived only
            # because their os.path.exists() guard made them skip silently, so a
            # COMPLETE ARCHIVE kept advertising n8n while backing up nothing.
            # Automation is now DHQ APScheduler jobs + native kbs_automations.)

            # 6. Backup deployment scripts — skip large binaries, caches, logs
            scripts_src = "/mnt/archie_brain/scripts"
            if "scripts" in components_to_backup and os.path.exists(scripts_src):
                current_app.logger.info("Backing up deployment scripts...")
                scripts_dst = os.path.join(backup_path, "scripts")

                def _scripts_ignore(directory, contents):
                    skip = set()
                    for name in contents:
                        full = os.path.join(directory, name)
                        if name in ("__pycache__",) or name.endswith((".log", ".pyc")):
                            skip.add(name)
                        elif os.path.isfile(full) and os.path.getsize(full) > 10 * 1024 * 1024:
                            skip.add(name)  # skip binaries/large files >10 MB
                    return skip

                shutil.copytree(scripts_src, scripts_dst, dirs_exist_ok=True, ignore=_scripts_ignore)
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

            # INSERT into backup_log so the list endpoint sees this backup immediately
            try:
                from database import get_db_cursor

                with get_db_cursor(commit=True) as (_c, _cur):
                    _platform_version = get_platform_version()
                    _cur.execute(
                        """INSERT INTO backup_log
                               (backup_type, file_path, size_bytes, status, tier,
                                component, notes, git_commit, git_branch,
                                triggered_by, proposal_id, pr_number, build_number,
                                platform_version, duration_ms, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
                        (
                            backup_type,
                            backup_path,
                            total_size,
                            "success",
                            "primary",
                            (
                                ",".join(components_to_backup)
                                if isinstance(components_to_backup, list)
                                else str(components_to_backup)
                            ),
                            description if description else "",
                            _git_commit,
                            _git_branch,
                            _triggered_by,
                            _proposal_id,
                            _pr_number,
                            new_build_number,
                            _platform_version,
                            int((time.time() - _t0) * 1000),
                        ),
                    )
            except Exception as _log_err:
                current_app.logger.warning("backup_log INSERT failed (non-fatal): %s", _log_err)

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

    @bp.route("/retention-status")
    @admin_required
    def retention_status():
        """
        Get current retention policy status showing which backups would be kept/deleted.

        Returns:
            {
                'keep': [list of backup names to keep],
                'delete': [list of backup names that can be deleted],
                'retention_daily': int,
                'retention_weekly': int,
                'retention_monthly': int,
                'stats': {
                    'total_backups': int,
                    'keep_count': int,
                    'delete_count': int,
                    'total_size_mb': float,
                    'space_to_free_mb': float
                }
            }
        """
        # Honest, read-only status (#5141). The ACTUAL pruning is done nightly by the
        # canonical per-(component, tier) engine scripts/backup/retention_prune.py (run by
        # backup_triage.sh) — which does NOT read a single global daily/weekly/monthly triple.
        # This endpoint used to synthesise a "7 daily + 4 weekly + 6 monthly" policy string
        # (from system_config values nothing enforces) plus a keep/delete split computed by
        # that same retired single-triple logic. Both were fiction. Report only what is real:
        # the last canonical prune + a truthful description of the policy model. The editable
        # triple and manual cleanup were retired the same day.
        try:
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

            return jsonify(
                {
                    "success": True,
                    "managed": "automatic",
                    "engine": "scripts/backup/retention_prune.py",
                    "schedule": "Nightly ~02:00 EDT (backup_triage.sh)",
                    "policy_summary": (
                        "Grandfather-Father-Son — a different daily / weekly / monthly keep "
                        "count for every component and storage tier (e.g. the database keeps "
                        "30 daily + 12 weekly + 6 monthly on the primary disk, but only 2 daily "
                        "on Google Drive)."
                    ),
                    "last_run": last_run,
                    "last_deleted_count": last_count,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/retention-policy", methods=["PUT"])
    @admin_required
    def update_retention_policy():
        """RETIRED (2026-07-23, #5141). There is no single editable daily/weekly/monthly policy.

        Retention is defined in code, per-(component, tier), in
        scripts/backup/retention_prune.py (run nightly by backup_triage.sh). The canonical
        engine NEVER read the system_config retention_daily/weekly/monthly values this
        endpoint wrote, so "saving" a policy here changed nothing about what actually got
        pruned — a silent no-op that reported success. It now refuses honestly instead of
        pretending to save.
        """
        return (
            jsonify(
                {
                    "success": False,
                    "retired": True,
                    "error": (
                        "Retention is managed in code, per-component and per-tier "
                        "(scripts/backup/retention_prune.py, run nightly). There is no single "
                        "global policy to edit here."
                    ),
                }
            ),
            410,
        )

    @bp.route("/cleanup", methods=["POST"])
    @admin_required
    def cleanup_backups():
        """RETIRED (2026-07-23, #5141). Manual cleanup no longer deletes anything.

        This ran cleanup_old_backups(), a SECOND pruner that applied a single global
        7/4/6 GFS triple to /backups — which is a symlink to /mnt/data2/backups, the
        exact directory the canonical per-(component, tier) engine
        scripts/backup/retention_prune.py already prunes nightly. Two pruners with
        different policies over one directory is the competing-pruner anti-pattern the
        platform retired (#4051); on a live run this one would have deleted restore
        points the real policy keeps. Retention is fully automatic now — there is
        nothing to run by hand.
        """
        return (
            jsonify(
                {
                    "success": False,
                    "retired": True,
                    "error": (
                        "Manual cleanup is retired. Backups are pruned automatically every "
                        "night by the canonical per-component / per-tier engine "
                        "(scripts/backup/retention_prune.py). This endpoint no longer deletes "
                        "anything."
                    ),
                }
            ),
            410,
        )

    @bp.route("/set-current/<int:build_number>", methods=["POST"])
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

    @bp.route("/lock-status")
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
