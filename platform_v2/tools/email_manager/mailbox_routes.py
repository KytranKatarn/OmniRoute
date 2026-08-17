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

        # force_reset: this is an EXPLICIT admin action that persists the new
        # credential to email_mailboxes below — the both-sides rotation #5698's
        # guard exists to protect is exactly what this route does correctly.
        result = create_mailbox(row["address"], row["display_name"], force_reset=True)
        if result["ok"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE email_mailboxes SET provisioned=TRUE, provisioned_at=NOW(), "
                    "imap_password=%s, updated_at=NOW() WHERE id=%s",
                    (result.get("password"), mailbox_id),
                )
            return jsonify({"success": True, "address": row["address"]})
        return jsonify({"success": False, "error": result.get("error")})

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
                        "UPDATE email_mailboxes SET provisioned=TRUE, provisioned_at=NOW(), "
                        "imap_password=%s, updated_at=NOW() WHERE id=%s",
                        (result.get("password"), row["id"]),
                    )
                provisioned += 1
            else:
                failed += 1
                logger.error("Failed to provision %s: %s", row["address"], result.get("error"))

        return jsonify({"provisioned": provisioned, "failed": failed, "skipped": len(pending) - provisioned - failed})

    @bp.route("/api/email/mailboxes/provision-owner", methods=["POST"])
    @login_required
    @admin_required
    def email_provision_owner():
        """Provision kytran@kytranempowerment.com as the owner inbox (10 GB quota)."""
        from .stalwart_service import create_mailbox

        address = "kytran@kytranempowerment.com"
        display_name = "Kytran Katarn"

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO email_mailboxes (address, mailbox_type, display_name)
                   VALUES (%s, 'owner', %s)
                   ON CONFLICT (address) DO UPDATE SET mailbox_type='owner', active=TRUE
                   RETURNING id""",
                (address, display_name),
            )
            row = cur.fetchone()
            mailbox_id = row["id"]

        # force_reset: explicit owner-provisioning admin action; the new
        # credential is persisted to email_mailboxes below (#5698 guard).
        result = create_mailbox(address, display_name, quota_gb=10, force_reset=True)
        # If Stalwart returns 409 (already exists), rotate the password instead
        if not result["ok"] and "409" in str(result.get("error", "")):
            from .stalwart_service import update_password

            result = update_password(address)

        if result["ok"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE email_mailboxes SET provisioned=TRUE, provisioned_at=NOW(), "
                    "imap_password=%s, updated_at=NOW() WHERE id=%s",
                    (result["password"], mailbox_id),
                )
            logger.info("Owner mailbox provisioned: %s", address)
            return jsonify({"success": True, "address": address})
        return jsonify({"success": False, "error": result.get("error")})

    @bp.route("/api/email/mailboxes/<int:mailbox_id>/rotate-password", methods=["POST"])
    @login_required
    @admin_required
    def email_rotate_mailbox_password(mailbox_id):
        """Generate a new password for an already-provisioned mailbox and save it."""
        from .stalwart_service import update_password

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT address FROM email_mailboxes WHERE id = %s AND active = TRUE AND provisioned = TRUE",
                (mailbox_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Mailbox not found or not provisioned"}), 404

        result = update_password(row["address"])
        if result["ok"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE email_mailboxes SET imap_password=%s, updated_at=NOW() WHERE id=%s",
                    (result["password"], mailbox_id),
                )
            return jsonify({"success": True, "address": row["address"]})
        return jsonify({"success": False, "error": result.get("error")}), 500

    @bp.route("/api/email/mailboxes/rotate-all-passwords", methods=["POST"])
    @login_required
    @admin_required
    def email_rotate_all_passwords():
        """Rotate passwords for all provisioned mailboxes that have no saved imap_password."""
        from .stalwart_service import update_password

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, address FROM email_mailboxes "
                "WHERE provisioned = TRUE AND active = TRUE AND imap_password IS NULL"
            )
            pending = cur.fetchall()

        rotated = failed = 0
        for row in pending:
            result = update_password(row["address"])
            if result["ok"]:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE email_mailboxes SET imap_password=%s, updated_at=NOW() WHERE id=%s",
                        (result["password"], row["id"]),
                    )
                rotated += 1
            else:
                failed += 1
                logger.error("Failed to rotate password for %s: %s", row["address"], result.get("error"))

        return jsonify({"rotated": rotated, "failed": failed})

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
