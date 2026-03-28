"""Construction industry plugin routes — projects, subcontractors, RFIs, change orders, inspections."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)

MODULE = "industry-construction"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_rfi_number(cur, project_id):
    """Generate the next RFI number: RFI-001, RFI-002, …"""
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM construction_rfis WHERE project_id = %s",
        (project_id,),
    )
    count = cur.fetchone()["cnt"]
    return f"RFI-{count + 1:03d}"


def _next_co_number(cur, project_id):
    """Generate the next change order number: CO-001, CO-002, …"""
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM construction_change_orders WHERE project_id = %s",
        (project_id,),
    )
    count = cur.fetchone()["cnt"]
    return f"CO-{count + 1:03d}"


def register_routes(bp):
    """Attach all Construction plugin routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module(MODULE)
    def index():
        return render_template("construction.html")

    # ------------------------------------------------------------------
    # Projects — list / create
    # ------------------------------------------------------------------

    @bp.route("/api/projects", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_projects():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, project_type, general_contractor, site_supervisor,
                       project_value, completion_percentage, phases, safety_plan,
                       weather_delays, metadata, created_at
                FROM construction_projects
                ORDER BY created_at DESC
                """
            )
            projects = cur.fetchall()
        return jsonify({"projects": projects})

    @bp.route("/api/projects", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_project():
        data = request.get_json(force=True)
        job_id = data.get("job_id")
        project_type = (data.get("project_type") or "commercial").strip()

        if not job_id:
            return jsonify({"error": "job_id is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO construction_projects
                    (job_id, project_type, general_contractor, site_supervisor,
                     project_value, completion_percentage, phases, safety_plan,
                     weather_delays, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, project_type, general_contractor, site_supervisor,
                          project_value, completion_percentage, phases, safety_plan,
                          weather_delays, metadata, created_at
                """,
                (
                    job_id,
                    project_type,
                    data.get("general_contractor"),
                    data.get("site_supervisor"),
                    data.get("project_value"),
                    data.get("completion_percentage", 0),
                    Json(data.get("phases", [])),
                    data.get("safety_plan"),
                    data.get("weather_delays", 0),
                    Json(data.get("metadata", {})),
                ),
            )
            project = cur.fetchone()
        return jsonify(project), 201

    # ------------------------------------------------------------------
    # Projects — single record
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_project(project_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, project_type, general_contractor, site_supervisor,
                       project_value, completion_percentage, phases, safety_plan,
                       weather_delays, metadata, created_at
                FROM construction_projects WHERE id = %s
                """,
                (project_id,),
            )
            project = cur.fetchone()
            if not project:
                return jsonify({"error": "Project not found"}), 404

            cur.execute(
                """
                SELECT id, rfi_number, subject, description, status,
                       submitted_by, response, responded_at, created_at
                FROM construction_rfis WHERE project_id = %s ORDER BY created_at
                """,
                (project_id,),
            )
            project["rfis"] = cur.fetchall()

            cur.execute(
                """
                SELECT id, co_number, description, reason, amount, status,
                       approved_by, approved_at, created_at
                FROM construction_change_orders WHERE project_id = %s ORDER BY created_at
                """,
                (project_id,),
            )
            project["change_orders"] = cur.fetchall()

            cur.execute(
                """
                SELECT id, inspection_type, inspector, scheduled_date,
                       status, notes, created_at
                FROM construction_inspections WHERE project_id = %s ORDER BY created_at
                """,
                (project_id,),
            )
            project["inspections"] = cur.fetchall()

        return jsonify(project)

    @bp.route("/api/projects/<int:project_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_project(project_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_projects WHERE id = %s", (project_id,)
            )
            if not cur.fetchone():
                return jsonify({"error": "Project not found"}), 404

            old_pct = None
            new_pct = data.get("completion_percentage")
            if new_pct is not None:
                cur.execute(
                    "SELECT completion_percentage FROM construction_projects WHERE id = %s",
                    (project_id,),
                )
                old_pct = cur.fetchone()["completion_percentage"]

            cur.execute(
                """
                UPDATE construction_projects SET
                    project_type          = COALESCE(%s, project_type),
                    general_contractor    = COALESCE(%s, general_contractor),
                    site_supervisor       = COALESCE(%s, site_supervisor),
                    project_value         = COALESCE(%s, project_value),
                    completion_percentage = COALESCE(%s, completion_percentage),
                    phases                = COALESCE(%s, phases),
                    safety_plan           = COALESCE(%s, safety_plan),
                    weather_delays        = COALESCE(%s, weather_delays)
                WHERE id = %s
                RETURNING id, job_id, project_type, general_contractor, site_supervisor,
                          project_value, completion_percentage, phases, safety_plan,
                          weather_delays, metadata, created_at
                """,
                (
                    data.get("project_type"),
                    data.get("general_contractor"),
                    data.get("site_supervisor"),
                    data.get("project_value"),
                    new_pct,
                    Json(data["phases"]) if data.get("phases") is not None else None,
                    data.get("safety_plan"),
                    data.get("weather_delays"),
                    project_id,
                ),
            )
            project = cur.fetchone()

        # Emit phase_completed when percentage hits 100
        if (
            new_pct is not None
            and new_pct == 100
            and old_pct is not None
            and old_pct < 100
        ):
            event_bus.emit(
                "project.phase_completed",
                {
                    "project_id": project_id,
                    "completion_percentage": 100,
                    "_tenant_id": g.tenant_id,
                },
            )
        return jsonify(project)

    # ------------------------------------------------------------------
    # Subcontractors
    # ------------------------------------------------------------------

    @bp.route("/api/subcontractors", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_subcontractors():
        active_only = request.args.get("active_only", "false").lower() == "true"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if active_only:
                cur.execute(
                    """
                    SELECT id, company_name, contact_name, phone, email, trade,
                           license_number, insurance_expiry, hourly_rate,
                           rating, is_active, notes, created_at
                    FROM construction_subcontractors
                    WHERE is_active = TRUE
                    ORDER BY company_name
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, company_name, contact_name, phone, email, trade,
                           license_number, insurance_expiry, hourly_rate,
                           rating, is_active, notes, created_at
                    FROM construction_subcontractors
                    ORDER BY company_name
                    """
                )
            subs = cur.fetchall()
        return jsonify({"subcontractors": subs})

    @bp.route("/api/subcontractors", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_subcontractor():
        data = request.get_json(force=True)
        company_name = (data.get("company_name") or "").strip()
        trade = (data.get("trade") or "").strip()
        if not company_name:
            return jsonify({"error": "company_name is required"}), 400
        if not trade:
            return jsonify({"error": "trade is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO construction_subcontractors
                    (company_name, contact_name, phone, email, trade,
                     license_number, insurance_expiry, hourly_rate,
                     rating, is_active, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, company_name, contact_name, phone, email, trade,
                          license_number, insurance_expiry, hourly_rate,
                          rating, is_active, notes, created_at
                """,
                (
                    company_name,
                    data.get("contact_name"),
                    data.get("phone"),
                    data.get("email"),
                    trade,
                    data.get("license_number"),
                    data.get("insurance_expiry"),
                    data.get("hourly_rate"),
                    data.get("rating"),
                    data.get("is_active", True),
                    data.get("notes"),
                ),
            )
            sub = cur.fetchone()
        return jsonify(sub), 201

    @bp.route("/api/subcontractors/<int:sub_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_subcontractor(sub_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_subcontractors WHERE id = %s", (sub_id,)
            )
            if not cur.fetchone():
                return jsonify({"error": "Subcontractor not found"}), 404
            cur.execute(
                """
                UPDATE construction_subcontractors SET
                    company_name     = COALESCE(%s, company_name),
                    contact_name     = COALESCE(%s, contact_name),
                    phone            = COALESCE(%s, phone),
                    email            = COALESCE(%s, email),
                    trade            = COALESCE(%s, trade),
                    license_number   = COALESCE(%s, license_number),
                    insurance_expiry = COALESCE(%s, insurance_expiry),
                    hourly_rate      = COALESCE(%s, hourly_rate),
                    rating           = COALESCE(%s, rating),
                    is_active        = COALESCE(%s, is_active),
                    notes            = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, company_name, contact_name, phone, email, trade,
                          license_number, insurance_expiry, hourly_rate,
                          rating, is_active, notes, created_at
                """,
                (
                    data.get("company_name"),
                    data.get("contact_name"),
                    data.get("phone"),
                    data.get("email"),
                    data.get("trade"),
                    data.get("license_number"),
                    data.get("insurance_expiry"),
                    data.get("hourly_rate"),
                    data.get("rating"),
                    data.get("is_active"),
                    data.get("notes"),
                    sub_id,
                ),
            )
            sub = cur.fetchone()
        return jsonify(sub)

    # ------------------------------------------------------------------
    # RFIs
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/rfis", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def submit_rfi(project_id):
        data = request.get_json(force=True)
        subject = (data.get("subject") or "").strip()
        if not subject:
            return jsonify({"error": "subject is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_projects WHERE id = %s", (project_id,)
            )
            if not cur.fetchone():
                return jsonify({"error": "Project not found"}), 404

            rfi_number = _next_rfi_number(cur, project_id)
            cur.execute(
                """
                INSERT INTO construction_rfis
                    (project_id, rfi_number, subject, description, status, submitted_by)
                VALUES (%s, %s, %s, %s, 'open', %s)
                RETURNING id, project_id, rfi_number, subject, description,
                          status, submitted_by, response, responded_at, created_at
                """,
                (
                    project_id,
                    rfi_number,
                    subject,
                    data.get("description"),
                    data.get("submitted_by"),
                ),
            )
            rfi = cur.fetchone()

        event_bus.emit(
            "rfi.submitted",
            {
                "rfi_id": rfi["id"],
                "rfi_number": rfi["rfi_number"],
                "project_id": project_id,
                "_tenant_id": g.tenant_id,
            },
        )
        return jsonify(rfi), 201

    @bp.route("/api/rfis/<int:rfi_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_rfi(rfi_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM construction_rfis WHERE id = %s", (rfi_id,))
            if not cur.fetchone():
                return jsonify({"error": "RFI not found"}), 404
            cur.execute(
                """
                UPDATE construction_rfis SET
                    status       = COALESCE(%s, status),
                    response     = COALESCE(%s, response),
                    responded_at = CASE
                                       WHEN %s IS NOT NULL THEN NOW()
                                       ELSE responded_at
                                   END
                WHERE id = %s
                RETURNING id, project_id, rfi_number, subject, description,
                          status, submitted_by, response, responded_at, created_at
                """,
                (
                    data.get("status"),
                    data.get("response"),
                    data.get("response"),
                    rfi_id,
                ),
            )
            rfi = cur.fetchone()
        return jsonify(rfi)

    # ------------------------------------------------------------------
    # Change Orders
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/change-orders", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_change_order(project_id):
        data = request.get_json(force=True)
        description = (data.get("description") or "").strip()
        amount = data.get("amount")
        if not description:
            return jsonify({"error": "description is required"}), 400
        if amount is None:
            return jsonify({"error": "amount is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_projects WHERE id = %s", (project_id,)
            )
            if not cur.fetchone():
                return jsonify({"error": "Project not found"}), 404

            co_number = _next_co_number(cur, project_id)
            cur.execute(
                """
                INSERT INTO construction_change_orders
                    (project_id, co_number, description, reason, amount, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                RETURNING id, project_id, co_number, description, reason, amount,
                          status, approved_by, approved_at, created_at
                """,
                (
                    project_id,
                    co_number,
                    description,
                    data.get("reason"),
                    amount,
                ),
            )
            co = cur.fetchone()
        return jsonify(co), 201

    @bp.route("/api/change-orders/<int:co_id>/approve", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def approve_change_order(co_id):
        data = request.get_json(force=True) or {}
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_change_orders WHERE id = %s", (co_id,)
            )
            if not cur.fetchone():
                return jsonify({"error": "Change order not found"}), 404
            cur.execute(
                """
                UPDATE construction_change_orders SET
                    status      = 'approved',
                    approved_by = %s,
                    approved_at = NOW()
                WHERE id = %s
                RETURNING id, project_id, co_number, description, reason, amount,
                          status, approved_by, approved_at, created_at
                """,
                (data.get("approved_by"), co_id),
            )
            co = cur.fetchone()

        event_bus.emit(
            "change_order.approved",
            {
                "change_order_id": co_id,
                "co_number": co["co_number"],
                "project_id": co["project_id"],
                "amount": float(co["amount"]),
                "_tenant_id": g.tenant_id,
            },
        )
        return jsonify(co)

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/inspections", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def schedule_inspection(project_id):
        data = request.get_json(force=True)
        inspection_type = (data.get("inspection_type") or "").strip()
        if not inspection_type:
            return jsonify({"error": "inspection_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_projects WHERE id = %s", (project_id,)
            )
            if not cur.fetchone():
                return jsonify({"error": "Project not found"}), 404
            cur.execute(
                """
                INSERT INTO construction_inspections
                    (project_id, inspection_type, inspector, scheduled_date, status, notes)
                VALUES (%s, %s, %s, %s, 'scheduled', %s)
                RETURNING id, project_id, inspection_type, inspector,
                          scheduled_date, status, notes, created_at
                """,
                (
                    project_id,
                    inspection_type,
                    data.get("inspector"),
                    data.get("scheduled_date"),
                    data.get("notes"),
                ),
            )
            inspection = cur.fetchone()
        return jsonify(inspection), 201

    @bp.route("/api/inspections/<int:inspection_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE)
    def update_inspection(inspection_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id FROM construction_inspections WHERE id = %s",
                (inspection_id,),
            )
            if not cur.fetchone():
                return jsonify({"error": "Inspection not found"}), 404
            cur.execute(
                """
                UPDATE construction_inspections SET
                    inspection_type = COALESCE(%s, inspection_type),
                    inspector       = COALESCE(%s, inspector),
                    scheduled_date  = COALESCE(%s, scheduled_date),
                    status          = COALESCE(%s, status),
                    notes           = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, project_id, inspection_type, inspector,
                          scheduled_date, status, notes, created_at
                """,
                (
                    data.get("inspection_type"),
                    data.get("inspector"),
                    data.get("scheduled_date"),
                    data.get("status"),
                    data.get("notes"),
                    inspection_id,
                ),
            )
            inspection = cur.fetchone()
        return jsonify(inspection)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE cp.completion_percentage < 100) AS active_projects,
                    COALESCE(SUM(cp.project_value), 0)                     AS total_project_value
                FROM construction_projects cp
                """
            )
            proj_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS pending_rfis FROM construction_rfis WHERE status = 'open'"
            )
            rfi_stats = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) AS pending_change_orders
                FROM construction_change_orders
                WHERE status = 'pending'
                """
            )
            co_stats = cur.fetchone()

        return jsonify(
            {
                "active_projects": proj_stats["active_projects"],
                "total_project_value": float(proj_stats["total_project_value"]),
                "pending_rfis": rfi_stats["pending_rfis"],
                "pending_change_orders": co_stats["pending_change_orders"],
            }
        )

    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def ask_ai():
        """Ask the Construction AI agent a question with optional context."""
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="construction",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code


# ---------------------------------------------------------------------------
# Event consumers
# ---------------------------------------------------------------------------

def on_job_created(data):
    """No-op placeholder — reserved for auto-creating a construction project on job.created."""
    pass


def on_job_completed(data):
    """No-op placeholder — reserved for marking a construction project complete on job.completed."""
    pass
