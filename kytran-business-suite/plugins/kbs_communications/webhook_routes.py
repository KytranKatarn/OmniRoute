"""Webhook routes for RingCentral call events and SMS delivery receipts."""

import hashlib
import hmac
import json
import logging

from flask import g, jsonify, request
from flask_login import login_required

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)

# RingCentral status code to KBS status mapping
_RC_STATUS_MAP = {
    "Answered": "completed",
    "Accepted": "completed",
    "CallConnected": "completed",
    "NoAnswer": "missed",
    "Voicemail": "missed",
    "Busy": "missed",
    "Rejected": "failed",
    "HangUp": "completed",
    "FaxReceive": "completed",
}


def _map_rc_status(rc_status):
    """Map a RingCentral call result/status code to KBS status."""
    return _RC_STATUS_MAP.get(rc_status, "initiated")


def _parse_ringcentral_call(event_body):
    """Extract call details from a RingCentral telephony event.

    Args:
        event_body: The decoded JSON body from the RingCentral webhook.

    Returns:
        Dict with normalized call fields, or None if no party data.
    """
    body = event_body.get("body", {})
    parties = body.get("parties", [])

    if not parties:
        return None

    party = parties[0]
    direction_raw = party.get("direction", "Inbound")
    status_raw = party.get("status", {}).get("code", "Unknown")
    recording = party.get("recording", {})

    return {
        "ringcentral_id": body.get("sessionId", ""),
        "direction": "inbound" if direction_raw.lower() == "inbound" else "outbound",
        "caller_number": party.get("from", {}).get("phoneNumber", ""),
        "callee_number": party.get("to", {}).get("phoneNumber", ""),
        "status": _map_rc_status(status_raw),
        "duration_seconds": party.get("duration", 0) or 0,
        "recording_url": recording.get("contentUri", ""),
    }


