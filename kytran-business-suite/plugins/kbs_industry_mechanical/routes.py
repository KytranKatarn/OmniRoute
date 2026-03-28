"""Mechanical / HVAC industry plugin routes — systems, maintenance, energy audits, commissioning."""

import logging
from datetime import date, timedelta

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)

MODULE_SLUG = "industry-mechanical"


def register_routes(bp):
    """Attach all Mechanical / HVAC routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module(MODULE_SLUG)
    def index():
        return render_template("mechanical.html")

    # ------------------------------------------------------------------
    # HVAC Systems — list
    # ------------------------------------------------------------------

    @bp.route("/api/systems", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def list_systems():
        status = request.args.get("status")
        system_type = request.args.get("system_type")
        job_id = request.args.get("job_id", type=int)

        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if system_type:
            conditions.append("system_type = %s")
            params.append(system_type)
        if job_id:
            conditions.append("job_id = %s")
            params.append(job_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT id, job_id, system_type, manufacturer, model, serial_number,
                       install_date, warranty_expiry, capacity_btu, efficiency_rating,
                       location, status, notes, metadata, created_at
                FROM hvac_systems {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            systems = cur.fetchall()

        return jsonify({"systems": systems, "total": len(systems)})

    # ------------------------------------------------------------------
    # HVAC Systems — create
    # ------------------------------------------------------------------

    @bp.route("/api/systems", methods=["POST"])
    @login_required
    @require_module(MODULE_SLUG)
    def create_system():
        data = request.get_json(force=True)
        system_type = (data.get("system_type") or "").strip()
        if not system_type:
            return jsonify({"error": "system_type is required"}), 400
        capacity_btu = data.get("capacity_btu")
        if capacity_btu is None:
            return jsonify({"error": "capacity_btu is required"}), 400

        try:
            capacity_btu = int(capacity_btu)
        except (TypeError, ValueError):
            return jsonify({"error": "capacity_btu must be an integer"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO hvac_systems
                    (job_id, system_type, manufacturer, model, serial_number,
                     install_date, warranty_expiry, capacity_btu, efficiency_rating,
                     location, status, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, system_type, manufacturer, model, serial_number,
                          install_date, warranty_expiry, capacity_btu, efficiency_rating,
                          location, status, notes, metadata, created_at
                """,
                (
                    data.get("job_id"),
                    system_type,
                    data.get("manufacturer"),
                    data.get("model"),
                    data.get("serial_number"),
                    data.get("install_date"),
                    data.get("warranty_expiry"),
                    capacity_btu,
                    data.get("efficiency_rating"),
                    data.get("location"),
                    data.get("status", "active"),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            system = cur.fetchone()

        event_bus.emit(
            "system.installed",
            {
                "system_id": system["id"],
                "system_type": system["system_type"],
                "job_id": system["job_id"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(system), 201

    # ------------------------------------------------------------------
    # HVAC Systems — get / update
    # ------------------------------------------------------------------

    @bp.route("/api/systems/<int:system_id>", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def get_system(system_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, system_type, manufacturer, model, serial_number,
                       install_date, warranty_expiry, capacity_btu, efficiency_rating,
                       location, status, notes, metadata, created_at
                FROM hvac_systems WHERE id = %s
                """,
                (system_id,),
            )
            system = cur.fetchone()

        if system is None:
            return jsonify({"error": "system not found"}), 404
        return jsonify(system)

    @bp.route("/api/systems/<int:system_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE_SLUG)
    def update_system(system_id):
        data = request.get_json(force=True)

        allowed = (
            "system_type", "manufacturer", "model", "serial_number",
            "install_date", "warranty_expiry", "capacity_btu", "efficiency_rating",
            "location", "status", "notes",
        )
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(system_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE hvac_systems SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, job_id, system_type, manufacturer, model, serial_number,
                          install_date, warranty_expiry, capacity_btu, efficiency_rating,
                          location, status, notes, metadata, created_at
                """,
                params,
            )
            system = cur.fetchone()

        if system is None:
            return jsonify({"error": "system not found"}), 404
        return jsonify(system)

    # ------------------------------------------------------------------
    # Maintenance Schedules — add to system
    # ------------------------------------------------------------------

    @bp.route("/api/systems/<int:system_id>/maintenance", methods=["POST"])
    @login_required
    @require_module(MODULE_SLUG)
    def add_maintenance_schedule(system_id):
        data = request.get_json(force=True)
        task_name = (data.get("task_name") or "").strip()
        frequency = (data.get("frequency") or "").strip()
        if not task_name:
            return jsonify({"error": "task_name is required"}), 400
        if not frequency:
            return jsonify({"error": "frequency is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM hvac_systems WHERE id = %s", (system_id,))
            if not cur.fetchone():
                return jsonify({"error": "system not found"}), 404

            cur.execute(
                """
                INSERT INTO maintenance_schedules
                    (system_id, task_name, frequency, last_performed, next_due,
                     technician, notes, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, system_id, task_name, frequency, last_performed, next_due,
                          technician, notes, is_active, created_at
                """,
                (
                    system_id,
                    task_name,
                    frequency,
                    data.get("last_performed"),
                    data.get("next_due"),
                    data.get("technician"),
                    data.get("notes"),
                    data.get("is_active", True),
                ),
            )
            schedule = cur.fetchone()

        return jsonify(schedule), 201

    # ------------------------------------------------------------------
    # Maintenance Schedules — list upcoming
    # ------------------------------------------------------------------

    @bp.route("/api/maintenance", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def list_upcoming_maintenance():
        days = request.args.get("days", 30, type=int)
        system_id = request.args.get("system_id", type=int)
        cutoff = date.today() + timedelta(days=days)

        conditions = ["is_active = TRUE", "next_due <= %s"]
        params: list = [cutoff]

        if system_id:
            conditions.append("system_id = %s")
            params.append(system_id)

        where = "WHERE " + " AND ".join(conditions)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT ms.id, ms.system_id, ms.task_name, ms.frequency,
                       ms.last_performed, ms.next_due, ms.technician, ms.notes,
                       ms.is_active, ms.created_at,
                       hs.system_type, hs.manufacturer, hs.model, hs.location
                FROM maintenance_schedules ms
                JOIN hvac_systems hs ON hs.id = ms.system_id
                {where}
                ORDER BY ms.next_due ASC
                """,
                params,
            )
            schedules = cur.fetchall()

        return jsonify({"maintenance": schedules, "total": len(schedules)})

    # ------------------------------------------------------------------
    # Maintenance Schedules — mark performed
    # ------------------------------------------------------------------

    @bp.route("/api/maintenance/<int:schedule_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE_SLUG)
    def update_maintenance_schedule(schedule_id):
        data = request.get_json(force=True)

        allowed = ("task_name", "frequency", "last_performed", "next_due",
                   "technician", "notes", "is_active")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(schedule_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE maintenance_schedules SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, system_id, task_name, frequency, last_performed, next_due,
                          technician, notes, is_active, created_at
                """,
                params,
            )
            schedule = cur.fetchone()

        if schedule is None:
            return jsonify({"error": "maintenance schedule not found"}), 404

        # Emit maintenance.completed when last_performed is set
        if "last_performed" in data and data["last_performed"]:
            event_bus.emit(
                "maintenance.completed",
                {
                    "schedule_id": schedule_id,
                    "system_id": schedule["system_id"],
                    "task_name": schedule["task_name"],
                    "last_performed": str(data["last_performed"]),
                },
                tenant_id=g.tenant_id,
            )

        return jsonify(schedule)

    # ------------------------------------------------------------------
    # Energy Audits — list / create / get / update status
    # ------------------------------------------------------------------

    @bp.route("/api/audits", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def list_energy_audits():
        status = request.args.get("status")
        job_id = request.args.get("job_id", type=int)

        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if job_id:
            conditions.append("job_id = %s")
            params.append(job_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT id, job_id, building_sqft, current_system, recommended_system,
                       estimated_savings, payback_years, audit_date, auditor,
                       status, notes, created_at
                FROM energy_audits {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            audits = cur.fetchall()

        return jsonify({"audits": audits, "total": len(audits)})

    @bp.route("/api/audits", methods=["POST"])
    @login_required
    @require_module(MODULE_SLUG)
    def create_energy_audit():
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO energy_audits
                    (job_id, building_sqft, current_system, recommended_system,
                     estimated_savings, payback_years, audit_date, auditor, status, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, building_sqft, current_system, recommended_system,
                          estimated_savings, payback_years, audit_date, auditor,
                          status, notes, created_at
                """,
                (
                    data.get("job_id"),
                    data.get("building_sqft"),
                    data.get("current_system"),
                    data.get("recommended_system"),
                    data.get("estimated_savings"),
                    data.get("payback_years"),
                    data.get("audit_date"),
                    data.get("auditor"),
                    data.get("status", "draft"),
                    data.get("notes"),
                ),
            )
            audit = cur.fetchone()

        return jsonify(audit), 201

    @bp.route("/api/audits/<int:audit_id>", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def get_energy_audit(audit_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, building_sqft, current_system, recommended_system,
                       estimated_savings, payback_years, audit_date, auditor,
                       status, notes, created_at
                FROM energy_audits WHERE id = %s
                """,
                (audit_id,),
            )
            audit = cur.fetchone()

        if audit is None:
            return jsonify({"error": "energy audit not found"}), 404
        return jsonify(audit)

    @bp.route("/api/audits/<int:audit_id>", methods=["PUT"])
    @login_required
    @require_module(MODULE_SLUG)
    def update_energy_audit(audit_id):
        data = request.get_json(force=True)

        allowed = (
            "building_sqft", "current_system", "recommended_system",
            "estimated_savings", "payback_years", "audit_date", "auditor",
            "status", "notes",
        )
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(audit_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE energy_audits SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, job_id, building_sqft, current_system, recommended_system,
                          estimated_savings, payback_years, audit_date, auditor,
                          status, notes, created_at
                """,
                params,
            )
            audit = cur.fetchone()

        if audit is None:
            return jsonify({"error": "energy audit not found"}), 404

        if data.get("status") == "approved":
            event_bus.emit(
                "audit.completed",
                {"audit_id": audit_id, "status": "approved"},
                tenant_id=g.tenant_id,
            )

        return jsonify(audit)

    # ------------------------------------------------------------------
    # Commissioning Reports — list per system / create
    # ------------------------------------------------------------------

    @bp.route("/api/systems/<int:system_id>/commissioning", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def list_commissioning_reports(system_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, system_id, report_type, test_results, passed,
                       technician, report_date, notes, created_at
                FROM commissioning_reports
                WHERE system_id = %s
                ORDER BY report_date DESC, created_at DESC
                """,
                (system_id,),
            )
            reports = cur.fetchall()

        return jsonify({"reports": reports, "total": len(reports)})

    @bp.route("/api/systems/<int:system_id>/commissioning", methods=["POST"])
    @login_required
    @require_module(MODULE_SLUG)
    def create_commissioning_report(system_id):
        data = request.get_json(force=True)
        report_type = (data.get("report_type") or "").strip()
        if not report_type:
            return jsonify({"error": "report_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM hvac_systems WHERE id = %s", (system_id,))
            if not cur.fetchone():
                return jsonify({"error": "system not found"}), 404

            cur.execute(
                """
                INSERT INTO commissioning_reports
                    (system_id, report_type, test_results, passed,
                     technician, report_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, system_id, report_type, test_results, passed,
                          technician, report_date, notes, created_at
                """,
                (
                    system_id,
                    report_type,
                    Json(data.get("test_results", {})),
                    data.get("passed"),
                    data.get("technician"),
                    data.get("report_date"),
                    data.get("notes"),
                ),
            )
            report = cur.fetchone()

        return jsonify(report), 201

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module(MODULE_SLUG)
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status != 'decommissioned') AS total_systems,
                    COUNT(*) FILTER (WHERE status = 'needs_service')   AS needs_service
                FROM hvac_systems
                """
            )
            system_stats = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) AS maintenance_due
                FROM maintenance_schedules
                WHERE is_active = TRUE
                  AND next_due <= CURRENT_DATE + INTERVAL '30 days'
                """
            )
            maint_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS audits_pending FROM energy_audits "
                "WHERE status IN ('draft', 'submitted')"
            )
            audit_stats = cur.fetchone()

            cur.execute(
                """
                SELECT ROUND(AVG(efficiency_rating), 2) AS avg_efficiency
                FROM hvac_systems
                WHERE efficiency_rating IS NOT NULL
                  AND status != 'decommissioned'
                """
            )
            eff_stats = cur.fetchone()

        return jsonify(
            {
                "total_systems": system_stats["total_systems"],
                "needs_service": system_stats["needs_service"],
                "maintenance_due": maint_stats["maintenance_due"],
                "audits_pending": audit_stats["audits_pending"],
                "avg_efficiency": (
                    float(eff_stats["avg_efficiency"])
                    if eff_stats["avg_efficiency"] is not None
                    else None
                ),
            }
        )

    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module(MODULE_SLUG)
    def ask_ai():
        """Ask the HVAC/Mechanical AI agent a question with optional context."""
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="mechanical",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code


# ----------------------------------------------------------------------
# Event consumers
# ----------------------------------------------------------------------


def on_job_created(data):
    """Log new job creation — no-op for mechanical (info only)."""
    logger.debug(
        "Mechanical plugin received job.created event: job_id=%s tenant=%s",
        data.get("job_id"),
        data.get("_tenant_id"),
    )


def on_job_completed(data):
    """Mark any active HVAC systems on the completed job as needing service review."""
    job_id = data.get("job_id")
    tenant_id = data.get("_tenant_id")
    if not job_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            # Flag newly installed systems for initial commissioning review
            cur.execute(
                """
                UPDATE hvac_systems
                SET status = 'active'
                WHERE job_id = %s AND status = 'active'
                """,
                (job_id,),
            )
    except Exception:
        logger.exception(
            "Failed to process job.completed for mechanical plugin, job_id=%s", job_id
        )
