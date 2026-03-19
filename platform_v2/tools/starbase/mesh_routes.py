"""
A.R.C.H.I.E. MESH API Routes
==============================
Mesh cluster sync protocol endpoints for code versioning,
learning pattern sharing, agent lending, and sync commands.

These routes are registered on the starbase blueprint from routes.py.

Author: A.R.C.H.I.E. Platform
Date: 2026-02-04
"""

import json
import hashlib
from hmac import compare_digest
import logging
import sys
from datetime import datetime

from flask import jsonify, request
from flask_login import login_required

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
        return False, f"Auth error: {str(e)}"


# ============================================================================
# ROUTE REGISTRATION
# ============================================================================


def register_mesh_routes(bp, admin_required=None):
    """Register all mesh cluster API routes on the starbase blueprint."""

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
                    SET status = %s, acknowledged_at = NOW(), error_message = %s
                    WHERE id = %s
                    RETURNING id, acknowledged_at
                    """,
                    (status, error_message, sync_id),
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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

    logger.info("Mesh API routes registered on bridge blueprint")