def _match_customer_by_phone(cur, phone_number):
    """Look up a CRM customer by phone number.

    Args:
        cur: Database cursor with tenant search path already set.
        phone_number: Phone number to match (e.g. "+15551234567").

    Returns:
        Customer ID (int) or None if no match.
    """
    if not phone_number:
        return None

    # Strip leading + and try various formats
    digits = (
        phone_number.lstrip("+")
        .replace("-", "")
        .replace(" ", "")
        .replace("(", "")
        .replace(")", "")
    )
    cur.execute(
        """
        SELECT id FROM crm_customers
        WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', ''), '(', ''), ')', '') = %s
           OR phone = %s
        LIMIT 1
        """,
        (digits, phone_number),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _verify_ringcentral_signature(body_bytes, signature, secret):
    """Verify RingCentral webhook signature (HMAC-SHA256)."""
    if not secret:
        return True  # Skip verification if no secret configured
    expected = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def register_webhook_routes(bp):
    """Attach webhook routes to the blueprint."""

    @bp.route("/api/webhooks/ringcentral", methods=["POST"])
    def ringcentral_webhook():
        """Receive RingCentral telephony session events.

        This endpoint is called by RingCentral when calls are made/received.
        It does NOT require login -- it is authenticated via webhook signature.
        RingCentral sends a validation token on subscription that must be echoed.
        """
        cfg = Config()

        # Handle RingCentral subscription validation
        validation_token = request.headers.get("Validation-Token")
        if validation_token:
            return jsonify({}), 200, {"Validation-Token": validation_token}

        # Verify webhook signature
        signature = request.headers.get("X-RingCentral-Signature")
        if cfg.KBS_RINGCENTRAL_WEBHOOK_SECRET:
            if not _verify_ringcentral_signature(
                request.data, signature, cfg.KBS_RINGCENTRAL_WEBHOOK_SECRET
            ):
                logger.warning("Invalid RingCentral webhook signature")
                return jsonify({"error": "Invalid signature"}), 401

        data = request.get_json(force=True)
        event_type = data.get("event", "")

        # Only process telephony session events
        if "/telephony/sessions" not in event_type:
            return jsonify({"status": "ignored"}), 200

        parsed = _parse_ringcentral_call(data)
        if not parsed:
            return jsonify({"status": "no parties"}), 200

        # Determine tenant from webhook URL query param
        # Convention: webhook URL includes ?tenant_id=N
        tenant_id = request.args.get("tenant_id", type=int)
        if not tenant_id:
            logger.warning("RingCentral webhook missing tenant_id")
            return jsonify({"error": "tenant_id required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Check for duplicate by ringcentral_id
            if parsed["ringcentral_id"]:
                cur.execute(
                    "SELECT id FROM call_records WHERE metadata->>'ringcentral_id' = %s",
                    (parsed["ringcentral_id"],),
                )
                if cur.fetchone():
                    return jsonify({"status": "duplicate"}), 200

            # Match caller to CRM customer
            lookup_number = (
                parsed["caller_number"]
                if parsed["direction"] == "inbound"
                else parsed["callee_number"]
            )
            customer_id = _match_customer_by_phone(cur, lookup_number)

            # Insert into call_records (call_center plugin table)
            cur.execute(
                """
                INSERT INTO call_records
                    (customer_id, direction, status, duration_seconds,
                     recording_url, metadata, started_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                RETURNING id, phone_number_id, customer_id, direction, status,
                          duration_seconds, notes, started_at, ended_at
                """,
                (
                    customer_id,
                    parsed["direction"],
                    parsed["status"],
                    parsed["duration_seconds"],
                    parsed["recording_url"] or None,
                    json.dumps(
                        {
                            "ringcentral_id": parsed["ringcentral_id"],
                            "caller_number": parsed["caller_number"],
                            "callee_number": parsed["callee_number"],
                        }
                    ),
                ),
            )
            call = cur.fetchone()

        event_bus.emit(
            "call.logged",
            {
                "call_id": call["id"],
                "customer_id": customer_id,
                "direction": parsed["direction"],
                "status": parsed["status"],
                "source": "ringcentral",
            },
            tenant_id=tenant_id,
        )

        return jsonify({"status": "logged", "call_id": call["id"]}), 201

    @bp.route("/api/calls", methods=["GET"])
    @login_required
    @require_module("communications")
    def list_calls():
        """List call records with CRM customer info and pagination."""
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
        offset = (page - 1) * per_page
        direction = request.args.get("direction")
        status = request.args.get("status")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ["1=1"]
            params = []
            if direction:
                where.append("cr.direction = %s")
                params.append(direction)
            if status:
                where.append("cr.status = %s")
                params.append(status)

            cur.execute(
                f"""
                SELECT cr.id, cr.phone_number_id, cr.customer_id, cr.direction,
                       cr.status, cr.duration_seconds, cr.recording_url,
                       cr.notes, cr.metadata, cr.started_at, cr.ended_at,
                       c.first_name || ' ' || c.last_name AS customer_name,
                       c.email AS customer_email, c.phone AS customer_phone
                FROM call_records cr
                LEFT JOIN crm_customers c ON c.id = cr.customer_id
                WHERE {' AND '.join(where)}
                ORDER BY cr.started_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            calls = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) AS total FROM call_records cr WHERE {' AND '.join(where)}",
                params,
            )
            total = cur.fetchone()["total"]

        return jsonify(
            {"calls": calls, "total": total, "page": page, "per_page": per_page}
        )

    @bp.route("/api/calls/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def call_stats():
        """Call volume, average duration, and missed rate."""
        days = request.args.get("days", 30, type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') AS answered,
                    COUNT(*) FILTER (WHERE status = 'missed') AS missed,
                    ROUND(AVG(duration_seconds) FILTER (WHERE status = 'completed'), 1) AS avg_duration,
                    COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
                    COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound
                FROM call_records
                WHERE started_at >= NOW() - make_interval(days => %s)
                """,
                (days,),
            )
            stats = dict(cur.fetchone())

        stats["missed_rate"] = (
            round(stats["missed"] / stats["total_calls"] * 100, 1)
            if stats["total_calls"] > 0
            else 0
        )

        return jsonify(stats)
