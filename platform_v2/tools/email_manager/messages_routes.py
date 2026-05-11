"""Email HQ — messages API routes.

Powers the three-panel layout:
  GET  /api/email/sidebar              → mailboxes grouped by dept + unread counts
  GET  /api/email/counts               → badge totals (unread, action)
  GET  /api/email/messages             → paginated message list (filter by mailbox/view)
  GET  /api/email/messages/<id>        → full message body (auto-marks read)
  POST /api/email/messages/<id>/read   → toggle is_read
  POST /api/email/messages/<id>/star   → toggle is_starred
  POST /api/email/messages/<id>/archive → archive message
  DELETE /api/email/messages/<id>      → soft-delete (sets is_archived=True)
  POST /api/email/messages/<id>/triage → trigger AI triage (async)
  POST /api/email/messages/batch-read  → mark list of IDs as read
  GET  /api/email/views/action         → cross-mailbox AI action items
  GET  /api/email/views/starred        → cross-mailbox starred messages
  GET  /api/email/views/unread         → cross-mailbox unread messages
  POST /api/email/sync/<mailbox_id>    → trigger manual sync for one mailbox
"""

from __future__ import annotations

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50


def _msg_row(r: dict) -> dict:
    """Serialise a message row for the list view (no body content)."""
    return {
        "id": r["id"],
        "mailbox_id": r["mailbox_id"],
        "from_address": r["from_address"],
        "to_address": r["to_address"],
        "subject": r["subject"],
        "preview": r["body_preview"],
        "received_at": r["received_at"].isoformat() if r.get("received_at") else None,
        "is_read": r["is_read"],
        "is_starred": r["is_starred"],
        "is_archived": r["is_archived"],
        "has_attachments": r["has_attachments"],
        "ai_priority": r.get("ai_priority"),
        "ai_suggestion": r.get("ai_suggestion"),
        "size_bytes": r.get("size_bytes"),
        "thread_id": r.get("thread_id"),
        "thread_count": r.get("thread_count"),
    }


