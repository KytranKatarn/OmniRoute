"""Salon/Hairdressing industry plugin routes — services, stylists, bookings, inventory, client history."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Salon routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("industry-salon")
    def index():
        return render_template("salon.html")

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    @bp.route("/api/services", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def list_services():
        category = request.args.get("category")
        active_only = request.args.get("active_only", "0")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if category:
                conditions.append("category = %s")
                params.append(category)
            if active_only == "1":
                conditions.append("is_active = TRUE")

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur.execute(
                f"""
                SELECT id, name, category, duration_minutes, price,
                       description, is_active, created_at
                FROM salon_services {where}
                ORDER BY category, name
                """,
                params,
            )
            services = cur.fetchall()

        return jsonify({"services": services, "total": len(services)})

    @bp.route("/api/services", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def create_service():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        category = (data.get("category") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not category:
            return jsonify({"error": "category is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO salon_services
                    (name, category, duration_minutes, price, description, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, category, duration_minutes, price,
                          description, is_active, created_at
                """,
                (
                    name,
                    category,
                    data.get("duration_minutes", 60),
                    data.get("price"),
                    data.get("description"),
                    data.get("is_active", True),
                ),
            )
            service = cur.fetchone()

        return jsonify(service), 201

    @bp.route("/api/services/<int:service_id>", methods=["PUT"])
    @login_required
    @require_module("industry-salon")
    def update_service(service_id):
        data = request.get_json(force=True)

        allowed = ("name", "category", "duration_minutes", "price", "description", "is_active")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(service_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE salon_services SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, category, duration_minutes, price,
                          description, is_active, created_at
                """,
                params,
            )
            service = cur.fetchone()

        if service is None:
            return jsonify({"error": "service not found"}), 404
        return jsonify(service)

    # ------------------------------------------------------------------
    # Stylists
    # ------------------------------------------------------------------

    @bp.route("/api/stylists", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def list_stylists():
        active_only = request.args.get("active_only", "0")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = "WHERE is_active = TRUE" if active_only == "1" else ""
            cur.execute(
                f"""
                SELECT id, name, specialties, commission_rate, schedule,
                       is_active, bio, created_at
                FROM salon_stylists {where}
                ORDER BY name
                """,
            )
            stylists = cur.fetchall()

        return jsonify({"stylists": stylists, "total": len(stylists)})

    @bp.route("/api/stylists", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def create_stylist():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO salon_stylists
                    (name, specialties, commission_rate, schedule, is_active, bio)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, specialties, commission_rate, schedule,
                          is_active, bio, created_at
                """,
                (
                    name,
                    Json(data.get("specialties", [])),
                    data.get("commission_rate", 0),
                    Json(data.get("schedule", {})),
                    data.get("is_active", True),
                    data.get("bio"),
                ),
            )
            stylist = cur.fetchone()

        return jsonify(stylist), 201

    @bp.route("/api/stylists/<int:stylist_id>", methods=["PUT"])
    @login_required
    @require_module("industry-salon")
    def update_stylist(stylist_id):
        data = request.get_json(force=True)

        allowed = ("name", "commission_rate", "is_active", "bio")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        for jsonb_field in ("specialties", "schedule"):
            if jsonb_field in data:
                sets.append(f"{jsonb_field} = %s")
                params.append(Json(data[jsonb_field]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(stylist_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE salon_stylists SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, specialties, commission_rate, schedule,
                          is_active, bio, created_at
                """,
                params,
            )
            stylist = cur.fetchone()

        if stylist is None:
            return jsonify({"error": "stylist not found"}), 404
        return jsonify(stylist)

    # ------------------------------------------------------------------
    # Bookings
    # ------------------------------------------------------------------

    @bp.route("/api/bookings", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def list_bookings():
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        stylist_id = request.args.get("stylist_id")
        status = request.args.get("status")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if date_from:
                conditions.append("booking_date >= %s")
                params.append(date_from)
            if date_to:
                conditions.append("booking_date <= %s")
                params.append(date_to)
            if stylist_id:
                conditions.append("stylist_id = %s")
                params.append(int(stylist_id))
            if status:
                conditions.append("status = %s")
                params.append(status)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur.execute(
                f"""
                SELECT id, customer_id, stylist_id, service_id,
                       booking_date::text, start_time::text, end_time::text,
                       status, notes, metadata, created_at
                FROM salon_bookings {where}
                ORDER BY booking_date DESC, start_time DESC
                """,
                params,
            )
            bookings = cur.fetchall()

        return jsonify({"bookings": bookings, "total": len(bookings)})

    @bp.route("/api/bookings", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def create_booking():
        data = request.get_json(force=True)
        booking_date = data.get("booking_date")
        start_time = data.get("start_time")
        if not booking_date:
            return jsonify({"error": "booking_date is required"}), 400
        if not start_time:
            return jsonify({"error": "start_time is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO salon_bookings
                    (customer_id, stylist_id, service_id, booking_date,
                     start_time, end_time, status, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, customer_id, stylist_id, service_id,
                          booking_date::text, start_time::text, end_time::text,
                          status, notes, metadata, created_at
                """,
                (
                    data.get("customer_id"),
                    data.get("stylist_id"),
                    data.get("service_id"),
                    booking_date,
                    start_time,
                    data.get("end_time"),
                    data.get("status", "scheduled"),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            booking = cur.fetchone()

        event_bus.emit(
            "booking.created",
            {
                "booking_id": booking["id"],
                "customer_id": booking["customer_id"],
                "stylist_id": booking["stylist_id"],
                "service_id": booking["service_id"],
                "booking_date": str(booking["booking_date"]),
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(booking), 201

    @bp.route("/api/bookings/<int:booking_id>", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def get_booking(booking_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, customer_id, stylist_id, service_id,
                       booking_date::text, start_time::text, end_time::text,
                       status, notes, metadata, created_at
                FROM salon_bookings
                WHERE id = %s
                """,
                (booking_id,),
            )
            booking = cur.fetchone()

        if booking is None:
            return jsonify({"error": "booking not found"}), 404
        return jsonify(booking)

    @bp.route("/api/bookings/<int:booking_id>/status", methods=["PUT"])
    @login_required
    @require_module("industry-salon")
    def update_booking_status(booking_id):
        data = request.get_json(force=True)
        status = data.get("status")
        if not status:
            return jsonify({"error": "status is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE salon_bookings SET status = %s
                WHERE id = %s
                RETURNING id, customer_id, stylist_id, service_id,
                          booking_date::text, start_time::text, end_time::text,
                          status, notes, metadata, created_at
                """,
                (status, booking_id),
            )
            booking = cur.fetchone()

        if booking is None:
            return jsonify({"error": "booking not found"}), 404

        if status == "completed":
            event_bus.emit(
                "booking.completed",
                {
                    "booking_id": booking["id"],
                    "customer_id": booking["customer_id"],
                    "stylist_id": booking["stylist_id"],
                    "service_id": booking["service_id"],
                },
                tenant_id=g.tenant_id,
            )
        return jsonify(booking)

    @bp.route("/api/bookings/<int:booking_id>/cancel", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def cancel_booking(booking_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE salon_bookings SET status = 'cancelled'
                WHERE id = %s AND status NOT IN ('completed', 'cancelled')
                RETURNING id, customer_id, stylist_id, service_id,
                          booking_date::text, start_time::text, end_time::text,
                          status, notes, metadata, created_at
                """,
                (booking_id,),
            )
            booking = cur.fetchone()

        if booking is None:
            return jsonify({"error": "booking not found or already finalised"}), 404
        return jsonify(booking)

    # ------------------------------------------------------------------
    # Product inventory
    # ------------------------------------------------------------------

    @bp.route("/api/inventory", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def list_inventory():
        low_stock = request.args.get("low_stock", "0")
        category = request.args.get("category")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if low_stock == "1":
                conditions.append("quantity <= min_quantity")
            if category:
                conditions.append("category = %s")
                params.append(category)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur.execute(
                f"""
                SELECT id, name, brand, category, sku, quantity, min_quantity,
                       retail_price, cost_price, supplier, created_at
                FROM salon_product_inventory {where}
                ORDER BY name
                """,
                params,
            )
            products = cur.fetchall()

        return jsonify({"products": products, "total": len(products)})

    @bp.route("/api/inventory", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def create_inventory_product():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO salon_product_inventory
                    (name, brand, category, sku, quantity, min_quantity,
                     retail_price, cost_price, supplier)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, brand, category, sku, quantity, min_quantity,
                          retail_price, cost_price, supplier, created_at
                """,
                (
                    name,
                    data.get("brand"),
                    data.get("category"),
                    data.get("sku"),
                    data.get("quantity", 0),
                    data.get("min_quantity", 3),
                    data.get("retail_price"),
                    data.get("cost_price"),
                    data.get("supplier"),
                ),
            )
            product = cur.fetchone()

        # Check low stock immediately after creation
        if product["quantity"] <= product["min_quantity"]:
            event_bus.emit(
                "product.low_stock",
                {"product_id": product["id"], "name": product["name"], "quantity": product["quantity"]},
                tenant_id=g.tenant_id,
            )

        return jsonify(product), 201

    @bp.route("/api/inventory/<int:product_id>", methods=["PUT"])
    @login_required
    @require_module("industry-salon")
    def update_inventory_product(product_id):
        data = request.get_json(force=True)

        allowed = ("name", "brand", "category", "sku", "quantity", "min_quantity",
                   "retail_price", "cost_price", "supplier")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(product_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE salon_product_inventory SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, brand, category, sku, quantity, min_quantity,
                          retail_price, cost_price, supplier, created_at
                """,
                params,
            )
            product = cur.fetchone()

        if product is None:
            return jsonify({"error": "product not found"}), 404

        # Emit low stock event if threshold crossed
        if product["quantity"] <= product["min_quantity"]:
            event_bus.emit(
                "product.low_stock",
                {"product_id": product["id"], "name": product["name"], "quantity": product["quantity"]},
                tenant_id=g.tenant_id,
            )

        return jsonify(product)

    # ------------------------------------------------------------------
    # Client history
    # ------------------------------------------------------------------

    @bp.route("/api/client-history", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def list_client_history():
        customer_id = request.args.get("customer_id")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            if customer_id:
                cur.execute(
                    """
                    SELECT id, customer_id, stylist_id, service_id, visit_date,
                           formula, color_used, notes, photos, satisfaction, created_at
                    FROM salon_client_history
                    WHERE customer_id = %s
                    ORDER BY visit_date DESC
                    """,
                    (int(customer_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT id, customer_id, stylist_id, service_id, visit_date,
                           formula, color_used, notes, photos, satisfaction, created_at
                    FROM salon_client_history
                    ORDER BY visit_date DESC
                    """,
                )
            entries = cur.fetchall()

        return jsonify({"history": entries, "total": len(entries)})

    @bp.route("/api/client-history", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def add_client_history():
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO salon_client_history
                    (customer_id, stylist_id, service_id, visit_date,
                     formula, color_used, notes, photos, satisfaction)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, customer_id, stylist_id, service_id, visit_date,
                          formula, color_used, notes, photos, satisfaction, created_at
                """,
                (
                    data.get("customer_id"),
                    data.get("stylist_id"),
                    data.get("service_id"),
                    data.get("visit_date"),
                    data.get("formula"),
                    data.get("color_used"),
                    data.get("notes"),
                    Json(data.get("photos", [])),
                    data.get("satisfaction"),
                ),
            )
            entry = cur.fetchone()

        return jsonify(entry), 201

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("industry-salon")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE booking_date = CURRENT_DATE
                          AND status NOT IN ('cancelled', 'no_show')
                    ) AS bookings_today,
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                          AND booking_date >= date_trunc('week', CURRENT_DATE)
                    ) AS completed_this_week
                FROM salon_bookings
                """
            )
            booking_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS low_stock_products FROM salon_product_inventory "
                "WHERE quantity <= min_quantity"
            )
            inv_stats = cur.fetchone()

            cur.execute(
                """
                SELECT COALESCE(
                    SUM(ss.price), 0
                ) AS revenue_this_month
                FROM salon_bookings sb
                JOIN salon_services ss ON ss.id = sb.service_id
                WHERE sb.status = 'completed'
                  AND sb.booking_date >= date_trunc('month', CURRENT_DATE)
                """
            )
            rev_stats = cur.fetchone()

        return jsonify(
            {
                "bookings_today": booking_stats["bookings_today"],
                "completed_this_week": booking_stats["completed_this_week"],
                "low_stock_products": inv_stats["low_stock_products"],
                "revenue_this_month": float(rev_stats["revenue_this_month"]),
            }
        )

    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-salon")
    def ask_ai():
        """Ask the Salon AI agent a question with optional context."""
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code


# ---------------------------------------------------------------------------
# Event consumers
# ---------------------------------------------------------------------------

def on_job_created(payload, tenant_id=None):
    """Log or act when a job is created — hook for future job-to-booking linkage."""
    logger.debug("industry-salon: job.created received — tenant=%s payload=%s", tenant_id, payload)
