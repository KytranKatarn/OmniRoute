"""Fleet Command — Mesh routes (merged from Starbase mesh + Starship health)

Mesh cluster sync protocol endpoints for code versioning,
learning pattern sharing, agent lending, sync commands,
and health monitoring.
"""

import json
import hashlib
from hmac import compare_digest
import logging
import sys
from datetime import datetime, timezone

import psycopg2.extras

from flask import jsonify, request
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _get_db_cursor():
    """
    Import get_db_cursor at call time to avoid circular imports.
    Returns the get_db_cursor context manager from database module.
    """
    platform_path = "/mnt/archie_brain/platform_v2"
    if platform_path not in sys.path:
        sys.path.insert(0, platform_path)
    from database import get_db_cursor

    return get_db_cursor


def _verify_node_api_key(node_id):
    """
    Verify X-Node-API-Key header against stored SHA256 hash in remote_nodes.

    Returns:
        (True, node_row) on success
        (False, error_msg) on failure
    """
    api_key = request.headers.get("X-Node-API-Key")
    if not api_key:
        return False, "Missing X-Node-API-Key header"

    get_db_cursor = _get_db_cursor()
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT node_id, node_name, api_key_hash, approval_status
                FROM remote_nodes
                WHERE node_id = %s AND is_active = true
                """,
                (node_id,),
            )
            node = cur.fetchone()

        if not node:
            return False, "Node not found or inactive"

        if node["approval_status"] != "approved":
            return False, "Node not approved"

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        if not compare_digest(key_hash, node["api_key_hash"]):
            return False, "Invalid API key"

        return True, node
    except Exception as e:
        logger.error(f"Error verifying node API key: {e}")
        return False, "Auth error"


# ============================================================================
# ROUTE REGISTRATION
# ============================================================================


def _epoch_to_iso(val):
    """Convert Nagios epoch timestamp string to ISO format."""
    if not val or val == "0":
        return None
    try:
        return datetime.fromtimestamp(int(val), tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def register_mesh_routes(bp, auth_decorator):
    """Register all mesh/health routes on the fleet blueprint."""

    # ========================================================================
    # VERSION REPORTING
    # ========================================================================

    @bp.route("/api/mesh/version", methods=["POST"])
    def mesh_report_version():
        """Node reports its code version. Auth via API key."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        if not node_id:
            return jsonify({"success": False, "error": "node_id is required"}), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        version = data.get("version")
        if not version:
            return jsonify({"success": False, "error": "version is required"}), 400

        git_commit = data.get("git_commit")
        migration_version = data.get("migration_version")
        modules_list = data.get("modules_list", [])

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO mesh_code_versions (node_id, version, git_commit, migration_version, modules_list)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (node_id) DO UPDATE SET
                        version = EXCLUDED.version,
                        git_commit = EXCLUDED.git_commit,
                        migration_version = EXCLUDED.migration_version,
                        modules_list = EXCLUDED.modules_list,
                        updated_at = NOW()
                    RETURNING id, reported_at, updated_at
                    """,
                    (
                        node_id,
                        version,
                        git_commit,
                        migration_version,
                        json.dumps(modules_list),
                    ),
                )
                row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "message": "Version reported",
                    "version_id": row["id"],
                    "reported_at": (row["reported_at"].isoformat() if row["reported_at"] else None),
                    "updated_at": (row["updated_at"].isoformat() if row["updated_at"] else None),
                }
            )
        except Exception as e:
            logger.error(f"Mesh version report failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # LEARNING PATTERNS
    # ========================================================================

    @bp.route("/api/mesh/learning", methods=["POST"])
    def mesh_submit_learning():
        """Node submits anonymized learning pattern. Auth via API key."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        if not node_id:
            return jsonify({"success": False, "error": "node_id is required"}), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        pattern_type = data.get("pattern_type")
        insight = data.get("insight")
        if not pattern_type or not insight:
            return (
                jsonify({"success": False, "error": "pattern_type and insight are required"}),
                400,
            )

        category = data.get("category")
        metric_name = data.get("metric_name")
        metric_value = data.get("metric_value")
        metric_unit = data.get("metric_unit")
        context = data.get("context", {})

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO mesh_learning_patterns
                        (node_id, pattern_type, category, insight, metric_name, metric_value, metric_unit, context)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id, created_at
                    """,
                    (
                        node_id,
                        pattern_type,
                        category,
                        insight,
                        metric_name,
                        metric_value,
                        metric_unit,
                        json.dumps(context),
                    ),
                )
                row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "message": "Learning pattern submitted",
                    "pattern_id": row["id"],
                    "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
                }
            )
        except Exception as e:
            logger.error(f"Mesh learning submit failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/learning", methods=["GET"])
    @login_required
    def mesh_get_learning():
        """Hub admin views learning patterns. Auth via login."""
        limit = request.args.get("limit", 50, type=int)
        pattern_type = request.args.get("type")

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                query = """
                    SELECT mlp.id, mlp.node_id, rn.node_name,
                           mlp.pattern_type, mlp.category, mlp.insight,
                           mlp.metric_name, mlp.metric_value, mlp.metric_unit,
                           mlp.context, mlp.created_at
                    FROM mesh_learning_patterns mlp
                    JOIN remote_nodes rn ON rn.node_id = mlp.node_id
                """
                params = []
                if pattern_type:
                    query += " WHERE mlp.pattern_type = %s"
                    params.append(pattern_type)
                query += " ORDER BY mlp.created_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                rows = cur.fetchall()

            patterns = []
            for r in rows:
                patterns.append(
                    {
                        "id": r["id"],
                        "node_id": r["node_id"],
                        "node_name": r["node_name"],
                        "pattern_type": r["pattern_type"],
                        "category": r["category"],
                        "insight": r["insight"],
                        "metric_name": r["metric_name"],
                        "metric_value": r["metric_value"],
                        "metric_unit": r["metric_unit"],
                        "context": r["context"],
                        "created_at": (r["created_at"].isoformat() if r["created_at"] else None),
                    }
                )

            return jsonify({"success": True, "patterns": patterns, "count": len(patterns)})
        except Exception as e:
            logger.error(f"Mesh learning fetch failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # AGENT LENDING
    # ========================================================================

    @bp.route("/api/mesh/agents/lend", methods=["POST"])
    @login_required
    def mesh_lend_agent():
        """Hub admin lends an agent from one node to another. Auth via login."""
        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        source_node_id = data.get("source_node_id")
        target_node_id = data.get("target_node_id")
        task_description = data.get("task_description")

        if not all([agent_id, source_node_id, target_node_id]):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "agent_id, source_node_id, and target_node_id are required",
                    }
                ),
                400,
            )

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                # Validate both nodes exist and are approved
                cur.execute(
                    """
                    SELECT node_id, approval_status
                    FROM remote_nodes
                    WHERE node_id IN (%s, %s) AND is_active = true
                    """,
                    (source_node_id, target_node_id),
                )
                nodes = cur.fetchall()
                node_ids_found = {n["node_id"] for n in nodes}

                if source_node_id not in node_ids_found:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Source node not found or inactive",
                            }
                        ),
                        404,
                    )
                if target_node_id not in node_ids_found:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Target node not found or inactive",
                            }
                        ),
                        404,
                    )

                for n in nodes:
                    if n["approval_status"] != "approved":
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Node {n['node_id']} is not approved (status: {n['approval_status']})",
                                }
                            ),
                            403,
                        )

                cur.execute(
                    """
                    INSERT INTO mesh_agent_loans (agent_id, source_node_id, target_node_id, task_description)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, lent_at
                    """,
                    (agent_id, source_node_id, target_node_id, task_description),
                )
                row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "message": "Agent lent successfully",
                    "loan_id": row["id"],
                    "lent_at": row["lent_at"].isoformat() if row["lent_at"] else None,
                }
            )
        except Exception as e:
            logger.error(f"Mesh agent lend failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/agents/return", methods=["POST"])
    def mesh_return_agent():
        """Node returns a borrowed agent. Auth via API key."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        loan_id = data.get("loan_id")

        if not node_id or not loan_id:
            return (
                jsonify({"success": False, "error": "node_id and loan_id are required"}),
                400,
            )

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        work_summary = data.get("work_summary")

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    UPDATE mesh_agent_loans
                    SET status = 'completed', returned_at = NOW(), work_summary = %s
                    WHERE id = %s AND target_node_id = %s AND status = 'active'
                    RETURNING id, returned_at
                    """,
                    (work_summary, loan_id, node_id),
                )
                row = cur.fetchone()

            if not row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Loan not found or already completed",
                        }
                    ),
                    404,
                )

            return jsonify(
                {
                    "success": True,
                    "message": "Agent returned successfully",
                    "loan_id": row["id"],
                    "returned_at": (row["returned_at"].isoformat() if row["returned_at"] else None),
                }
            )
        except Exception as e:
            logger.error(f"Mesh agent return failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/agents/return-admin", methods=["POST"])
    @login_required
    def mesh_return_agent_admin():
        """Hub admin returns a borrowed agent (no API key needed)."""
        get_db_cursor = _get_db_cursor()
        data = request.get_json(force=True) or {}
        loan_id = data.get("loan_id")
        if not loan_id:
            return jsonify({"success": False, "error": "loan_id is required"}), 400
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE mesh_agent_loans
                       SET status = 'completed', returned_at = NOW(),
                           work_summary = COALESCE(work_summary, 'Returned by hub admin')
                       WHERE id = %s AND status = 'active'
                       RETURNING id""",
                    (loan_id,),
                )
                row = cur.fetchone()
                if not row:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Loan not found or already completed",
                            }
                        ),
                        404,
                    )
            return jsonify({"success": True, "message": "Agent returned successfully"})
        except Exception as e:
            logger.error(f"Mesh admin return agent failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/agents/loans", methods=["GET"])
    @login_required
    def mesh_get_loans():
        """Hub admin views agent loans. Auth via login."""
        status_filter = request.args.get("status")

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                query = """
                    SELECT mal.id, mal.agent_id,
                           mal.source_node_id,
                           COALESCE(sn.node_name, mal.source_node_id) AS source_node_name,
                           mal.target_node_id,
                           COALESCE(tn.node_name, mal.target_node_id) AS target_node_name,
                           na.display_name AS agent_display_name,
                           na.name AS agent_name,
                           mal.task_description, mal.status,
                           mal.lent_at, mal.returned_at, mal.work_summary, mal.initiated_by
                    FROM mesh_agent_loans mal
                    LEFT JOIN remote_nodes sn ON sn.node_id = mal.source_node_id
                    LEFT JOIN remote_nodes tn ON tn.node_id = mal.target_node_id
                    LEFT JOIN node_agents na ON na.id = mal.agent_id
                """
                params = []
                if status_filter:
                    query += " WHERE mal.status = %s"
                    params.append(status_filter)
                query += " ORDER BY mal.lent_at DESC"

                cur.execute(query, params)
                rows = cur.fetchall()

            loans = []
            for r in rows:
                loans.append(
                    {
                        "id": r["id"],
                        "agent_id": r["agent_id"],
                        "agent_display_name": r["agent_display_name"],
                        "agent_name": r["agent_name"],
                        "source_node_id": r["source_node_id"],
                        "source_node_name": r["source_node_name"],
                        "target_node_id": r["target_node_id"],
                        "target_node_name": r["target_node_name"],
                        "task_description": r["task_description"],
                        "status": r["status"],
                        "lent_at": r["lent_at"].isoformat() if r["lent_at"] else None,
                        "returned_at": (r["returned_at"].isoformat() if r["returned_at"] else None),
                        "work_summary": r["work_summary"],
                        "initiated_by": r["initiated_by"],
                    }
                )

            return jsonify({"success": True, "loans": loans, "count": len(loans)})
        except Exception as e:
            logger.error(f"Mesh loans fetch failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # SYNC LOG
    # ========================================================================

    @bp.route("/api/mesh/sync", methods=["POST"])
    @login_required
    def mesh_push_sync():
        """Hub admin pushes a sync command to a node. Auth via login."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        sync_type = data.get("sync_type")

        if not node_id or not sync_type:
            return (
                jsonify({"success": False, "error": "node_id and sync_type are required"}),
                400,
            )

        payload = data.get("payload", {})

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO mesh_sync_log (node_id, sync_type, payload)
                    VALUES (%s, %s, %s::jsonb)
                    RETURNING id, sent_at
                    """,
                    (node_id, sync_type, json.dumps(payload)),
                )
                row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "message": "Sync command pushed",
                    "sync_id": row["id"],
                    "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
                }
            )
        except Exception as e:
            logger.error(f"Mesh sync push failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/sync/<node_id>/pending", methods=["GET"])
    def mesh_get_pending_syncs(node_id):
        """Node polls for pending sync commands. Auth via API key."""
        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, sync_type, payload, sent_at
                    FROM mesh_sync_log
                    WHERE node_id = %s AND status = 'sent'
                    ORDER BY sent_at ASC
                    """,
                    (node_id,),
                )
                rows = cur.fetchall()

            syncs = []
            for r in rows:
                syncs.append(
                    {
                        "id": r["id"],
                        "sync_type": r["sync_type"],
                        "payload": r["payload"],
                        "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                    }
                )

            return jsonify({"success": True, "syncs": syncs, "count": len(syncs)})
        except Exception as e:
            logger.error(f"Mesh pending syncs fetch failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/sync/<int:sync_id>/ack", methods=["POST"])
    def mesh_ack_sync(sync_id):
        """Node acknowledges a sync command. Auth via API key."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        if not node_id:
            return jsonify({"success": False, "error": "node_id is required"}), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        status = data.get("status", "acknowledged")
        error_message = data.get("error_message")
        ack_payload = data.get("result")  # Job result payload from node

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                # Fetch sync entry first to check type
                cur.execute(
                    """
                    SELECT id, sync_type, payload
                    FROM mesh_sync_log
                    WHERE id = %s AND node_id = %s AND status = 'sent'
                    """,
                    (sync_id, node_id),
                )
                sync_entry = cur.fetchone()

                if not sync_entry:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Sync not found or already acknowledged",
                            }
                        ),
                        404,
                    )

                # Update status
                cur.execute(
                    """
                    UPDATE mesh_sync_log
                    SET status = %s, acknowledged_at = NOW(), error_message = %s,
                        result_payload = %s
                    WHERE id = %s
                    RETURNING id, acknowledged_at
                    """,
                    (status, error_message, psycopg2.extras.Json(ack_payload), sync_id),
                )
                row = cur.fetchone()

                # Process job_request results — log to task_execution_log
                if sync_entry["sync_type"] == "job_request" and ack_payload:
                    try:
                        original = sync_entry["payload"] or {}
                        if isinstance(original, str):
                            original = json.loads(original)
                        station_codes = original.get("station_codes", [])
                        cur.execute(
                            """
                            INSERT INTO task_execution_log
                                (agent_name, station_code, capability,
                                 module_source, success, duration_ms,
                                 created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, NOW())
                            """,
                            (
                                ack_payload.get(
                                    "agent_name",
                                    original.get("target_agent"),
                                ),
                                station_codes[0] if station_codes else "UNKNOWN",
                                original.get("capability"),
                                original.get("module_id", "remote"),
                                ack_payload.get("success", False),
                                ack_payload.get("duration_ms", 0),
                            ),
                        )
                    except Exception as job_err:
                        logger.warning(f"Mesh ack job result logging failed: {job_err}")

            return jsonify(
                {
                    "success": True,
                    "message": "Sync acknowledged",
                    "sync_id": row["id"],
                    "acknowledged_at": (row["acknowledged_at"].isoformat() if row["acknowledged_at"] else None),
                }
            )
        except Exception as e:
            logger.error(f"Mesh sync ack failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # FLEET BROADCAST + CONFIG VERSION
    # ========================================================================

    @bp.route("/api/mesh/broadcast", methods=["POST"])
    @login_required
    def mesh_broadcast():
        """Broadcast a sync entry to all active online nodes."""
        data = request.get_json() or {}
        sync_type = data.get("sync_type")
        payload = data.get("payload", {})

        if not sync_type:
            return jsonify({"success": False, "error": "sync_type required"}), 400

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT node_id FROM remote_nodes
                    WHERE status = 'online'
                      AND last_heartbeat > NOW() - INTERVAL '90 seconds'
                    """
                )
                nodes = cur.fetchall()

                created = 0
                for node in nodes:
                    cur.execute(
                        """
                        INSERT INTO mesh_sync_log
                            (node_id, sync_type, payload, status, sent_at)
                        VALUES (%s, %s, %s, 'sent', NOW())
                        """,
                        (node["node_id"], sync_type, json.dumps(payload)),
                    )
                    created += 1

            return jsonify(
                {
                    "success": True,
                    "broadcast": True,
                    "nodes_targeted": created,
                    "sync_type": sync_type,
                }
            )
        except Exception as e:
            logger.error(f"Mesh broadcast failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/mesh/version", methods=["GET"])
    def mesh_config_version():
        """Return current config versions for sync checks."""
        return jsonify(
            {
                "success": True,
                "capability_map_version": 1,
                "station_commands_version": 1,
                "agent_config_version": 1,
            }
        )

    # ========================================================================
    # CLUSTER OVERVIEW
    # ========================================================================

    @bp.route("/api/mesh/cluster", methods=["GET"])
    @login_required
    def mesh_cluster_overview():
        """Hub admin gets cluster overview. Auth via login."""
        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT * FROM v_mesh_cluster_overview ORDER BY node_id")
                rows = cur.fetchall()

            nodes = []
            for r in rows:
                node = {}
                for key, val in r.items():
                    if isinstance(val, datetime):
                        node[key] = val.isoformat()
                    else:
                        node[key] = val
                nodes.append(node)

            return jsonify({"success": True, "nodes": nodes, "count": len(nodes)})
        except Exception as e:
            logger.error(f"Mesh cluster overview failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # AVAILABLE AGENTS (for Request Help modal)
    # ========================================================================

    @bp.route("/api/mesh/agents/available", methods=["GET"])
    @login_required
    def mesh_available_agents():
        """Hub admin views agents available for lending across the mesh."""
        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Find lendable agents: node must be online, approved,
                # bridge_enabled, active, with capacity, and not local_data_only.
                # Agent must be allowed, active, and not on an active loan.
                cur.execute(
                    """
                    SELECT
                        na.id AS agent_id,
                        na.name,
                        na.display_name,
                        na.title,
                        na.model,
                        na.capabilities,
                        na.station_codes,
                        rn.id AS remote_node_pk,
                        rn.node_id,
                        rn.node_name,
                        rn.current_load,
                        rn.max_concurrent,
                        rn.privacy_settings
                    FROM node_agents na
                    JOIN remote_nodes rn ON rn.id = na.node_id
                    WHERE rn.status = 'online'
                      AND rn.approval_status = 'approved'
                      AND rn.bridge_enabled = true
                      AND rn.is_active = true
                      AND rn.current_load < rn.max_concurrent
                      AND COALESCE(
                          (rn.privacy_settings->>'local_data_only')::boolean,
                          false
                      ) = false
                      AND na.is_allowed = true
                      AND na.status = 'active'
                      AND NOT EXISTS (
                          SELECT 1 FROM mesh_agent_loans mal
                          WHERE mal.agent_id = na.id
                            AND mal.status = 'active'
                      )
                    ORDER BY rn.node_name, na.display_name
                    """
                )
                rows = cur.fetchall()

                # Count active loans for summary
                cur.execute("SELECT COUNT(*) AS cnt FROM mesh_agent_loans WHERE status = 'active'")
                active_loans = cur.fetchone()["cnt"]

            available_agents = []
            node_ids_seen = set()
            for r in rows:
                # Compute privacy_level from privacy_settings JSONB
                ps = r["privacy_settings"] or {}
                if ps.get("share_nothing"):
                    privacy_level = "restricted"
                elif ps.get("anonymize_data") or ps.get("strip_pii"):
                    privacy_level = "anonymized"
                else:
                    privacy_level = "open"

                node_ids_seen.add(r["node_id"])
                available_agents.append(
                    {
                        "agent_id": r["agent_id"],
                        "name": r["name"],
                        "display_name": r["display_name"],
                        "title": r["title"],
                        "model": r["model"],
                        "capabilities": r["capabilities"],
                        "station_codes": r["station_codes"],
                        "node_id": r["node_id"],
                        "node_name": r["node_name"],
                        "node_capacity": {
                            "current_load": r["current_load"],
                            "max_concurrent": r["max_concurrent"],
                        },
                        "privacy_level": privacy_level,
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "available_agents": available_agents,
                    "summary": {
                        "total_available": len(available_agents),
                        "nodes_with_capacity": len(node_ids_seen),
                        "active_loans": active_loans,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Mesh available agents fetch failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # OTA CODE UPDATE
    # ========================================================================

    @bp.route("/api/mesh/push-update", methods=["POST"])
    @login_required
    def mesh_push_code_update():
        """
        Push a code_update sync to one or all active nodes.

        POST body:
            node_id (str, optional): Target node. Omit to push to all active nodes.
            version (str): Version string for this update.
            files (list[str]): Python files to update (default: node_sync.py, node_api.py)
            migrations (list[str]): Migration filenames to download + apply on nodes.
        """
        data = request.get_json() or {}
        target_node_id = data.get("node_id")
        version = data.get("version", "latest")
        files = data.get("files", ["node_sync.py", "node_api.py"])
        migrations = data.get("migrations", [])

        payload = {
            "version": version,
            "files": files,
            "migrations": migrations,
        }

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                if target_node_id:
                    node_ids = [target_node_id]
                else:
                    cur.execute(
                        "SELECT node_id FROM remote_nodes " "WHERE is_active = true AND approval_status = 'approved'"
                    )
                    node_ids = [r["node_id"] for r in cur.fetchall()]

                pushed = []
                for nid in node_ids:
                    cur.execute(
                        """
                        INSERT INTO mesh_sync_log (node_id, sync_type, payload)
                        VALUES (%s, 'code_update', %s::jsonb)
                        RETURNING id
                        """,
                        (nid, json.dumps(payload)),
                    )
                    sync_id = cur.fetchone()["id"]
                    pushed.append({"node_id": nid, "sync_id": sync_id})

            return jsonify(
                {
                    "success": True,
                    "message": f"Code update pushed to {len(pushed)} node(s)",
                    "version": version,
                    "files": files,
                    "migrations": migrations,
                    "pushed": pushed,
                }
            )
        except Exception as e:
            logger.error(f"Mesh push-update failed: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ================================================================
    # MESH VPN — Headscale topology, health, and auth key management
    # ================================================================

    @bp.route("/api/mesh/topology")
    @login_required
    def get_mesh_topology():
        """Return mesh topology — all nodes with their mesh status."""
        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, node_id, node_name, hostname, vpn_ip,
                           mesh_ip, mesh_status, mesh_latency_ms,
                           mesh_connection_type, mesh_last_seen,
                           status, gpu_model, gpu_vram_gb, ram_gb,
                           last_heartbeat, approval_status
                    FROM remote_nodes
                    WHERE approval_status = 'approved'
                    ORDER BY mesh_status = 'connected' DESC, node_name
                """
                )
                nodes = cur.fetchall()

            mesh_nodes = []
            for n in nodes:
                mesh_nodes.append(
                    {
                        "id": n["id"],
                        "node_id": n["node_id"],
                        "node_name": n["node_name"],
                        "hostname": n["hostname"],
                        "vpn_ip": n["vpn_ip"],
                        "mesh_ip": n["mesh_ip"],
                        "mesh_status": n["mesh_status"] or "disconnected",
                        "mesh_latency_ms": n["mesh_latency_ms"],
                        "mesh_connection_type": n["mesh_connection_type"],
                        "mesh_last_seen": n["mesh_last_seen"].isoformat() if n["mesh_last_seen"] else None,
                        "status": n["status"],
                        "gpu_model": n["gpu_model"],
                        "gpu_vram_gb": float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else 0,
                        "ram_gb": float(n["ram_gb"]) if n["ram_gb"] else 0,
                        "online": (
                            (
                                n["last_heartbeat"] is not None
                                and (datetime.now(n["last_heartbeat"].tzinfo) - n["last_heartbeat"]).total_seconds()
                                < 60
                            )
                            if n["last_heartbeat"]
                            else False
                        ),
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "nodes": mesh_nodes,
                    "total": len(mesh_nodes),
                    "mesh_connected": sum(1 for n in mesh_nodes if n["mesh_status"] == "connected"),
                }
            )
        except Exception as e:
            logger.error(f"Mesh topology error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/mesh/health")
    @login_required
    def get_mesh_health():
        """Return mesh health summary with recent latency data."""
        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                # Aggregate mesh stats
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE mesh_status = 'connected') as connected,
                        COUNT(*) FILTER (WHERE mesh_status = 'disconnected' OR mesh_status IS NULL) as disconnected,
                        COUNT(*) FILTER (WHERE mesh_status = 'relay') as relay,
                        AVG(mesh_latency_ms) FILTER (WHERE mesh_latency_ms IS NOT NULL) as avg_latency,
                        MAX(mesh_latency_ms) FILTER (WHERE mesh_latency_ms IS NOT NULL) as max_latency
                    FROM remote_nodes
                    WHERE approval_status = 'approved'
                """
                )
                stats = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "connected": stats["connected"] or 0,
                        "disconnected": stats["disconnected"] or 0,
                        "relay": stats["relay"] or 0,
                        "avg_latency_ms": round(float(stats["avg_latency"]), 1) if stats["avg_latency"] else None,
                        "max_latency_ms": int(stats["max_latency"]) if stats["max_latency"] else None,
                    }
                )
        except Exception as e:
            logger.error(f"Mesh health error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/mesh/authkeys", methods=["GET", "POST"])
    @login_required
    def manage_mesh_authkeys():
        """Create or list Headscale pre-auth keys."""
        get_db_cursor = _get_db_cursor()
        if request.method == "POST":
            # Generate a new pre-auth key via Headscale CLI
            try:
                import subprocess

                data = request.get_json() or {}
                expiry = data.get("expiration", "1h")
                reusable = data.get("reusable", False)

                cmd = [
                    "docker",
                    "exec",
                    "archie_headscale",
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "archie-fleet",
                    "--expiration",
                    expiry,
                ]
                if not reusable:
                    cmd.append("--ephemeral")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    return jsonify({"success": False, "error": result.stderr}), 500

                # Parse key from output (skip WRN lines)
                lines = [
                    l.strip()
                    for l in result.stdout.strip().split("\n")
                    if l.strip() and "WRN" not in l and "TRC" not in l
                ]
                if not lines:
                    return jsonify({"success": False, "error": "No key in output"}), 500

                key = lines[-1]
                key_prefix = key[:12] + "..."

                # Store in DB for tracking
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """
                        INSERT INTO headscale_authkeys
                            (key_prefix, key_hash, created_by, is_ephemeral, is_reusable, expires_at)
                        VALUES (%s, %s, %s, %s, %s, NOW() + %s::interval)
                        RETURNING id
                    """,
                        (
                            key_prefix,
                            hashlib.sha256(key.encode()).hexdigest(),
                            current_user.id if hasattr(current_user, "id") else None,
                            not reusable,
                            reusable,
                            expiry,
                        ),
                    )
                    key_id = cur.fetchone()["id"]
                    conn.commit()

                return jsonify(
                    {
                        "success": True,
                        "key": key,
                        "key_id": key_id,
                        "prefix": key_prefix,
                        "expiration": expiry,
                        "reusable": reusable,
                    }
                )
            except Exception as e:
                logger.error(f"Mesh authkey creation error: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        else:  # GET — list keys
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """
                        SELECT id, key_prefix, is_ephemeral, is_reusable,
                               is_used, expires_at, created_at
                        FROM headscale_authkeys
                        ORDER BY created_at DESC
                        LIMIT 50
                    """
                    )
                    keys = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "keys": [
                            {
                                "id": k["id"],
                                "prefix": k["key_prefix"],
                                "ephemeral": k["is_ephemeral"],
                                "reusable": k["is_reusable"],
                                "used": k["is_used"],
                                "expires_at": k["expires_at"].isoformat() if k["expires_at"] else None,
                                "created_at": k["created_at"].isoformat() if k["created_at"] else None,
                            }
                            for k in keys
                        ],
                    }
                )
            except Exception as e:
                logger.error(f"Mesh authkey list error: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

    # ================================================================
    # SAAS MESH — Module discovery + API proxy for fleet nodes
    # ================================================================

    @bp.route("/api/mesh/saas-modules")
    def get_saas_modules():
        """Return available SaaS modules for fleet nodes."""
        try:
            from module_registry import MODULES, ModuleCategory

            saas = []
            for mod in MODULES:
                if mod.category == ModuleCategory.SAAS_SERVICES and mod.enabled:
                    saas.append(
                        {
                            "id": mod.id,
                            "name": mod.name,
                            "description": mod.description,
                            "route": mod.route,
                            "icon": mod.icon,
                            "tags": mod.tags,
                        }
                    )
            return jsonify({"success": True, "modules": saas, "count": len(saas)})
        except Exception as e:
            logger.error(f"SaaS modules list error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route(
        "/api/mesh/saas-proxy/<path:path>",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    def saas_proxy(path):
        """Proxy SaaS API calls from fleet nodes.

        Nodes call /api/mesh/saas-proxy/tools/crm/api/contacts
        and this forwards to the local Flask route, preserving auth.
        """
        api_key = request.headers.get("X-Node-API-Key")
        if not api_key:
            return jsonify({"error": "API key required"}), 401

        # Verify the node is approved
        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id FROM remote_nodes
                       WHERE api_key_hash = %s
                         AND approval_status = 'approved'""",
                    (hashlib.sha256(api_key.encode()).hexdigest(),),
                )
                if not cur.fetchone():
                    return jsonify({"error": "Invalid or unapproved node"}), 403
        except Exception:
            return jsonify({"error": "Auth check failed"}), 500

        # Forward to internal route
        try:
            from flask import current_app, Response

            with current_app.test_client() as client:
                method_fn = getattr(client, request.method.lower())
                resp = method_fn(
                    f"/{path}",
                    data=request.get_data(),
                    content_type=request.content_type,
                )
                return Response(resp.data, resp.status_code, resp.headers)
        except Exception as e:
            logger.error(f"SaaS proxy error for /{path}: {e}")
            return jsonify({"error": str(e)}), 500

    # ================================================================
    # DATA SYNC — Incremental data packages for fleet nodes
    # ================================================================

    @bp.route("/api/mesh/sync-data", methods=["POST"])
    def sync_data():
        """Serve incremental data package for node DB sync.

        Node sends watermarks (last sync timestamps per type).
        Hub returns records updated since those watermarks.
        """
        api_key = request.headers.get("X-Node-API-Key")
        if not api_key:
            return jsonify({"error": "API key required"}), 401

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                # Verify node
                cur.execute(
                    """SELECT id, node_name FROM remote_nodes
                       WHERE api_key_hash = %s
                         AND approval_status = 'approved'""",
                    (hashlib.sha256(api_key.encode()).hexdigest(),),
                )
                node = cur.fetchone()
                if not node:
                    return jsonify({"error": "Invalid node"}), 403

                data = request.get_json() or {}
                watermarks = data.get("watermarks", {})
                limit = min(data.get("limit", 100), 500)

                package = {}

                # Knowledge sync
                kb_since = watermarks.get("knowledge_sync", "1970-01-01")
                cur.execute(
                    """SELECT id, title, content, knowledge_type, category,
                              tags, importance_score, source_type, updated_at
                       FROM knowledge_base
                       WHERE updated_at > %s AND status = 'active'
                       ORDER BY updated_at ASC LIMIT %s""",
                    (kb_since, limit),
                )
                package["knowledge"] = [dict(r) for r in cur.fetchall()]

                # Projects sync
                proj_since = watermarks.get("project_sync", "1970-01-01")
                cur.execute(
                    """SELECT id, name, slug, description, status, priority,
                              project_type, tags, updated_at
                       FROM unified_projects
                       WHERE updated_at > %s
                       ORDER BY updated_at ASC LIMIT %s""",
                    (proj_since, limit),
                )
                package["projects"] = [dict(r) for r in cur.fetchall()]

                # Tasks sync
                task_since = watermarks.get("task_sync", "1970-01-01")
                cur.execute(
                    """SELECT id, project_id, title, description, status,
                              priority, assigned_agent, tags, updated_at
                       FROM unified_tasks
                       WHERE updated_at > %s
                       ORDER BY updated_at ASC LIMIT %s""",
                    (task_since, limit),
                )
                package["tasks"] = [dict(r) for r in cur.fetchall()]

                # Contacts sync (CRM)
                contact_since = watermarks.get("contact_sync", "1970-01-01")
                cur.execute(
                    """SELECT id, name, email, company, role, tags,
                              updated_at
                       FROM crm_customers
                       WHERE updated_at > %s
                       ORDER BY updated_at ASC LIMIT %s""",
                    (contact_since, limit),
                )
                package["contacts"] = [dict(r) for r in cur.fetchall()]

                # Serialize datetimes
                for section in package.values():
                    for row in section:
                        for k, v in row.items():
                            if hasattr(v, "isoformat"):
                                row[k] = v.isoformat()

                return jsonify(
                    {
                        "success": True,
                        "package": package,
                        "counts": {k: len(v) for k, v in package.items()},
                    }
                )

        except Exception as e:
            logger.error(f"Sync data error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    logger.info("Mesh API routes registered on bridge blueprint")

    # ============================================================================
    # HEALTH MONITORING (from Starship)
    # ============================================================================

    @bp.route("/api/health-status")
    @login_required
    def api_health_status():
        """Unified health status for all monitored hosts."""
        try:
            from services.monitoring_service import get_unified_health

            health = get_unified_health()

            ok_count = 0
            warn_count = 0
            crit_count = 0

            hosts = []
            for node_id, data in health.items():
                if data["summary"] == "ok":
                    ok_count += 1
                elif data["summary"] == "warning":
                    warn_count += 1
                elif data["summary"] == "critical":
                    crit_count += 1

                hosts.append(
                    {
                        "node_id": node_id,
                        "summary": data["summary"],
                        "host_status": (data["host"].get("status", "unknown") if data["host"] else "unknown"),
                        "services": [
                            {
                                "name": s.get("service_description", s.get("check_name", "unknown")),
                                "status": s.get("status", "unknown"),
                                "output": s.get("plugin_output", ""),
                                "last_check": _epoch_to_iso(s.get("last_check")),
                            }
                            for s in data["services"]
                        ],
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "summary": {
                        "total": len(hosts),
                        "ok": ok_count,
                        "warning": warn_count,
                        "critical": crit_count,
                    },
                    "hosts": hosts,
                }
            )
        except Exception as e:
            logger.error("Health status error: %s", e)
            return (
                jsonify({"success": False, "error": "Internal server error"}),
                500,
            )

    @bp.route("/api/health-status/<node_id>")
    @login_required
    def api_host_health(node_id):
        """Health checks for a specific host."""
        try:
            from services.monitoring_service import get_host_checks

            data = get_host_checks(node_id)
            return jsonify(
                {
                    "success": True,
                    "node_id": node_id,
                    "summary": data["summary"],
                    "host": data["host"],
                    "services": data["services"],
                }
            )
        except Exception as e:
            logger.error("Host health error: %s", e)
            return (
                jsonify({"success": False, "error": "Internal server error"}),
                500,
            )
