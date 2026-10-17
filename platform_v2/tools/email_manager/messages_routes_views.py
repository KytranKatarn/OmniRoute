"""Email HQ — messages API routes (views, sync, thread).

Second half of the messages routes, split from messages_routes.py to keep
each file under 600 lines. Registered via register_email_messages_views_routes()
which is called from register_email_messages_routes() in messages_routes.py.
"""

from __future__ import annotations

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

logger = logging.getLogger(__name__)


def register_email_messages_views_routes(bp, access_required):
    """Register smart-view, sync, and thread routes on the email blueprint."""

    # ------------------------------------------------------------------
    # Smart views (cross-mailbox)
    # ------------------------------------------------------------------

    def _smart_view(where_clause: str, params: list = None, *, visible: list | None):
        """Run a cross-mailbox view query.

        Args:
            where_clause: SQL WHERE fragment (m-aliased columns).
            params: Positional params for where_clause.
            visible: Result of get_visible_mailbox_ids(). Mandatory keyword arg —
                     omitting it raises TypeError at call time (prevents silent data leaks).
                     None = admin path (no mailbox filter).
                     list = filter to those mailbox IDs.
        """
        extra_clause = ""
        extra_params: list = []
        if visible is not None:
            extra_clause = " AND m.mailbox_id = ANY(%s)"
            extra_params = [visible]

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT m.id, m.mailbox_id, m.from_address, m.to_address, m.subject,
                           m.body_preview, m.received_at, m.is_read, m.is_starred,
                           m.is_archived, m.has_attachments, m.ai_priority, m.ai_suggestion,
                           m.size_bytes, mb.address AS mailbox_address, mb.display_name AS mailbox_name
                    FROM email_messages m
                    JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                    WHERE """
                + where_clause
                + extra_clause
                + """
                    ORDER BY m.received_at DESC
                    LIMIT 200""",
                (params or []) + extra_params,
            )
            return [dict(r) for r in cur.fetchall()]

    @bp.route("/api/email/views/action", methods=["GET"])
    @login_required
    @access_required
    def email_view_action():
        visible = get_visible_mailbox_ids(current_user)
        rows = _smart_view("m.ai_priority = 'action' AND m.is_archived = FALSE", visible=visible)
        return jsonify({"messages": rows})

    @bp.route("/api/email/views/starred", methods=["GET"])
    @login_required
    @access_required
    def email_view_starred():
        visible = get_visible_mailbox_ids(current_user)
        rows = _smart_view("m.is_starred = TRUE AND m.is_archived = FALSE", visible=visible)
        return jsonify({"messages": rows})

    @bp.route("/api/email/views/unread", methods=["GET"])
    @login_required
    @access_required
    def email_view_unread():
        visible = get_visible_mailbox_ids(current_user)
        rows = _smart_view("m.is_read = FALSE AND m.is_archived = FALSE", visible=visible)
        return jsonify({"messages": rows})

    # ------------------------------------------------------------------
    # Manual sync trigger
    # ------------------------------------------------------------------

    @bp.route("/api/email/sync/<int:mailbox_id>", methods=["POST"])
    @login_required
    @access_required
    def email_sync_mailbox(mailbox_id):
        """Trigger a full body sync for one mailbox (runs synchronously, max 50 msgs)."""
        from .sync_jobs import MailboxSyncError, sync_single_mailbox_full

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, address, imap_password FROM email_mailboxes "
                "WHERE id = %s AND provisioned = TRUE AND active = TRUE AND imap_password IS NOT NULL",
                (mailbox_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": "Mailbox not found, not provisioned, or missing password"}), 404

        try:
            new_count = sync_single_mailbox_full(row["id"], row["address"], row["imap_password"])
        except MailboxSyncError as exc:
            # Honest failure surface — never report a failed IMAP sync as success.
            logger.warning("Manual sync failed for %s (%s): %s", row["address"], exc.category, exc.original)
            return jsonify({"success": False, "error": f"{exc.category} error", "detail": str(exc.original)}), 502
        return jsonify({"success": True, "new_messages": new_count})

    @bp.route("/api/email/sync/bulk", methods=["POST"])
    @login_required
    @access_required
    def email_sync_bulk():
        """Sync IMAP for the caller's visible mailboxes.

        Admins:        full sync across all active provisioned mailboxes (same
                       as the scheduled job — uses run_email_imap_sync()).
        COLLABORATORs: their department + explicit-grant mailboxes only.

        Returns JSON: {success, synced, new_messages, errors}
        """
        from .sync_jobs import EmailSyncOutageError, run_email_imap_sync, sync_single_mailbox_full

        visible = get_visible_mailbox_ids(current_user)

        if visible is None:
            # Admin fast path — delegate to the full sync job.
            try:
                result = run_email_imap_sync()
            except EmailSyncOutageError as exc:
                logger.error("Bulk sync IMAP outage: %s", exc)
                return jsonify({"success": False, "error": "IMAP outage", "detail": str(exc)}), 502
            return jsonify(
                {
                    "success": True,
                    "synced": result["mailboxes"],
                    "new_messages": result["new_messages"],
                    "errors": result["errors"],
                }
            )

        # COLLABORATOR: only their department + granted mailboxes.
        if not visible:
            return jsonify({"success": True, "synced": 0, "new_messages": 0, "errors": 0})

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, address, imap_password FROM email_mailboxes "
                "WHERE id = ANY(%s) AND provisioned = TRUE AND active = TRUE"
                " AND imap_password IS NOT NULL",
                (visible,),
            )
            rows = cur.fetchall()

        total_new = 0
        errors = 0
        for row in rows:
            try:
                total_new += sync_single_mailbox_full(row["id"], row["address"], row["imap_password"])
            except Exception:
                logger.exception("Bulk sync error for mailbox %s", row["address"])
                errors += 1

        return jsonify(
            {
                "success": True,
                "synced": len(rows),
                "new_messages": total_new,
                "errors": errors,
            }
        )

    # ------------------------------------------------------------------
    # Thread view
    # ------------------------------------------------------------------

    @bp.route("/api/email/threads/<int:thread_id>", methods=["GET"])
    @login_required
    @access_required
    def email_get_thread(thread_id):
        """Return all messages in a thread sorted chronologically."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT t.id AS thread_id, t.subject AS thread_subject,
                          t.message_count, t.last_message_at
                   FROM email_threads t WHERE t.id = %s""",
                (thread_id,),
            )
            thread = cur.fetchone()
            if not thread:
                return jsonify({"error": "Thread not found"}), 404

            cur.execute(
                """SELECT m.id, m.mailbox_id, m.from_address, m.to_address, m.subject,
                          m.body_preview, m.body_text, m.body_html,
                          m.received_at, m.is_read, m.is_starred, m.is_archived,
                          m.has_attachments, m.ai_priority, m.ai_suggestion, m.size_bytes,
                          m.thread_id,
                          mb.display_name AS mailbox_display_name, mb.address AS mailbox_address
                   FROM email_messages m
                   JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                   WHERE m.thread_id = %s
                   ORDER BY m.received_at ASC""",
                (thread_id,),
            )
            messages = [dict(r) for r in cur.fetchall()]

        # Guard: all messages in a thread share the same mailbox — check the first.
        if messages:
            visible = get_visible_mailbox_ids(current_user)
            if visible is not None and messages[0]["mailbox_id"] not in visible:
                return jsonify({"error": "Access denied"}), 403

        for m in messages:
            if m.get("received_at"):
                m["received_at"] = m["received_at"].isoformat()
            if m.get("last_message_at"):
                m["last_message_at"] = m["last_message_at"].isoformat()

        thread_dict = dict(thread)
        if thread_dict.get("last_message_at"):
            thread_dict["last_message_at"] = thread_dict["last_message_at"].isoformat()

        return jsonify({"thread": thread_dict, "messages": messages})
