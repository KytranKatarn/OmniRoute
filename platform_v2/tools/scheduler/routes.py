"""
Scheduler Routes
================
Calendar, events, subscriptions, and task scheduling for A.R.C.H.I.E. Business Tools.

Features:
- Calendar view with events
- Subscription renewal tracking
- Scheduled task management
- Reminders and notifications
- Availability/working hours
- Integration with CRM and Invoicing

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, time
import os
from database import _get_db_password
import json
from decimal import Decimal

# Import user context helpers
try:
    from services.user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
scheduler_bp = Blueprint(
    "scheduler",
    __name__,
    url_prefix="/tools/scheduler",
    template_folder="../../templates/tools",
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.strftime("%H:%M:%S")
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


# ============================================================================
# MAIN PAGE
# ============================================================================


@scheduler_bp.route("/")
@login_required
def index():
    """Main Scheduler dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get event stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_events,
                COUNT(*) FILTER (WHERE start_time >= NOW() AND start_time < NOW() + INTERVAL '7 days') as upcoming_week,
                COUNT(*) FILTER (WHERE start_time >= NOW() AND start_time < NOW() + INTERVAL '1 day') as today,
                COUNT(*) FILTER (WHERE status = 'completed') as completed
            FROM calendar_events
            WHERE start_time >= NOW() - INTERVAL '30 days' AND user_id = %s
        """,
            (current_user.id,),
        )
        event_stats = cur.fetchone() or {}

        # Get subscription stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_subscriptions,
                COUNT(*) FILTER (WHERE status = 'active') as active,
                COUNT(*) FILTER (WHERE next_billing_date <= NOW() + INTERVAL '7 days' AND status = 'active') as renewing_soon,
                COALESCE(SUM(amount) FILTER (WHERE status = 'active'), 0) as monthly_revenue
            FROM subscription_schedules
            WHERE user_id = %s
        """,
            (current_user.id,),
        )
        sub_stats = cur.fetchone() or {}

        # Get pending reminders count
        cur.execute(
            """
            SELECT COUNT(*) as pending
            FROM reminders
            WHERE status = 'pending' AND remind_at <= NOW() + INTERVAL '1 day' AND user_id = %s
        """,
            (current_user.id,),
        )
        reminder_stats = cur.fetchone() or {}

        # Get pending tasks count
        cur.execute(
            """
            SELECT COUNT(*) as pending
            FROM scheduled_tasks
            WHERE status = 'pending' AND scheduled_for <= NOW() + INTERVAL '7 days' AND created_by = %s
        """,
            (current_user.id,),
        )
        task_stats = cur.fetchone() or {}

        stats = {
            **event_stats,
            "active_subscriptions": sub_stats.get("active", 0),
            "renewing_soon": sub_stats.get("renewing_soon", 0),
            "monthly_revenue": sub_stats.get("monthly_revenue", 0),
            "pending_reminders": reminder_stats.get("pending", 0),
            "pending_tasks": task_stats.get("pending", 0),
        }

        # Get events for current month
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        if now.month == 12:
            month_end = month_start.replace(year=now.year + 1, month=1)
        else:
            month_end = month_start.replace(month=now.month + 1)

        cur.execute(
            """
            SELECT e.*, c.first_name || ' ' || c.last_name as customer_name
            FROM calendar_events e
            LEFT JOIN crm_customers c ON e.customer_id = c.id
            WHERE e.start_time >= %s AND e.start_time < %s AND e.user_id = %s
            ORDER BY e.start_time
        """,
            (month_start, month_end, current_user.id),
        )
        events = cur.fetchall()

        # Get upcoming subscriptions
        cur.execute(
            """
            SELECT s.*, c.first_name || ' ' || c.last_name as customer_name, c.email as customer_email
            FROM subscription_schedules s
            LEFT JOIN crm_customers c ON s.customer_id = c.id
            WHERE s.status = 'active' AND s.user_id = %s
            ORDER BY s.next_billing_date
            LIMIT 10
        """,
            (current_user.id,),
        )
        subscriptions = cur.fetchall()

        # Get reminders
        cur.execute(
            """
            SELECT r.*, c.first_name || ' ' || c.last_name as customer_name
            FROM reminders r
            LEFT JOIN crm_customers c ON r.customer_id = c.id
            WHERE r.status = 'pending' AND r.user_id = %s
            ORDER BY r.remind_at
            LIMIT 10
        """,
            (current_user.id,),
        )
        reminders = cur.fetchall()

        return render_template(
            "tools/scheduler.html",
            stats=stats,
            events=events,
            subscriptions=subscriptions,
            reminders=reminders,
        )

    except Exception as e:
        current_app.logger.error(f"Scheduler index error: {str(e)}")
        return render_template(
            "tools/scheduler.html",
            stats={},
            events=[],
            subscriptions=[],
            reminders=[],
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CALENDAR EVENTS API
# ============================================================================


@scheduler_bp.route("/api/events")
@login_required
def get_events():
    """Get calendar events"""
    try:
        start = request.args.get("start")
        end = request.args.get("end")
        event_type = request.args.get("type", "")
        customer_id = request.args.get("customer_id", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT e.*, c.first_name || ' ' || c.last_name as customer_name,
                   u.username as assigned_to_name
            FROM calendar_events e
            LEFT JOIN crm_customers c ON e.customer_id = c.id
            LEFT JOIN users u ON e.assigned_to = u.id
            WHERE e.user_id = %s
        """
        params = [current_user.id]

        if start:
            query += " AND e.start_time >= %s"
            params.append(start)
        if end:
            query += " AND e.start_time < %s"
            params.append(end)
        if event_type:
            query += " AND e.event_type = %s"
            params.append(event_type)
        if customer_id:
            query += " AND e.customer_id = %s"
            params.append(customer_id)

        query += " ORDER BY e.start_time"

        cur.execute(query, params)
        events = cur.fetchall()

        # Format for FullCalendar
        formatted = []
        for e in events:
            formatted.append(
                {
                    "id": e["id"],
                    "title": e["title"],
                    "start": e["start_time"].isoformat() if e["start_time"] else None,
                    "end": e["end_time"].isoformat() if e["end_time"] else None,
                    "allDay": e["all_day"],
                    "color": e["color"],
                    "extendedProps": {
                        "description": e["description"],
                        "event_type": e["event_type"],
                        "location": e["location"],
                        "customer_name": e["customer_name"],
                        "customer_id": e["customer_id"],
                        "status": e["status"],
                    },
                }
            )

        return jsonify({"success": True, "events": formatted})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/events", methods=["POST"])
@login_required
def create_event():
    """Create a new calendar event"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO calendar_events (
                title, description, event_type, start_time, end_time, all_day,
                location, video_link, is_recurring, recurrence_rule, recurrence_end,
                customer_id, user_id, assigned_to, status, color, reminders,
                metadata, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING *
        """,
            (
                data.get("title"),
                data.get("description"),
                data.get("event_type", "general"),
                data.get("start_time"),
                data.get("end_time"),
                data.get("all_day", False),
                data.get("location"),
                data.get("video_link"),
                data.get("is_recurring", False),
                data.get("recurrence_rule"),
                data.get("recurrence_end"),
                data.get("customer_id") or None,
                current_user.id,
                data.get("assigned_to") or None,
                data.get("status", "scheduled"),
                data.get("color", "#3b82f6"),
                json.dumps(data.get("reminders", [30, 1440])),
                json.dumps(data.get("metadata", {})),
                current_user.id,
            ),
        )

        event = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "event": json.loads(json.dumps(dict(event), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/events/<int:event_id>")
@login_required
def get_event(event_id):
    """Get a single event"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT e.*, c.first_name || ' ' || c.last_name as customer_name,
                   c.email as customer_email, u.username as assigned_to_name
            FROM calendar_events e
            LEFT JOIN crm_customers c ON e.customer_id = c.id
            LEFT JOIN users u ON e.assigned_to = u.id
            WHERE e.id = %s AND e.user_id = %s
        """,
            (event_id, current_user.id),
        )

        event = cur.fetchone()

        if not event:
            return jsonify({"success": False, "error": "Event not found"}), 404

        return jsonify(
            {
                "success": True,
                "event": json.loads(json.dumps(dict(event), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/events/<int:event_id>", methods=["PUT"])
@login_required
def update_event(event_id):
    """Update an event"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE calendar_events SET
                title = COALESCE(%s, title),
                description = COALESCE(%s, description),
                event_type = COALESCE(%s, event_type),
                start_time = COALESCE(%s, start_time),
                end_time = COALESCE(%s, end_time),
                all_day = COALESCE(%s, all_day),
                location = COALESCE(%s, location),
                video_link = COALESCE(%s, video_link),
                customer_id = %s,
                assigned_to = %s,
                status = COALESCE(%s, status),
                color = COALESCE(%s, color),
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            (
                data.get("title"),
                data.get("description"),
                data.get("event_type"),
                data.get("start_time"),
                data.get("end_time"),
                data.get("all_day"),
                data.get("location"),
                data.get("video_link"),
                data.get("customer_id"),
                data.get("assigned_to"),
                data.get("status"),
                data.get("color"),
                event_id,
                current_user.id,
            ),
        )

        event = cur.fetchone()
        conn.commit()

        if not event:
            return jsonify({"success": False, "error": "Event not found"}), 404

        return jsonify(
            {
                "success": True,
                "event": json.loads(json.dumps(dict(event), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/events/<int:event_id>", methods=["DELETE"])
@login_required
def delete_event(event_id):
    """Delete an event"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM calendar_events WHERE id = %s AND user_id = %s", (event_id, current_user.id))
        deleted = cur.rowcount > 0
        conn.commit()

        if not deleted:
            return jsonify({"success": False, "error": "Event not found"}), 404

        return jsonify({"success": True, "message": "Event deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/events/<int:event_id>/complete", methods=["POST"])
@login_required
def complete_event(event_id):
    """Mark event as completed"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE calendar_events SET status = 'completed', updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """,
            (event_id, current_user.id),
        )
        conn.commit()

        return jsonify({"success": True, "message": "Event marked as completed"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SUBSCRIPTION SCHEDULES API
# ============================================================================


@scheduler_bp.route("/api/subscriptions")
@login_required
def get_subscriptions():
    """Get subscription schedules"""
    try:
        status = request.args.get("status", "")
        days = request.args.get("days", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT s.*, c.first_name || ' ' || c.last_name as customer_name,
                   c.email as customer_email, c.company as customer_company
            FROM subscription_schedules s
            LEFT JOIN crm_customers c ON s.customer_id = c.id
            WHERE s.user_id = %s
        """
        params = [current_user.id]

        if status:
            query += " AND s.status = %s"
            params.append(status)

        if days:
            query += " AND s.next_billing_date <= NOW() + (%s * INTERVAL '1 day')"
            params.append(int(days))

        query += " ORDER BY s.next_billing_date"

        cur.execute(query, params)
        subscriptions = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "subscriptions": json.loads(json.dumps([dict(s) for s in subscriptions], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/subscriptions", methods=["POST"])
@login_required
def create_subscription_schedule():
    """Create a new subscription schedule"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO subscription_schedules (
                subscription_id, customer_id, user_id, tier, billing_cycle,
                amount, currency, start_date, next_billing_date, status,
                auto_renew, payment_method, stripe_subscription_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING *
        """,
            (
                data.get("subscription_id"),
                data.get("customer_id"),
                data.get("user_id") or current_user.id,
                data.get("tier", "pro"),
                data.get("billing_cycle", "monthly"),
                data.get("amount"),
                data.get("currency", "CAD"),
                data.get("start_date") or date.today(),
                data.get("next_billing_date"),
                data.get("status", "active"),
                data.get("auto_renew", True),
                data.get("payment_method"),
                data.get("stripe_subscription_id"),
            ),
        )

        schedule = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "subscription": json.loads(json.dumps(dict(schedule), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/subscriptions/<int:schedule_id>", methods=["PUT"])
@login_required
def update_subscription_schedule(schedule_id):
    """Update a subscription schedule"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Handle status changes
        status = data.get("status")

        cur.execute(
            """
            UPDATE subscription_schedules SET
                tier = COALESCE(%s, tier),
                billing_cycle = COALESCE(%s, billing_cycle),
                amount = COALESCE(%s, amount),
                status = COALESCE(%s, status),
                auto_renew = COALESCE(%s, auto_renew),
                next_billing_date = COALESCE(%s, next_billing_date),
                end_date = CASE WHEN %s = 'cancelled' THEN CURRENT_DATE ELSE end_date END,
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            (
                data.get("tier"),
                data.get("billing_cycle"),
                data.get("amount"),
                status,
                data.get("auto_renew"),
                data.get("next_billing_date"),
                status,
                schedule_id,
                current_user.id,
            ),
        )

        schedule = cur.fetchone()
        conn.commit()

        if not schedule:
            return jsonify({"success": False, "error": "Schedule not found"}), 404

        return jsonify(
            {
                "success": True,
                "subscription": json.loads(json.dumps(dict(schedule), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/subscriptions/<int:schedule_id>/renew", methods=["POST"])
@login_required
def process_renewal(schedule_id):
    """Process a subscription renewal (mark as billed)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current schedule
        cur.execute(
            "SELECT * FROM subscription_schedules WHERE id = %s AND user_id = %s", (schedule_id, current_user.id)
        )
        schedule = cur.fetchone()

        if not schedule:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Schedule not found"}), 404

        # Update billing history
        history = schedule.get("billing_history", []) or []
        history.append(
            {
                "date": date.today().isoformat(),
                "amount": float(schedule["amount"]),
                "status": "paid",
            }
        )

        # Update schedule
        cur.execute(
            """
            UPDATE subscription_schedules SET
                last_billed_date = CURRENT_DATE,
                billing_history = %s,
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            (json.dumps(history), schedule_id, current_user.id),
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "subscription": json.loads(json.dumps(dict(updated), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SCHEDULED TASKS API
# ============================================================================


@scheduler_bp.route("/api/tasks")
@login_required
def get_scheduled_tasks():
    """Get scheduled tasks"""
    try:
        status = request.args.get("status", "")
        task_type = request.args.get("type", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT t.*, u.username as created_by_name
            FROM scheduled_tasks t
            LEFT JOIN users u ON t.created_by = u.id
            WHERE t.created_by = %s
        """
        params = [current_user.id]

        if status:
            query += " AND t.status = %s"
            params.append(status)

        if task_type:
            query += " AND t.task_type = %s"
            params.append(task_type)

        query += " ORDER BY t.scheduled_for"

        cur.execute(query, params)
        tasks = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "tasks": json.loads(json.dumps([dict(t) for t in tasks], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/tasks", methods=["POST"])
@login_required
def create_scheduled_task():
    """Create a new scheduled task"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO scheduled_tasks (
                name, description, task_type, scheduled_for, is_recurring,
                recurrence_rule, next_run, target_type, target_id,
                action_config, priority, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING *
        """,
            (
                data.get("name"),
                data.get("description"),
                data.get("task_type", "reminder"),
                data.get("scheduled_for"),
                data.get("is_recurring", False),
                data.get("recurrence_rule"),
                data.get("scheduled_for"),  # next_run starts as scheduled_for
                data.get("target_type"),
                data.get("target_id"),
                json.dumps(data.get("action_config", {})),
                data.get("priority", 5),
                current_user.id,
            ),
        )

        task = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "task": json.loads(json.dumps(dict(task), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_scheduled_task(task_id):
    """Update a scheduled task"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE scheduled_tasks SET
                name = COALESCE(%s, name),
                description = COALESCE(%s, description),
                scheduled_for = COALESCE(%s, scheduled_for),
                status = COALESCE(%s, status),
                priority = COALESCE(%s, priority),
                updated_at = NOW()
            WHERE id = %s AND created_by = %s
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("description"),
                data.get("scheduled_for"),
                data.get("status"),
                data.get("priority"),
                task_id,
                current_user.id,
            ),
        )

        task = cur.fetchone()
        conn.commit()

        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        return jsonify(
            {
                "success": True,
                "task": json.loads(json.dumps(dict(task), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_scheduled_task(task_id):
    """Delete a scheduled task"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM scheduled_tasks WHERE id = %s AND created_by = %s", (task_id, current_user.id))
        deleted = cur.rowcount > 0
        conn.commit()

        if not deleted:
            return jsonify({"success": False, "error": "Task not found"}), 404

        return jsonify({"success": True, "message": "Task deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# REMINDERS API
# ============================================================================


@scheduler_bp.route("/api/reminders")
@login_required
def get_reminders():
    """Get reminders"""
    try:
        status = request.args.get("status", "pending")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT r.*, c.first_name || ' ' || c.last_name as customer_name
            FROM reminders r
            LEFT JOIN crm_customers c ON r.customer_id = c.id
            WHERE r.status = %s AND r.user_id = %s
            ORDER BY r.remind_at
        """,
            (status, current_user.id),
        )

        reminders = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "reminders": json.loads(json.dumps([dict(r) for r in reminders], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/reminders", methods=["POST"])
@login_required
def create_reminder():
    """Create a new reminder"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO reminders (
                title, message, reminder_type, remind_at, user_id, customer_id,
                related_type, related_id, notification_channels
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data.get("title"),
                data.get("message"),
                data.get("reminder_type", "general"),
                data.get("remind_at"),
                data.get("user_id") or current_user.id,
                data.get("customer_id"),
                data.get("related_type"),
                data.get("related_id"),
                json.dumps(data.get("notification_channels", ["in_app"])),
            ),
        )

        reminder = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "reminder": json.loads(json.dumps(dict(reminder), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/reminders/<int:reminder_id>/dismiss", methods=["POST"])
@login_required
def dismiss_reminder(reminder_id):
    """Dismiss a reminder"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE reminders SET status = 'dismissed'
            WHERE id = %s AND user_id = %s
        """,
            (reminder_id, current_user.id),
        )
        conn.commit()

        return jsonify({"success": True, "message": "Reminder dismissed"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/reminders/<int:reminder_id>/snooze", methods=["POST"])
@login_required
def snooze_reminder(reminder_id):
    """Snooze a reminder"""
    try:
        data = request.get_json()
        minutes = data.get("minutes", 30)

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE reminders SET
                status = 'snoozed',
                snoozed_until = NOW() + (%s * INTERVAL '1 minute'),
                remind_at = NOW() + (%s * INTERVAL '1 minute')
            WHERE id = %s AND user_id = %s
        """,
            (minutes, minutes, reminder_id, current_user.id),
        )
        conn.commit()

        return jsonify({"success": True, "message": f"Reminder snoozed for {minutes} minutes"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# AVAILABILITY API
# ============================================================================


@scheduler_bp.route("/api/availability")
@login_required
def get_availability():
    """Get user availability settings"""
    try:
        user_id = request.args.get("user_id") or current_user.id

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM user_availability
            WHERE user_id = %s
            ORDER BY day_of_week
        """,
            (user_id,),
        )

        availability = cur.fetchall()

        # Get time blocks
        cur.execute(
            """
            SELECT * FROM time_blocks
            WHERE user_id = %s AND end_time >= NOW()
            ORDER BY start_time
        """,
            (user_id,),
        )

        blocks = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "availability": json.loads(json.dumps([dict(a) for a in availability], default=json_serial)),
                "time_blocks": json.loads(json.dumps([dict(b) for b in blocks], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/availability", methods=["POST"])
@login_required
def save_availability():
    """Save user availability settings"""
    try:
        data = request.get_json()
        user_id = current_user.id

        conn = get_db_connection()
        cur = conn.cursor()

        # Clear existing
        cur.execute("DELETE FROM user_availability WHERE user_id = %s", (user_id,))

        # Insert new
        for slot in data.get("availability", []):
            cur.execute(
                """
                INSERT INTO user_availability (user_id, day_of_week, start_time, end_time, is_available, timezone)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    user_id,
                    slot.get("day_of_week"),
                    slot.get("start_time"),
                    slot.get("end_time"),
                    slot.get("is_available", True),
                    slot.get("timezone", "America/Toronto"),
                ),
            )

        conn.commit()

        return jsonify({"success": True, "message": "Availability saved"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/time-blocks", methods=["POST"])
@login_required
def create_time_block():
    """Create a time block"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO time_blocks (user_id, title, start_time, end_time, block_type)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("title"),
                data.get("start_time"),
                data.get("end_time"),
                data.get("block_type", "busy"),
            ),
        )

        block = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "time_block": json.loads(json.dumps(dict(block), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/time-blocks/<int:block_id>", methods=["DELETE"])
@login_required
def delete_time_block(block_id):
    """Delete a time block"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM time_blocks WHERE id = %s AND user_id = %s",
            (block_id, current_user.id),
        )
        conn.commit()

        return jsonify({"success": True, "message": "Time block deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# INTEGRATION ENDPOINTS
# ============================================================================


@scheduler_bp.route("/api/from-crm", methods=["POST"])
@login_required
def create_from_crm():
    """Create event from CRM customer"""
    try:
        data = request.get_json()
        customer_id = data.get("customer_id")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get customer info
        cur.execute(
            """
            SELECT * FROM crm_customers WHERE id = %s
        """,
            (customer_id,),
        )
        customer = cur.fetchone()

        if not customer:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Customer not found"}), 404

        # Create event
        cur.execute(
            """
            INSERT INTO calendar_events (
                title, description, event_type, start_time, end_time,
                customer_id, created_by, status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 'scheduled'
            ) RETURNING *
        """,
            (
                data.get(
                    "title",
                    f"Meeting with {customer['first_name']} {customer['last_name']}",
                ),
                data.get("description"),
                data.get("event_type", "meeting"),
                data.get("start_time"),
                data.get("end_time"),
                customer_id,
                current_user.id,
            ),
        )

        event = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "event": json.loads(json.dumps(dict(event), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@scheduler_bp.route("/api/from-subscription", methods=["POST"])
@login_required
def create_from_subscription():
    """Create schedule from subscription"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO subscription_schedules (
                subscription_id, customer_id, user_id, tier, billing_cycle,
                amount, start_date, next_billing_date, status, payment_method,
                stripe_subscription_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
            RETURNING *
        """,
            (
                data.get("subscription_id"),
                data.get("customer_id"),
                data.get("user_id"),
                data.get("tier"),
                data.get("billing_cycle", "monthly"),
                data.get("amount"),
                data.get("start_date") or date.today(),
                data.get("next_billing_date"),
                data.get("payment_method"),
                data.get("stripe_subscription_id"),
            ),
        )

        schedule = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "subscription_schedule": json.loads(json.dumps(dict(schedule), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@scheduler_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM calendar_events")
        event_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM subscription_schedules")
        sub_count = cur.fetchone()[0]

        return jsonify(
            {
                "module": "scheduler",
                "status": "operational",
                "healthy": True,
                "events": event_count,
                "subscriptions": sub_count,
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "scheduler",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
