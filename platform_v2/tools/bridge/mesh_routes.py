"""
A.R.C.H.I.E. MESH API Routes
==============================
Mesh cluster sync protocol endpoints for code versioning,
learning pattern sharing, agent lending, and sync commands.

These routes are registered on the bridge blueprint from routes.py.

Author: A.R.C.H.I.E. Platform
Date: 2026-02-04
"""

import json
import hashlib
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
        if key_hash != node["api_key_hash"]:
            return False, "Invalid API key"

        return True, node
    except Exception as e:
        logger.error(f"Error verifying node API key: {e}")
        return False, f"Auth error: {str(e)}"


# ============================================================================
# ROUTE REGISTRATION
# ============================================================================


def register_mesh_routes(bridge_bp):
    """Register all mesh cluster API routes on the bridge blueprint."""

    # ========================================================================
    # VERSION REPORTING
    # ========================================================================

    @bridge_bp.route("/api/mesh/version", methods=["POST"])
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
                    (node_id, version, git_commit, migration_version, json.dumps(modules_list)),
                )
                row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "message": "Version reported",
                    "version_id": row["id"],
                    "reported_at": row["reported_at"].isoformat() if row["reported_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
            )
        except Exception as e:
            logger.error(f"Mesh version report failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ========================================================================
    # LEARNING PATTERNS
    # ========================================================================

    @bridge_bp.route("/api/mesh/learning", methods=["POST"])
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
            return jsonify({"success": False, "error": "pattern_type and insight are required"}), 400

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
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )
        except Exception as e:
            logger.error(f"Mesh learning submit failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/learning", methods=["GET"])
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
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                )

            return jsonify({"success": True, "patterns": patterns, "count": len(patterns)})
        except Exception as e:
            logger.error(f"Mesh learning fetch failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ========================================================================
    # AGENT LENDING
    # ========================================================================

    @bridge_bp.route("/api/mesh/agents/lend", methods=["POST"])
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
                jsonify({"success": False, "error": "agent_id, source_node_id, and target_node_id are required"}),
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
                    return jsonify({"success": False, "error": "Source node not found or inactive"}), 404
                if target_node_id not in node_ids_found:
                    return jsonify({"success": False, "error": "Target node not found or inactive"}), 404

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

    @bridge_bp.route("/api/mesh/agents/return", methods=["POST"])
    def mesh_return_agent():
        """Node returns a borrowed agent. Auth via API key."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        loan_id = data.get("loan_id")

        if not node_id or not loan_id:
            return jsonify({"success": False, "error": "node_id and loan_id are required"}), 400

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
                return jsonify({"success": False, "error": "Loan not found or already completed"}), 404

            return jsonify(
                {
                    "success": True,
                    "message": "Agent returned successfully",
                    "loan_id": row["id"],
                    "returned_at": row["returned_at"].isoformat() if row["returned_at"] else None,
                }
            )
        except Exception as e:
            logger.error(f"Mesh agent return failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/agents/loans", methods=["GET"])
    @login_required
    def mesh_get_loans():
        """Hub admin views agent loans. Auth via login."""
        status_filter = request.args.get("status")

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                query = """
                    SELECT mal.id, mal.agent_id,
                           mal.source_node_id, sn.node_name AS source_node_name,
                           mal.target_node_id, tn.node_name AS target_node_name,
                           mal.task_description, mal.status,
                           mal.lent_at, mal.returned_at, mal.work_summary, mal.initiated_by
                    FROM mesh_agent_loans mal
                    JOIN remote_nodes sn ON sn.node_id = mal.source_node_id
                    JOIN remote_nodes tn ON tn.node_id = mal.target_node_id
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
                        "source_node_id": r["source_node_id"],
                        "source_node_name": r["source_node_name"],
                        "target_node_id": r["target_node_id"],
                        "target_node_name": r["target_node_name"],
                        "task_description": r["task_description"],
                        "status": r["status"],
                        "lent_at": r["lent_at"].isoformat() if r["lent_at"] else None,
                        "returned_at": r["returned_at"].isoformat() if r["returned_at"] else None,
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

    @bridge_bp.route("/api/mesh/sync", methods=["POST"])
    @login_required
    def mesh_push_sync():
        """Hub admin pushes a sync command to a node. Auth via login."""
        data = request.get_json() or {}
        node_id = data.get("node_id")
        sync_type = data.get("sync_type")

        if not node_id or not sync_type:
            return jsonify({"success": False, "error": "node_id and sync_type are required"}), 400

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

    @bridge_bp.route("/api/mesh/sync/<node_id>/pending", methods=["GET"])
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

    @bridge_bp.route("/api/mesh/sync/<int:sync_id>/ack", methods=["POST"])
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

        get_db_cursor = _get_db_cursor()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    UPDATE mesh_sync_log
                    SET status = %s, acknowledged_at = NOW(), error_message = %s
                    WHERE id = %s AND node_id = %s AND status = 'sent'
                    RETURNING id, acknowledged_at
                    """,
                    (status, error_message, sync_id, node_id),
                )
                row = cur.fetchone()

            if not row:
                return jsonify({"success": False, "error": "Sync not found or already acknowledged"}), 404

            return jsonify(
                {
                    "success": True,
                    "message": "Sync acknowledged",
                    "sync_id": row["id"],
                    "acknowledged_at": row["acknowledged_at"].isoformat() if row["acknowledged_at"] else None,
                }
            )
        except Exception as e:
            logger.error(f"Mesh sync ack failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ========================================================================
    # CLUSTER OVERVIEW
    # ========================================================================

    @bridge_bp.route("/api/mesh/cluster", methods=["GET"])
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

    logger.info("Mesh API routes registered on bridge blueprint")
