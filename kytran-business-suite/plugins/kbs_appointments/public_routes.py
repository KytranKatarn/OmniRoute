"""Public booking routes — no login required, tenant resolved by URL slug."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, abort, jsonify, render_template, request
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.mail_client import send_email
from core.email_templates import render_appointment_confirmation_email

logger = logging.getLogger(__name__)


def create_public_blueprint():
    """Create and return the public booking blueprint (no login required)."""
    public_bp = Blueprint(
        "appointments_public",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/appointments_public",
    )

    def _resolve_tenant_by_slug(slug):
        """Look up tenant by slug. Returns dict with id, name, slug, tier or None."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            cur.execute(
                """
                SELECT t.id, t.name, t.slug, t.tier
                FROM tenants t
                JOIN tenant_modules tm ON tm.tenant_id = t.id
                WHERE t.slug = %s
                  AND t.is_active = TRUE
                  AND tm.module_slug = 'appointments'
                  AND tm.enabled = TRUE
                """,
                (slug,),
            )
            return cur.fetchone()

    def _generate_cancel_token(appointment_id, tenant_id):
        """Generate a unique cancel token for an appointment."""
        raw = f"{appointment_id}-{tenant_id}-{secrets.token_hex(16)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Public booking page — shows available services and time slots
    # ------------------------------------------------------------------

    @public_bp.route("/<slug>")
    def booking_page(slug):
        """Render the public booking page for a given tenant slug."""
        tenant = _resolve_tenant_by_slug(slug)
        if tenant is None:
            abort(404)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])
            cur.execute(
                """
                SELECT id, name, description, duration_minutes, price, color
                FROM appointment_types
                WHERE is_active = TRUE
                ORDER BY name
                """
            )
            service_types = cur.fetchall()

            cur.execute(
                """
                SELECT id, day_of_week,
                       start_time::text AS start_time,
                       end_time::text AS end_time
                FROM availability_slots
                WHERE is_active = TRUE
                ORDER BY day_of_week, start_time
                """
            )
            availability = cur.fetchall()

        return render_template(
            "booking_public.html",
            tenant=tenant,
            service_types=service_types,
            availability=availability,
        )

    # ------------------------------------------------------------------
    # API: Available time slots for a given date and service type
    # ------------------------------------------------------------------

    @public_bp.route("/<slug>/api/slots")
    def available_slots(slug):
        """Return available time slots for a given date and service type.

        Query params:
            date: ISO date string (YYYY-MM-DD)
            type_id: appointment type ID
        """
        tenant = _resolve_tenant_by_slug(slug)
        if tenant is None:
            return jsonify({"error": "business not found"}), 404

        date_str = request.args.get("date")
        type_id = request.args.get("type_id", type=int)

        if not date_str or not type_id:
            return jsonify({"error": "date and type_id are required"}), 400

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "invalid date format, use YYYY-MM-DD"}), 400

        day_of_week = target_date.weekday()  # Monday=0, Sunday=6

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            # Get service duration
            cur.execute(
                "SELECT duration_minutes FROM appointment_types WHERE id = %s AND is_active = TRUE",
                (type_id,),
            )
            appt_type = cur.fetchone()
            if appt_type is None:
                return jsonify({"error": "service type not found"}), 404

            duration = appt_type["duration_minutes"]

            # Get availability windows for this day of week
            cur.execute(
                """
                SELECT start_time::text AS start_time, end_time::text AS end_time
                FROM availability_slots
                WHERE day_of_week = %s AND is_active = TRUE
                ORDER BY start_time
                """,
                (day_of_week,),
            )
            windows = cur.fetchall()

            if not windows:
                return jsonify({"slots": []})

            # Get existing appointments on this date to check conflicts
            cur.execute(
                """
                SELECT start_time, end_time
                FROM appointments
                WHERE start_time::date = %s
                  AND status NOT IN ('cancelled')
                ORDER BY start_time
                """,
                (date_str,),
            )
            booked = cur.fetchall()

        # Generate available slots in 30-minute increments
        slots = []
        for window in windows:
            window_start = datetime.strptime(window["start_time"], "%H:%M:%S").time()
            window_end = datetime.strptime(window["end_time"], "%H:%M:%S").time()

            current = datetime.combine(target_date, window_start)
            end_boundary = datetime.combine(target_date, window_end)

            while current + timedelta(minutes=duration) <= end_boundary:
                slot_end = current + timedelta(minutes=duration)

                # Check for conflicts with existing bookings
                conflict = False
                for booking in booked:
                    booked_start = booking["start_time"]
                    booked_end = booking["end_time"]
                    if isinstance(booked_start, str):
                        booked_start = datetime.fromisoformat(booked_start)
                    if isinstance(booked_end, str):
                        booked_end = datetime.fromisoformat(booked_end)
                    if current < booked_end and slot_end > booked_start:
                        conflict = True
                        break

                if not conflict:
                    slots.append(
                        {
                            "start_time": current.strftime("%H:%M"),
                            "end_time": slot_end.strftime("%H:%M"),
                        }
                    )

                current += timedelta(minutes=30)

        return jsonify({"slots": slots, "date": date_str, "duration_minutes": duration})

    # ------------------------------------------------------------------
    # API: Book an appointment (public, no login)
    # ------------------------------------------------------------------

    @public_bp.route("/<slug>/book", methods=["POST"])
    def book_appointment(slug):
        """Create an appointment from the public booking page.

        JSON body:
            customer_name: str (required)
            customer_email: str (required)
            customer_phone: str (optional)
            appointment_type_id: int (required)
            date: str YYYY-MM-DD (required)
            time: str HH:MM (required)
            notes: str (optional)
        """
        tenant = _resolve_tenant_by_slug(slug)
        if tenant is None:
            return jsonify({"error": "business not found"}), 404

        data = request.get_json(force=True)
        customer_name = (data.get("customer_name") or "").strip()
        customer_email = (data.get("customer_email") or "").strip()
        customer_phone = (data.get("customer_phone") or "").strip()
        type_id = data.get("appointment_type_id")
        date_str = data.get("date")
        time_str = data.get("time")

        if (
            not customer_name
            or not customer_email
            or not type_id
            or not date_str
            or not time_str
        ):
            return (
                jsonify(
                    {
                        "error": "customer_name, customer_email, appointment_type_id, date, and time are required"
                    }
                ),
                400,
            )

        try:
            start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify({"error": "invalid date/time format"}), 400

        if start_dt <= datetime.now():
            return jsonify({"error": "cannot book appointments in the past"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            # Verify the appointment type exists
            cur.execute(
                "SELECT id, name, duration_minutes, price FROM appointment_types WHERE id = %s AND is_active = TRUE",
                (type_id,),
            )
            appt_type = cur.fetchone()
            if appt_type is None:
                return jsonify({"error": "service type not found"}), 404

            end_dt = start_dt + timedelta(minutes=appt_type["duration_minutes"])

            # Check for time slot conflicts
            cur.execute(
                """
                SELECT id FROM appointments
                WHERE status NOT IN ('cancelled')
                  AND start_time < %s
                  AND end_time > %s
                LIMIT 1
                """,
                (end_dt.isoformat(), start_dt.isoformat()),
            )
            if cur.fetchone():
                return (
                    jsonify({"error": "this time slot is no longer available"}),
                    409,
                )

            # Find or create CRM customer
            cur.execute(
                "SELECT id FROM crm_customers WHERE email = %s LIMIT 1",
                (customer_email,),
            )
            customer_row = cur.fetchone()
            if customer_row:
                customer_id = customer_row["id"]
            else:
                cur.execute(
                    """
                    INSERT INTO crm_customers (name, email, phone, source, status)
                    VALUES (%s, %s, %s, 'booking_page', 'lead')
                    RETURNING id
                    """,
                    (customer_name, customer_email, customer_phone or None),
                )
                customer_id = cur.fetchone()["id"]

            # Generate cancel token
            cancel_token = _generate_cancel_token(0, tenant["id"])

            # Create the appointment
            title = f"{appt_type['name']} — {customer_name}"
            cur.execute(
                """
                INSERT INTO appointments
                    (customer_id, appointment_type_id, title, start_time, end_time,
                     status, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, 'confirmed', %s, %s)
                RETURNING id, customer_id, appointment_type_id, title,
                          start_time, end_time, status, notes, metadata,
                          created_at, updated_at
                """,
                (
                    customer_id,
                    type_id,
                    title,
                    start_dt.isoformat(),
                    end_dt.isoformat(),
                    data.get("notes"),
                    Json(
                        {
                            "booked_via": "public_page",
                            "customer_email": customer_email,
                            "customer_phone": customer_phone,
                            "cancel_token": cancel_token,
                        }
                    ),
                ),
            )
            appointment = cur.fetchone()

        # Emit event for other plugins (e.g. CRM activity log)
        event_bus.emit(
            "appointment.booked",
            {
                "appointment_id": appointment["id"],
                "customer_id": customer_id,
                "title": appointment["title"],
                "start_time": str(appointment["start_time"]),
                "booked_via": "public_page",
            },
            tenant_id=tenant["id"],
        )

        # Send confirmation email
        try:
            html_body, text_body = render_appointment_confirmation_email(
                customer_name=customer_name,
                service_name=appt_type["name"],
                appointment_date=start_dt.strftime("%B %d, %Y"),
                appointment_time=start_dt.strftime("%-I:%M %p"),
                duration_minutes=appt_type["duration_minutes"],
                business_name=tenant["name"],
                booking_slug=slug,
                cancel_token=cancel_token,
            )
            send_email(
                to=customer_email,
                subject=f"Appointment Confirmed — {appt_type['name']}",
                body=text_body,
                html_body=html_body,
            )
        except Exception:
            logger.exception(
                "Failed to send booking confirmation email to %s", customer_email
            )

        return (
            jsonify(
                {
                    "appointment_id": appointment["id"],
                    "title": appointment["title"],
                    "start_time": str(appointment["start_time"]),
                    "end_time": str(appointment["end_time"]),
                    "status": appointment["status"],
                    "message": "Appointment booked successfully! A confirmation email has been sent.",
                }
            ),
            201,
        )

    # ------------------------------------------------------------------
    # API: Cancel via token (public, no login)
    # ------------------------------------------------------------------

    @public_bp.route("/<slug>/cancel", methods=["GET", "POST"])
    def cancel_by_token(slug):
        """Cancel an appointment using a cancel token (from confirmation email)."""
        tenant = _resolve_tenant_by_slug(slug)
        if tenant is None:
            abort(404)

        token = request.args.get("token") or (
            request.get_json(force=True) or {}
        ).get("token")
        if not token:
            return jsonify({"error": "cancel token is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])
            cur.execute(
                """
                SELECT id, customer_id, title, status
                FROM appointments
                WHERE metadata->>'cancel_token' = %s
                  AND status NOT IN ('cancelled', 'completed')
                LIMIT 1
                """,
                (token,),
            )
            appointment = cur.fetchone()

            if appointment is None:
                return (
                    jsonify({"error": "appointment not found or already cancelled"}),
                    404,
                )

            cur.execute(
                """
                UPDATE appointments SET status = 'cancelled', updated_at = NOW()
                WHERE id = %s
                RETURNING id, title, status
                """,
                (appointment["id"],),
            )
            updated = cur.fetchone()

        event_bus.emit(
            "appointment.cancelled",
            {
                "appointment_id": updated["id"],
                "customer_id": appointment["customer_id"],
                "title": updated["title"],
                "cancelled_via": "public_cancel_link",
            },
            tenant_id=tenant["id"],
        )

        if request.method == "GET":
            return render_template(
                "booking_public.html",
                tenant=tenant,
                service_types=[],
                availability=[],
                cancel_success=True,
                cancelled_title=updated["title"],
            )
        return jsonify({"cancelled": True, "appointment_id": updated["id"]})

    return public_bp
