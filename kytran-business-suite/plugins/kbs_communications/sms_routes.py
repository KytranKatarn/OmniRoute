"""SMS routes for sending, listing, and receiving SMS messages."""

import logging

from flask import g, jsonify, request
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.sms_service import send_sms
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_sms_routes(bp):
    """Attach SMS routes to the blueprint."""

    @bp.route("/api/sms/send", methods=["POST"])
    @login_required
    @require_module("communications")
    def sms_send():
        """Send an SMS message to a phone number."""
        data = request.get_json(force=True)
        to = data.get("to", "").strip()
        message = data.get("message", "").strip()
        customer_id = data.get("customer_id")

        if not to or not message:
            return jsonify({"error": "to and message are required"}), 400

        try:
            result = send_sms(
                to=to,
                message=message,
                tenant_id=g.tenant_id,
                customer_id=customer_id,
            )
            return jsonify(result), 201
        except Exception as e:
            logger.exception("Failed to send SMS to %s", to)
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/sms", methods=["GET"])
    @login_required
    @require_module("communications")
    def sms_list():
        """List SMS messages with pagination and filters."""
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
        offset = (page - 1) * per_page
        direction = request.args.get("direction")
        customer_id = request.args.get("customer_id", type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ["1=1"]
            params = []
            if direction:
                where.append("sm.direction = %s")
                params.append(direction)
            if customer_id:
                where.append("sm.customer_id = %s")
                params.append(customer_id)

            cur.execute(
                f"""
                SELECT sm.id, sm.direction, sm.phone_number, sm.customer_id,
                       sm.message, sm.status, sm.provider, sm.external_id,
                       sm.error_message, sm.created_at,
                       c.first_name || ' ' || c.last_name AS customer_name
                FROM sms_messages sm
                LEFT JOIN crm_customers c ON c.id = sm.customer_id
                WHERE {' AND '.join(where)}
                ORDER BY sm.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            messages = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) AS total FROM sms_messages sm WHERE {' AND '.join(where)}",
                params,
            )
            total = cur.fetchone()["total"]

        return jsonify(
            {"messages": messages, "total": total, "page": page, "per_page": per_page}
        )

    @bp.route("/api/sms/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def sms_stats():
        """SMS volume stats for the last N days."""
        days = request.args.get("days", 30, type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE direction = 'outbound') AS sent,
                    COUNT(*) FILTER (WHERE direction = 'inbound') AS received,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed
                FROM sms_messages
                WHERE created_at >= NOW() - make_interval(days => %s)
                """,
                (days,),
            )
            stats = dict(cur.fetchone())

        return jsonify(stats)

    @bp.route("/api/webhooks/sms/inbound", methods=["POST"])
    def sms_inbound_webhook():
        """Receive inbound SMS from Twilio or RingCentral."""
        data = request.form.to_dict() or request.get_json(force=True, silent=True) or {}

        from_number = data.get("From", data.get("from", {}).get("phoneNumber", ""))
        body = data.get("Body", data.get("subject", ""))
        external_id = data.get("MessageSid", data.get("id", ""))

        tenant_id = request.args.get("tenant_id", type=int)
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        if not from_number or not body:
            return jsonify({"error": "Missing from or body"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Try to match to CRM customer
            cur.execute(
                "SELECT id FROM crm_customers WHERE phone = %s LIMIT 1",
                (from_number,),
            )
            customer = cur.fetchone()
            customer_id = customer["id"] if customer else None

            cur.execute(
                """
                INSERT INTO sms_messages
                    (direction, phone_number, customer_id, message, status,
                     provider, external_id)
                VALUES ('inbound', %s, %s, %s, 'received', 'twilio', %s)
                RETURNING id
                """,
                (from_number, customer_id, body, external_id),
            )
            row = cur.fetchone()

        event_bus.emit(
            "sms.received",
            {
                "sms_id": row["id"],
                "from": from_number,
                "customer_id": customer_id,
                "message": body,
            },
            tenant_id=tenant_id,
        )

        return jsonify({"status": "received", "sms_id": row["id"]}), 201
