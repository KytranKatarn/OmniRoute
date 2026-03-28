# KBS Wave 1 Plan B: Appointments — Public Booking + Notifications

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public-facing booking page (no login required), an embeddable booking widget, and transactional email notifications (confirmation on booking + reminder before appointment) to the existing Appointments plugin.

**Architecture:** The public booking page is a separate Flask Blueprint (`public_bp`) registered without `@login_required`. Tenant context is resolved by URL slug (`/{slug}`) via a DB lookup on the `tenants` table. Email templates follow the existing LCARS-styled `render_*` pattern in `core/email_templates.py`. The embeddable widget is a static JS file that creates an iframe pointing at the public booking page. Reminder emails are sent by a background scheduler job.

**Tech Stack:** Flask, PostgreSQL, psycopg2, pytest

**Spec:** `docs/superpowers/specs/2026-03-28-kbs-completion-saas-resale-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `core/email_templates.py` | Add appointment confirmation + reminder templates |
| Create | `plugins/kbs_appointments/public_routes.py` | Public booking page — no login, tenant by slug |
| Create | `plugins/kbs_appointments/templates/booking_public.html` | Public-facing booking page template |
| Create | `plugins/kbs_appointments/static/booking-widget.js` | Embeddable JS widget (iframe loader) |
| Modify | `plugins/kbs_appointments/__init__.py` | Register public blueprint |
| Modify | `plugins/kbs_appointments/routes.py` | Wire confirmation email into existing booking route |
| Create | `tests/test_appointment_emails.py` | Email template rendering tests |
| Create | `tests/test_appointment_public_booking.py` | Public booking flow integration tests |

---

## Task 1: Appointment Email Templates

**Files:**
- Modify: `core/email_templates.py`
- Create: `tests/test_appointment_emails.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_appointment_emails.py`:

```python
"""Tests for appointment email templates — confirmation and reminder."""

import pytest


def test_appointment_confirmation_email_contains_key_fields():
    from core.email_templates import render_appointment_confirmation_email

    html, text = render_appointment_confirmation_email(
        customer_name="Alice Johnson",
        service_name="Initial Consultation",
        appointment_date="April 1, 2026",
        appointment_time="10:00 AM",
        duration_minutes=45,
        business_name="Kytran Empowerment Inc.",
        booking_slug="kytran-emp",
    )

    assert "Alice Johnson" in html
    assert "Initial Consultation" in html
    assert "April 1, 2026" in html
    assert "10:00 AM" in html
    assert "45" in html
    assert "Kytran Empowerment" in html

    assert "Alice Johnson" in text
    assert "Initial Consultation" in text
    assert "April 1, 2026" in text
    assert "10:00 AM" in text


def test_appointment_confirmation_email_cancel_link():
    from core.email_templates import render_appointment_confirmation_email

    html, text = render_appointment_confirmation_email(
        customer_name="Bob",
        service_name="Checkup",
        appointment_date="April 2, 2026",
        appointment_time="2:00 PM",
        duration_minutes=30,
        business_name="Test Biz",
        booking_slug="test-biz",
        cancel_token="abc123",
    )

    assert "abc123" in html
    assert "cancel" in html.lower()


def test_appointment_reminder_email_contains_key_fields():
    from core.email_templates import render_appointment_reminder_email

    html, text = render_appointment_reminder_email(
        customer_name="Carol Davis",
        service_name="Follow-Up Session",
        appointment_date="April 5, 2026",
        appointment_time="3:30 PM",
        duration_minutes=60,
        business_name="Kytran Empowerment Inc.",
        hours_until=24,
    )

    assert "Carol Davis" in html
    assert "Follow-Up Session" in html
    assert "April 5, 2026" in html
    assert "3:30 PM" in html
    assert "24" in html
    assert "Kytran Empowerment" in html

    assert "Carol Davis" in text
    assert "Follow-Up Session" in text
    assert "24" in text


def test_appointment_reminder_email_pluralizes_hours():
    from core.email_templates import render_appointment_reminder_email

    html, text = render_appointment_reminder_email(
        customer_name="Dan",
        service_name="Massage",
        appointment_date="April 6, 2026",
        appointment_time="9:00 AM",
        duration_minutes=90,
        business_name="Test Spa",
        hours_until=1,
    )

    assert "1 hour" in text
    assert "1 hours" not in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_appointment_emails.py -v
