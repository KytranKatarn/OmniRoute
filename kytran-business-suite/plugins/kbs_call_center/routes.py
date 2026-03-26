"""Call Center plugin routes — phone numbers, call records, escalations, CRM lookup."""

import logging
from datetime import datetime, timezone

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Call Center routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("call-center")
    def index():
        return render_template("call_center.html")

    # ------------------------------------------------------------------
    # Phone Numbers
    # ------------------------------------------------------------------

    @bp.route("/api/numbers", methods=["GET"])
    @login_required
    @require_module("call-center")
    def list_numbers():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, number, provider, label, is_active, metadata, created_at"
                " FROM call_phone_numbers ORDER BY created_at DESC"
            )
            numbers = cur.fetchall()
        return jsonify({"numbers": numbers})

    @bp.route("/api/numbers", methods=["POST"])
    @login_required
    @require_module("call-center")
    def add_number():
        data = request.get_json(force=True)
        number = (data.get("number") or "").strip()
        provider = (data.get("provider") or "other").strip()
        if not number:
            return jsonify({"error": "number is required"}), 400
        valid_providers = {"twilio", "telnyx", "telus", "other"}
        if provider not in valid_providers:
            return jsonify({"error": f"provider must be one of {sorted(valid_providers)}"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO call_phone_numbers (number, provider, label, is_active, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, number, provider, label, is_active, metadata, created_at
                """,
                (
                    number,
                    provider,
                    (data.get("label") or "").strip() or None,
                    data.get("is_active", True),
                    Json(data.get("metadata") or {}),
                ),
            )
            phone = cur.fetchone()
        return jsonify(phone), 201

    @bp.route("/api/numbers/<int:number_id>", methods=["DELETE"])
    @login_required
    @require_module("call-center")
    def remove_number(number_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM call_phone_numbers WHERE id = %s RETURNING id",
                (number_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Phone number not found"}), 404
        return jsonify({"deleted": True, "id": number_id})

    # ------------------------------------------------------------------
    # Call Records
    # ------------------------------------------------------------------

    @bp.route("/api/calls", methods=["GET"])
    @login_required
    @require_module("call-center")
    def list_calls():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        direction = request.args.get("direction")
        offset = (page - 1) * per_page

        filters = []
        params: list = []
        if status:
            filters.append("r.status = %s")
            params.append(status)
        if direction:
            filters.append("r.direction = %s")
            params.append(direction)

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"SELECT COUNT(*) AS total FROM call_records r {where}",
                params,
            )
            total = cur.fetchone()["total"]
            cur.execute(
                f"""
                SELECT r.id, r.phone_number_id, r.customer_id, r.direction, r.status,
                       r.duration_seconds, r.recording_url, r.notes,
                       r.started_at, r.ended_at,
                       n.number AS phone_number, n.label AS phone_label
                FROM call_records r
                LEFT JOIN call_phone_numbers n ON n.id = r.phone_number_id
                {where}
                ORDER BY r.started_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            calls = cur.fetchall()

        return jsonify({"calls": calls, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/calls", methods=["POST"])
    @login_required
    @require_module("call-center")
    def log_call():
        data = request.get_json(force=True)
        phone_number_id = data.get("phone_number_id")
        direction = (data.get("direction") or "").strip()
        if not phone_number_id:
            return jsonify({"error": "phone_number_id is required"}), 400
        if direction not in ("inbound", "outbound"):
            return jsonify({"error": "direction must be inbound or outbound"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO call_records
                    (phone_number_id, customer_id, direction, status, notes, metadata)
                VALUES (%s, %s, %s, 'initiated', %s, %s)
                RETURNING id, phone_number_id, customer_id, direction, status,
                          duration_seconds, notes, metadata, started_at, ended_at
                """,
                (
                    phone_number_id,
                    data.get("customer_id"),
                    direction,
                    (data.get("notes") or "").strip() or None,
                    Json(data.get("metadata") or {}),
                ),
            )
            call = cur.fetchone()

        event_bus.emit(
            "call.started",
            {
                "call_id": call["id"],
                "phone_number_id": call["phone_number_id"],
                "customer_id": call["customer_id"],
                "direction": call["direction"],
            },
            tenant_id=g.tenant_id,
        )

        return jsonify(call), 201

    @bp.route("/api/calls/<int:call_id>", methods=["GET"])
    @login_required
    @require_module("call-center")
    def get_call(call_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT r.id, r.phone_number_id, r.customer_id, r.direction, r.status,
                       r.duration_seconds, r.recording_url, r.transcript, r.notes,
                       r.metadata, r.started_at, r.ended_at,
                       n.number AS phone_number, n.label AS phone_label
                FROM call_records r
                LEFT JOIN call_phone_numbers n ON n.id = r.phone_number_id
                WHERE r.id = %s
                """,
                (call_id,),
            )
            call = cur.fetchone()
        if not call:
            return jsonify({"error": "Call not found"}), 404
        return jsonify(call)

    @bp.route("/api/calls/<int:call_id>", methods=["PUT"])
    @login_required
    @require_module("call-center")
    def update_call(call_id):
        data = request.get_json(force=True)
        allowed_statuses = {"initiated", "ringing", "in_progress", "completed", "missed", "failed"}

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, status FROM call_records WHERE id = %s", (call_id,)
            )
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Call not found"}), 404

            new_status = data.get("status", existing["status"])
            if new_status not in allowed_statuses:
                return jsonify({"error": f"Invalid status: {new_status}"}), 400

            cur.execute(
                """
                UPDATE call_records
                SET status = %s,
                    notes = COALESCE(%s, notes),
                    duration_seconds = COALESCE(%s, duration_seconds),
                    recording_url = COALESCE(%s, recording_url),
                    transcript = COALESCE(%s, transcript)
                WHERE id = %s
                RETURNING id, phone_number_id, customer_id, direction, status,
                          duration_seconds, recording_url, transcript, notes, started_at, ended_at
                """,
                (
                    new_status,
                    data.get("notes"),
                    data.get("duration_seconds"),
                    data.get("recording_url"),
                    data.get("transcript"),
                    call_id,
                ),
            )
            call = cur.fetchone()
        return jsonify(call)

    @bp.route("/api/calls/<int:call_id>/end", methods=["POST"])
    @login_required
    @require_module("call-center")
    def end_call(call_id):
        data = request.get_json(force=True) or {}

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, customer_id FROM call_records WHERE id = %s", (call_id,)
            )
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Call not found"}), 404

            cur.execute(
                """
                UPDATE call_records
                SET status = 'completed',
                    ended_at = NOW(),
                    duration_seconds = COALESCE(%s, duration_seconds),
                    notes = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, phone_number_id, customer_id, direction, status,
                          duration_seconds, notes, started_at, ended_at
                """,
                (data.get("duration_seconds"), data.get("notes"), call_id),
            )
            call = cur.fetchone()

        event_bus.emit(
            "call.ended",
            {
                "call_id": call["id"],
                "customer_id": call["customer_id"],
                "duration_seconds": call["duration_seconds"],
                "status": call["status"],
            },
            tenant_id=g.tenant_id,
        )

        return jsonify(call)

    # ------------------------------------------------------------------
    # Escalations
    # ------------------------------------------------------------------

    @bp.route("/api/escalations", methods=["GET"])
    @login_required
    @require_module("call-center")
    def list_escalations():
        status = request.args.get("status")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if status:
                cur.execute(
                    """
                    SELECT id, call_id, reason, priority, status, assigned_to,
                           resolved_at, notes, created_at
                    FROM call_escalations WHERE status = %s ORDER BY created_at DESC
                    """,
                    (status,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, call_id, reason, priority, status, assigned_to,
                           resolved_at, notes, created_at
                    FROM call_escalations ORDER BY created_at DESC
                    """
                )
            escalations = cur.fetchall()
        return jsonify({"escalations": escalations})

    @bp.route("/api/calls/<int:call_id>/escalate", methods=["POST"])
    @login_required
    @require_module("call-center")
    def escalate_call(call_id):
        data = request.get_json(force=True)
        reason = (data.get("reason") or "").strip()
        if not reason:
            return jsonify({"error": "reason is required"}), 400

        priority = (data.get("priority") or "normal").strip()
        valid_priorities = {"low", "normal", "high", "urgent"}
        if priority not in valid_priorities:
            return jsonify({"error": f"priority must be one of {sorted(valid_priorities)}"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, customer_id FROM call_records WHERE id = %s", (call_id,)
            )
            call = cur.fetchone()
            if not call:
                return jsonify({"error": "Call not found"}), 404

            cur.execute(
                """
                INSERT INTO call_escalations (call_id, reason, priority, notes)
                VALUES (%s, %s, %s, %s)
                RETURNING id, call_id, reason, priority, status, assigned_to,
                          resolved_at, notes, created_at
                """,
                (
                    call_id,
                    reason,
                    priority,
                    (data.get("notes") or "").strip() or None,
                ),
            )
            escalation = cur.fetchone()

        event_bus.emit(
            "call.escalated",
            {
                "escalation_id": escalation["id"],
                "call_id": call_id,
                "customer_id": call["customer_id"],
                "reason": reason,
                "priority": priority,
            },
            tenant_id=g.tenant_id,
        )

        return jsonify(escalation), 201

    @bp.route("/api/escalations/<int:escalation_id>", methods=["PUT"])
    @login_required
    @require_module("call-center")
    def update_escalation(escalation_id):
        data = request.get_json(force=True)
        valid_statuses = {"pending", "assigned", "resolved"}

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, status FROM call_escalations WHERE id = %s",
                (escalation_id,),
            )
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Escalation not found"}), 404

            new_status = data.get("status", existing["status"])
            if new_status not in valid_statuses:
                return jsonify({"error": f"Invalid status: {new_status}"}), 400

            cur.execute(
                """
                UPDATE call_escalations
                SET status = %s,
                    assigned_to = COALESCE(%s, assigned_to),
                    notes = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, call_id, reason, priority, status, assigned_to,
                          resolved_at, notes, created_at
                """,
                (
                    new_status,
                    data.get("assigned_to"),
                    data.get("notes"),
                    escalation_id,
                ),
            )
            escalation = cur.fetchone()
        return jsonify(escalation)

    @bp.route("/api/escalations/<int:escalation_id>/resolve", methods=["POST"])
    @login_required
    @require_module("call-center")
    def resolve_escalation(escalation_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE call_escalations
                SET status = 'resolved', resolved_at = NOW()
                WHERE id = %s
                RETURNING id, call_id, reason, priority, status, assigned_to,
                          resolved_at, notes, created_at
                """,
                (escalation_id,),
            )
            escalation = cur.fetchone()
        if not escalation:
            return jsonify({"error": "Escalation not found"}), 404
        return jsonify(escalation)

    # ------------------------------------------------------------------
    # CRM Lookup
    # ------------------------------------------------------------------

    @bp.route("/api/crm/lookup", methods=["GET"])
    @login_required
    @require_module("call-center")
    def crm_lookup():
        phone = (request.args.get("phone") or "").strip()
        if not phone:
            return jsonify({"error": "phone query parameter is required"}), 400

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, email, phone, company, status
                FROM crm_customers
                WHERE phone ILIKE %s
                ORDER BY name
                LIMIT 10
                """,
                (f"%{phone}%",),
            )
            customers = cur.fetchall()

        return jsonify({"customers": customers, "query": phone})

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("call-center")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_calls,
                    COUNT(*) FILTER (WHERE status IN ('initiated', 'ringing', 'in_progress'))
                        AS active_calls,
                    COALESCE(AVG(duration_seconds) FILTER (WHERE status = 'completed'), 0)
                        AS avg_duration_seconds,
                    COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound_calls,
                    COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound_calls,
                    COUNT(*) FILTER (WHERE status = 'missed') AS missed_calls
                FROM call_records
                """
            )
            call_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS pending_escalations FROM call_escalations WHERE status = 'pending'"
            )
            esc_stats = cur.fetchone()

        return jsonify({**call_stats, **esc_stats})


# ------------------------------------------------------------------
# Event consumers
# ------------------------------------------------------------------


def on_contact_created(data):
    """Log when a CRM contact is created — no action needed, just telemetry."""
    logger.debug(
        "call-center: contact.created received for tenant=%s contact_id=%s",
        data.get("_tenant_id"),
        data.get("id"),
    )
