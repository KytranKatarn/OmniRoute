"""Backup Manager — admin (hooks, audit, config, snapshots) routes.

Split from the original backup_manager_routes.py monolith (Task #2699).
All routes are registered via register_admin_routes(bp, admin_required).
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
    HOOKS_DIR,
    POST_HOOKS_DIR,
    PRE_HOOKS_DIR,
    admin_required,
)


def register_admin_routes(bp, admin_required):
    """Register admin (hooks, audit, config, snapshots) routes onto the supplied blueprint."""

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
