"""Communications Hub plugin routes — dashboard and unified inbox."""

import logging
from datetime import datetime, timedelta

from flask import g, jsonify, render_template, request
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.sms_service import send_sms
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach dashboard and unified inbox routes to the blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("communications")
    def index():
        return render_template("communications.html")

    # ------------------------------------------------------------------
    # Unified Inbox
    # ------------------------------------------------------------------

    @bp.route("/api/inbox", methods=["GET"])
    @login_required
    @require_module("communications")
    def unified_inbox():
        """Aggregate recent calls, SMS, chat, and email into one timeline."""
        channel = request.args.get("channel")
        status = request.args.get("status")
        customer_id = request.args.get("customer_id", type=int)
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
        offset = (page - 1) * per_page

        items = []

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # --- Calls (from call_center plugin tables) ---
            if not channel or channel == "call":
                call_where = ["1=1"]
                call_params = []
                if customer_id:
                    call_where.append("cr.customer_id = %s")
                    call_params.append(customer_id)
                if date_from:
                    call_where.append("cr.started_at >= %s")
                    call_params.append(date_from)
                if date_to:
                    call_where.append("cr.started_at <= %s")
                    call_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT cr.id, 'call' AS channel, cr.direction, cr.status,
                           cr.started_at AS created_at, cr.customer_id,
                           cr.duration_seconds, cr.notes,
                           c.first_name || ' ' || c.last_name AS customer_name
                    FROM call_records cr
                    LEFT JOIN crm_customers c ON c.id = cr.customer_id
                    WHERE {' AND '.join(call_where)}
                    ORDER BY cr.started_at DESC
                    LIMIT %s
                    """,
                    call_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

            # --- SMS ---
            if not channel or channel == "sms":
                sms_where = ["1=1"]
                sms_params = []
                if customer_id:
                    sms_where.append("sm.customer_id = %s")
                    sms_params.append(customer_id)
                if date_from:
                    sms_where.append("sm.created_at >= %s")
                    sms_params.append(date_from)
                if date_to:
                    sms_where.append("sm.created_at <= %s")
                    sms_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT sm.id, 'sms' AS channel, sm.direction, sm.status,
                           sm.created_at, sm.customer_id,
                           sm.message AS notes, sm.phone_number,
                           c.first_name || ' ' || c.last_name AS customer_name
                    FROM sms_messages sm
                    LEFT JOIN crm_customers c ON c.id = sm.customer_id
                    WHERE {' AND '.join(sms_where)}
                    ORDER BY sm.created_at DESC
                    LIMIT %s
                    """,
                    sms_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

            # --- Chat ---
            if not channel or channel == "chat":
                chat_where = ["1=1"]
                chat_params = []
                if customer_id:
                    chat_where.append("cc.customer_id = %s")
                    chat_params.append(customer_id)
                if status:
                    chat_where.append("cc.status = %s")
                    chat_params.append(status)
                if date_from:
                    chat_where.append("cc.created_at >= %s")
                    chat_params.append(date_from)
                if date_to:
                    chat_where.append("cc.created_at <= %s")
                    chat_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT cc.id, 'chat' AS channel, cc.status,
                           cc.created_at, cc.customer_id,
                           cc.visitor_name, cc.visitor_email,
                           c.first_name || ' ' || c.last_name AS customer_name,
                           (SELECT content FROM chat_messages
                            WHERE conversation_id = cc.id
                            ORDER BY created_at DESC LIMIT 1) AS notes
                    FROM chat_conversations cc
                    LEFT JOIN crm_customers c ON c.id = cc.customer_id
                    WHERE {' AND '.join(chat_where)}
                    ORDER BY cc.created_at DESC
                    LIMIT %s
                    """,
                    chat_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

            # --- Email Campaigns ---
            if not channel or channel == "email":
                email_where = ["1=1"]
                email_params = []
                if date_from:
                    email_where.append("ec.created_at >= %s")
                    email_params.append(date_from)
                if date_to:
                    email_where.append("ec.created_at <= %s")
                    email_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT ec.id, 'email' AS channel, ec.status,
                           ec.created_at, ec.name, ec.subject AS notes,
                           ecs.total_sent, ecs.delivered, ecs.opened
                    FROM email_campaigns ec
                    LEFT JOIN email_campaign_stats ecs ON ecs.campaign_id = ec.id
                    WHERE {' AND '.join(email_where)}
                    ORDER BY ec.created_at DESC
                    LIMIT %s
                    """,
                    email_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

        # Sort all items by created_at descending, apply pagination
        items.sort(
            key=lambda x: x.get("created_at") or datetime.min,
            reverse=True,
        )
        paginated = items[offset : offset + per_page]

        return jsonify({"items": paginated, "page": page, "per_page": per_page})

    @bp.route("/api/inbox/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def inbox_stats():
        """Counts per channel and recent activity."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            stats = {}

            # Call count (last 30 days)
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'missed') AS missed
                FROM call_records
                WHERE started_at >= NOW() - INTERVAL '30 days'
                """
            )
            stats["calls"] = dict(cur.fetchone())

            # SMS count (last 30 days)
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
                       COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound
                FROM sms_messages
                WHERE created_at >= NOW() - INTERVAL '30 days'
                """
            )
            stats["sms"] = dict(cur.fetchone())

            # Active chats
            cur.execute(
                """
                SELECT COUNT(*) AS active
                FROM chat_conversations
                WHERE status = 'active'
                """
            )
            stats["chat"] = dict(cur.fetchone())

            # Campaign stats
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                       COUNT(*) FILTER (WHERE status = 'draft') AS drafts
                FROM email_campaigns
                """
            )
            stats["campaigns"] = dict(cur.fetchone())

        return jsonify(stats)


# ------------------------------------------------------------------
# Event consumers (called from __init__.py registration)
# ------------------------------------------------------------------

def on_appointment_booked(data):
    """Send SMS confirmation when an appointment is booked."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return

    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            "SELECT phone, first_name, last_name FROM crm_customers WHERE id = %s",
            (customer_id,),
        )
        customer = cur.fetchone()

    if not customer or not customer.get("phone"):
        logger.info("No phone number for customer %s — skipping SMS confirmation", customer_id)
        return

    service_name = data.get("service_name", "your appointment")
    appointment_date = data.get("appointment_date", "")
    appointment_time = data.get("appointment_time", "")

    message = (
        f"Hi {customer['first_name']}, your appointment for {service_name} "
        f"on {appointment_date} at {appointment_time} is confirmed. "
        f"Reply CANCEL to cancel."
    )

    try:
        send_sms(
            to=customer["phone"],
            message=message,
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        logger.info("SMS confirmation sent to customer %s", customer_id)
    except Exception:
        logger.exception("Failed to send SMS confirmation to customer %s", customer_id)


def on_appointment_cancelled(data):
    """Send SMS notification when an appointment is cancelled."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return

    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            "SELECT phone, first_name FROM crm_customers WHERE id = %s",
            (customer_id,),
        )
        customer = cur.fetchone()

    if not customer or not customer.get("phone"):
        return

    service_name = data.get("service_name", "your appointment")
    message = (
        f"Hi {customer['first_name']}, your appointment for {service_name} "
        f"has been cancelled. Contact us to reschedule."
    )

    try:
        send_sms(
            to=customer["phone"],
            message=message,
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
    except Exception:
        logger.exception("Failed to send cancellation SMS to customer %s", customer_id)
