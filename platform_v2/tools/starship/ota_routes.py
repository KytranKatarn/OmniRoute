import json
import logging
from flask import jsonify, request
from flask_login import current_user
from database import get_db_cursor
from .helpers import _get_node_for_user_by_int_id, LATEST_NODE_VERSION

logger = logging.getLogger(__name__)


def register_ota_routes(bp, auth_decorator):
    """Register OTA push and sync routes on the starship blueprint."""

    @bp.route("/api/nodes/<int:node_id>/push-config", methods=["POST"])
    @auth_decorator
    def api_push_agent_config(node_id):
        """Push current agent configuration to a node via mesh_sync_log."""
        import psycopg2

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
        except Exception as e:
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
        except Exception as e:
            logger.exception("Failed to pull model for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/push-update", methods=["POST"])
    @auth_decorator
    def api_push_code_update(node_id):
        """Push a code update request to a node."""
        import psycopg2

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
        except Exception as e:
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
        except Exception as e:
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
                config_payload = {
                    "hub_url": request.host_url.rstrip("/"),
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
        except Exception as e:
            logger.exception("Failed to resync node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

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
                           error_message
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
                    }
                )

            return jsonify({"success": True, "logs": logs})
        except Exception as e:
            logger.exception("Failed to get sync log for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

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
        except Exception as e:
            logger.exception("Failed to get sync status for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500
