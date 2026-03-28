"""Limo Service plugin routes — vehicles, drivers, bookings, dispatch, maintenance, stats."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Limo Service routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("industry-limo")
    def index():
        return render_template("limo.html")

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------

    @bp.route("/api/vehicles", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def list_vehicles():
        status = request.args.get("status")
        vehicle_type = request.args.get("vehicle_type")
        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if vehicle_type:
            conditions.append("vehicle_type = %s")
            params.append(vehicle_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT id, name, vehicle_type, make, model, year, license_plate,
                       capacity, status, mileage, last_service_date, next_service_date,
                       features, created_at
                FROM limo_vehicles {where}
                ORDER BY name
                """,
                params,
            )
            vehicles = cur.fetchall()
        return jsonify({"vehicles": vehicles})

    @bp.route("/api/vehicles", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def create_vehicle():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        vehicle_type = (data.get("vehicle_type") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not vehicle_type:
            return jsonify({"error": "vehicle_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO limo_vehicles
                    (name, vehicle_type, make, model, year, license_plate, capacity,
                     status, mileage, last_service_date, next_service_date, features)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, vehicle_type, make, model, year, license_plate,
                          capacity, status, mileage, last_service_date, next_service_date,
                          features, created_at
                """,
                (
                    name,
                    vehicle_type,
                    data.get("make"),
                    data.get("model"),
                    data.get("year"),
                    data.get("license_plate"),
                    data.get("capacity"),
                    data.get("status", "available"),
                    data.get("mileage", 0),
                    data.get("last_service_date"),
                    data.get("next_service_date"),
                    Json(data.get("features", [])),
                ),
            )
            vehicle = cur.fetchone()
        return jsonify(vehicle), 201

    @bp.route("/api/vehicles/<int:vehicle_id>", methods=["PUT"])
    @login_required
    @require_module("industry-limo")
    def update_vehicle(vehicle_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM limo_vehicles WHERE id = %s", (vehicle_id,))
            if not cur.fetchone():
                return jsonify({"error": "Vehicle not found"}), 404
            cur.execute(
                """
                UPDATE limo_vehicles SET
                    name               = COALESCE(%s, name),
                    vehicle_type       = COALESCE(%s, vehicle_type),
                    make               = COALESCE(%s, make),
                    model              = COALESCE(%s, model),
                    year               = COALESCE(%s, year),
                    license_plate      = COALESCE(%s, license_plate),
                    capacity           = COALESCE(%s, capacity),
                    mileage            = COALESCE(%s, mileage),
                    last_service_date  = COALESCE(%s, last_service_date),
                    next_service_date  = COALESCE(%s, next_service_date)
                WHERE id = %s
                RETURNING id, name, vehicle_type, make, model, year, license_plate,
                          capacity, status, mileage, last_service_date, next_service_date,
                          features, created_at
                """,
                (
                    data.get("name"),
                    data.get("vehicle_type"),
                    data.get("make"),
                    data.get("model"),
                    data.get("year"),
                    data.get("license_plate"),
                    data.get("capacity"),
                    data.get("mileage"),
                    data.get("last_service_date"),
                    data.get("next_service_date"),
                    vehicle_id,
                ),
            )
            vehicle = cur.fetchone()
        return jsonify(vehicle)

    @bp.route("/api/vehicles/<int:vehicle_id>/status", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def update_vehicle_status(vehicle_id):
        data = request.get_json(force=True)
        status = (data.get("status") or "").strip()
        if not status:
            return jsonify({"error": "status is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE limo_vehicles SET status = %s WHERE id = %s"
                " RETURNING id, name, status",
                (status, vehicle_id),
            )
            vehicle = cur.fetchone()
        if not vehicle:
            return jsonify({"error": "Vehicle not found"}), 404
        return jsonify(vehicle)

    # ------------------------------------------------------------------
    # Drivers
    # ------------------------------------------------------------------

    @bp.route("/api/drivers", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def list_drivers():
        status = request.args.get("status")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if status:
                cur.execute(
                    "SELECT id, name, license_number, license_expiry, phone, email,"
                    " status, rating, total_trips, notes, created_at"
                    " FROM limo_drivers WHERE status = %s ORDER BY name",
                    (status,),
                )
            else:
                cur.execute(
                    "SELECT id, name, license_number, license_expiry, phone, email,"
                    " status, rating, total_trips, notes, created_at"
                    " FROM limo_drivers ORDER BY name"
                )
            drivers = cur.fetchall()
        return jsonify({"drivers": drivers})

    @bp.route("/api/drivers", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def create_driver():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO limo_drivers
                    (name, license_number, license_expiry, phone, email,
                     status, rating, total_trips, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, license_number, license_expiry, phone, email,
                          status, rating, total_trips, notes, created_at
                """,
                (
                    name,
                    data.get("license_number"),
                    data.get("license_expiry"),
                    data.get("phone"),
                    data.get("email"),
                    data.get("status", "available"),
                    data.get("rating", 5.0),
                    data.get("total_trips", 0),
                    data.get("notes"),
                ),
            )
            driver = cur.fetchone()
        return jsonify(driver), 201

    @bp.route("/api/drivers/<int:driver_id>", methods=["PUT"])
    @login_required
    @require_module("industry-limo")
    def update_driver(driver_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM limo_drivers WHERE id = %s", (driver_id,))
            if not cur.fetchone():
                return jsonify({"error": "Driver not found"}), 404
            cur.execute(
                """
                UPDATE limo_drivers SET
                    name            = COALESCE(%s, name),
                    license_number  = COALESCE(%s, license_number),
                    license_expiry  = COALESCE(%s, license_expiry),
                    phone           = COALESCE(%s, phone),
                    email           = COALESCE(%s, email),
                    notes           = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, name, license_number, license_expiry, phone, email,
                          status, rating, total_trips, notes, created_at
                """,
                (
                    data.get("name"),
                    data.get("license_number"),
                    data.get("license_expiry"),
                    data.get("phone"),
                    data.get("email"),
                    data.get("notes"),
                    driver_id,
                ),
            )
            driver = cur.fetchone()
        return jsonify(driver)

    @bp.route("/api/drivers/<int:driver_id>/status", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def update_driver_status(driver_id):
        data = request.get_json(force=True)
        status = (data.get("status") or "").strip()
        if not status:
            return jsonify({"error": "status is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE limo_drivers SET status = %s WHERE id = %s"
                " RETURNING id, name, status",
                (status, driver_id),
            )
            driver = cur.fetchone()
        if not driver:
            return jsonify({"error": "Driver not found"}), 404
        return jsonify(driver)

    # ------------------------------------------------------------------
    # Bookings
    # ------------------------------------------------------------------

    @bp.route("/api/bookings", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def list_bookings():
        status = request.args.get("status")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if date_from:
            conditions.append("pickup_time >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("pickup_time <= %s")
            params.append(date_to)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(f"SELECT COUNT(*) AS cnt FROM limo_bookings {where}", params)
            total = cur.fetchone()["cnt"]
            cur.execute(
                f"""
                SELECT id, customer_id, vehicle_id, driver_id, booking_type,
                       pickup_address, dropoff_address, pickup_time,
                       estimated_duration_hours, actual_duration_hours, passengers,
                       status, base_fare, extras, total_fare, payment_status,
                       special_requests, metadata, created_at
                FROM limo_bookings {where}
                ORDER BY pickup_time DESC
                """,
                params,
            )
            bookings = cur.fetchall()
        return jsonify({"bookings": bookings, "total": total})

    @bp.route("/api/bookings", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def create_booking():
        data = request.get_json(force=True)
        booking_type = (data.get("booking_type") or "").strip()
        pickup_address = (data.get("pickup_address") or "").strip()
        pickup_time = data.get("pickup_time")
        if not booking_type:
            return jsonify({"error": "booking_type is required"}), 400
        if not pickup_address:
            return jsonify({"error": "pickup_address is required"}), 400
        if not pickup_time:
            return jsonify({"error": "pickup_time is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO limo_bookings
                    (customer_id, vehicle_id, driver_id, booking_type,
                     pickup_address, dropoff_address, pickup_time,
                     estimated_duration_hours, passengers, status,
                     base_fare, extras, total_fare, special_requests, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, customer_id, vehicle_id, driver_id, booking_type,
                          pickup_address, dropoff_address, pickup_time,
                          estimated_duration_hours, actual_duration_hours, passengers,
                          status, base_fare, extras, total_fare, payment_status,
                          special_requests, metadata, created_at
                """,
                (
                    data.get("customer_id"),
                    data.get("vehicle_id"),
                    data.get("driver_id"),
                    booking_type,
                    pickup_address,
                    data.get("dropoff_address"),
                    pickup_time,
                    data.get("estimated_duration_hours"),
                    data.get("passengers", 1),
                    data.get("status", "pending"),
                    data.get("base_fare"),
                    data.get("extras", 0),
                    data.get("total_fare"),
                    data.get("special_requests"),
                    Json(data.get("metadata", {})),
                ),
            )
            booking = cur.fetchone()
        return jsonify(booking), 201

    @bp.route("/api/bookings/<int:booking_id>", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def get_booking(booking_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, customer_id, vehicle_id, driver_id, booking_type,
                       pickup_address, dropoff_address, pickup_time,
                       estimated_duration_hours, actual_duration_hours, passengers,
                       status, base_fare, extras, total_fare, payment_status,
                       special_requests, metadata, created_at
                FROM limo_bookings WHERE id = %s
                """,
                (booking_id,),
            )
            booking = cur.fetchone()
        if not booking:
            return jsonify({"error": "Booking not found"}), 404
        return jsonify(booking)

    @bp.route("/api/bookings/<int:booking_id>", methods=["PUT"])
    @login_required
    @require_module("industry-limo")
    def update_booking(booking_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM limo_bookings WHERE id = %s", (booking_id,))
            if not cur.fetchone():
                return jsonify({"error": "Booking not found"}), 404
            cur.execute(
                """
                UPDATE limo_bookings SET
                    booking_type             = COALESCE(%s, booking_type),
                    pickup_address           = COALESCE(%s, pickup_address),
                    dropoff_address          = COALESCE(%s, dropoff_address),
                    pickup_time              = COALESCE(%s, pickup_time),
                    estimated_duration_hours = COALESCE(%s, estimated_duration_hours),
                    passengers               = COALESCE(%s, passengers),
                    base_fare                = COALESCE(%s, base_fare),
                    extras                   = COALESCE(%s, extras),
                    total_fare               = COALESCE(%s, total_fare),
                    special_requests         = COALESCE(%s, special_requests)
                WHERE id = %s
                RETURNING id, customer_id, vehicle_id, driver_id, booking_type,
                          pickup_address, dropoff_address, pickup_time,
                          estimated_duration_hours, actual_duration_hours, passengers,
                          status, base_fare, extras, total_fare, payment_status,
                          special_requests, metadata, created_at
                """,
                (
                    data.get("booking_type"),
                    data.get("pickup_address"),
                    data.get("dropoff_address"),
                    data.get("pickup_time"),
                    data.get("estimated_duration_hours"),
                    data.get("passengers"),
                    data.get("base_fare"),
                    data.get("extras"),
                    data.get("total_fare"),
                    data.get("special_requests"),
                    booking_id,
                ),
            )
            booking = cur.fetchone()
        return jsonify(booking)

    @bp.route("/api/bookings/<int:booking_id>/dispatch", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def dispatch_booking(booking_id):
        data = request.get_json(force=True)
        driver_id = data.get("driver_id")
        vehicle_id = data.get("vehicle_id")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM limo_bookings WHERE id = %s", (booking_id,))
            if not cur.fetchone():
                return jsonify({"error": "Booking not found"}), 404

            cur.execute(
                """
                UPDATE limo_bookings SET
                    status     = 'dispatched',
                    driver_id  = COALESCE(%s, driver_id),
                    vehicle_id = COALESCE(%s, vehicle_id)
                WHERE id = %s
                RETURNING id, booking_type, status, driver_id, vehicle_id, pickup_time
                """,
                (driver_id, vehicle_id, booking_id),
            )
            booking = cur.fetchone()

            # Update driver and vehicle status
            if booking["driver_id"]:
                cur.execute(
                    "UPDATE limo_drivers SET status = 'on_trip' WHERE id = %s",
                    (booking["driver_id"],),
                )
            if booking["vehicle_id"]:
                cur.execute(
                    "UPDATE limo_vehicles SET status = 'in_service' WHERE id = %s",
                    (booking["vehicle_id"],),
                )

        event_bus.emit("booking.dispatched", {
            "booking_id": booking_id,
            "booking_type": booking["booking_type"],
            "driver_id": booking["driver_id"],
            "vehicle_id": booking["vehicle_id"],
            "_tenant_id": g.tenant_id,
        })
        return jsonify(booking)

    @bp.route("/api/bookings/<int:booking_id>/complete", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def complete_booking(booking_id):
        data = request.get_json(force=True)
        actual_duration = data.get("actual_duration_hours")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, driver_id, vehicle_id FROM limo_bookings WHERE id = %s",
                (booking_id,),
            )
            booking_row = cur.fetchone()
            if not booking_row:
                return jsonify({"error": "Booking not found"}), 404

            cur.execute(
                """
                UPDATE limo_bookings SET
                    status                = 'completed',
                    actual_duration_hours = COALESCE(%s, actual_duration_hours)
                WHERE id = %s
                RETURNING id, booking_type, status, actual_duration_hours,
                          driver_id, vehicle_id, total_fare
                """,
                (actual_duration, booking_id),
            )
            booking = cur.fetchone()

            # Free up driver and vehicle
            if booking_row["driver_id"]:
                cur.execute(
                    "UPDATE limo_drivers SET status = 'available', total_trips = total_trips + 1"
                    " WHERE id = %s",
                    (booking_row["driver_id"],),
                )
            if booking_row["vehicle_id"]:
                cur.execute(
                    "UPDATE limo_vehicles SET status = 'available' WHERE id = %s",
                    (booking_row["vehicle_id"],),
                )

        event_bus.emit("trip.completed", {
            "booking_id": booking_id,
            "booking_type": booking["booking_type"],
            "_tenant_id": g.tenant_id,
        })
        return jsonify(booking)

    @bp.route("/api/bookings/<int:booking_id>/cancel", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def cancel_booking(booking_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, driver_id, vehicle_id, status FROM limo_bookings WHERE id = %s",
                (booking_id,),
            )
            booking_row = cur.fetchone()
            if not booking_row:
                return jsonify({"error": "Booking not found"}), 404
            if booking_row["status"] == "completed":
                return jsonify({"error": "Cannot cancel a completed booking"}), 400

            cur.execute(
                "UPDATE limo_bookings SET status = 'cancelled' WHERE id = %s"
                " RETURNING id, status",
                (booking_id,),
            )
            booking = cur.fetchone()

            # Free up driver and vehicle if dispatched
            if booking_row["status"] in ("dispatched", "in_progress"):
                if booking_row["driver_id"]:
                    cur.execute(
                        "UPDATE limo_drivers SET status = 'available' WHERE id = %s",
                        (booking_row["driver_id"],),
                    )
                if booking_row["vehicle_id"]:
                    cur.execute(
                        "UPDATE limo_vehicles SET status = 'available' WHERE id = %s",
                        (booking_row["vehicle_id"],),
                    )

        return jsonify(booking)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    @bp.route("/api/vehicles/<int:vehicle_id>/maintenance", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def list_vehicle_maintenance(vehicle_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, vehicle_id, maintenance_type, description, cost,"
                " performed_date, next_due_date, mileage_at_service, performed_by, notes, created_at"
                " FROM limo_maintenance WHERE vehicle_id = %s ORDER BY performed_date DESC NULLS LAST",
                (vehicle_id,),
            )
            records = cur.fetchall()
        return jsonify({"maintenance": records})

    @bp.route("/api/vehicles/<int:vehicle_id>/maintenance", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def create_maintenance_record(vehicle_id):
        data = request.get_json(force=True)
        maintenance_type = (data.get("maintenance_type") or "").strip()
        if not maintenance_type:
            return jsonify({"error": "maintenance_type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM limo_vehicles WHERE id = %s", (vehicle_id,))
            if not cur.fetchone():
                return jsonify({"error": "Vehicle not found"}), 404

            cur.execute(
                """
                INSERT INTO limo_maintenance
                    (vehicle_id, maintenance_type, description, cost,
                     performed_date, next_due_date, mileage_at_service, performed_by, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, vehicle_id, maintenance_type, description, cost,
                          performed_date, next_due_date, mileage_at_service, performed_by, notes, created_at
                """,
                (
                    vehicle_id,
                    maintenance_type,
                    data.get("description"),
                    data.get("cost"),
                    data.get("performed_date"),
                    data.get("next_due_date"),
                    data.get("mileage_at_service"),
                    data.get("performed_by"),
                    data.get("notes"),
                ),
            )
            record = cur.fetchone()

            # Update vehicle service dates
            if data.get("performed_date"):
                cur.execute(
                    "UPDATE limo_vehicles SET last_service_date = %s"
                    + (", next_service_date = %s" if data.get("next_due_date") else "")
                    + " WHERE id = %s",
                    (
                        [data["performed_date"], data["next_due_date"], vehicle_id]
                        if data.get("next_due_date")
                        else [data["performed_date"], vehicle_id]
                    ),
                )

        # Emit maintenance.due if next_due_date is set
        if data.get("next_due_date"):
            event_bus.emit("maintenance.due", {
                "vehicle_id": vehicle_id,
                "maintenance_type": maintenance_type,
                "next_due_date": data["next_due_date"],
                "_tenant_id": g.tenant_id,
            })

        return jsonify(record), 201

    @bp.route("/api/maintenance/upcoming", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def upcoming_maintenance():
        days_ahead = request.args.get("days", 30, type=int)
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT m.id, m.vehicle_id, v.name AS vehicle_name, m.maintenance_type,
                       m.next_due_date, m.description, m.notes
                FROM limo_maintenance m
                JOIN limo_vehicles v ON m.vehicle_id = v.id
                WHERE m.next_due_date IS NOT NULL
                  AND m.next_due_date <= CURRENT_DATE + INTERVAL '%s days'
                  AND m.next_due_date >= CURRENT_DATE
                ORDER BY m.next_due_date
                """ % days_ahead
            )
            upcoming = cur.fetchall()
        return jsonify({"upcoming": upcoming})

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("industry-limo")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT COUNT(*) AS available_vehicles FROM limo_vehicles WHERE status = 'available'"
            )
            vehicle_stats = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('confirmed','dispatched','in_progress'))
                        AS active_bookings,
                    COALESCE(SUM(total_fare) FILTER (
                        WHERE status = 'completed'
                        AND created_at >= CURRENT_DATE
                    ), 0) AS revenue_today,
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                        AND created_at >= date_trunc('week', CURRENT_DATE)
                    ) AS trips_this_week
                FROM limo_bookings
                """
            )
            booking_stats = cur.fetchone()

        return jsonify({
            "available_vehicles": vehicle_stats["available_vehicles"],
            "active_bookings": booking_stats["active_bookings"],
            "revenue_today": float(booking_stats["revenue_today"]),
            "trips_this_week": booking_stats["trips_this_week"],
        })

    # ------------------------------------------------------------------
    # AI Agent
    # ------------------------------------------------------------------

    @bp.route("/api/ai/ask", methods=["POST"])
    @login_required
    @require_module("industry-limo")
    def ask_ai():
        """Ask the Limo/Fleet AI agent a question with optional context."""
        from core.industry_agents import IndustryAgentService

        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "question is required"}), 400

        result = IndustryAgentService.ask_agent(
            vertical_slug="limo",
            question=question,
            context=data.get("context", {}),
            tenant_id=g.tenant_id,
        )
        status_code = 200 if result["success"] else 502
        return jsonify(result), status_code


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------

def on_job_created(data):
    """No-op placeholder — reserved for future auto-booking-from-job logic."""
    pass
