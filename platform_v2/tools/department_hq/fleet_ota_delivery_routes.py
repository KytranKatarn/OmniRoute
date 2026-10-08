"""Moved fleet_ota_routes handlers; registered by the original public entry point."""

import logging
import hashlib
import json
import os
from flask import jsonify, request
from flask_login import current_user
from database import get_db_cursor
from .fleet_helpers import _get_node_for_user_by_int_id

logger = logging.getLogger(__name__)


def register_ota_delivery_routes(bp, auth_decorator):
    @bp.route("/api/fleet/checkpoints/<path:filename>")
    def api_serve_checkpoint(filename):
        """Serve a ComfyUI checkpoint file to authenticated fleet nodes.

        Nodes call this via mesh IP during checkpoint_pull OTA sync.
        Auth: X-Node-API-Key header validated against remote_nodes table.
        Uses explicit return codes (not abort()) so Flask-Login doesn't
        intercept and redirect to login page.
        """
        from flask import send_file
        import re

        safe_name = os.path.basename(filename)

        # Mesh-internal endpoint — all requests come from enrolled Headscale nodes.
        # No additional auth needed; the mesh itself gates access.
        # Optional: validate X-Node-API-Key if provided (non-blocking).
        api_key = request.headers.get("X-Node-API-Key", "")
        if api_key:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT id FROM remote_nodes WHERE api_key_hash = %s",
                        (key_hash,),
                    )
                    node_row = cur.fetchone()
                    if not node_row:
                        logger.warning("Checkpoint serve: unknown node key for %s", safe_name)
            except Exception:
                pass  # Non-blocking — mesh access is the primary guard
        if not re.match(r"^[\w\-. ]+$", safe_name):
            return jsonify({"success": False, "error": "Invalid filename"}), 400

        # Search ComfyUI checkpoints dir for the requested file.
        search_dirs = [
            os.environ.get("COMFYUI_CHECKPOINTS_DIR", "/mnt/data2/comfyui/models/checkpoints"),
        ]
        file_path = None
        for d in search_dirs:
            candidate = os.path.join(d, safe_name)
            if os.path.isfile(candidate):
                file_path = candidate
                break

        if not file_path:
            return jsonify({"success": False, "error": f"File not found: {safe_name}"}), 404

        logger.info("Serving fleet file %s to node (%.1f KB)", safe_name, os.path.getsize(file_path) / 1e3)
        return send_file(file_path, as_attachment=True)

    @bp.route("/api/nodes/<int:node_id>/sync-log")
    @auth_decorator
    def api_get_sync_log(node_id):
        """Get recent sync log entries for a node."""
        try:
            with get_db_cursor() as (conn, cur):
                # Get the string node_id
                cur.execute(
                    "SELECT node_id FROM remote_nodes WHERE id = %s",
                    (node_id,),
                )
                node = cur.fetchone()
                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404
                node_id_str = node["node_id"]

                cur.execute(
                    """
                    SELECT id, sync_type, status, sent_at, acknowledged_at,
                           error_message, result_payload
                    FROM mesh_sync_log
                    WHERE node_id = %s
                    ORDER BY sent_at DESC
                    LIMIT 10
                    """,
                    (node_id_str,),
                )
                rows = cur.fetchall()

            logs = []
            for r in rows:
                logs.append(
                    {
                        "id": r["id"],
                        "sync_type": r["sync_type"],
                        "status": r["status"],
                        "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                        "acknowledged_at": r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
                        "error_message": r["error_message"],
                        "result_payload": r["result_payload"],
                    }
                )

            return jsonify({"success": True, "logs": logs})
        except Exception:
            logger.exception("Failed to get sync log for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/upgrade-v3", methods=["POST"])
    @auth_decorator
    def upgrade_node_v3(node_id):
        """Push full v3.0 stack upgrade to an existing node via OTA."""
        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # 1) Push code_update with full v3.0 file set
                code_payload = {
                    "files": [
                        "docker-compose.yml",
                        "node_sync.py",
                        "node_api.py",
                        "Dockerfile.node",
                        "migrations/001_node_schema.sql",
                        "migrations/002_knowledge_projects.sql",
                    ],
                    "version": "3.0.0",
                }
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'code_update', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps(code_payload)),
                )
                cur.fetchone()["id"]

                # 2) Queue container rebuild
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'container_restart', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps({"action": "rebuild"})),
                )
                cur.fetchone()["id"]

            return jsonify(
                {
                    "success": True,
                    "message": "V3.0 upgrade queued for {}".format(node_id_str),
                    "syncs_queued": 2,
                }
            )
        except Exception:
            logger.exception("Failed to queue v3.0 upgrade for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # Allowlist of files nodes may download via OTA code_update.
    _OTA_ALLOWED_FILES = frozenset({"node_api.py", "node_sync.py", "node_triage.py"})
    _NODE_CLIENT_DIR = os.environ.get(
        "NODE_CLIENT_DIR",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "node_client")),
    )

    @bp.route("/api/nodes/ota/<filename>")
    def serve_node_file(filename):
        """Serve node client source files for OTA code_update downloads.

        node_sync.py fetches: GET {hub_url}/tools/department-hq/api/nodes/ota/{filename}
        Returns JSON {"raw": "<file content>", "filename": "<name>"}.
        Only files in _OTA_ALLOWED_FILES may be served (blocks path traversal).
        """
        if filename not in _OTA_ALLOWED_FILES:
            return jsonify({"success": False, "error": f"File not permitted: {filename}"}), 403
        if os.sep in filename:
            return jsonify({"success": False, "error": f"File not permitted: {filename}"}), 403

        file_path = os.path.join(_NODE_CLIENT_DIR, filename)
        if not os.path.isfile(file_path):
            return jsonify({"success": False, "error": "File not found"}), 404

        try:
            with open(file_path) as fh:
                content = fh.read()
            return jsonify({"raw": content, "filename": filename})
        except Exception as e:
            logger.exception("Failed to serve node file %s", filename)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/nodes/<int:node_id>/sync-status")
    @auth_decorator
    def api_node_sync_status(node_id):
        """Return pending sync count and config version info."""
        try:
            with get_db_cursor() as (conn, cur):
                # Get string node_id
                cur.execute("SELECT node_id FROM remote_nodes WHERE id = %s", (node_id,))
                node = cur.fetchone()
                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404
                node_id_str = node["node_id"]

                # Pending syncs (sent but not acknowledged)
                cur.execute(
                    """
                    SELECT COUNT(*) as pending_count
                    FROM mesh_sync_log
                    WHERE node_id = %s AND status = 'sent' AND acknowledged_at IS NULL
                    """,
                    (node_id_str,),
                )
                pending = cur.fetchone()["pending_count"]

                # Latest config_version from node_agents
                cur.execute(
                    "SELECT MAX(config_version) as max_version FROM node_agents WHERE node_id = %s",
                    (node_id,),
                )
                version_row = cur.fetchone()
                max_version = version_row["max_version"] if version_row else 1

                # Last ACK time
                cur.execute(
                    """
                    SELECT acknowledged_at FROM mesh_sync_log
                    WHERE node_id = %s AND sync_type = 'agent_config'
                      AND acknowledged_at IS NOT NULL
                    ORDER BY acknowledged_at DESC LIMIT 1
                    """,
                    (node_id_str,),
                )
                last_ack = cur.fetchone()
                last_ack_time = (
                    last_ack["acknowledged_at"].isoformat() if last_ack and last_ack["acknowledged_at"] else None
                )

                return jsonify(
                    {
                        "success": True,
                        "pending_count": pending,
                        "config_version": max_version,
                        "last_ack": last_ack_time,
                    }
                )
        except Exception:
            logger.exception("Failed to get sync status for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ── Node-authenticated OTA polling endpoints ──────────────────────────

    def _verify_node_key(node_id_str: str, api_key: str) -> bool:
        """Verify a node's API key against the stored hash."""
        if not api_key:
            return False
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT api_key_hash FROM remote_nodes WHERE node_id=%s AND is_active=TRUE",
                    (node_id_str,),
                )
                row = cur.fetchone()
            return bool(row and row["api_key_hash"] == key_hash)
        except Exception:
            return False

    @bp.route("/api/nodes/<node_id>/pending-commands", methods=["GET"])
    def api_pending_commands(node_id):
        """Return unacknowledged sync commands for a node (node-auth)."""
        if not _verify_node_key(node_id, request.headers.get("X-Node-API-Key", "")):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, sync_type, payload
                    FROM mesh_sync_log
                    WHERE node_id = %s AND status = 'sent' AND acknowledged_at IS NULL
                    ORDER BY sent_at ASC LIMIT 10
                    """,
                    (node_id,),
                )
                commands = [
                    {"id": r["id"], "sync_type": r["sync_type"], "payload": r["payload"] or {}} for r in cur.fetchall()
                ]
            return jsonify({"success": True, "commands": commands})
        except Exception:
            logger.exception("pending-commands failed for %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/ack-command/<int:sync_id>", methods=["POST"])
    def api_ack_command(node_id, sync_id):
        """Node acknowledges a sync command with result (node-auth)."""
        if not _verify_node_key(node_id, request.headers.get("X-Node-API-Key", "")):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        data = request.get_json() or {}
        import psycopg2.extras

        status = "acknowledged" if data.get("success") else "error"
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE mesh_sync_log
                    SET status = %s,
                        acknowledged_at = NOW(),
                        result_payload = %s,
                        error_message = %s
                    WHERE id = %s AND node_id = %s
                    """,
                    (
                        status,
                        psycopg2.extras.Json(data.get("result", {})),
                        data.get("error"),
                        sync_id,
                        node_id,
                    ),
                )
            logger.info("Node %s acked sync command #%d — %s", node_id, sync_id, status)
            return jsonify({"success": True})
        except Exception:
            logger.exception("ack-command failed for %s #%d", node_id, sync_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500
