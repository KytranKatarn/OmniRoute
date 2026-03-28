"""Plumbing industry plugin routes — service calls, fixtures, inventory, backflow tests."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Plumbing routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("industry-plumbing")
    def index():
        return render_template("plumbing.html")

    # ------------------------------------------------------------------
    # Service Calls
    # ------------------------------------------------------------------

    @bp.route("/api/service-calls", methods=["GET"])
    @login_required
    @require_module("industry-plumbing")
    def list_service_calls():
        status = request.args.get("status")
        call_type = request.args.get("type")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if status:
                conditions.append("status = %s")
                params.append(status)
            if call_type:
                conditions.append("call_type = %s")
                params.append(call_type)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(
                f"""
                SELECT id, job_id, customer_id, call_type, priority, description,
                       technician, scheduled_date, completed_date, status,
                       diagnosis, resolution, parts_used, metadata, created_at
                FROM plumbing_service_calls {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            calls = cur.fetchall()

        return jsonify({"service_calls": calls, "total": len(calls)})

    @bp.route("/api/service-calls", methods=["POST"])
    @login_required
    @require_module("industry-plumbing")
    def create_service_call():
        data = request.get_json(force=True)
        call_type = (data.get("call_type") or "").strip()
        if not call_type:
            return jsonify({"error": "call_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO plumbing_service_calls
                    (job_id, customer_id, call_type, priority, description,
                     technician, scheduled_date, status, parts_used, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, customer_id, call_type, priority, description,
                          technician, scheduled_date, completed_date, status,
                          diagnosis, resolution, parts_used, metadata, created_at
                """,
                (
                    data.get("job_id"),
                    data.get("customer_id"),
                    call_type,
                    data.get("priority", "normal"),
                    data.get("description"),
                    data.get("technician"),
                    data.get("scheduled_date"),
                    data.get("status", "new"),
                    Json(data.get("parts_used", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            call = cur.fetchone()

        event_bus.emit(
            "service_call.dispatched",
            {
                "service_call_id": call["id"],
                "call_type": call["call_type"],
                "priority": call["priority"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(call), 201

    @bp.route("/api/service-calls/<int:call_id>", methods=["GET"])
    @login_required
    @require_module("industry-plumbing")
    def get_service_call(call_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, customer_id, call_type, priority, description,
                       technician, scheduled_date, completed_date, status,
                       diagnosis, resolution, parts_used, metadata, created_at
                FROM plumbing_service_calls WHERE id = %s
                """,
                (call_id,),
            )
            call = cur.fetchone()

        if call is None:
            return jsonify({"error": "service call not found"}), 404
        return jsonify(call)

    @bp.route("/api/service-calls/<int:call_id>", methods=["PUT"])
    @login_required
    @require_module("industry-plumbing")
    def update_service_call(call_id):
        data = request.get_json(force=True)

        allowed = ("status", "technician", "diagnosis", "resolution",
                   "priority", "description", "scheduled_date", "completed_date")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "parts_used" in data:
            sets.append("parts_used = %s")
            params.append(Json(data["parts_used"]))
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(call_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE plumbing_service_calls SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, job_id, customer_id, call_type, priority, description,
                          technician, scheduled_date, completed_date, status,
                          diagnosis, resolution, parts_used, metadata, created_at
                """,
                params,
            )
            call = cur.fetchone()

        if call is None:
            return jsonify({"error": "service call not found"}), 404
        return jsonify(call)

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @bp.route("/api/fixtures", methods=["GET"])
    @login_required
    @require_module("industry-plumbing")
    def list_fixtures():
        job_id = request.args.get("job_id", type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = "WHERE job_id = %s" if job_id else ""
            params = [job_id] if job_id else []

            cur.execute(
                f"""
                SELECT id, job_id, fixture_type, brand, model, location,
                       install_date, warranty_expiry, status, serial_number,
                       notes, created_at
                FROM plumbing_fixtures {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            fixtures = cur.fetchall()

        return jsonify({"fixtures": fixtures, "total": len(fixtures)})

    @bp.route("/api/fixtures", methods=["POST"])
    @login_required
    @require_module("industry-plumbing")
    def add_fixture():
        data = request.get_json(force=True)
        fixture_type = (data.get("fixture_type") or "").strip()
        if not fixture_type:
            return jsonify({"error": "fixture_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO plumbing_fixtures
                    (job_id, fixture_type, brand, model, location,
                     install_date, warranty_expiry, status, serial_number, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, fixture_type, brand, model, location,
                          install_date, warranty_expiry, status, serial_number,
                          notes, created_at
                """,
                (
                    data.get("job_id"),
                    fixture_type,
                    data.get("brand"),
                    data.get("model"),
                    data.get("location"),
                    data.get("install_date"),
                    data.get("warranty_expiry"),
                    data.get("status", "active"),
                    data.get("serial_number"),
                    data.get("notes"),
                ),
            )
            fixture = cur.fetchone()

        event_bus.emit(
            "fixture.installed",
            {
                "fixture_id": fixture["id"],
                "fixture_type": fixture["fixture_type"],
                "job_id": fixture["job_id"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(fixture), 201

    @bp.route("/api/fixtures/<int:fixture_id>", methods=["PUT"])
    @login_required
    @require_module("industry-plumbing")
    def update_fixture(fixture_id):
        data = request.get_json(force=True)

        allowed = ("fixture_type", "brand", "model", "location", "install_date",
                   "warranty_expiry", "status", "serial_number", "notes")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(fixture_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE plumbing_fixtures SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, job_id, fixture_type, brand, model, location,
                          install_date, warranty_expiry, status, serial_number,
                          notes, created_at
                """,
                params,
            )
            fixture = cur.fetchone()

        if fixture is None:
            return jsonify({"error": "fixture not found"}), 404
        return jsonify(fixture)

    # ------------------------------------------------------------------
    # Parts Inventory
    # ------------------------------------------------------------------

    @bp.route("/api/inventory", methods=["GET"])
    @login_required
    @require_module("industry-plumbing")
    def list_inventory():
        low_stock = request.args.get("low_stock", "").lower() in ("1", "true", "yes")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = "WHERE quantity <= min_quantity" if low_stock else ""

            cur.execute(
                f"""
                SELECT id, name, category, sku, quantity, min_quantity,
                       unit_cost, supplier, location, created_at, updated_at
                FROM plumbing_parts_inventory {where}
                ORDER BY name
                """,
            )
            parts = cur.fetchall()

        return jsonify({"parts": parts, "total": len(parts)})

    @bp.route("/api/inventory", methods=["POST"])
    @login_required
    @require_module("industry-plumbing")
    def add_inventory_part():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO plumbing_parts_inventory
                    (name, category, sku, quantity, min_quantity,
                     unit_cost, supplier, location)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, category, sku, quantity, min_quantity,
                          unit_cost, supplier, location, created_at, updated_at
                """,
                (
                    name,
                    data.get("category"),
                    data.get("sku"),
                    data.get("quantity", 0),
                    data.get("min_quantity", 5),
                    data.get("unit_cost"),
                    data.get("supplier"),
                    data.get("location"),
                ),
            )
            part = cur.fetchone()

        return jsonify(part), 201

    @bp.route("/api/inventory/<int:part_id>", methods=["PUT"])
    @login_required
    @require_module("industry-plumbing")
    def update_inventory_part(part_id):
        data = request.get_json(force=True)

        allowed = ("name", "category", "sku", "quantity", "min_quantity",
                   "unit_cost", "supplier", "location")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(part_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE plumbing_parts_inventory SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, category, sku, quantity, min_quantity,
                          unit_cost, supplier, location, created_at, updated_at
                """,
                params,
            )
            part = cur.fetchone()

        if part is None:
            return jsonify({"error": "part not found"}), 404
        return jsonify(part)

    # ------------------------------------------------------------------
    # Backflow Tests
    # ------------------------------------------------------------------

    @bp.route("/api/backflow-tests", methods=["GET"])
    @login_required
    @require_module("industry-plumbing")
    def list_backflow_tests():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, device_location, device_type, serial_number,
                       test_date, tester_name, test_result, pressure_readings,
                       next_test_date, certification_number, notes, created_at
                FROM plumbing_backflow_tests
                ORDER BY test_date DESC
                """
            )
            tests = cur.fetchall()

        return jsonify({"backflow_tests": tests, "total": len(tests)})

    @bp.route("/api/backflow-tests", methods=["POST"])
    @login_required
    @require_module("industry-plumbing")
    def record_backflow_test():
        data = request.get_json(force=True)
        device_location = (data.get("device_location") or "").strip()
        test_date = data.get("test_date")
        if not device_location:
            return jsonify({"error": "device_location is required"}), 400
        if not test_date:
            return jsonify({"error": "test_date is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO plumbing_backflow_tests
                    (job_id, device_location, device_type, serial_number,
                     test_date, tester_name, test_result, pressure_readings,
                     next_test_date, certification_number, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, device_location, device_type, serial_number,
                          test_date, tester_name, test_result, pressure_readings,
                          next_test_date, certification_number, notes, created_at
                """,
                (
                    data.get("job_id"),
                    device_location,
                    data.get("device_type"),
                    data.get("serial_number"),
                    test_date,
                    data.get("tester_name"),
                    data.get("test_result", "pending"),
                    Json(data.get("pressure_readings", {})),
                    data.get("next_test_date"),
                    data.get("certification_number"),
                    data.get("notes"),
                ),
            )
            test = cur.fetchone()

        event_bus.emit(
            "backflow.tested",
            {
                "backflow_test_id": test["id"],
                "device_location": test["device_location"],
                "test_result": test["test_result"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(test), 201

    @bp.route("/api/backflow-tests/<int:test_id>", methods=["PUT"])
    @login_required
    @require_module("industry-plumbing")
    def update_backflow_test(test_id):
        data = request.get_json(force=True)

        allowed = ("test_result", "tester_name", "next_test_date",
                   "certification_number", "notes", "test_date")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "pressure_readings" in data:
            sets.append("pressure_readings = %s")
            params.append(Json(data["pressure_readings"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(test_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE plumbing_backflow_tests SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, job_id, device_location, device_type, serial_number,
                          test_date, tester_name, test_result, pressure_readings,
                          next_test_date, certification_number, notes, created_at
                """,
                params,
            )
            test = cur.fetchone()

        if test is None:
            return jsonify({"error": "backflow test not found"}), 404
        return jsonify(test)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("industry-plumbing")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status NOT IN ('completed', 'cancelled'))
                        AS active_calls,
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                          AND completed_date >= date_trunc('day', CURRENT_DATE)
                    ) AS completed_today
                FROM plumbing_service_calls
                """
            )
            call_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS low_stock_items FROM plumbing_parts_inventory "
                "WHERE quantity <= min_quantity"
            )
            inv_stats = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) AS upcoming_backflow_tests
                FROM plumbing_backflow_tests
                WHERE next_test_date <= CURRENT_DATE + INTERVAL '30 days'
                  AND next_test_date >= CURRENT_DATE
                """
            )
            backflow_stats = cur.fetchone()

        return jsonify(
            {
                "active_calls": call_stats["active_calls"],
                "completed_today": call_stats["completed_today"],
                "low_stock_items": inv_stats["low_stock_items"],
                "upcoming_backflow_tests": backflow_stats["upcoming_backflow_tests"],
            }
        )

    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-plumbing")
    def ask_ai():
        """Ask the Plumbing AI agent a question with optional context."""
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="plumbing",
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
    """Log new job creation — no-op for plumbing (info only)."""
    logger.debug(
        "Plumbing plugin received job.created event: job_id=%s tenant=%s",
        data.get("job_id"),
        data.get("_tenant_id"),
    )


def on_job_completed(data):
    """Mark any active service calls for the completed job as completed."""
    job_id = data.get("job_id")
    tenant_id = data.get("_tenant_id")
    if not job_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE plumbing_service_calls
                SET status = 'completed', completed_date = NOW()
                WHERE job_id = %s AND status NOT IN ('completed', 'cancelled')
                """,
                (job_id,),
            )
    except Exception:
        logger.exception(
            "Failed to auto-complete service calls for job_id=%s", job_id
        )