def register_email_messages_routes(bp, admin_required):

    # ------------------------------------------------------------------
    # Sidebar + badge counts
    # ------------------------------------------------------------------

    @bp.route("/api/email/sidebar", methods=["GET"])
    @login_required
    @admin_required
    def email_sidebar():
        """Mailboxes grouped by department with per-mailbox unread counts."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT m.id, m.address, m.display_name, m.mailbox_type,
                          m.provisioned, a.name AS agent_name,
                          a.department AS department,
                          COALESCE(u.unread, 0) AS unread_count
                   FROM email_mailboxes m
                   LEFT JOIN agents a ON a.id = m.owner_agent_id
                   LEFT JOIN (
                       SELECT mailbox_id, COUNT(*) AS unread
                       FROM email_messages
                       WHERE is_read = FALSE AND is_archived = FALSE
                       GROUP BY mailbox_id
                   ) u ON u.mailbox_id = m.id
                   WHERE m.active = TRUE
                   ORDER BY m.mailbox_type, a.department, m.address"""
            )
            rows = [dict(r) for r in cur.fetchall()]

        # Group by mailbox_type / department
        groups: dict[str, list] = {}
        for r in rows:
            key = r.get("department") or r["mailbox_type"]
            groups.setdefault(key, []).append(r)

        return jsonify({"groups": groups, "mailboxes": rows})

    @bp.route("/api/email/counts", methods=["GET"])
    @login_required
    @admin_required
    def email_counts():
        """Total unread and action-priority counts for header badges."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT
                     COUNT(*) FILTER (WHERE is_read = FALSE AND is_archived = FALSE) AS unread,
                     COUNT(*) FILTER (WHERE ai_priority = 'action' AND is_archived = FALSE) AS action_items
                   FROM email_messages"""
            )
            row = dict(cur.fetchone())
        return jsonify(row)

    # ------------------------------------------------------------------
    # Message list
    # ------------------------------------------------------------------

    @bp.route("/api/email/messages", methods=["GET"])
    @login_required
    @admin_required
    def email_list_messages():
        """Paginated message list. Query params: mailbox_id, view, page, search."""
        mailbox_id = request.args.get("mailbox_id", type=int)
        view = request.args.get("view", "inbox")
        page = max(1, request.args.get("page", 1, type=int))
        search = (request.args.get("search") or "").strip()
        offset = (page - 1) * _PAGE_SIZE

        conditions = ["is_archived = FALSE"]
        params: list = []

        if mailbox_id:
            conditions.append("mailbox_id = %s")
            params.append(mailbox_id)

        if view == "unread":
            conditions.append("is_read = FALSE")
        elif view == "action":
            conditions.append("ai_priority = 'action'")
        elif view == "review":
            conditions.append("ai_priority = 'review'")
        elif view == "starred":
            conditions.append("is_starred = TRUE")

        if search:
            conditions.append("(subject ILIKE %s OR from_address ILIKE %s OR body_preview ILIKE %s)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where = " AND ".join(conditions)

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) AS total FROM email_messages WHERE " + where, params)
            total = cur.fetchone()["total"]

            cur.execute(
                "SELECT id, mailbox_id, from_address, to_address, subject,"
                " body_preview, received_at, is_read, is_starred,"
                " is_archived, has_attachments, ai_priority, ai_suggestion, size_bytes"
                " FROM email_messages WHERE " + where + " ORDER BY received_at DESC LIMIT %s OFFSET %s",
                params + [_PAGE_SIZE, offset],
            )
            messages = [_msg_row(dict(r)) for r in cur.fetchall()]

        return jsonify({"messages": messages, "total": total, "page": page, "page_size": _PAGE_SIZE})

    # ------------------------------------------------------------------
    # Single message
    # ------------------------------------------------------------------

    @bp.route("/api/email/messages/<int:message_id>", methods=["GET"])
    @login_required
    @admin_required
    def email_get_message(message_id):
        """Return full message including body. Auto-marks as read."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT m.*, mb.address AS mailbox_address, mb.mailbox_type,
                          mb.display_name AS mailbox_display_name
                   FROM email_messages m
                   JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                   WHERE m.id = %s""",
                (message_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": "Message not found"}), 404

        row = dict(row)

        # Auto-mark read
        if not row["is_read"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("UPDATE email_messages SET is_read = TRUE WHERE id = %s", (message_id,))

        result = {
            **_msg_row(row),
            "body_html": row.get("body_html"),
            "body_text": row.get("body_text"),
            "cc_address": row.get("cc_address"),
            "message_id": row.get("message_id"),
            "ai_triaged_at": row["ai_triaged_at"].isoformat() if row.get("ai_triaged_at") else None,
            "mailbox_address": row["mailbox_address"],
            "mailbox_type": row["mailbox_type"],
            "mailbox_display_name": row["mailbox_display_name"],
        }
        return jsonify(result)

    @bp.route("/api/email/messages/<int:message_id>/draft-reply", methods=["POST"])
    @login_required
    @admin_required
    def email_draft_reply(message_id):
        """Dispatch to R.E.S.O.L.V.E. via DHQ to draft a professional reply.

        Returns {draft: str, agent: str} or {error: str}.
        """
        from tools.department_hq.services.department_dispatcher import dispatch_json

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT m.subject, m.from_address, m.body_text, m.body_preview,
                          mb.mailbox_type, mb.display_name AS mailbox_name
                   FROM email_messages m
                   JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                   WHERE m.id = %s""",
                (message_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": "Message not found"}), 404

        mailbox_type = row["mailbox_type"]
        if mailbox_type not in ("owner", "business"):
            return jsonify({"error": f"Draft reply not available for {mailbox_type} mailboxes"})

        body_snippet = (row["body_text"] or row["body_preview"] or "")[:1000]

        prompt = (
            f"Draft a concise, professional email reply to the following message.\n\n"
            f"Mailbox: {row['mailbox_name']}\n"
            f"From: {row['from_address']}\n"
            f"Subject: {row['subject']}\n"
            f"Message:\n{body_snippet}\n\n"
            f"Write only the reply body text — no subject line, no greeting header, "
            f"no 'Here is a draft' preamble. Start directly with the reply content."
        )

        result = dispatch_json(capability="support", prompt=prompt)
        if not result.get("success"):
            return jsonify({"error": result.get("error", "Dispatch failed")}), 500

        draft = (result.get("response") or "").strip()
        agent = result.get("agent_name") or "R.E.S.O.L.V.E."
        return jsonify({"draft": draft, "agent": agent})

    # ------------------------------------------------------------------
    # Message actions
    # ------------------------------------------------------------------

    @bp.route("/api/email/messages/<int:message_id>/read", methods=["POST"])
    @login_required
    @admin_required
    def email_toggle_read(message_id):
        """Toggle is_read. Body: {read: bool} (optional — toggles if omitted)."""
        data = request.get_json() or {}
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT is_read FROM email_messages WHERE id = %s", (message_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Message not found"}), 404

        new_read = data.get("read", not row["is_read"])
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE email_messages SET is_read = %s WHERE id = %s", (new_read, message_id))
        return jsonify({"success": True, "is_read": new_read})

    @bp.route("/api/email/messages/<int:message_id>/star", methods=["POST"])
    @login_required
    @admin_required
    def email_toggle_star(message_id):
        """Toggle is_starred."""
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT is_starred FROM email_messages WHERE id = %s", (message_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Message not found"}), 404

        new_starred = not row["is_starred"]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE email_messages SET is_starred = %s WHERE id = %s",
                (new_starred, message_id),
            )
        return jsonify({"success": True, "is_starred": new_starred})

    @bp.route("/api/email/messages/<int:message_id>/archive", methods=["POST"])
    @login_required
    @admin_required
    def email_archive_message(message_id):
        """Archive a message (sets is_archived=True, is_read=True)."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE email_messages SET is_archived = TRUE, is_read = TRUE WHERE id = %s",
                (message_id,),
            )
            if not cur.rowcount:
                return jsonify({"error": "Message not found"}), 404
        return jsonify({"success": True})

    @bp.route("/api/email/messages/<int:message_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def email_delete_message(message_id):
        """Soft-delete by archiving (no hard deletes on email)."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE email_messages SET is_archived = TRUE WHERE id = %s", (message_id,))
            if not cur.rowcount:
                return jsonify({"error": "Message not found"}), 404
        return jsonify({"success": True})

    @bp.route("/api/email/messages/<int:message_id>/triage", methods=["POST"])
    @login_required
    @admin_required
    def email_triage_message(message_id):
        """Trigger AI triage (async). Returns immediately."""
        from .triage_service import triage_message_async

        triage_message_async(message_id)
        return jsonify({"success": True, "queued": True})

    @bp.route("/api/email/messages/batch-read", methods=["POST"])
    @login_required
    @admin_required
    def email_batch_read():
        """Mark a list of message IDs as read. Body: {ids: [int, ...]}"""
        data = request.get_json() or {}
        ids = [int(i) for i in (data.get("ids") or []) if str(i).isdigit()]
        if not ids:
            return jsonify({"error": "ids required"}), 400
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE email_messages SET is_read = TRUE WHERE id = ANY(%s)", (ids,))
            updated = cur.rowcount
        return jsonify({"success": True, "updated": updated})

    # ------------------------------------------------------------------
    # Smart views (cross-mailbox)
    # ------------------------------------------------------------------

    def _smart_view(where_clause: str, params: list = None):
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT m.id, m.mailbox_id, m.from_address, m.to_address, m.subject,
                           m.body_preview, m.received_at, m.is_read, m.is_starred,
                           m.is_archived, m.has_attachments, m.ai_priority, m.ai_suggestion,
                           m.size_bytes, mb.address AS mailbox_address, mb.display_name AS mailbox_name
                    FROM email_messages m
                    JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                    WHERE {where_clause}
                    ORDER BY m.received_at DESC
                    LIMIT 200""",
                params or [],
            )
            return [dict(r) for r in cur.fetchall()]

    @bp.route("/api/email/views/action", methods=["GET"])
    @login_required
    @admin_required
    def email_view_action():
        rows = _smart_view("m.ai_priority = 'action' AND m.is_archived = FALSE")
        return jsonify({"messages": rows})

    @bp.route("/api/email/views/starred", methods=["GET"])
    @login_required
    @admin_required
    def email_view_starred():
        rows = _smart_view("m.is_starred = TRUE AND m.is_archived = FALSE")
        return jsonify({"messages": rows})

    @bp.route("/api/email/views/unread", methods=["GET"])
    @login_required
    @admin_required
    def email_view_unread():
        rows = _smart_view("m.is_read = FALSE AND m.is_archived = FALSE")
        return jsonify({"messages": rows})

    # ------------------------------------------------------------------
    # Manual sync trigger
    # ------------------------------------------------------------------

    @bp.route("/api/email/sync/<int:mailbox_id>", methods=["POST"])
    @login_required
    @admin_required
    def email_sync_mailbox(mailbox_id):
        """Trigger a full body sync for one mailbox (runs synchronously, max 50 msgs)."""
        from .sync_jobs import sync_single_mailbox_full

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, address, imap_password FROM email_mailboxes "
                "WHERE id = %s AND provisioned = TRUE AND active = TRUE AND imap_password IS NOT NULL",
                (mailbox_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": "Mailbox not found, not provisioned, or missing password"}), 404

        new_count = sync_single_mailbox_full(row["id"], row["address"], row["imap_password"])
        return jsonify({"success": True, "new_messages": new_count})

    # ------------------------------------------------------------------
    # Thread view
    # ------------------------------------------------------------------

    @bp.route("/api/email/threads/<int:thread_id>", methods=["GET"])
    @login_required
    @admin_required
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
            for m in messages:
                if m.get("received_at"):
                    m["received_at"] = m["received_at"].isoformat()
                if m.get("last_message_at"):
                    m["last_message_at"] = m["last_message_at"].isoformat()

        thread_dict = dict(thread)
        if thread_dict.get("last_message_at"):
            thread_dict["last_message_at"] = thread_dict["last_message_at"].isoformat()

        return jsonify({"thread": thread_dict, "messages": messages})
