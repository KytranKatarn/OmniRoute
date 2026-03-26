"""Help Desk plugin routes — tickets, comments, SLA, assignment, resolution."""

import logging
from datetime import datetime, timezone

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def _next_ticket_number(cur, tenant_id: int) -> str:
    """Generate the next sequential HD-NNNN ticket number for this tenant."""
    cur.execute("SELECT COUNT(*) FROM support_tickets")
    row = cur.fetchone()
    count = row[0] if row else 0
    return f"HD-{count + 1:04d}"


def register_routes(bp):
    """Attach all Help Desk routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("help-desk")
    def index():
        return render_template("help_desk.html")

    # ------------------------------------------------------------------
    # Tickets — list + create
    # ------------------------------------------------------------------

    @bp.route("/api/tickets", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def list_tickets():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        priority = request.args.get("priority")
        category = request.args.get("category")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            conditions = []
            params: list = []
            if status:
                conditions.append("status = %s")
                params.append(status)
            if priority:
                conditions.append("priority = %s")
                params.append(priority)
            if category:
                conditions.append("category = %s")
                params.append(category)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM support_tickets {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, ticket_number, customer_id, subject, status, priority,
                       category, assigned_to, tags, created_at, updated_at,
                       resolved_at, closed_at
                FROM support_tickets
                {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            tickets = cur.fetchall()

        return jsonify(
            {
                "tickets": tickets,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/tickets", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def create_ticket():
        data = request.get_json(force=True)
        subject = (data.get("subject") or "").strip()
        if not subject:
            return jsonify({"error": "subject is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            ticket_number = _next_ticket_number(cur, g.tenant_id)

            cur.execute(
                """
                INSERT INTO support_tickets
                    (ticket_number, customer_id, subject, description, status,
                     priority, category, assigned_to, tags, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, ticket_number, customer_id, subject, description,
                          status, priority, category, assigned_to, tags, metadata,
                          created_at, updated_at, resolved_at, closed_at
                """,
                (
                    ticket_number,
                    data.get("customer_id"),
                    subject,
                    data.get("description"),
                    data.get("status", "open"),
                    data.get("priority", "medium"),
                    data.get("category"),
                    data.get("assigned_to"),
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            ticket = cur.fetchone()

        event_bus.emit(
            "ticket.created",
            {
                "ticket_id": ticket["id"],
                "ticket_number": ticket["ticket_number"],
                "subject": ticket["subject"],
                "priority": ticket["priority"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(ticket), 201

    # ------------------------------------------------------------------
    # Tickets — single ticket
    # ------------------------------------------------------------------

    @bp.route("/api/tickets/<int:ticket_id>", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def get_ticket(ticket_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT id, ticket_number, customer_id, subject, description,
                       status, priority, category, assigned_to, tags, metadata,
                       created_at, updated_at, resolved_at, closed_at
                FROM support_tickets WHERE id = %s
                """,
                (ticket_id,),
            )
            ticket = cur.fetchone()
            if ticket is None:
                return jsonify({"error": "ticket not found"}), 404

            cur.execute(
                """
                SELECT id, ticket_id, author, content, is_internal, metadata, created_at
                FROM ticket_comments WHERE ticket_id = %s ORDER BY created_at ASC
                """,
                (ticket_id,),
            )
            comments = cur.fetchall()

        return jsonify({"ticket": ticket, "comments": comments})

    @bp.route("/api/tickets/<int:ticket_id>", methods=["PUT"])
    @login_required
    @require_module("help-desk")
    def update_ticket(ticket_id):
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM support_tickets WHERE id = %s", (ticket_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "ticket not found"}), 404

            fields = []
            params: list = []
            allowed = ["subject", "description", "status", "priority", "category",
                       "assigned_to"]
            for field in allowed:
                if field in data:
                    fields.append(f"{field} = %s")
                    params.append(data[field])
            if "tags" in data:
                fields.append("tags = %s")
                params.append(Json(data["tags"]))
            if "metadata" in data:
                fields.append("metadata = %s")
                params.append(Json(data["metadata"]))

            if not fields:
                return jsonify({"error": "no fields to update"}), 400

            fields.append("updated_at = NOW()")
            params.append(ticket_id)

            cur.execute(
                f"""
                UPDATE support_tickets SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, ticket_number, customer_id, subject, description,
                          status, priority, category, assigned_to, tags, metadata,
                          created_at, updated_at, resolved_at, closed_at
                """,
                params,
            )
            ticket = cur.fetchone()

        event_bus.emit(
            "ticket.updated",
            {"ticket_id": ticket_id, "changes": list(data.keys())},
            tenant_id=g.tenant_id,
        )
        return jsonify(ticket)

    # ------------------------------------------------------------------
    # Ticket actions
    # ------------------------------------------------------------------

    @bp.route("/api/tickets/<int:ticket_id>/assign", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def assign_ticket(ticket_id):
        data = request.get_json(force=True)
        assigned_to = (data.get("assigned_to") or "").strip()
        if not assigned_to:
            return jsonify({"error": "assigned_to is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE support_tickets
                SET assigned_to = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, ticket_number, assigned_to, updated_at
                """,
                (assigned_to, ticket_id),
            )
            ticket = cur.fetchone()
            if ticket is None:
                return jsonify({"error": "ticket not found"}), 404

        event_bus.emit(
            "ticket.updated",
            {"ticket_id": ticket_id, "assigned_to": assigned_to},
            tenant_id=g.tenant_id,
        )
        return jsonify(ticket)

    @bp.route("/api/tickets/<int:ticket_id>/resolve", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def resolve_ticket(ticket_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE support_tickets
                SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING id, ticket_number, status, resolved_at, updated_at
                """,
                (ticket_id,),
            )
            ticket = cur.fetchone()
            if ticket is None:
                return jsonify({"error": "ticket not found"}), 404

        event_bus.emit(
            "ticket.resolved",
            {"ticket_id": ticket_id, "ticket_number": ticket["ticket_number"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(ticket)

    @bp.route("/api/tickets/<int:ticket_id>/close", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def close_ticket(ticket_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE support_tickets
                SET status = 'closed', closed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING id, ticket_number, status, closed_at, updated_at
                """,
                (ticket_id,),
            )
            ticket = cur.fetchone()
            if ticket is None:
                return jsonify({"error": "ticket not found"}), 404

        event_bus.emit(
            "ticket.closed",
            {"ticket_id": ticket_id, "ticket_number": ticket["ticket_number"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(ticket)

    @bp.route("/api/tickets/<int:ticket_id>/reopen", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def reopen_ticket(ticket_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE support_tickets
                SET status = 'open', resolved_at = NULL, closed_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, ticket_number, status, resolved_at, closed_at, updated_at
                """,
                (ticket_id,),
            )
            ticket = cur.fetchone()
            if ticket is None:
                return jsonify({"error": "ticket not found"}), 404

        event_bus.emit(
            "ticket.updated",
            {"ticket_id": ticket_id, "action": "reopen"},
            tenant_id=g.tenant_id,
        )
        return jsonify(ticket)

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    @bp.route("/api/tickets/<int:ticket_id>/comments", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def list_comments(ticket_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM support_tickets WHERE id = %s", (ticket_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "ticket not found"}), 404

            cur.execute(
                """
                SELECT id, ticket_id, author, content, is_internal, metadata, created_at
                FROM ticket_comments WHERE ticket_id = %s ORDER BY created_at ASC
                """,
                (ticket_id,),
            )
            comments = cur.fetchall()

        return jsonify({"comments": comments})

    @bp.route("/api/tickets/<int:ticket_id>/comments", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def add_comment(ticket_id):
        data = request.get_json(force=True)
        author = (data.get("author") or "").strip()
        content = (data.get("content") or "").strip()
        if not author:
            return jsonify({"error": "author is required"}), 400
        if not content:
            return jsonify({"error": "content is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM support_tickets WHERE id = %s", (ticket_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "ticket not found"}), 404

            cur.execute(
                """
                INSERT INTO ticket_comments (ticket_id, author, content, is_internal, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, ticket_id, author, content, is_internal, metadata, created_at
                """,
                (
                    ticket_id,
                    author,
                    content,
                    data.get("is_internal", False),
                    Json(data.get("metadata", {})),
                ),
            )
            comment = cur.fetchone()

            # Touch updated_at on the ticket
            cur.execute(
                "UPDATE support_tickets SET updated_at = NOW() WHERE id = %s",
                (ticket_id,),
            )

        return jsonify(comment), 201

    # ------------------------------------------------------------------
    # SLA Policies
    # ------------------------------------------------------------------

    @bp.route("/api/sla", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def list_sla():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, priority, first_response_hours, resolution_hours,
                       is_active, created_at
                FROM sla_policies ORDER BY priority, name
                """
            )
            policies = cur.fetchall()
        return jsonify({"policies": policies})

    @bp.route("/api/sla", methods=["POST"])
    @login_required
    @require_module("help-desk")
    def create_sla():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        priority = (data.get("priority") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not priority:
            return jsonify({"error": "priority is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO sla_policies
                    (name, priority, first_response_hours, resolution_hours, is_active)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, priority, first_response_hours, resolution_hours,
                          is_active, created_at
                """,
                (
                    name,
                    priority,
                    data.get("first_response_hours", 24),
                    data.get("resolution_hours", 72),
                    data.get("is_active", True),
                ),
            )
            policy = cur.fetchone()

        return jsonify(policy), 201

    @bp.route("/api/sla/<int:policy_id>", methods=["PUT"])
    @login_required
    @require_module("help-desk")
    def update_sla(policy_id):
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM sla_policies WHERE id = %s", (policy_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "SLA policy not found"}), 404

            fields = []
            params: list = []
            for field in ["name", "priority", "first_response_hours",
                          "resolution_hours", "is_active"]:
                if field in data:
                    fields.append(f"{field} = %s")
                    params.append(data[field])

            if not fields:
                return jsonify({"error": "no fields to update"}), 400

            params.append(policy_id)
            cur.execute(
                f"""
                UPDATE sla_policies SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, name, priority, first_response_hours, resolution_hours,
                          is_active, created_at
                """,
                params,
            )
            policy = cur.fetchone()

        return jsonify(policy)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("help-desk")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_tickets,
                    COUNT(*) FILTER (WHERE status IN ('open','in_progress','waiting'))
                        AS open_tickets,
                    ROUND(
                        AVG(
                            EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0
                        ) FILTER (WHERE resolved_at IS NOT NULL),
                        2
                    ) AS avg_resolution_hours,
                    COUNT(*) FILTER (WHERE status = 'resolved' OR status = 'closed')
                        AS resolved_tickets
                FROM support_tickets
                """
            )
            row = cur.fetchone()

        total = row["total_tickets"] or 0
        resolved = row["resolved_tickets"] or 0
        sla_compliance_rate = round((resolved / total * 100), 1) if total > 0 else 0.0

        return jsonify(
            {
                "total_tickets": total,
                "open_tickets": row["open_tickets"] or 0,
                "avg_resolution_hours": float(row["avg_resolution_hours"] or 0),
                "sla_compliance_rate": sla_compliance_rate,
            }
        )


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------


def on_contact_created(data):
    """Placeholder — no-op when a CRM contact is created."""
    logger.debug(
        "help-desk received contact.created event for contact_id=%s",
        data.get("customer_id"),
    )
