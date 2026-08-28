"""Backup Manager — restore + preview + sandbox + module backup routes.

Split from the original backup_manager_routes.py monolith (Task #2699).
All routes are registered via register_restore_routes(bp, admin_required).
"""

from flask import jsonify, request, current_app
from flask_login import current_user
import os
import json
import shutil
import subprocess
import tempfile
import time
import hashlib
from datetime import datetime


# Pull every shared helper / constant / programmatic function into module scope
from ._shared import (
    BACKUP_DIR,
    PLATFORM_DIR,
    _AI_BRIDGE_ROOTS,
    acquire_backup_lock,
    backup_module,
    compare_backups,
    get_backup_db_cursor,
    get_module_dependencies,
    preview_restore,
    release_backup_lock,
    restore_components,
    _host_restore_command,
)


def register_restore_routes(bp, admin_required):  # noqa: F811
    """Register restore + preview + sandbox + module backup routes onto the supplied blueprint."""

    @bp.route("/restore/<backup_name>", methods=["POST"])
    @admin_required
    def restore_backup(backup_name):
        """Restore a backup"""
        try:
            backup_path = os.path.join(BACKUP_DIR, backup_name)

            if not os.path.exists(backup_path):
                return jsonify({"success": False, "error": "Backup not found"}), 404

            # Phase 1-6 (-Fc) layout: NEVER restore from the web thread — the platform can't
            # DROP+restore its own live DB, and a multi-minute pg_restore would block/timeout the
            # worker. Hand back the exact host command (whether or not a rollback.sh exists).
            # Runbook KB #272184. (#4049)
            db_dir = os.path.join(backup_path, "database")
            is_phase16 = os.path.isdir(db_dir) and any(f.endswith(".dump") for f in os.listdir(db_dir))
            if is_phase16:
                return (
                    jsonify(
                        {
                            "success": False,
                            "requires_host_restore": True,
                            "layout": "phase16",
                            "error": (
                                "This backup uses the Phase 1-6 (-Fc) layout. Restore it from the "
                                "host — the platform cannot DROP+restore its own live DB. "
                                "Runbook KB #272184."
                            ),
                            "host_command": _host_restore_command(backup_path, db="all", force=True),
                            "verify_command": _host_restore_command(backup_path, db="archie", force=False),
                            "kb": "#272184",
                        }
                    ),
                    409,
                )

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

    @bp.route("/deploy-to-sandbox", methods=["POST"])
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

    @bp.route("/backup-module", methods=["POST"])
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

    @bp.route("/module-dependencies/<module_name>")
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

    @bp.route("/restore-module/<backup_name>", methods=["POST"])
    @admin_required
    def restore_module_backup(backup_name):
        """Restore a module backup over the LIVE platform.

        Hardened 2026-07-23 (#5136). Measured beforehand: this returned HTTP 200 in
        0.1s having taken NO lock, made NO reversible copy, verified NOTHING, and
        written NO backup_log row — while the sandbox sibling
        (deploy-to-sandbox, #2381/#2403) does all four.

        The part that actually misleads: the platform runs gunicorn --workers 4, and
        Python caches imported modules. Restoring routes.py changes the file on disk
        while every worker keeps serving the OLD code until archie_platform restarts.
        So "restored successfully" described a rollback that had not taken effect —
        discovered at the worst possible moment, mid-incident. The response now says
        so explicitly (`restart_required`) instead of implying the work is done.
        """
        lock_held = False
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

            module_name = metadata.get("module_name") or ""

            # Serialise against every other backup/restore. Without this a full code
            # backup running concurrently captures a half-restored tree and is silently
            # unrestorable — the failure would surface only at the NEXT restore.
            ok, lock_err = acquire_backup_lock(f"restore_module_{module_name}", "restore-module")
            if not ok:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"a backup/restore is already in progress — {lock_err}",
                        }
                    ),
                    409,
                )
            lock_held = True

            # Pre-restore snapshot, so restoring the WRONG backup is undoable. This is
            # the cheap half of the module story: ~1 MB and ~1s, versus the 2,470 MB
            # pre-deploy snapshot it replaces. A restore with no way back is not a
            # rollback path, it is a second outage.
            safety_backup = None
            if module_name:
                try:
                    pre = backup_module(
                        module_name=module_name,
                        created_by_username=f"pre-restore:{getattr(current_user, 'username', 'system')}",
                    )
                    if pre.get("success"):
                        safety_backup = pre.get("backup_name")
                except Exception as pre_err:  # noqa: BLE001
                    current_app.logger.warning("pre-restore snapshot failed for %s: %s", module_name, pre_err)

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

            # CONTENT verification. Everything above proves shutil did not raise — not
            # that live now matches the backup. The sandbox path already hashes what it
            # deployed (#5043); the production path had no equivalent, so a partial copy
            # reported success. md5 here is content-equality, NOT a security primitive.
            mismatched = []
            src_tools_root = os.path.join(backup_path, "tools")
            if os.path.isdir(src_tools_root):
                for item in os.listdir(src_tools_root):
                    s_root = os.path.join(src_tools_root, item)
                    d_root = os.path.join(PLATFORM_DIR, "tools", item)
                    for dp, _, fns in os.walk(s_root):
                        for fn in fns:
                            if "__pycache__" in dp:
                                continue
                            s_file = os.path.join(dp, fn)
                            d_file = os.path.join(d_root, os.path.relpath(s_file, s_root))
                            try:
                                with open(s_file, "rb") as a, open(d_file, "rb") as b:
                                    if hashlib.md5(a.read()).hexdigest() != hashlib.md5(b.read()).hexdigest():
                                        mismatched.append(os.path.relpath(s_file, src_tools_root))
                            except OSError:
                                mismatched.append(os.path.relpath(s_file, src_tools_root))

            status = "failed" if mismatched else "success"
            try:
                with get_backup_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "INSERT INTO backup_log "
                        "(file_path, backup_type, component, tier, size_bytes, status, "
                        " triggered_by, notes, created_at) "
                        "VALUES (%s, 'module_restore', %s, 'module', 0, %s, %s, %s, NOW())",
                        (
                            backup_path,
                            module_name or "unknown",
                            status,
                            getattr(current_user, "username", "system"),
                            (
                                f"restored from {backup_name}; safety={safety_backup or 'none'}; "
                                f"files={', '.join(files_restored)}"
                                + (f"; MISMATCHED={', '.join(mismatched[:5])}" if mismatched else "")
                            )[:400],
                        ),
                    )
            except Exception as log_err:  # noqa: BLE001 — bookkeeping must not mask the result
                current_app.logger.warning("module_restore backup_log INSERT failed: %s", log_err)

            if mismatched:
                return (
                    jsonify(
                        {
                            "success": False,
                            "module": module_name,
                            "error": (
                                f"{len(mismatched)} file(s) do not match the backup after copy — "
                                "the module is in an UNKNOWN state, do not restart"
                            ),
                            "mismatched": mismatched[:20],
                            "safety_backup": safety_backup,
                        }
                    ),
                    500,
                )

            return jsonify(
                {
                    "success": True,
                    "message": (
                        f'Module {module_name or "unknown"} restored to disk and verified. '
                        "NOT YET LIVE — archie_platform must restart before the running "
                        "workers serve this code."
                    ),
                    "files_restored": files_restored,
                    "verified": True,
                    # The caller has to know the job is half-done. Omitting this is what
                    # made the old response a lie by silence.
                    "restart_required": True,
                    "safety_backup": safety_backup,
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if lock_held:
                release_backup_lock()

    @bp.route("/verify-modules")
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

            # #5835 / ADR-009: `ai_bridge` and `services` are not registry modules, but
            # they ARE first-class pre-deploy backup scopes — backup_module() copies each
            # tree wholesale and _predeploy_module_scope() will now select them. Without
            # these rows the coverage view silently omits the two trees that carry scoped
            # restore points, which reads as "not covered" when the opposite is true.
            for pseudo_id, pseudo_root in (
                ("ai_bridge", next((r for r in _AI_BRIDGE_ROOTS if os.path.isdir(r)), None)),
                ("services", os.path.join(PLATFORM_DIR, "services")),
            ):
                info = {
                    "id": pseudo_id,
                    "name": pseudo_id,
                    "category": "Pre-deploy scope (pseudo-module)",
                    "has_routes": bool(pseudo_root and os.path.isdir(pseudo_root)),
                    "has_templates": False,
                    "enabled": True,
                    "status": "live",
                    "pseudo": True,
                }
                (covered if info["has_routes"] else missing).append(info)

            # Divide by the COMBINED total, not len(modules) — the two rows above are not
            # in the registry, so the original denominator would overstate coverage.
            total_modules = len(covered) + len(missing)
            coverage_pct = (len(covered) / total_modules * 100) if total_modules else 0

            return jsonify(
                {
                    "success": True,
                    "total_modules": total_modules,
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

    @bp.route("/preview-restore/<backup_name>")
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

    @bp.route("/restore-selective/<backup_name>", methods=["POST"])
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

    @bp.route("/compare/<backup1>/<backup2>")
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

    @bp.route("/api/modules/<module_name>/deploy-to-sandbox", methods=["POST"])
    @admin_required
    def deploy_module_to_sandbox(module_name):
        """Copy a module backup into the sandbox worktree and restart archie_staging."""
        SANDBOX_TOOLS = "/mnt/archie_sandbox/platform_v2/tools"
        SANDBOX_TEMPLATES = "/mnt/archie_sandbox/platform_v2/templates/tools"

        module_backup_path = os.path.join(BACKUP_DIR, "modules")
        # EXACT suffix, not `module_name in d`. Backup dirs are
        # '<YYYYmmdd>_<HHMMSS>_module_<name>', so the old substring test resolved
        # module_name='therap' to a *therapy* backup (measured live 2026-07-20). No two
        # current module names collide, but the moment one is a substring of another this
        # silently deploys the wrong module's code into the sandbox.
        suffix = f"_module_{module_name}"
        candidates = (
            sorted([d for d in os.listdir(module_backup_path) if d.endswith(suffix)], reverse=True)
            if os.path.exists(module_backup_path)
            else []
        )

        if not candidates:
            return jsonify({"success": False, "error": f"No module backup found for '{module_name}'"}), 404

        latest = os.path.join(module_backup_path, candidates[0])
        log = []

        # The module's code IS the deliverable here. Previously a missing tools/<module>/
        # merely skipped the copy and still returned success:true with the "✓ tools/..."
        # line absent from the log — so "deployed nothing" was indistinguishable from a
        # real deploy to any caller checking `success`, including an ADR-009 sandbox
        # rehearsal gating a Repair Bay fix. Fail loudly instead.
        src_tools = os.path.join(latest, "tools", module_name)
        if not os.path.isdir(src_tools):
            return (
                jsonify(
                    {
                        "success": False,
                        "module": module_name,
                        "backup": candidates[0],
                        "error": (
                            f"backup '{candidates[0]}' contains no tools/{module_name}/ — " "nothing was deployed"
                        ),
                    }
                ),
                500,
            )

        dst_tools = os.path.join(SANDBOX_TOOLS, module_name)
        if os.path.exists(dst_tools):
            shutil.rmtree(dst_tools)
        shutil.copytree(src_tools, dst_tools)
        log.append(f"✓ tools/{module_name}/ deployed to sandbox")

        src_tpl = os.path.join(latest, "templates", "tools")
        dst_tpl = SANDBOX_TEMPLATES
        if os.path.exists(src_tpl):
            for f in os.listdir(src_tpl):
                shutil.copy2(os.path.join(src_tpl, f), os.path.join(dst_tpl, f))
            log.append(f"✓ templates/tools/ deployed to sandbox")

        # A restart that did not happen leaves the sandbox serving the OLD code, so the
        # rehearsal proves nothing. That was previously a "⚠ restart warning" attached to
        # a success:true response.
        result = subprocess.run(["docker", "restart", "archie_staging"], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.append(f"✗ archie_staging restart FAILED: {result.stderr[:200]}")
            return (
                jsonify(
                    {
                        "success": False,
                        "module": module_name,
                        "backup": candidates[0],
                        "log": log,
                        "error": "files deployed but archie_staging did not restart — sandbox serves stale code",
                    }
                ),
                500,
            )
        log.append("✓ archie_staging restarted")

        # `docker restart` returns as soon as the process is signalled, so it is not
        # evidence the container came back. Wait for it, bounded. NOTE: this confirms the
        # container is UP — it does not verify it is serving this specific code. Real
        # content verification is still open (task #5043).
        came_back = False
        for _ in range(15):  # ~30s
            probe = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                    "archie_staging",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            running, _, health = (probe.stdout or "").strip().partition("|")
            if running == "true" and health in ("healthy", "none"):
                came_back = True
                break
            time.sleep(2)

        if not came_back:
            log.append("✗ archie_staging did not report healthy within 30s")
            return (
                jsonify(
                    {
                        "success": False,
                        "module": module_name,
                        "backup": candidates[0],
                        "log": log,
                        "error": "archie_staging did not come back up — sandbox state is unverified",
                    }
                ),
                500,
            )
        log.append("✓ archie_staging back up")

        # CONTENT verification (#5043, the last open point). Everything above proves the
        # container is UP — not that it is serving THIS code, and a rehearsal that cannot
        # show the sandbox running the deployed bytes proves nothing. ADR-009 gates Repair
        # Bay fixes on this rehearsal, so "deployed" has to mean verified, not assumed.
        # /mnt/archie_sandbox/platform_v2 is bind-mounted to /app, so hashing the SAME file
        # read from inside the container and comparing it to the backup's copy is direct
        # evidence the container sees what we deployed. md5 here is a content-equality
        # check, NOT a security primitive.
        import hashlib

        probe = next((c for c in ("routes.py", "__init__.py") if os.path.isfile(os.path.join(src_tools, c))), None)
        if probe is None:
            _pys = sorted(f for f in os.listdir(src_tools) if f.endswith(".py"))
            probe = _pys[0] if _pys else None

        if probe is None:
            # Nothing importable to compare against. Say so plainly rather than letting
            # silence imply the deploy was verified.
            log.append("⚠ backup contains no .py file — content could NOT be verified")
        else:
            with open(os.path.join(src_tools, probe), "rb") as _f:
                expected = hashlib.md5(_f.read()).hexdigest()
            chk = subprocess.run(
                ["docker", "exec", "archie_staging", "md5sum", f"/app/tools/{module_name}/{probe}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            actual = (chk.stdout or "").split()[0] if chk.returncode == 0 and (chk.stdout or "").strip() else ""
            if actual != expected:
                log.append(f"✗ sandbox is NOT serving the deployed {probe}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "module": module_name,
                            "backup": candidates[0],
                            "log": log,
                            "error": (
                                f"content verification FAILED for tools/{module_name}/{probe}: "
                                f"sandbox has {actual or 'unreadable'}, backup has {expected} — "
                                "the rehearsal is not trustworthy"
                            ),
                        }
                    ),
                    500,
                )
            log.append(f"✓ verified: sandbox serves the deployed tools/{module_name}/{probe}")

        return jsonify({"success": True, "module": module_name, "backup": candidates[0], "log": log})

    @bp.route("/api/packages/<int:package_id>/test-in-sandbox", methods=["POST"])
    @admin_required
    def test_package_in_sandbox(package_id):
        """Start a sandbox restore for the DB state captured in a deployment package."""
        from services.backup_restore_service import initiate_sandbox_restore

        with get_backup_db_cursor(commit=False) as (conn, cur):
            # backup_source is the real column (backup_id does not exist — that
            # SELECT 500'd, #4051). It holds a backup NAME; sandbox restore wants
            # an int backup_log id, so map name -> id below.
            cur.execute(
                "SELECT id, package_name, backup_source FROM deployment_packages WHERE id = %s",
                (package_id,),
            )
            pkg = cur.fetchone()

        if not pkg:
            return jsonify({"success": False, "error": f"Package #{package_id} not found"}), 404

        backup_source = pkg[2]
        if not backup_source:
            return jsonify({"success": False, "error": "Package has no associated DB backup"}), 400

        # Resolve a backup_log id: accept an int id directly, else look up by name.
        backup_id = None
        try:
            backup_id = int(backup_source)
        except (TypeError, ValueError):
            with get_backup_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT id FROM backup_log WHERE file_path LIKE %s ORDER BY created_at DESC LIMIT 1",
                    (f"%{backup_source}%",),
                )
                row = cur.fetchone()
                backup_id = row[0] if row else None
        if not backup_id:
            return jsonify({"success": False, "error": f"No backup_log entry for source '{backup_source}'"}), 400

        result = initiate_sandbox_restore(
            backup_id=int(backup_id),
            triggered_by=getattr(current_user, "username", "unknown"),
        )
        if result["success"]:
            result["package_name"] = pkg[1]
            result["backup_id"] = backup_id
        return jsonify(result), 200 if result["success"] else 400

    @bp.route("/api/restore/sandbox", methods=["POST"])
    @admin_required
    def initiate_restore_sandbox():
        """Start a sandbox restore test for a backup. Returns immediately (async)."""
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

    @bp.route("/api/restore/sandbox-by-name", methods=["POST"])
    @admin_required
    def initiate_restore_sandbox_by_name():
        """Start a sandbox restore test using backup directory name. Looks up backup_log.id automatically."""
        from services.backup_restore_service import initiate_sandbox_restore

        data = request.get_json() or {}
        backup_name = data.get("backup_name")
        if not backup_name:
            return jsonify({"success": False, "error": "backup_name required"}), 400

        with get_backup_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM backup_log WHERE file_path LIKE %s ORDER BY created_at DESC LIMIT 1",
                (f"%{backup_name}",),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": f"No backup_log entry found for '{backup_name}'"}), 404

        backup_id = row[0]
        result = initiate_sandbox_restore(
            backup_id=backup_id,
            triggered_by=getattr(current_user, "username", "unknown"),
        )
        if result["success"]:
            result["backup_id"] = backup_id
        return jsonify(result), 200 if result["success"] else 400

    @bp.route("/api/restore/status/<int:backup_id>", methods=["GET"])
    @admin_required
    def get_restore_status_endpoint(backup_id):
        """Get current restore session status for a backup."""
        from services.backup_restore_service import get_restore_status

        return jsonify(get_restore_status(backup_id))

    @bp.route("/api/restore/promote", methods=["POST"])
    @admin_required
    def promote_restore_to_production():
        """Promote a QA-verified sandbox restore to production. Only works after qa_passed."""
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
