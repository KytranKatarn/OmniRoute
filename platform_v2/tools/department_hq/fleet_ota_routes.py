import hashlib
import json
import logging
import os
from flask import jsonify, request
from flask_login import current_user
from database import get_db_cursor
from .fleet_helpers import _get_node_for_user_by_int_id, LATEST_NODE_VERSION

logger = logging.getLogger(__name__)


def register_ota_routes(bp, auth_decorator):
    """Register OTA push and sync routes on the fleet blueprint."""

    @bp.route("/api/nodes/<int:node_id>/push-config", methods=["POST"])
    @auth_decorator
    def api_push_agent_config(node_id):
        """Push current agent configuration to a node via mesh_sync_log."""

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Build crew manifest from node_agents
                cur.execute(
                    """
                    SELECT na.name, na.display_name, na.title, na.model,
                           na.system_prompt, na.capabilities, na.station_codes,
                           na.is_allowed, na.status
                    FROM node_agents na
                    WHERE na.node_id = %s AND na.status = 'active'
                    ORDER BY na.display_name
                    """,
                    (node_id,),
                )
                agents = cur.fetchall()

                crew_manifest = []
                for a in agents:
                    crew_manifest.append(
                        {
                            "name": a["name"],
                            "display_name": a["display_name"],
                            "title": a["title"],
                            "model": a["model"],
                            "system_prompt": a["system_prompt"],
                            "capabilities": a["capabilities"],
                            "station_codes": a["station_codes"],
                            "is_allowed": a["is_allowed"],
                            "status": a["status"],
                        }
                    )

                payload = {"agents": crew_manifest, "agent_count": len(crew_manifest)}

                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'agent_config', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps(payload)),
                )
                sync_row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "sync_id": sync_row["id"],
                    "agent_count": len(crew_manifest),
                }
            )
        except Exception:
            logger.exception("Failed to push agent config to node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/pull-model", methods=["POST"])
    @auth_decorator
    def api_pull_model(node_id):
        """Queue a model pull on a node via mesh_sync_log."""
        data = request.get_json()
        model_name = data.get("model_name") if data else None
        if not model_name:
            return jsonify({"success": False, "error": "model_name required"}), 400

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'model_pull', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps({"model_name": model_name})),
                )
                sync_row = cur.fetchone()

            return jsonify({"success": True, "sync_id": sync_row["id"], "model": model_name})
        except Exception:
            logger.exception("Failed to pull model for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/pull-checkpoint", methods=["POST"])
    @auth_decorator
    def api_pull_checkpoint(node_id):
        """Queue a ComfyUI checkpoint download on a node via OTA."""
        data = request.get_json()
        url = data.get("url") if data else None
        filename = data.get("filename") if data else None
        if not url or not filename:
            return jsonify({"success": False, "error": "url and filename required"}), 400

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'checkpoint_pull', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (
                        node_id_str,
                        json.dumps(
                            {
                                "url": url,
                                "filename": filename,
                                "checkpoints_dir": data.get("checkpoints_dir", "/comfyui/models/checkpoints"),
                            }
                        ),
                    ),
                )
                sync_row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "sync_id": sync_row["id"],
                    "filename": filename,
                    "message": f"Checkpoint download queued for {filename}",
                }
            )
        except Exception:
            logger.exception("Failed to queue checkpoint pull for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/provision-warm-set", methods=["POST"])
    @auth_decorator
    def api_provision_warm_set(node_id):
        """Queue the hardware-recommended warm-set onto a node in one shot (#3731).

        Computes the model plan from the node's reported hardware
        (services.node_provisioning) then fans out to the SAME mesh_sync_log queue
        the per-model OTA endpoints use: one 'model_pull' per recommended Ollama
        model + one 'checkpoint_pull' for the ComfyUI checkpoint (if the node has a
        GPU that fits one). This is the "+Add Node: download everything you need"
        action. Body (optional): {"include_comfyui": true}.
        """
        from services.node_provisioning import recommend_from_node_row

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]
        # In DR mode the hub (checkpoint source) is down + boston-2 has no checkpoint
        # files, so don't queue ComfyUI checkpoint pulls — they resume after failback.
        include_comfyui = (request.get_json(silent=True) or {}).get("include_comfyui", True) and os.getenv(
            "ARCHIE_DR_MODE", "0"
        ) != "1"

        try:
            queued = {"models": [], "checkpoint": None}
            with get_db_cursor(commit=True) as (conn, cur):
                # Re-fetch hardware columns directly — don't depend on the helper's SELECT.
                cur.execute(
                    "SELECT cpu_cores, ram_gb, gpu_available, gpu_vram_gb, gpu_model "
                    "FROM remote_nodes WHERE node_id = %s",
                    (node_id_str,),
                )
                hw = cur.fetchone() or {}
                rec = recommend_from_node_row(hw)

                for model_name in rec.recommended_ollama:
                    cur.execute(
                        "INSERT INTO mesh_sync_log (node_id, sync_type, payload, status, sent_at) "
                        "VALUES (%s, 'model_pull', %s, 'sent', NOW()) RETURNING id",
                        (node_id_str, json.dumps({"model_name": model_name})),
                    )
                    queued["models"].append({"model": model_name, "sync_id": cur.fetchone()["id"]})

                if include_comfyui and rec.recommended_comfyui:
                    filename = rec.recommended_comfyui
                    # Hub serves checkpoints over the mesh at the PREFIXED path (KB #266408).
                    url = f"http://100.64.0.4:3000/tools/department-hq/api/fleet/checkpoints/{filename}"
                    cur.execute(
                        "INSERT INTO mesh_sync_log (node_id, sync_type, payload, status, sent_at) "
                        "VALUES (%s, 'checkpoint_pull', %s, 'sent', NOW()) RETURNING id",
                        (
                            node_id_str,
                            json.dumps(
                                {
                                    "url": url,
                                    "filename": filename,
                                    "checkpoints_dir": "/comfyui/models/checkpoints",
                                }
                            ),
                        ),
                    )
                    queued["checkpoint"] = {"filename": filename, "sync_id": cur.fetchone()["id"]}

            return jsonify(
                {
                    "success": True,
                    "node_id": node_id_str,
                    "tier": rec.tier,
                    "queued": queued,
                    "recommendation": rec.to_dict(),
                }
            )
        except Exception:
            logger.exception("Failed to provision warm-set for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/compose-recreate", methods=["POST"])
    @auth_decorator
    def api_compose_recreate(node_id):
        """Remotely recreate a node's sync container with updated volumes.

        Calls the node_api's /api/compose-recreate endpoint directly.
        Used after OTA pushes docker-compose changes that need container recreation.
        """
        import requests as _req

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        from tools.department_hq.fleet_helpers import node_inter_cluster_host

        hostname = node_inter_cluster_host(node)
        api_port = 3001  # node_api default port

        data = request.get_json() or {}
        add_volumes = data.get("add_volumes", {"comfyui_data": "/comfyui/models"})

        try:
            resp = _req.post(
                f"http://{hostname}:{api_port}/api/compose-recreate",
                json={"add_volumes": add_volumes},
                timeout=30,
            )
            result = resp.json()
            return jsonify(result)
        except Exception as e:
            logger.exception("Failed to recreate containers on node %s", node_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/nodes/<int:node_id>/push-update", methods=["POST"])
    @auth_decorator
    def api_push_code_update(node_id):
        """Push a code update request to a node."""

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Get latest deployment package
                cur.execute(
                    """
                    SELECT id, package_name, version_tag, file_path, created_at
                    FROM deployment_packages
                    ORDER BY created_at DESC LIMIT 1
                    """
                )
                pkg = cur.fetchone()
                version = pkg["version_tag"] if pkg else LATEST_NODE_VERSION

                # Flag node for update
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET update_requested = true, update_requested_at = NOW()
                    WHERE id = %s
                    """,
                    (node_id,),
                )

                # Log to mesh_sync_log
                payload = {
                    "version": version,
                    "package_name": pkg["package_name"] if pkg else None,
                    "file_path": pkg["file_path"] if pkg else None,
                }
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'code_update', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps(payload)),
                )
                sync_row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "sync_id": sync_row["id"],
                    "version": version,
                }
            )
        except Exception:
            logger.exception("Failed to push update to node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/push-config-update", methods=["POST"])
    @auth_decorator
    def api_push_config_update(node_id):
        """Push config changes to a node via mesh_sync_log (config_update)."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        # Allowed config fields that can be pushed to nodes
        ALLOWED_FIELDS = {
            "hub_url",
            "hub_api_key",
            "ollama_host",
            "heartbeat_interval",
            "sync_poll_interval",
            "archie_version",
        }
        config_payload = {k: v for k, v in data.items() if k in ALLOWED_FIELDS}
        if not config_payload:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"No valid config fields provided. Allowed: {sorted(ALLOWED_FIELDS)}",
                    }
                ),
                400,
            )

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'config_update', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps(config_payload)),
                )
                sync_row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "sync_id": sync_row["id"],
                    "fields_updated": list(config_payload.keys()),
                }
            )
        except Exception:
            logger.exception("Failed to push config update to node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/resync", methods=["POST"])
    @auth_decorator
    def api_resync_node(node_id):
        """Full resync: push fresh config_update + code_update to a node."""
        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        node_id_str = node["node_id"]

        try:
            sync_ids = []
            with get_db_cursor(commit=True) as (conn, cur):
                # 1) Push fresh config_update with current hub settings
                # Use internal network URL, not request.host_url which may be
                # the external domain behind a reverse proxy that requires auth
                hub_url = os.environ.get("HUB_INTERNAL_URL", "http://192.168.1.200:3000")
                config_payload = {
                    "hub_url": hub_url,
                    "heartbeat_interval": 30,
                    "sync_poll_interval": 60,
                }
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log
                        (node_id, sync_type, payload, status, sent_at)
                    VALUES (%s, 'config_update', %s, 'sent', NOW())
                    RETURNING id
                    """,
                    (node_id_str, json.dumps(config_payload)),
                )
                sync_ids.append({"sync_type": "config_update", "sync_id": cur.fetchone()["id"]})

                # 2) Push code_update with latest node_sync.py
                code_payload = {
                    "version": LATEST_NODE_VERSION,
                    "files": ["node_sync.py", "node_api.py"],
                    "migrations": [],
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
                sync_ids.append({"sync_type": "code_update", "sync_id": cur.fetchone()["id"]})

            return jsonify({"success": True, "sync_ids": sync_ids})
        except Exception:
            logger.exception("Failed to resync node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

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
