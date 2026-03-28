"""Appointments plugin routes — types, availability, booking, and stats."""

import logging
from datetime import datetime, timedelta

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.mail_client import send_email
from core.email_templates import render_appointment_confirmation_email
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Appointments routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("appointments")
    def index():
        return render_template("appointments.html")

    # ------------------------------------------------------------------
    # Appointment Types
    # ------------------------------------------------------------------

    @bp.route("/api/types", methods=["GET"])
    @login_required
    @require_module("appointments")
    def list_types():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, duration_minutes, price, color, is_active, created_at
                FROM appointment_types
                WHERE is_active = TRUE
                ORDER BY name
                """
            )
            types = cur.fetchall()
        return jsonify({"types": types})

    @bp.route("/api/types", methods=["POST"])
    @login_required
    @require_module("appointments")
    def create_type():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO appointment_types (name, description, duration_minutes, price, color)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, description, duration_minutes, price, color, is_active, created_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("duration_minutes", 60),
                    data.get("price"),
                    data.get("color", "#00e5ff"),
                ),
            )
            appt_type = cur.fetchone()

        return jsonify(appt_type), 201

    @bp.route("/api/types/<int:type_id>", methods=["PUT"])
    @login_required
    @require_module("appointments")
    def update_type(type_id):
        data = request.get_json(force=True)

        allowed = ("name", "description", "duration_minutes", "price", "color", "is_active")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(type_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE appointment_types SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, description, duration_minutes, price, color, is_active, created_at
                """,
                params,
            )
            appt_type = cur.fetchone()

        if appt_type is None:
            return jsonify({"error": "appointment type not found"}), 404
        return jsonify(appt_type)

    @bp.route("/api/types/<int:type_id>", methods=["DELETE"])
    @login_required
    @require_module("appointments")
    def delete_type(type_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE appointment_types SET is_active = FALSE
                WHERE id = %s
                RETURNING id, name
                """,
                (type_id,),
            )
            result = cur.fetchone()

        if result is None:
            return jsonify({"error": "appointment type not found"}), 404
        return jsonify({"deleted": True, "id": result["id"]})

    # ------------------------------------------------------------------
    # Availability Slots
    # ------------------------------------------------------------------

    @bp.route("/api/availability", methods=["GET"])
    @login_required
    @require_module("appointments")
    def list_availability():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, day_of_week,
                       start_time::text AS start_time,
                       end_time::text AS end_time,
                       is_active
                FROM availability_slots
                WHERE is_active = TRUE
                ORDER BY day_of_week, start_time
                """
            )
            slots = cur.fetchall()
        return jsonify({"slots": slots})

    @bp.route("/api/availability", methods=["POST"])
    @login_required
    @require_module("appointments")
    def create_availability():
        data = request.get_json(force=True)
        day_of_week = data.get("day_of_week")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        if day_of_week is None or start_time is None or end_time is None:
            return jsonify({"error": "day_of_week, start_time, and end_time are required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO availability_slots (day_of_week, start_time, end_time)
                VALUES (%s, %s, %s)
                RETURNING id, day_of_week,
                          start_time::text AS start_time,
                          end_time::text AS end_time,
                          is_active
                """,
                (day_of_week, start_time, end_time),
            )
            slot = cur.fetchone()

        return jsonify(slot), 201

    @bp.route("/api/availability/<int:slot_id>", methods=["DELETE"])
    @login_required
    @require_module("appointments")
    def delete_availability(slot_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM availability_slots WHERE id = %s RETURNING id",
                (slot_id,),
            )
            result = cur.fetchone()

        if result is None:
            return jsonify({"error": "availability slot not found"}), 404
        return jsonify({"deleted": True, "id": result["id"]})

    # ------------------------------------------------------------------
    # Appointments
    # ------------------------------------------------------------------

    @bp.route("/api/appointments", methods=["GET"])
    @login_required
    @require_module("appointments")
    def list_appointments():
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        status = request.args.get("status")

        where_clauses = []
        params: list = []

        if start_date:
            where_clauses.append("start_time >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("start_time <= %s")
            params.append(end_date)
        if status:
            where_clauses.append("status = %s")
            params.append(status)

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT a.id, a.customer_id, a.appointment_type_id, a.title,
                       a.start_time, a.end_time, a.status, a.notes, a.metadata,
                       a.created_at, a.updated_at,
                       at.name AS type_name, at.color AS type_color,
                       at.duration_minutes
                FROM appointments a
                LEFT JOIN appointment_types at ON at.id = a.appointment_type_id
                {where}
                ORDER BY a.start_time DESC
                """,
                params,
            )
            appointments = cur.fetchall()

        return jsonify({"appointments": appointments})

    @bp.route("/api/appointments", methods=["POST"])
    @login_required
    @require_module("appointments")
    def book_appointment():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        start_time = data.get("start_time")
        appointment_type_id = data.get("appointment_type_id")

        if not title or not start_time or not appointment_type_id:
            return jsonify({"error": "title, start_time, and appointment_type_id are required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Fetch type to auto-set end_time
            cur.execute(
                "SELECT duration_minutes FROM appointment_types WHERE id = %s AND is_active = TRUE",
                (appointment_type_id,),
            )
            appt_type = cur.fetchone()
            if appt_type is None:
                return jsonify({"error": "appointment type not found"}), 404

            # Calculate end_time from duration
            if data.get("end_time"):
                end_time = data["end_time"]
            else:
                start_dt = datetime.fromisoformat(start_time)
                end_dt = start_dt + timedelta(minutes=appt_type["duration_minutes"])
                end_time = end_dt.isoformat()

            cur.execute(
                """
                INSERT INTO appointments
                    (customer_id, appointment_type_id, title, start_time, end_time, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, customer_id, appointment_type_id, title,
                          start_time, end_time, status, notes, metadata, created_at, updated_at
                """,
                (
                    data.get("customer_id"),
                    appointment_type_id,
                    title,
                    start_time,
                    end_time,
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            appointment = cur.fetchone()

        event_bus.emit(
            "appointment.booked",
            {
                "appointment_id": appointment["id"],
                "customer_id": appointment["customer_id"],
                "title": appointment["title"],
                "start_time": str(appointment["start_time"]),
            },
            tenant_id=g.tenant_id,
        )

        # Send confirmation email if customer has an email on file
        if appointment.get("customer_id"):
            try:
                with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
                    set_tenant_search_path(cur, g.tenant_id)
                    cur.execute(
                        "SELECT name, email FROM crm_customers WHERE id = %s",
                        (appointment["customer_id"],),
                    )
                    customer = cur.fetchone()
                    cur.execute(
                        "SELECT name, duration_minutes FROM appointment_types WHERE id = %s",
                        (appointment["appointment_type_id"],),
                    )
                    appt_type_row = cur.fetchone()

                if customer and customer.get("email") and appt_type_row:
                    start_dt = appointment["start_time"]
                    if isinstance(start_dt, str):
                        start_dt = datetime.fromisoformat(start_dt)

                    tenant_name = getattr(g, "tenant_name", "Our Business")
                    tenant_slug = getattr(g, "tenant_slug", "")

                    html_body, text_body = render_appointment_confirmation_email(
                        customer_name=customer["name"],
                        service_name=appt_type_row["name"],
                        appointment_date=start_dt.strftime("%B %d, %Y"),
                        appointment_time=start_dt.strftime("%-I:%M %p"),
                        duration_minutes=appt_type_row["duration_minutes"],
                        business_name=tenant_name,
                        booking_slug=tenant_slug,
                    )
                    send_email(
                        to=customer["email"],
                        subject=f"Appointment Confirmed — {appt_type_row['name']}",
                        body=text_body,
                        html_body=html_body,
                    )
            except Exception:
                logger.exception(
                    "Failed to send confirmation email for appointment %s",
                    appointment["id"],
                )

        return jsonify(appointment), 201

    @bp.route("/api/appointments/<int:appointment_id>", methods=["GET"])
    @login_required
    @require_module("appointments")
    def get_appointment(appointment_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT a.id, a.customer_id, a.appointment_type_id, a.title,
                       a.start_time, a.end_time, a.status, a.notes, a.metadata,
                       a.created_at, a.updated_at,
                       at.name AS type_name, at.color AS type_color,
                       at.duration_minutes
                FROM appointments a
                LEFT JOIN appointment_types at ON at.id = a.appointment_type_id
                WHERE a.id = %s
                """,
                (appointment_id,),
            )
            appointment = cur.fetchone()

        if appointment is None:
            return jsonify({"error": "appointment not found"}), 404
        return jsonify(appointment)

    @bp.route("/api/appointments/<int:appointment_id>", methods=["PUT"])
    @login_required
    @require_module("appointments")
    def update_appointment(appointment_id):
        data = request.get_json(force=True)

        allowed = ("title", "start_time", "end_time", "status", "notes", "customer_id", "appointment_type_id")
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

        sets.append("updated_at = NOW()")
        params.append(appointment_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE appointments SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, customer_id, appointment_type_id, title,
                          start_time, end_time, status, notes, metadata, created_at, updated_at
                """,
                params,
            )
            appointment = cur.fetchone()

        if appointment is None:
            return jsonify({"error": "appointment not found"}), 404
        return jsonify(appointment)

    @bp.route("/api/appointments/<int:appointment_id>/cancel", methods=["POST"])
    @login_required
    @require_module("appointments")
    def cancel_appointment(appointment_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE appointments SET status = 'cancelled', updated_at = NOW()
                WHERE id = %s
                RETURNING id, customer_id, title, status
                """,
                (appointment_id,),
            )
            appointment = cur.fetchone()

        if appointment is None:
            return jsonify({"error": "appointment not found"}), 404

        event_bus.emit(
            "appointment.cancelled",
            {
                "appointment_id": appointment["id"],
                "customer_id": appointment["customer_id"],
                "title": appointment["title"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(appointment)

    @bp.route("/api/appointments/<int:appointment_id>/complete", methods=["POST"])
    @login_required
    @require_module("appointments")
    def complete_appointment(appointment_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE appointments SET status = 'completed', updated_at = NOW()
                WHERE id = %s
                RETURNING id, customer_id, title, status
                """,
                (appointment_id,),
            )
            appointment = cur.fetchone()

        if appointment is None:
            return jsonify({"error": "appointment not found"}), 404

        event_bus.emit(
            "appointment.completed",
            {
                "appointment_id": appointment["id"],
                "customer_id": appointment["customer_id"],
                "title": appointment["title"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(appointment)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("appointments")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_appointments,
                    COUNT(*) FILTER (WHERE status IN ('scheduled', 'confirmed') AND start_time > NOW()) AS upcoming_count,
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                        AND start_time >= date_trunc('month', CURRENT_DATE)
                    ) AS completed_this_month,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE status = 'cancelled')
                        / NULLIF(COUNT(*), 0),
                        1
                    ) AS cancellation_rate
                FROM appointments
                """
            )
            row = cur.fetchone()

        return jsonify(row)


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------


def on_contact_created(data):
    """Placeholder — no action needed when a contact is created."""
    pass
