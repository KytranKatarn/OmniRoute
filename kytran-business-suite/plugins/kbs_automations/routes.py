"""Automations plugin routes — workflow template CRUD + execution history + stats."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Automations routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("automations")
    def index():
        return render_template("automations.html")

    # ------------------------------------------------------------------
    # Workflow Templates — CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/workflows", methods=["GET"])
    @login_required
    @require_module("automations")
    def list_workflows():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, trigger_event, conditions, actions,
                       is_active, created_at, updated_at
                FROM workflow_templates
                ORDER BY created_at DESC
                """
            )
            workflows = cur.fetchall()
        return jsonify({"workflows": workflows})

    @bp.route("/api/workflows", methods=["POST"])
    @login_required
    @require_module("automations")
    def create_workflow():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        trigger_event = (data.get("trigger_event") or "").strip()

        if not name:
            return jsonify({"error": "name is required"}), 400
        if not trigger_event:
            return jsonify({"error": "trigger_event is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO workflow_templates
                    (name, description, trigger_event, conditions, actions, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, description, trigger_event, conditions, actions,
                          is_active, created_at, updated_at
                """,
                (
                    name,
                    data.get("description"),
                    trigger_event,
                    Json(data.get("conditions") or {}),
                    Json(data.get("actions") or []),
                    data.get("is_active", True),
                ),
            )
            workflow = cur.fetchone()

        return jsonify(workflow), 201

    @bp.route("/api/workflows/<int:workflow_id>", methods=["GET"])
    @login_required
    @require_module("automations")
    def get_workflow(workflow_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, trigger_event, conditions, actions,
                       is_active, created_at, updated_at
                FROM workflow_templates WHERE id = %s
                """,
                (workflow_id,),
            )
            workflow = cur.fetchone()

        if workflow is None:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify(workflow)

    @bp.route("/api/workflows/<int:workflow_id>", methods=["PUT"])
    @login_required
    @require_module("automations")
    def update_workflow(workflow_id):
        data = request.get_json(force=True)

        allowed_scalar = ("name", "description", "trigger_event")
        sets = []
        params = []

        for field in allowed_scalar:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if "conditions" in data:
            sets.append("conditions = %s")
            params.append(Json(data["conditions"]))
        if "actions" in data:
            sets.append("actions = %s")
            params.append(Json(data["actions"]))
        if "is_active" in data:
            sets.append("is_active = %s")
            params.append(bool(data["is_active"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(workflow_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE workflow_templates SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, description, trigger_event, conditions, actions,
                          is_active, created_at, updated_at
                """,
                params,
            )
            workflow = cur.fetchone()

        if workflow is None:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify(workflow)

    @bp.route("/api/workflows/<int:workflow_id>", methods=["DELETE"])
    @login_required
    @require_module("automations")
    def delete_workflow(workflow_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM workflow_templates WHERE id = %s RETURNING id, name",
                (workflow_id,),
            )
            deleted = cur.fetchone()

        if deleted is None:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify({"deleted": True, "id": deleted["id"], "name": deleted["name"]})

    # ------------------------------------------------------------------
    # Execution History
    # ------------------------------------------------------------------

    @bp.route("/api/workflows/<int:workflow_id>/executions", methods=["GET"])
    @login_required
    @require_module("automations")
    def list_executions(workflow_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, template_id, trigger_event, event_data, status,
                       result, started_at, completed_at, error_message
                FROM workflow_executions
                WHERE template_id = %s
                ORDER BY started_at DESC
                LIMIT 100
                """,
                (workflow_id,),
            )
            executions = cur.fetchall()
        return jsonify({"executions": executions})

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("automations")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_workflows,
                    COUNT(*) FILTER (WHERE is_active = TRUE) AS active_workflows
                FROM workflow_templates
                """
            )
            wf_row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_executions,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed_executions,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_executions
                FROM workflow_executions
                """
            )
            ex_row = cur.fetchone()

        total_ex = ex_row["total_executions"] or 0
        completed_ex = ex_row["completed_executions"] or 0
        success_rate = round(completed_ex / total_ex * 100, 1) if total_ex > 0 else 0.0

        return jsonify(
            {
                "total_workflows": wf_row["total_workflows"],
                "active_workflows": wf_row["active_workflows"],
                "total_executions": total_ex,
                "success_rate": success_rate,
            }
        )