```

Expected: FAIL with `ImportError: cannot import name 'render_appointment_confirmation_email'`

- [ ] **Step 3: Add the confirmation template to core/email_templates.py**

Append to the end of `core/email_templates.py`:

```python
def render_appointment_confirmation_email(
    customer_name: str,
    service_name: str,
    appointment_date: str,
    appointment_time: str,
    duration_minutes: int,
    business_name: str,
    booking_slug: str,
    cancel_token: str | None = None,
) -> tuple[str, str]:
    """Render appointment booking confirmation email. Returns (html, plain_text)."""
    cancel_section_html = ""
    cancel_section_text = ""
    if cancel_token:
        cancel_section_html = f"""
  <p style="margin-top: 20px;">
    Need to cancel?
    <a href="https://book.kytranempowerment.com/{booking_slug}/cancel?token={cancel_token}"
       style="color: #ef4444;">Cancel this appointment</a>
  </p>"""
        cancel_section_text = (
            f"\nNeed to cancel? Visit: "
            f"https://book.kytranempowerment.com/{booking_slug}/cancel?token={cancel_token}"
        )

    html = f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d0d1a; color: #e0e0e0; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #1a1a2e; border-radius: 8px; border: 1px solid #00e5ff33; padding: 30px; }}
  .header {{ color: #00e5ff; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
  .highlight {{ color: #00e5ff; font-weight: bold; }}
  .detail-row {{ margin: 8px 0; }}
  .label {{ color: #888; display: inline-block; width: 100px; }}
  .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #333; font-size: 12px; color: #888; }}
</style></head>
<body>
<div class="container">
  <div class="header">{business_name}</div>
  <p>Hi {customer_name},</p>
  <p>Your appointment has been <span class="highlight">confirmed</span>!</p>
  <div style="background: #0d0d1a; border-radius: 6px; padding: 16px; margin: 20px 0; border-left: 3px solid #00e5ff;">
    <div class="detail-row"><span class="label">Service:</span> <strong>{service_name}</strong></div>
    <div class="detail-row"><span class="label">Date:</span> <strong>{appointment_date}</strong></div>
    <div class="detail-row"><span class="label">Time:</span> <strong>{appointment_time}</strong></div>
    <div class="detail-row"><span class="label">Duration:</span> <strong>{duration_minutes} minutes</strong></div>
  </div>
  <p>We look forward to seeing you!</p>{cancel_section_html}
  <div class="footer">Booked via {business_name}</div>
</div>
</body>
</html>"""

    text = f"""Hi {customer_name},

Your appointment has been confirmed!

Service:  {service_name}
Date:     {appointment_date}
Time:     {appointment_time}
Duration: {duration_minutes} minutes

We look forward to seeing you!
{cancel_section_text}
— {business_name}"""

    return html, text


def render_appointment_reminder_email(
    customer_name: str,
    service_name: str,
    appointment_date: str,
    appointment_time: str,
    duration_minutes: int,
    business_name: str,
    hours_until: int,
) -> tuple[str, str]:
    """Render appointment reminder email. Returns (html, plain_text)."""
    hour_word = "hour" if hours_until == 1 else "hours"

    html = f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d0d1a; color: #e0e0e0; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #1a1a2e; border-radius: 8px; border: 1px solid #00e5ff33; padding: 30px; }}
  .header {{ color: #00e5ff; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
  .highlight {{ color: #00e5ff; font-weight: bold; }}
  .reminder-badge {{ display: inline-block; background: #fbbf24; color: #0d0d1a; padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: 14px; margin-bottom: 16px; }}
  .detail-row {{ margin: 8px 0; }}
  .label {{ color: #888; display: inline-block; width: 100px; }}
  .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #333; font-size: 12px; color: #888; }}
</style></head>
<body>
<div class="container">
  <div class="header">{business_name}</div>
  <div class="reminder-badge">Reminder: {hours_until} {hour_word} away</div>
  <p>Hi {customer_name},</p>
  <p>This is a friendly reminder about your upcoming appointment:</p>
  <div style="background: #0d0d1a; border-radius: 6px; padding: 16px; margin: 20px 0; border-left: 3px solid #fbbf24;">
    <div class="detail-row"><span class="label">Service:</span> <strong>{service_name}</strong></div>
    <div class="detail-row"><span class="label">Date:</span> <strong>{appointment_date}</strong></div>
    <div class="detail-row"><span class="label">Time:</span> <strong>{appointment_time}</strong></div>
    <div class="detail-row"><span class="label">Duration:</span> <strong>{duration_minutes} minutes</strong></div>
  </div>
  <p>We look forward to seeing you!</p>
  <div class="footer">Sent by {business_name}</div>
</div>
</body>
</html>"""

    text = f"""Hi {customer_name},

Reminder: Your appointment is in {hours_until} {hour_word}!

Service:  {service_name}
Date:     {appointment_date}
Time:     {appointment_time}
Duration: {duration_minutes} minutes

We look forward to seeing you!

— {business_name}"""

    return html, text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_appointment_emails.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/email_templates.py tests/test_appointment_emails.py
git commit -m "feat(appointments): add confirmation and reminder email templates"
```

---

## Task 2: Public Booking Page Blueprint

**Files:**
- Create: `plugins/kbs_appointments/public_routes.py`
- Create: `plugins/kbs_appointments/templates/booking_public.html`

- [ ] **Step 1: Create the public routes module**

Create `plugins/kbs_appointments/public_routes.py`:

```python
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
                    slots.append({
                        "start_time": current.strftime("%H:%M"),
                        "end_time": slot_end.strftime("%H:%M"),
                    })

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

        if not customer_name or not customer_email or not type_id or not date_str or not time_str:
            return jsonify({
                "error": "customer_name, customer_email, appointment_type_id, date, and time are required"
            }), 400

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
                return jsonify({"error": "this time slot is no longer available"}), 409

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
                    Json({
                        "booked_via": "public_page",
                        "customer_email": customer_email,
                        "customer_phone": customer_phone,
                        "cancel_token": cancel_token,
                    }),
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
            logger.exception("Failed to send booking confirmation email to %s", customer_email)

        return jsonify({
            "appointment_id": appointment["id"],
            "title": appointment["title"],
            "start_time": str(appointment["start_time"]),
            "end_time": str(appointment["end_time"]),
            "status": appointment["status"],
            "message": "Appointment booked successfully! A confirmation email has been sent.",
        }), 201

    # ------------------------------------------------------------------
    # API: Cancel via token (public, no login)
    # ------------------------------------------------------------------

    @public_bp.route("/<slug>/cancel", methods=["GET", "POST"])
    def cancel_by_token(slug):
        """Cancel an appointment using a cancel token (from confirmation email)."""
        tenant = _resolve_tenant_by_slug(slug)
        if tenant is None:
            abort(404)

        token = request.args.get("token") or (request.get_json(force=True) or {}).get("token")
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
                return jsonify({"error": "appointment not found or already cancelled"}), 404

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
```

- [ ] **Step 2: Create the public booking HTML template**

Create `plugins/kbs_appointments/templates/booking_public.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Book an Appointment — {{ tenant.name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: #0d0d1a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .booking-container {
            max-width: 720px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        .booking-header {
            text-align: center;
            margin-bottom: 40px;
        }
        .booking-header h1 {
            color: #00e5ff;
            font-size: 28px;
            margin-bottom: 8px;
        }
        .booking-header p {
            color: #888;
            font-size: 14px;
        }

        /* Cancel success banner */
        .cancel-banner {
            background: #1a2e1a;
            border: 1px solid #22c55e44;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            margin-bottom: 30px;
        }
        .cancel-banner h2 { color: #22c55e; margin-bottom: 8px; }

        /* Step indicator */
        .steps { display: flex; gap: 8px; margin-bottom: 30px; justify-content: center; }
        .step {
            width: 32px; height: 32px; border-radius: 50%;
            background: #1a1a2e; border: 2px solid #333;
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: bold; color: #888;
            transition: all 0.3s;
        }
        .step.active { border-color: #00e5ff; color: #00e5ff; background: #00e5ff11; }
        .step.done { border-color: #22c55e; color: #22c55e; background: #22c55e11; }

        /* Service cards */
        .services-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }
        .service-card {
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .service-card:hover { border-color: #00e5ff; transform: translateY(-2px); }
        .service-card.selected { border-color: #00e5ff; background: #00e5ff11; }
        .service-card h3 { color: #fff; margin-bottom: 6px; }
        .service-card .meta { color: #888; font-size: 13px; }
        .service-card .price { color: #00e5ff; font-weight: bold; font-size: 18px; margin-top: 8px; }

        /* Date picker */
        .date-section, .time-section, .info-section { margin-bottom: 30px; }
        .section-title { color: #00e5ff; font-size: 18px; margin-bottom: 16px; }
        input[type="date"], input[type="text"], input[type="email"], input[type="tel"], textarea {
            width: 100%;
            padding: 12px;
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 15px;
            margin-bottom: 12px;
        }
        input:focus, textarea:focus { outline: none; border-color: #00e5ff; }

        /* Time slots */
        .time-slots {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
            gap: 8px;
        }
        .time-slot {
            padding: 10px;
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 6px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }
        .time-slot:hover { border-color: #00e5ff; }
        .time-slot.selected { border-color: #00e5ff; background: #00e5ff22; color: #00e5ff; font-weight: bold; }

        /* Buttons */
        .btn-book {
            display: block;
            width: 100%;
            padding: 14px;
            background: #00e5ff;
            color: #0d0d1a;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.2s;
        }
        .btn-book:hover { background: #00c4d9; }
        .btn-book:disabled { background: #333; color: #666; cursor: not-allowed; }

        /* Success message */
        .success-panel {
            background: #1a2e1a;
            border: 1px solid #22c55e44;
            border-radius: 8px;
            padding: 30px;
            text-align: center;
            display: none;
        }
        .success-panel h2 { color: #22c55e; margin-bottom: 12px; }
        .success-panel .checkmark { font-size: 48px; margin-bottom: 16px; }

        .error-msg { color: #ef4444; font-size: 13px; margin-bottom: 8px; display: none; }
        .loading { opacity: 0.5; pointer-events: none; }

        @media (max-width: 480px) {
            .booking-container { padding: 20px 12px; }
            .services-grid { grid-template-columns: 1fr; }
            .time-slots { grid-template-columns: repeat(3, 1fr); }
        }
    </style>
</head>
<body>
    <div class="booking-container">
        <div class="booking-header">
            <h1>{{ tenant.name }}</h1>
            <p>Book an appointment online</p>
        </div>

        {% if cancel_success %}
        <div class="cancel-banner">
            <h2>Appointment Cancelled</h2>
            <p>{{ cancelled_title }} has been cancelled successfully.</p>
        </div>
        {% endif %}

        <div class="steps">
            <div class="step active" id="step-1">1</div>
            <div class="step" id="step-2">2</div>
            <div class="step" id="step-3">3</div>
        </div>

        <!-- Step 1: Choose service -->
        <div id="panel-service">
            <div class="section-title">Choose a service</div>
            <div class="services-grid">
                {% for svc in service_types %}
                <div class="service-card" data-type-id="{{ svc.id }}" data-duration="{{ svc.duration_minutes }}"
                     onclick="selectService(this)">
                    <h3>{{ svc.name }}</h3>
                    {% if svc.description %}<p class="meta">{{ svc.description }}</p>{% endif %}
                    <p class="meta">{{ svc.duration_minutes }} min</p>
                    {% if svc.price %}<div class="price">${{ "%.2f"|format(svc.price) }}</div>{% endif %}
                </div>
                {% endfor %}
            </div>
        </div>

        <!-- Step 2: Choose date + time -->
        <div id="panel-datetime" style="display:none;">
            <div class="date-section">
                <div class="section-title">Choose a date</div>
                <input type="date" id="booking-date" onchange="loadSlots()">
            </div>
            <div class="time-section">
                <div class="section-title">Available times</div>
                <div class="time-slots" id="time-slots-container">
                    <p class="meta">Select a date to see available times.</p>
                </div>
            </div>
        </div>

        <!-- Step 3: Your info -->
        <div id="panel-info" style="display:none;">
            <div class="section-title">Your information</div>
            <input type="text" id="cust-name" placeholder="Full name" required>
            <input type="email" id="cust-email" placeholder="Email address" required>
            <input type="tel" id="cust-phone" placeholder="Phone (optional)">
            <textarea id="cust-notes" placeholder="Notes (optional)" rows="3"></textarea>
            <div class="error-msg" id="book-error"></div>
            <button class="btn-book" id="btn-confirm" onclick="submitBooking()">Confirm Booking</button>
        </div>

        <!-- Success -->
        <div class="success-panel" id="panel-success">
            <div class="checkmark">&#10003;</div>
            <h2>Booking Confirmed!</h2>
            <p id="success-details"></p>
            <p style="margin-top:12px; color:#888; font-size:13px;">A confirmation email has been sent to your inbox.</p>
        </div>
    </div>

    <script>
        var SLUG = "{{ tenant.slug }}";
        var selectedTypeId = null;
        var selectedTime = null;

        function selectService(el) {
            document.querySelectorAll('.service-card').forEach(function(c) { c.classList.remove('selected'); });
            el.classList.add('selected');
            selectedTypeId = parseInt(el.dataset.typeId);
            document.getElementById('step-1').classList.add('done');
            document.getElementById('step-2').classList.add('active');
            document.getElementById('panel-datetime').style.display = 'block';
            var today = new Date().toISOString().split('T')[0];
            document.getElementById('booking-date').min = today;
            document.getElementById('booking-date').value = today;
            loadSlots();
        }

        function loadSlots() {
            var dateVal = document.getElementById('booking-date').value;
            if (!dateVal || !selectedTypeId) return;
            var container = document.getElementById('time-slots-container');
            container.textContent = 'Loading...';
            selectedTime = null;

            fetch('/' + SLUG + '/api/slots?date=' + dateVal + '&type_id=' + selectedTypeId)
                .then(function(resp) { return resp.json(); })
                .then(function(data) {
                    if (!data.slots || data.slots.length === 0) {
                        container.textContent = 'No available times on this date.';
                        return;
                    }
                    container.textContent = '';
                    data.slots.forEach(function(s) {
                        var div = document.createElement('div');
                        div.className = 'time-slot';
                        div.dataset.time = s.start_time;
                        div.textContent = s.start_time;
                        div.onclick = function() { selectTime(div); };
                        container.appendChild(div);
                    });
                })
                .catch(function() {
                    container.textContent = 'Failed to load times.';
                });
        }

        function selectTime(el) {
            document.querySelectorAll('.time-slot').forEach(function(s) { s.classList.remove('selected'); });
            el.classList.add('selected');
            selectedTime = el.dataset.time;
            document.getElementById('step-2').classList.add('done');
            document.getElementById('step-3').classList.add('active');
            document.getElementById('panel-info').style.display = 'block';
        }

        function submitBooking() {
            var name = document.getElementById('cust-name').value.trim();
            var email = document.getElementById('cust-email').value.trim();
            var phone = document.getElementById('cust-phone').value.trim();
            var notes = document.getElementById('cust-notes').value.trim();
            var dateVal = document.getElementById('booking-date').value;
            var errEl = document.getElementById('book-error');
            errEl.style.display = 'none';

            if (!name || !email) {
                errEl.textContent = 'Name and email are required.';
                errEl.style.display = 'block';
                return;
            }

            var btn = document.getElementById('btn-confirm');
            btn.disabled = true;
            btn.textContent = 'Booking...';

            fetch('/' + SLUG + '/book', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    customer_name: name,
                    customer_email: email,
                    customer_phone: phone,
                    appointment_type_id: selectedTypeId,
                    date: dateVal,
                    time: selectedTime,
                    notes: notes || null
                })
            })
            .then(function(resp) { return resp.json().then(function(d) { return {ok: resp.ok, data: d}; }); })
            .then(function(result) {
                if (!result.ok) {
                    errEl.textContent = result.data.error || 'Booking failed.';
                    errEl.style.display = 'block';
                    btn.disabled = false;
                    btn.textContent = 'Confirm Booking';
                    return;
                }
                document.getElementById('step-3').classList.add('done');
                document.getElementById('panel-service').style.display = 'none';
                document.getElementById('panel-datetime').style.display = 'none';
                document.getElementById('panel-info').style.display = 'none';
                document.getElementById('panel-success').style.display = 'block';
                document.getElementById('success-details').textContent = result.data.message;
            })
            .catch(function() {
                errEl.textContent = 'Network error. Please try again.';
                errEl.style.display = 'block';
                btn.disabled = false;
                btn.textContent = 'Confirm Booking';
            });
        }
    </script>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_appointments/public_routes.py plugins/kbs_appointments/templates/booking_public.html
git commit -m "feat(appointments): add public booking page with slot selection and booking flow"
```

---

## Task 3: Register Public Blueprint in __init__.py

**Files:**
- Modify: `plugins/kbs_appointments/__init__.py`

- [ ] **Step 1: Update __init__.py to register the public blueprint**

Replace the contents of `plugins/kbs_appointments/__init__.py` with:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "appointments",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/appointments",
    )
    from plugins.kbs_appointments.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_appointments.routes import on_contact_created

    event_bus.on("contact.created")(on_contact_created)

    return bp


def create_public_blueprint():
    """Return the public booking blueprint (no login required).

    Called by the app factory to register routes at /<slug> for public booking.
    """
    from plugins.kbs_appointments.public_routes import create_public_blueprint as _create

    return _create()
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_appointments/__init__.py
git commit -m "feat(appointments): register public booking blueprint in plugin init"
```

---

## Task 4: Embeddable Booking Widget

**Files:**
- Create: `plugins/kbs_appointments/static/booking-widget.js`

- [ ] **Step 1: Create the widget script**

Create `plugins/kbs_appointments/static/booking-widget.js`:

```javascript
/**
 * Kytran Business Suite — Embeddable Booking Widget
 *
 * Usage:
 *   <div id="kbs-booking"></div>
 *   <script src="https://book.kytranempowerment.com/static/appointments_public/booking-widget.js"
 *           data-slug="your-business-slug"
 *           data-accent="#00e5ff"
 *           data-width="100%"
 *           data-height="700px">
 *   </script>
 *
 * Or programmatically:
 *   KBSBooking.init({ slug: 'your-slug', target: '#my-container' });
 */
(function () {
    "use strict";

    var BOOKING_HOST = "https://book.kytranempowerment.com";

    function getScriptData() {
        var scripts = document.getElementsByTagName("script");
        var current = scripts[scripts.length - 1];
        return {
            slug: current.getAttribute("data-slug") || "",
            accent: current.getAttribute("data-accent") || "#00e5ff",
            width: current.getAttribute("data-width") || "100%",
            height: current.getAttribute("data-height") || "700px",
            target: current.getAttribute("data-target") || "kbs-booking",
        };
    }

    function createIframe(config) {
        var container = document.getElementById(config.target);
        if (!container) {
            console.error("[KBS Booking] Target element #" + config.target + " not found.");
            return;
        }

        if (!config.slug) {
            console.error("[KBS Booking] data-slug attribute is required.");
            return;
        }

        var iframe = document.createElement("iframe");
        iframe.src = BOOKING_HOST + "/" + config.slug + "?embed=1";
        iframe.style.width = config.width;
        iframe.style.height = config.height;
        iframe.style.border = "none";
        iframe.style.borderRadius = "8px";
        iframe.style.overflow = "hidden";
        iframe.setAttribute("loading", "lazy");
        iframe.setAttribute("title", "Book an appointment");
        iframe.setAttribute("allow", "payment");

        container.appendChild(iframe);

        // Listen for resize messages from the iframe
        window.addEventListener("message", function (e) {
            if (e.data && e.data.type === "kbs-booking-resize") {
                iframe.style.height = e.data.height + "px";
            }
        });
    }

    // Auto-initialize when script is loaded with data attributes
    var config = getScriptData();
    if (config.slug) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", function () {
                createIframe(config);
            });
        } else {
            createIframe(config);
        }
    }

    // Expose public API
    window.KBSBooking = {
        init: function (opts) {
            createIframe({
                slug: opts.slug || "",
                accent: opts.accent || "#00e5ff",
                width: opts.width || "100%",
                height: opts.height || "700px",
                target: (opts.target || "#kbs-booking").replace("#", ""),
            });
        },
    };
})();
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_appointments/static/booking-widget.js
git commit -m "feat(appointments): add embeddable booking widget script"
```

---

## Task 5: Wire Confirmation Email into Existing Booking Route

**Files:**
- Modify: `plugins/kbs_appointments/routes.py`

- [ ] **Step 1: Add email imports at the top of routes.py**

Add these imports after the existing `from core.event_bus import event_bus` line:

```python
from core.mail_client import send_email
from core.email_templates import render_appointment_confirmation_email
```

- [ ] **Step 2: Add confirmation email send after event_bus.emit in book_appointment**

After the `event_bus.emit(...)` block in the `book_appointment` function (which ends just before `return jsonify(appointment), 201`), insert the following code before the return statement:

```python
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
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_appointments/routes.py
git commit -m "feat(appointments): wire confirmation email into authenticated booking route"
```

---

## Task 6: Public Booking Integration Tests

**Files:**
- Create: `tests/test_appointment_public_booking.py`

- [ ] **Step 1: Write the integration tests**

Create `tests/test_appointment_public_booking.py`:

```python
"""Tests for public booking page — no login required, tenant by slug."""

import json
import os

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    run_migration_file,
    set_tenant_search_path,
)

TEST_TENANT_ID = 9903
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_SLUG = "public-booking-test"

CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "kbs_crm",
    "migrations",
    "001_crm_tables.sql",
)
APPT_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "kbs_appointments",
    "migrations",
    "001_appointments_tables.sql",
)


@pytest.fixture(scope="module")
def public_app():
    """Create the Flask app with the public booking blueprint registered."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    # Register public booking blueprint at root
    from plugins.kbs_appointments import create_public_blueprint

    public_bp = create_public_blueprint()
    application.register_blueprint(public_bp)

    return application


@pytest.fixture(scope="module")
def public_setup(public_app):
    """Create test tenant, schema, and tables for public booking tests."""
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Cleanup leftovers
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Public Booking Test Biz', %s, 'business', TRUE)
            """,
            (TEST_TENANT_ID, TEST_SLUG),
        )

        # Enable appointments module
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'appointments', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    # Create schema and run migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(APPT_MIGRATION_PATH, schema=TEST_SCHEMA)

    # Seed a service type and availability
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute(
            """
            INSERT INTO appointment_types (name, description, duration_minutes, price, is_active)
            VALUES ('Test Consultation', 'A test service', 30, 50.00, TRUE)
            RETURNING id
            """
        )
        type_id = cur.fetchone()["id"]

        # Add availability for all weekdays (Monday-Friday, 09:00-17:00)
        for dow in range(0, 5):
            cur.execute(
                """
                INSERT INTO availability_slots (day_of_week, start_time, end_time, is_active)
                VALUES (%s, '09:00', '17:00', TRUE)
                """,
                (dow,),
            )

    yield {"tenant_id": TEST_TENANT_ID, "slug": TEST_SLUG, "type_id": type_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))


@pytest.fixture()
def client(public_app, public_setup):
    """Yield a plain (unauthenticated) test client."""
    with public_app.test_client() as c:
        yield c


# ======================================================================
# Tests
# ======================================================================


class TestPublicBookingPage:
    """Tests for the public booking page rendering."""

    def test_booking_page_renders(self, client, public_setup):
        resp = client.get(f"/{public_setup['slug']}")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Public Booking Test Biz" in html
        assert "Test Consultation" in html

    def test_booking_page_404_for_unknown_slug(self, client):
        resp = client.get("/nonexistent-slug-12345")
        assert resp.status_code == 404


class TestAvailableSlots:
    """Tests for the available time slots API."""

    def test_get_available_slots(self, client, public_setup):
        # Pick a future Monday (day_of_week=0)
        from datetime import date, timedelta

        today = date.today()
        days_until_monday = (0 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)

        resp = client.get(
            f"/{public_setup['slug']}/api/slots"
            f"?date={next_monday.isoformat()}&type_id={public_setup['type_id']}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "slots" in data
        # 30-min service in 9:00-17:00 window should produce multiple slots
        assert len(data["slots"]) >= 1

    def test_get_slots_missing_params(self, client, public_setup):
        resp = client.get(f"/{public_setup['slug']}/api/slots")
        assert resp.status_code == 400

    def test_get_slots_invalid_date(self, client, public_setup):
        resp = client.get(
            f"/{public_setup['slug']}/api/slots?date=not-a-date&type_id={public_setup['type_id']}"
        )
        assert resp.status_code == 400


class TestPublicBooking:
    """Tests for the public booking POST endpoint."""

    def _future_monday(self):
        from datetime import date, timedelta

        today = date.today()
        days_until_monday = (0 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return today + timedelta(days=days_until_monday)

    def test_book_appointment_success(self, client, public_setup):
        monday = self._future_monday()
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({
                "customer_name": "Test User",
                "customer_email": "testuser@example.com",
                "appointment_type_id": public_setup["type_id"],
                "date": monday.isoformat(),
                "time": "10:00",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "confirmed"
        assert "appointment_id" in data
        assert "confirmation" in data["message"].lower() or "booked" in data["message"].lower()

    def test_book_appointment_creates_crm_customer(self, client, public_setup):
        monday = self._future_monday()
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({
                "customer_name": "New Lead",
                "customer_email": "newlead@example.com",
                "customer_phone": "555-1234",
                "appointment_type_id": public_setup["type_id"],
                "date": monday.isoformat(),
                "time": "14:00",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201

        # Verify CRM customer was created
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, public_setup["tenant_id"])
            cur.execute(
                "SELECT name, email, source FROM crm_customers WHERE email = 'newlead@example.com'"
            )
            customer = cur.fetchone()
            assert customer is not None
            assert customer["name"] == "New Lead"
            assert customer["source"] == "booking_page"

    def test_book_appointment_missing_fields(self, client, public_setup):
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({"customer_name": "Incomplete"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_book_appointment_conflict(self, client, public_setup):
        monday = self._future_monday()
        # Book the 11:00 slot
        client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({
                "customer_name": "First Booker",
                "customer_email": "first@example.com",
                "appointment_type_id": public_setup["type_id"],
                "date": monday.isoformat(),
                "time": "11:00",
            }),
            content_type="application/json",
        )
        # Try to book the same 11:00 slot again
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({
                "customer_name": "Second Booker",
                "customer_email": "second@example.com",
                "appointment_type_id": public_setup["type_id"],
                "date": monday.isoformat(),
                "time": "11:00",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_book_appointment_unknown_slug(self, client):
        resp = client.post(
            "/fake-slug-xyz/book",
            data=json.dumps({
                "customer_name": "Nobody",
                "customer_email": "nobody@example.com",
                "appointment_type_id": 1,
                "date": "2026-04-07",
                "time": "10:00",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 404


class TestCancelByToken:
    """Tests for the public cancel-by-token endpoint."""

    def test_cancel_by_token(self, client, public_setup):
        from datetime import date, timedelta

        monday = date.today() + timedelta(days=(0 - date.today().weekday()) % 7 or 7)

        # Book an appointment
        book_resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({
                "customer_name": "Cancel Tester",
                "customer_email": "cancel@example.com",
                "appointment_type_id": public_setup["type_id"],
                "date": monday.isoformat(),
                "time": "15:00",
            }),
            content_type="application/json",
        )
        assert book_resp.status_code == 201
        appt_id = book_resp.get_json()["appointment_id"]

        # Get the cancel token from the DB
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, public_setup["tenant_id"])
            cur.execute(
                "SELECT metadata->>'cancel_token' AS token FROM appointments WHERE id = %s",
                (appt_id,),
            )
            token = cur.fetchone()["token"]

        # Cancel via POST
        resp = client.post(
            f"/{public_setup['slug']}/cancel",
            data=json.dumps({"token": token}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["cancelled"] is True

    def test_cancel_invalid_token(self, client, public_setup):
        resp = client.post(
            f"/{public_setup['slug']}/cancel",
            data=json.dumps({"token": "invalid-token-value"}),
            content_type="application/json",
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests**

```bash
docker exec kbs_app python -m pytest tests/test_appointment_public_booking.py -v
```

Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_appointment_public_booking.py
git commit -m "test(appointments): add integration tests for public booking page"
```

---

## Task 7: Run Full Test Suite

- [ ] **Step 1: Run all appointment-related tests together**

```bash
docker exec kbs_app python -m pytest tests/test_appointment_emails.py tests/test_appointment_public_booking.py plugins/kbs_appointments/tests/test_appointments.py -v
```

Expected: All tests pass (existing + new)

- [ ] **Step 2: Final commit with all files verified**

```bash
cd /mnt/archie_brain/kytran-business-suite
git log --oneline -6
```

Expected output shows 5 new commits from Tasks 1-6.
