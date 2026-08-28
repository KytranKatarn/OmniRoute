"""Backup Manager — admin (hooks, audit, config, snapshots) routes.

Split from the original backup_manager_routes.py monolith (Task #2699).
All routes are registered via register_admin_routes(bp, admin_required).
"""

from flask import jsonify, request
from flask_login import current_user
import os
import json
from datetime import datetime
from psycopg2.extras import RealDictCursor


# Pull every shared helper / constant / programmatic function into module scope
from ._shared import (
    HOOKS_DIR,
    POST_HOOKS_DIR,
    PRE_HOOKS_DIR,
    get_backup_db_cursor,
)


def register_admin_routes(bp, admin_required):  # noqa: F811
    """Register admin (hooks, audit, config, snapshots) routes onto the supplied blueprint."""

    # ── W.A.R.D.E.N. pre-deploy governance gates (#2708) ─────────────────────────
    @bp.route("/api/governance-gates", methods=["GET"])
    @admin_required
    def get_governance_gates():
        """Return the backup-freshness gate config (system_config 'backup_governance_gates',
        or the service defaults when unset) that W.A.R.D.E.N. uses before Repair Bay deploys."""
        try:
            from services.backup_governance_service import _load_gate_config

            return jsonify({"success": True, "gates": _load_gate_config()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/governance-gates", methods=["POST"])
    @admin_required
    def save_governance_gates():
        """Validate + persist the gate config. Body: {"gates": {sev: {max_age_hours, gate_type, override}}}."""
        from database import get_db_cursor

        VALID_SEV = ("critical", "high", "medium", "low")
        VALID_GATE = ("soft", "hard")
        VALID_OVERRIDE = ("none", "telegram_approval", "kytran_approval")
        data = request.get_json(force=True) or {}
        gates = data.get("gates") or {}
        clean = {}
        for sev in VALID_SEV:
            g = gates.get(sev) or {}
            try:
                max_age = int(g.get("max_age_hours"))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": f"{sev}: max_age_hours must be an integer"}), 400
            if not (0 <= max_age <= 8760):
                return jsonify({"success": False, "error": f"{sev}: max_age_hours out of range (0-8760)"}), 400
            gate_type = str(g.get("gate_type", "")).lower()
            if gate_type not in VALID_GATE:
                return jsonify({"success": False, "error": f"{sev}: gate_type must be soft|hard"}), 400
            override = str(g.get("override", "none"))
            if override not in VALID_OVERRIDE:
                override = "none"
            clean[sev] = {"max_age_hours": max_age, "gate_type": gate_type, "override": override}
        try:
            uid = getattr(current_user, "id", None)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_config (key, value, updated_at, updated_by)
                       VALUES ('backup_governance_gates', %s, NOW(), %s)
                       ON CONFLICT (key) DO UPDATE
                         SET value = EXCLUDED.value, updated_at = NOW(), updated_by = EXCLUDED.updated_by""",
                    (json.dumps(clean), uid),
                )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        return jsonify({"success": True, "gates": clean})

    @bp.route("/api/hooks")
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

    @bp.route("/api/hooks/<hook_type>", methods=["POST"])
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

    @bp.route("/api/hooks/<hook_type>/<name>", methods=["DELETE"])
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

    @bp.route("/api/snapshot-module", methods=["POST"])
    @admin_required
    def create_module_snapshot():
        """Manually checkpoint a module's current state."""
        data = request.get_json() or {}
        module_name = data.get("module_name", "").strip()
        if not module_name:
            return jsonify({"success": False, "error": "module_name required"}), 400
        from services.backup_service import snapshot_module

        result = snapshot_module(
            module_name=module_name,
            snapshot_type="manual",
            trigger_source="manual",
            metadata={"triggered_by": "ui", "user": getattr(current_user, "username", "unknown")},
        )
        return jsonify(result)

    @bp.route("/api/snapshots", methods=["GET"])
    @admin_required
    def list_module_snapshots():
        """List recent module snapshots, optionally filtered by module."""
        from database import get_db_cursor

        module = request.args.get("module")
        limit = min(int(request.args.get("limit", 100)), 500)
        with get_db_cursor(commit=False) as (conn, cur):
            if module:
                cur.execute(
                    "SELECT id, module_name, snapshot_type, trigger_source, backup_id, clearance_task_id, metadata, created_at FROM module_snapshots WHERE module_name = %s ORDER BY created_at DESC LIMIT %s",
                    (module, limit),
                )
            else:
                cur.execute(
                    "SELECT id, module_name, snapshot_type, trigger_source, backup_id, clearance_task_id, metadata, created_at FROM module_snapshots ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = []
            for r in cur.fetchall():
                row = dict(r)
                if row.get("created_at"):
                    row["created_at"] = row["created_at"].isoformat()
                rows.append(row)
        return jsonify({"snapshots": rows, "total": len(rows)})

    @bp.route("/api/cleanup-orphan-log-entries", methods=["POST"])
    @admin_required
    def cleanup_orphan_log_entries():
        """Remove backup_log rows whose file_path directory no longer exists on disk."""
        try:
            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    "SELECT id, file_path FROM backup_log "
                    "WHERE backup_type NOT IN ('standalone', 'module') AND file_path IS NOT NULL"
                )
                rows = cur.fetchall()

            removed = []
            for row in rows:
                fp = row["file_path"]
                fp = os.path.normpath(fp)
                if fp and not os.path.exists(fp):
                    removed.append(row["id"])

            if removed:
                with get_backup_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "DELETE FROM backup_log WHERE id = ANY(%s)",
                        (removed,),
                    )

            return jsonify({"success": True, "removed_count": len(removed), "removed_ids": removed})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
