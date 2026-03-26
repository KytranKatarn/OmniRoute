"""Industry Framework plugin routes — config, jobs, items, notes, permits, opportunities."""

import logging
from datetime import date, datetime

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def _next_job_number(cur):
    """Generate the next sequential job number: JOB-0001, JOB-0002, …"""
    cur.execute("SELECT COUNT(*) AS cnt FROM jobs")
    count = cur.fetchone()["cnt"]
    return f"JOB-{count + 1:04d}"


def register_routes(bp):
    """Attach all Industry Framework routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("industry")
    def index():
        return render_template("industry.html")

    # ------------------------------------------------------------------
    # Industry Config
    # ------------------------------------------------------------------

    @bp.route("/api/config", methods=["GET"])
    @login_required
    @require_module("industry")
    def get_config():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, industry_type, company_license, license_expiry,
                       insurance_info, certifications, service_area, settings,
                       created_at, updated_at
                FROM industry_config
                LIMIT 1
                """
            )
            row = cur.fetchone()
        return jsonify(row or {})

    @bp.route("/api/config", methods=["POST"])
    @login_required
    @require_module("industry")
    def set_config():
        data = request.get_json(force=True)
        industry_type = (data.get("industry_type") or "").strip()
        if not industry_type:
            return jsonify({"error": "industry_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM industry_config LIMIT 1")
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE industry_config
                    SET industry_type   = %s,
                        company_license = %s,
                        license_expiry  = %s,
                        insurance_info  = %s,
                        certifications  = %s,
                        service_area    = %s,
                        settings        = %s,
                        updated_at      = NOW()
                    WHERE id = %s
                    RETURNING id, industry_type, company_license, license_expiry,
                              insurance_info, certifications, service_area, settings,
                              created_at, updated_at
                    """,
                    (
                        industry_type,
                        data.get("company_license"),
                        data.get("license_expiry"),
                        Json(data.get("insurance_info", {})),
                        Json(data.get("certifications", [])),
                        data.get("service_area"),
                        Json(data.get("settings", {})),
                        existing["id"],
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO industry_config
                        (industry_type, company_license, license_expiry,
                         insurance_info, certifications, service_area, settings)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, industry_type, company_license, license_expiry,
                              insurance_info, certifications, service_area, settings,
                              created_at, updated_at
                    """,
                    (
                        industry_type,
                        data.get("company_license"),
                        data.get("license_expiry"),
                        Json(data.get("insurance_info", {})),
                        Json(data.get("certifications", [])),
                        data.get("service_area"),
                        Json(data.get("settings", {})),
                    ),
                )
            row = cur.fetchone()
        return jsonify(row), 200

    # ------------------------------------------------------------------
    # Jobs — list / create
    # ------------------------------------------------------------------

    @bp.route("/api/jobs", methods=["GET"])
    @login_required
    @require_module("industry")
    def list_jobs():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        job_type = request.args.get("job_type")
        assigned_to = request.args.get("assigned_to")
        offset = (page - 1) * per_page

        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if job_type:
            conditions.append("job_type = %s")
            params.append(job_type)
        if assigned_to:
            conditions.append("assigned_to = %s")
            params.append(assigned_to)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(f"SELECT COUNT(*) AS cnt FROM jobs {where}", params)
            total = cur.fetchone()["cnt"]
            cur.execute(
                f"""
                SELECT id, job_number, customer_id, title, job_type, status, priority,
                       estimated_cost, actual_cost, start_date, end_date, completion_date,
                       site_address, assigned_to, tags, created_at, updated_at
                FROM jobs {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            jobs = cur.fetchall()
        return jsonify({"jobs": jobs, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/jobs", methods=["POST"])
    @login_required
    @require_module("industry")
    def create_job():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            job_number = _next_job_number(cur)
            cur.execute(
                """
                INSERT INTO jobs
                    (job_number, customer_id, title, description, job_type, status, priority,
                     estimated_cost, estimated_hours, start_date, end_date,
                     site_address, site_notes, assigned_to, tags, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_number, customer_id, title, description, job_type, status,
                          priority, estimated_cost, actual_cost, estimated_hours, actual_hours,
                          start_date, end_date, completion_date, site_address, site_notes,
                          assigned_to, tags, metadata, created_at, updated_at
                """,
                (
                    job_number,
                    data.get("customer_id"),
                    title,
                    data.get("description"),
                    data.get("job_type", "service"),
                    data.get("status", "quoted"),
                    data.get("priority", "normal"),
                    data.get("estimated_cost"),
                    data.get("estimated_hours"),
                    data.get("start_date"),
                    data.get("end_date"),
                    data.get("site_address"),
                    data.get("site_notes"),
                    data.get("assigned_to"),
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            job = cur.fetchone()

        event_bus.emit("job.created", {"job_id": job["id"], "job_number": job["job_number"],
                                        "title": job["title"], "_tenant_id": g.tenant_id})
        return jsonify(job), 201

    # ------------------------------------------------------------------
    # Jobs — single record
    # ------------------------------------------------------------------

    @bp.route("/api/jobs/<int:job_id>", methods=["GET"])
    @login_required
    @require_module("industry")
    def get_job(job_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_number, customer_id, title, description, job_type, status,
                       priority, estimated_cost, actual_cost, estimated_hours, actual_hours,
                       start_date, end_date, completion_date, site_address, site_notes,
                       assigned_to, tags, metadata, created_at, updated_at
                FROM jobs WHERE id = %s
                """,
                (job_id,),
            )
            job = cur.fetchone()
        if not job:
            return jsonify({"error": "Job not found"}), 404

        # Attach items and notes inline
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, item_type, description, quantity, unit_price, total, notes, created_at"
                " FROM job_items WHERE job_id = %s ORDER BY id",
                (job_id,),
            )
            job["items"] = cur.fetchall()
            cur.execute(
                "SELECT id, author, content, note_type, attachments, created_at"
                " FROM job_notes WHERE job_id = %s ORDER BY created_at",
                (job_id,),
            )
            job["notes"] = cur.fetchall()
        return jsonify(job)

    @bp.route("/api/jobs/<int:job_id>", methods=["PUT"])
    @login_required
    @require_module("industry")
    def update_job(job_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
            if not cur.fetchone():
                return jsonify({"error": "Job not found"}), 404
            cur.execute(
                """
                UPDATE jobs SET
                    title           = COALESCE(%s, title),
                    description     = COALESCE(%s, description),
                    job_type        = COALESCE(%s, job_type),
                    status          = COALESCE(%s, status),
                    priority        = COALESCE(%s, priority),
                    estimated_cost  = COALESCE(%s, estimated_cost),
                    actual_cost     = COALESCE(%s, actual_cost),
                    estimated_hours = COALESCE(%s, estimated_hours),
                    actual_hours    = COALESCE(%s, actual_hours),
                    start_date      = COALESCE(%s, start_date),
                    end_date        = COALESCE(%s, end_date),
                    site_address    = COALESCE(%s, site_address),
                    site_notes      = COALESCE(%s, site_notes),
                    assigned_to     = COALESCE(%s, assigned_to),
                    updated_at      = NOW()
                WHERE id = %s
                RETURNING id, job_number, customer_id, title, description, job_type, status,
                          priority, estimated_cost, actual_cost, estimated_hours, actual_hours,
                          start_date, end_date, completion_date, site_address, site_notes,
                          assigned_to, tags, metadata, created_at, updated_at
                """,
                (
                    data.get("title"),
                    data.get("description"),
                    data.get("job_type"),
                    data.get("status"),
                    data.get("priority"),
                    data.get("estimated_cost"),
                    data.get("actual_cost"),
                    data.get("estimated_hours"),
                    data.get("actual_hours"),
                    data.get("start_date"),
                    data.get("end_date"),
                    data.get("site_address"),
                    data.get("site_notes"),
                    data.get("assigned_to"),
                    job_id,
                ),
            )
            job = cur.fetchone()
        event_bus.emit("job.updated", {"job_id": job_id, "_tenant_id": g.tenant_id})
        return jsonify(job)

    @bp.route("/api/jobs/<int:job_id>/approve", methods=["POST"])
    @login_required
    @require_module("industry")
    def approve_job(job_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE jobs SET status = 'approved', updated_at = NOW()"
                " WHERE id = %s RETURNING id, job_number, status",
                (job_id,),
            )
            job = cur.fetchone()
        if not job:
            return jsonify({"error": "Job not found"}), 404
        event_bus.emit("job.updated", {"job_id": job_id, "status": "approved", "_tenant_id": g.tenant_id})
        return jsonify(job)

    @bp.route("/api/jobs/<int:job_id>/start", methods=["POST"])
    @login_required
    @require_module("industry")
    def start_job(job_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE jobs SET status = 'in_progress', start_date = COALESCE(start_date, CURRENT_DATE),"
                " updated_at = NOW() WHERE id = %s RETURNING id, job_number, status, start_date",
                (job_id,),
            )
            job = cur.fetchone()
        if not job:
            return jsonify({"error": "Job not found"}), 404
        event_bus.emit("job.updated", {"job_id": job_id, "status": "in_progress", "_tenant_id": g.tenant_id})
        return jsonify(job)

    @bp.route("/api/jobs/<int:job_id>/complete", methods=["POST"])
    @login_required
    @require_module("industry")
    def complete_job(job_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE jobs SET status = 'completed', completion_date = CURRENT_DATE,"
                " updated_at = NOW() WHERE id = %s"
                " RETURNING id, job_number, status, completion_date",
                (job_id,),
            )
            job = cur.fetchone()
        if not job:
            return jsonify({"error": "Job not found"}), 404
        event_bus.emit("job.completed", {"job_id": job_id, "job_number": job["job_number"],
                                          "_tenant_id": g.tenant_id})
        return jsonify(job)

    @bp.route("/api/jobs/<int:job_id>/invoice", methods=["POST"])
    @login_required
    @require_module("industry")
    def invoice_job(job_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE jobs SET status = 'invoiced', updated_at = NOW()"
                " WHERE id = %s RETURNING id, job_number, status",
                (job_id,),
            )
            job = cur.fetchone()
        if not job:
            return jsonify({"error": "Job not found"}), 404
        event_bus.emit("job.updated", {"job_id": job_id, "status": "invoiced", "_tenant_id": g.tenant_id})
        return jsonify(job)

    @bp.route("/api/jobs/<int:job_id>", methods=["DELETE"])
    @login_required
    @require_module("industry")
    def delete_job(job_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id, status FROM jobs WHERE id = %s", (job_id,))
            job = cur.fetchone()
            if not job:
                return jsonify({"error": "Job not found"}), 404
            if job["status"] != "quoted":
                return jsonify({"error": "Only quoted jobs can be deleted"}), 400
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        return jsonify({"deleted": True})

    # ------------------------------------------------------------------
    # Job Items
    # ------------------------------------------------------------------

    @bp.route("/api/jobs/<int:job_id>/items", methods=["GET"])
    @login_required
    @require_module("industry")
    def list_job_items(job_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, item_type, description, quantity, unit_price, total, notes, created_at"
                " FROM job_items WHERE job_id = %s ORDER BY id",
                (job_id,),
            )
            items = cur.fetchall()
        return jsonify({"items": items})

    @bp.route("/api/jobs/<int:job_id>/items", methods=["POST"])
    @login_required
    @require_module("industry")
    def add_job_item(job_id):
        data = request.get_json(force=True)
        item_type = (data.get("item_type") or "").strip()
        description = (data.get("description") or "").strip()
        unit_price = data.get("unit_price")

        if not item_type:
            return jsonify({"error": "item_type is required"}), 400
        if not description:
            return jsonify({"error": "description is required"}), 400
        if unit_price is None:
            return jsonify({"error": "unit_price is required"}), 400

        try:
            unit_price = float(unit_price)
            quantity = float(data.get("quantity", 1))
        except (TypeError, ValueError):
            return jsonify({"error": "unit_price and quantity must be numbers"}), 400

        total = round(quantity * unit_price, 2)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
            if not cur.fetchone():
                return jsonify({"error": "Job not found"}), 404
            cur.execute(
                """
                INSERT INTO job_items (job_id, item_type, description, quantity, unit_price, total, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, item_type, description, quantity, unit_price, total, notes, created_at
                """,
                (job_id, item_type, description, quantity, unit_price, total, data.get("notes")),
            )
            item = cur.fetchone()
        return jsonify(item), 201

    @bp.route("/api/items/<int:item_id>", methods=["DELETE"])
    @login_required
    @require_module("industry")
    def delete_job_item(item_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM job_items WHERE id = %s", (item_id,))
            if not cur.fetchone():
                return jsonify({"error": "Item not found"}), 404
            cur.execute("DELETE FROM job_items WHERE id = %s", (item_id,))
        return jsonify({"deleted": True})

    # ------------------------------------------------------------------
    # Job Notes
    # ------------------------------------------------------------------

    @bp.route("/api/jobs/<int:job_id>/notes", methods=["GET"])
    @login_required
    @require_module("industry")
    def list_job_notes(job_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, author, content, note_type, attachments, created_at"
                " FROM job_notes WHERE job_id = %s ORDER BY created_at",
                (job_id,),
            )
            notes = cur.fetchall()
        return jsonify({"notes": notes})

    @bp.route("/api/jobs/<int:job_id>/notes", methods=["POST"])
    @login_required
    @require_module("industry")
    def add_job_note(job_id):
        data = request.get_json(force=True)
        author = (data.get("author") or "").strip()
        content = (data.get("content") or "").strip()
        if not author:
            return jsonify({"error": "author is required"}), 400
        if not content:
            return jsonify({"error": "content is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
            if not cur.fetchone():
                return jsonify({"error": "Job not found"}), 404
            cur.execute(
                """
                INSERT INTO job_notes (job_id, author, content, note_type, attachments)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, job_id, author, content, note_type, attachments, created_at
                """,
                (
                    job_id,
                    author,
                    content,
                    data.get("note_type", "general"),
                    Json(data.get("attachments", [])),
                ),
            )
            note = cur.fetchone()
        return jsonify(note), 201

    # ------------------------------------------------------------------
    # Permits & Licences
    # ------------------------------------------------------------------

    @bp.route("/api/permits", methods=["GET"])
    @login_required
    @require_module("industry")
    def list_permits():
        status = request.args.get("status")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if status:
                cur.execute(
                    "SELECT id, job_id, permit_type, permit_number, issuing_authority,"
                    " status, applied_date, approval_date, expiry_date, cost, notes, created_at"
                    " FROM permits_licenses WHERE status = %s ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cur.execute(
                    "SELECT id, job_id, permit_type, permit_number, issuing_authority,"
                    " status, applied_date, approval_date, expiry_date, cost, notes, created_at"
                    " FROM permits_licenses ORDER BY created_at DESC"
                )
            permits = cur.fetchall()
        return jsonify({"permits": permits})

    @bp.route("/api/permits", methods=["POST"])
    @login_required
    @require_module("industry")
    def create_permit():
        data = request.get_json(force=True)
        permit_type = (data.get("permit_type") or "").strip()
        if not permit_type:
            return jsonify({"error": "permit_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO permits_licenses
                    (job_id, permit_type, permit_number, issuing_authority, status,
                     applied_date, approval_date, expiry_date, cost, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, permit_type, permit_number, issuing_authority,
                          status, applied_date, approval_date, expiry_date, cost, notes, created_at
                """,
                (
                    data.get("job_id"),
                    permit_type,
                    data.get("permit_number"),
                    data.get("issuing_authority"),
                    data.get("status", "pending"),
                    data.get("applied_date"),
                    data.get("approval_date"),
                    data.get("expiry_date"),
                    data.get("cost"),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            permit = cur.fetchone()
        return jsonify(permit), 201

    @bp.route("/api/permits/<int:permit_id>", methods=["PUT"])
    @login_required
    @require_module("industry")
    def update_permit(permit_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM permits_licenses WHERE id = %s", (permit_id,))
            if not cur.fetchone():
                return jsonify({"error": "Permit not found"}), 404
            cur.execute(
                """
                UPDATE permits_licenses SET
                    status            = COALESCE(%s, status),
                    permit_number     = COALESCE(%s, permit_number),
                    issuing_authority = COALESCE(%s, issuing_authority),
                    applied_date      = COALESCE(%s, applied_date),
                    approval_date     = COALESCE(%s, approval_date),
                    expiry_date       = COALESCE(%s, expiry_date),
                    cost              = COALESCE(%s, cost),
                    notes             = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, job_id, permit_type, permit_number, issuing_authority,
                          status, applied_date, approval_date, expiry_date, cost, notes, created_at
                """,
                (
                    data.get("status"),
                    data.get("permit_number"),
                    data.get("issuing_authority"),
                    data.get("applied_date"),
                    data.get("approval_date"),
                    data.get("expiry_date"),
                    data.get("cost"),
                    data.get("notes"),
                    permit_id,
                ),
            )
            permit = cur.fetchone()
        return jsonify(permit)

    @bp.route("/api/jobs/<int:job_id>/permits", methods=["GET"])
    @login_required
    @require_module("industry")
    def list_job_permits(job_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, job_id, permit_type, permit_number, issuing_authority,"
                " status, applied_date, approval_date, expiry_date, cost, notes, created_at"
                " FROM permits_licenses WHERE job_id = %s ORDER BY created_at",
                (job_id,),
            )
            permits = cur.fetchall()
        return jsonify({"permits": permits})

    # ------------------------------------------------------------------
    # Government Opportunities
    # ------------------------------------------------------------------

    @bp.route("/api/opportunities", methods=["GET"])
    @login_required
    @require_module("industry")
    def list_opportunities():
        status = request.args.get("status")
        industry = request.args.get("industry")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            conditions = []
            params: list = []
            if status:
                conditions.append("status = %s")
                params.append(status)
            if industry:
                conditions.append("industry_types @> %s::jsonb")
                params.append(Json([industry]))
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur.execute(
                f"""
                SELECT id, title, source, reference_number, industry_types, region,
                       value_min, value_max, deadline, url, status, match_score,
                       notes, discovered_at, updated_at
                FROM government_opportunities {where}
                ORDER BY discovered_at DESC
                """,
                params,
            )
            opps = cur.fetchall()
        return jsonify({"opportunities": opps})

    @bp.route("/api/opportunities", methods=["POST"])
    @login_required
    @require_module("industry")
    def create_opportunity():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        source = (data.get("source") or "").strip()
        if not title:
            return jsonify({"error": "title is required"}), 400
        if not source:
            return jsonify({"error": "source is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO government_opportunities
                    (title, source, reference_number, description, industry_types,
                     region, value_min, value_max, deadline, url, status, match_score, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, title, source, reference_number, industry_types, region,
                          value_min, value_max, deadline, url, status, match_score,
                          notes, discovered_at, updated_at
                """,
                (
                    title,
                    source,
                    data.get("reference_number"),
                    data.get("description"),
                    Json(data.get("industry_types", [])),
                    data.get("region"),
                    data.get("value_min"),
                    data.get("value_max"),
                    data.get("deadline"),
                    data.get("url"),
                    data.get("status", "new"),
                    data.get("match_score", 0),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            opp = cur.fetchone()
        event_bus.emit("opportunity.found", {"opportunity_id": opp["id"], "title": opp["title"],
                                              "_tenant_id": g.tenant_id})
        return jsonify(opp), 201

    @bp.route("/api/opportunities/<int:opp_id>", methods=["PUT"])
    @login_required
    @require_module("industry")
    def update_opportunity(opp_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM government_opportunities WHERE id = %s", (opp_id,))
            if not cur.fetchone():
                return jsonify({"error": "Opportunity not found"}), 404
            cur.execute(
                """
                UPDATE government_opportunities SET
                    status       = COALESCE(%s, status),
                    notes        = COALESCE(%s, notes),
                    match_score  = COALESCE(%s, match_score),
                    updated_at   = NOW()
                WHERE id = %s
                RETURNING id, title, source, status, match_score, notes, updated_at
                """,
                (data.get("status"), data.get("notes"), data.get("match_score"), opp_id),
            )
            opp = cur.fetchone()
        return jsonify(opp)

    @bp.route("/api/opportunities/<int:opp_id>/apply", methods=["POST"])
    @login_required
    @require_module("industry")
    def apply_opportunity(opp_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE government_opportunities SET status = 'applied', updated_at = NOW()"
                " WHERE id = %s RETURNING id, title, status",
                (opp_id,),
            )
            opp = cur.fetchone()
        if not opp:
            return jsonify({"error": "Opportunity not found"}), 404
        event_bus.emit("opportunity.applied", {"opportunity_id": opp_id, "title": opp["title"],
                                                "_tenant_id": g.tenant_id})
        return jsonify(opp)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("industry")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('approved','in_progress','on_hold')) AS active_jobs,
                    COUNT(*) FILTER (WHERE status = 'completed'
                        AND completion_date >= date_trunc('month', CURRENT_DATE)) AS completed_this_month,
                    COALESCE(SUM(actual_cost) FILTER (WHERE status = 'completed'), 0) AS total_revenue,
                    COUNT(*) FILTER (WHERE status = 'quoted') AS quoted_jobs
                FROM jobs
                """
            )
            job_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS pending_permits FROM permits_licenses WHERE status = 'pending'"
            )
            permit_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS new_opportunities FROM government_opportunities WHERE status = 'new'"
            )
            opp_stats = cur.fetchone()

        return jsonify({
            "active_jobs": job_stats["active_jobs"],
            "completed_this_month": job_stats["completed_this_month"],
            "total_revenue": float(job_stats["total_revenue"]),
            "quoted_jobs": job_stats["quoted_jobs"],
            "pending_permits": permit_stats["pending_permits"],
            "new_opportunities": opp_stats["new_opportunities"],
        })


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------

def on_contact_created(data):
    """No-op placeholder — reserved for future auto-lead-to-job conversion."""
    pass


def on_invoice_paid(data):
    """Mark linked job as invoiced when an invoice is paid."""
    job_id = data.get("job_id")
    tenant_id = data.get("_tenant_id")
    if not job_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                "UPDATE jobs SET status = 'invoiced', updated_at = NOW() WHERE id = %s AND status = 'completed'",
                (job_id,),
            )
    except Exception:
        logger.exception("Failed to update job %s on invoice.paid event", job_id)


def on_contract_signed(data):
    """No-op placeholder — reserved for future auto-approve-on-contract logic."""
    pass
