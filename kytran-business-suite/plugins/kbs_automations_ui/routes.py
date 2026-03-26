"""Automations UI plugin routes — visual workflow builder, categories, logs, dry-run testing."""

import logging

from flask import current_app, g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Automations UI routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("automations-ui")
    def index():
        return render_template("automations_ui.html")

    # ------------------------------------------------------------------
    # Workflow Builder — reads/writes workflow_templates (automations plugin)
    # ------------------------------------------------------------------

    @bp.route("/api/workflows", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def list_workflows():
        """List all workflows with execution stats."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    wt.id,
                    wt.name,
                    wt.description,
                    wt.trigger_event,
                    wt.conditions,
                    wt.actions,
                    wt.is_active,
                    wt.created_at,
                    wt.updated_at,
                    COUNT(we.id)                                         AS total_executions,
                    COUNT(we.id) FILTER (WHERE we.status = 'completed')  AS successful_executions,
                    COUNT(we.id) FILTER (WHERE we.status = 'failed')     AS failed_executions,
                    MAX(we.started_at)                                   AS last_run_at
                FROM workflow_templates wt
                LEFT JOIN workflow_executions we ON we.template_id = wt.id
                GROUP BY wt.id
                ORDER BY wt.created_at DESC
                """
            )
            workflows = cur.fetchall()
        return jsonify({"workflows": workflows})

    @bp.route("/api/workflows/<int:workflow_id>", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def get_workflow(workflow_id):
        """Get a single workflow with config and recent executions."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, trigger_event, conditions, actions,
                       is_active, created_at, updated_at
                FROM workflow_templates
                WHERE id = %s
                """,
                (workflow_id,),
            )
            workflow = cur.fetchone()

        if workflow is None:
            return jsonify({"error": "workflow not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, trigger_event, status, result, started_at, completed_at, error_message
                FROM workflow_executions
                WHERE template_id = %s
                ORDER BY started_at DESC
                LIMIT 20
                """,
                (workflow_id,),
            )
            executions = cur.fetchall()

        workflow["recent_executions"] = executions
        return jsonify(workflow)

    @bp.route("/api/workflows", methods=["POST"])
    @login_required
    @require_module("automations-ui")
    def create_workflow():
        """Create a workflow from visual builder data."""
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

    @bp.route("/api/workflows/<int:workflow_id>", methods=["PUT"])
    @login_required
    @require_module("automations-ui")
    def update_workflow(workflow_id):
        """Update a workflow."""
        data = request.get_json(force=True)

        allowed_scalar = ["name", "description", "trigger_event"]
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

    @bp.route("/api/workflows/<int:workflow_id>/toggle", methods=["POST"])
    @login_required
    @require_module("automations-ui")
    def toggle_workflow(workflow_id):
        """Toggle workflow active/inactive."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE workflow_templates
                SET is_active = NOT is_active, updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, is_active
                """,
                (workflow_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify({"id": row["id"], "name": row["name"], "is_active": row["is_active"]})

    @bp.route("/api/workflows/<int:workflow_id>/test", methods=["POST"])
    @login_required
    @require_module("automations-ui")
    def test_workflow(workflow_id):
        """Dry-run: evaluate conditions against sample data without executing actions."""
        data = request.get_json(force=True)
        sample_event_data = data.get("event_data") or {}

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, trigger_event, conditions, actions, is_active
                FROM workflow_templates
                WHERE id = %s
                """,
                (workflow_id,),
            )
            workflow = cur.fetchone()

        if workflow is None:
            return jsonify({"error": "workflow not found"}), 404

        from plugins.kbs_automations.engine import evaluate_conditions

        conditions = workflow.get("conditions") or {}
        actions = workflow.get("actions") or []

        conditions_pass = evaluate_conditions(conditions, sample_event_data)

        return jsonify(
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow["name"],
                "trigger_event": workflow["trigger_event"],
                "is_active": workflow["is_active"],
                "conditions_pass": conditions_pass,
                "conditions_evaluated": conditions,
                "actions_that_would_run": actions if conditions_pass else [],
                "action_count": len(actions) if conditions_pass else 0,
                "sample_event_data": sample_event_data,
                "dry_run": True,
            }
        )

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    @bp.route("/api/categories", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def list_categories():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, name, description, color, sort_order, created_at FROM workflow_categories ORDER BY sort_order, name"
            )
            categories = cur.fetchall()
        return jsonify({"categories": categories})

    @bp.route("/api/categories", methods=["POST"])
    @login_required
    @require_module("automations-ui")
    def create_category():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO workflow_categories (name, description, color, sort_order)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, description, color, sort_order, created_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("color", "#00e5ff"),
                    data.get("sort_order", 0),
                ),
            )
            category = cur.fetchone()
        return jsonify(category), 201

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    @bp.route("/api/logs", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def list_logs():
        """Recent workflow logs across all workflows, optional level filter."""
        level = request.args.get("level")
        limit = request.args.get("limit", 100, type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ""
            params: list = [limit]
            if level:
                where = "WHERE level = %s"
                params = [level, limit]

            cur.execute(
                f"""
                SELECT id, execution_id, workflow_name, event_type, message, level, created_at
                FROM workflow_logs
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            logs = cur.fetchall()
        return jsonify({"logs": logs})

    @bp.route("/api/workflows/<int:workflow_id>/logs", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def workflow_logs(workflow_id):
        """Logs for a specific workflow (matched via workflow_name from workflow_templates)."""
        limit = request.args.get("limit", 50, type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            # First resolve workflow name
            cur.execute(
                "SELECT name FROM workflow_templates WHERE id = %s",
                (workflow_id,),
            )
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "workflow not found"}), 404

        workflow_name = row["name"]

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, execution_id, workflow_name, event_type, message, level, created_at
                FROM workflow_logs
                WHERE workflow_name = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (workflow_name, limit),
            )
            logs = cur.fetchall()
        return jsonify({"workflow_id": workflow_id, "workflow_name": workflow_name, "logs": logs})

    # ------------------------------------------------------------------
    # Available events + actions (for the builder UI)
    # ------------------------------------------------------------------

    @bp.route("/api/available-events", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def available_events():
        """Scan all loaded plugin manifests for their emitted events."""
        plugins = current_app.extensions.get("kbs_plugins", {})
        events = []
        for slug, meta in plugins.items():
            manifest = meta.get("manifest", {})
            for event in manifest.get("emits", []):
                events.append({"event": event, "source": slug})
        # Add wildcard entry for convenience
        events.append({"event": "*", "source": "system", "description": "Any event"})
        return jsonify({"events": events})

    @bp.route("/api/available-actions", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def available_actions():
        """Return the list of supported action types."""
        actions = [
            {
                "type": "log",
                "label": "Log Message",
                "description": "Write a message to the automation log",
                "config_schema": {
                    "message": {"type": "string", "label": "Message", "required": True}
                },
            },
            {
                "type": "create_interaction",
                "label": "Create CRM Interaction",
                "description": "Log an interaction against a CRM contact",
                "config_schema": {
                    "interaction_type": {
                        "type": "select",
                        "label": "Interaction Type",
                        "options": ["email", "call", "meeting", "note", "order", "invoice", "support", "other"],
                        "default": "note",
                    },
                    "subject": {"type": "string", "label": "Subject"},
                    "content": {"type": "text", "label": "Content"},
                },
            },
            {
                "type": "send_email",
                "label": "Send Email",
                "description": "Send a notification email",
                "config_schema": {
                    "to": {"type": "string", "label": "To Address", "required": True},
                    "subject": {"type": "string", "label": "Subject", "required": True},
                    "body": {"type": "text", "label": "Body", "required": True},
                },
            },
            {
                "type": "webhook",
                "label": "HTTP Webhook",
                "description": "POST event data to an external URL",
                "config_schema": {
                    "url": {"type": "string", "label": "Webhook URL", "required": True},
                    "headers": {"type": "object", "label": "Custom Headers"},
                },
            },
        ]
        return jsonify({"actions": actions})

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("automations-ui")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*)                                              AS total_workflows,
                    COUNT(*) FILTER (WHERE is_active = TRUE)             AS active_workflows,
                    COUNT(*) FILTER (WHERE is_active = FALSE)            AS inactive_workflows
                FROM workflow_templates
                """
            )
            wf_row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*)                                              AS total_executions,
                    COUNT(*) FILTER (WHERE status = 'completed')         AS successful_executions,
                    COUNT(*) FILTER (WHERE status = 'failed')            AS failed_executions,
                    COUNT(*) FILTER (WHERE status = 'running')           AS running_executions
                FROM workflow_executions
                """
            )
            ex_row = cur.fetchone()

        total_exec = ex_row["total_executions"] or 0
        successful = ex_row["successful_executions"] or 0
        success_rate = round((successful / total_exec * 100), 1) if total_exec > 0 else 0.0

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT we.template_id, wt.name, we.error_message, we.started_at
                FROM workflow_executions we
                JOIN workflow_templates wt ON wt.id = we.template_id
                WHERE we.status = 'failed'
                ORDER BY we.started_at DESC
                LIMIT 5
                """
            )
            recent_failures = cur.fetchall()

        return jsonify(
            {
                "total_workflows": wf_row["total_workflows"],
                "active_workflows": wf_row["active_workflows"],
                "inactive_workflows": wf_row["inactive_workflows"],
                "total_executions": total_exec,
                "successful_executions": successful,
                "failed_executions": ex_row["failed_executions"],
                "running_executions": ex_row["running_executions"],
                "success_rate": success_rate,
                "recent_failures": recent_failures,
            }
        )
