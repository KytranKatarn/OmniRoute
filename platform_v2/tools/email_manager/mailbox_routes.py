"""Email HQ — Agents tab: mailbox list + Stalwart provisioning."""

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_mailbox_routes(bp, admin_required):

    @bp.route("/api/email/mailboxes", methods=["GET"])
    @login_required
    @admin_required
    def email_list_mailboxes():
        """List all mailboxes with provisioning status, grouped by type."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT m.id, m.address, m.mailbox_type, m.display_name,
                       m.provisioned, m.provisioned_at, m.active,
                       a.name AS agent_name
                FROM email_mailboxes m
                LEFT JOIN agents a ON a.id = m.owner_agent_id
                WHERE m.active = TRUE
                ORDER BY m.mailbox_type, m.address
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("provisioned_at"):
                    r["provisioned_at"] = r["provisioned_at"].isoformat()
        return jsonify({"mailboxes": rows})

    @bp.route("/api/email/mailboxes/<int:mailbox_id>/provision", methods=["POST"])
    @login_required
    @admin_required
    def email_provision_mailbox(mailbox_id):
        """Provision a single mailbox in Stalwart."""
        from .stalwart_service import create_mailbox

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT address, display_name FROM email_mailboxes WHERE id = %s AND active = TRUE",
                (mailbox_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Mailbox not found"}), 404

        result = create_mailbox(row["address"], row["display_name"])
        if result["ok"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE email_mailboxes SET provisioned=TRUE, provisioned_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (mailbox_id,),
                )
            return jsonify({"success": True, "address": row["address"]})
        return jsonify({"success": False, "error": result.get("error")}), 500

    @bp.route("/api/email/mailboxes/provision-all-agents", methods=["POST"])
    @login_required
    @admin_required
    def email_provision_all_agents():
        """Provision all unprovisioned AI agent mailboxes in Stalwart."""
        from .stalwart_service import create_mailbox

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, address, display_name FROM email_mailboxes "
                "WHERE mailbox_type='ai_agent' AND provisioned=FALSE AND active=TRUE"
            )
            pending = cur.fetchall()

        provisioned = failed = 0
        for row in pending:
            result = create_mailbox(row["address"], row["display_name"])
            if result["ok"]:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE email_mailboxes SET provisioned=TRUE, provisioned_at=NOW(), updated_at=NOW() WHERE id=%s",
                        (row["id"],),
                    )
                provisioned += 1
            else:
                failed += 1
                logger.error("Failed to provision %s: %s", row["address"], result.get("error"))

        return jsonify({"provisioned": provisioned, "failed": failed, "skipped": len(pending) - provisioned - failed})

    @bp.route("/api/email/mailboxes", methods=["POST"])
    @login_required
    @admin_required
    def email_add_mailbox():
        """Add a human agent mailbox manually."""
        data = request.get_json() or {}
        address = (data.get("address") or "").strip().lower()
        display_name = (data.get("display_name") or "").strip()
        if not address or "@kytranempowerment.com" not in address:
            return jsonify({"error": "Must be @kytranempowerment.com"}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO email_mailboxes (address, mailbox_type, display_name)
                   VALUES (%s, 'human_agent', %s)
                   ON CONFLICT (address) DO NOTHING RETURNING id""",
                (address, display_name),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Address already exists"}), 409
        return jsonify({"success": True, "id": row["id"], "address": address})
