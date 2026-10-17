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
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

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


def _sent_replies_for(cur, message_id, thread_id):
    """Executed agent approve-to-send replies linked to this message (or its thread).

    Sourced from autonomy_approval_queue (action_type='email_reply', status='executed'),
    which carries the original message_id, thread_id, drafted body, agent + executed_at.
    Manual compose sends (email_activity_log — no thread link / body) are a follow-up
    (#4523 ph2; would need thread_id on the activity log).
    """
    tid = str(thread_id) if thread_id is not None else None
    cur.execute(
        """SELECT action_data->>'to_address'   AS to_address,
                  action_data->>'from_address' AS from_address,
                  action_data->>'subject'      AS subject,
                  action_data->>'draft_reply'  AS body,
                  action_data->>'agent'        AS agent,
                  executed_at
             FROM autonomy_approval_queue
            WHERE action_type = 'email_reply' AND status = 'executed'
              AND ( action_data->>'message_id' = %s
                    OR (%s IS NOT NULL AND action_data->>'thread_id' = %s) )
            ORDER BY executed_at ASC NULLS LAST""",
        (str(message_id), tid, tid),
    )
    replies = []
    for r in cur.fetchall():
        r = dict(r)
        replies.append(
            {
                "to_address": r.get("to_address"),
                "from_address": r.get("from_address"),
                "subject": r.get("subject"),
                "body": r.get("body"),
                "agent": r.get("agent"),
                "sent_at": r["executed_at"].isoformat() if r.get("executed_at") else None,
            }
        )
    return replies


def register_email_messages_routes(bp, admin_required):

    # ------------------------------------------------------------------
    # Sidebar + badge counts
    # ------------------------------------------------------------------

    @bp.route("/api/email/sidebar", methods=["GET"])
    @login_required
    @admin_required
    def email_sidebar():
        """Mailboxes grouped by department with per-mailbox unread counts."""
        visible = get_visible_mailbox_ids(current_user)
        # None = admin (no filter). list = scoped to dept + explicit grants.
        mailbox_filter = " AND m.id = ANY(%s)" if visible is not None else ""
        filter_params = [visible] if visible is not None else []

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
                   WHERE m.active = TRUE"""
                + mailbox_filter
                + " ORDER BY m.mailbox_type, a.department, m.address",
                filter_params,
            )
            rows = [dict(r) for r in cur.fetchall()]

        # Group by mailbox_type / department.
        # human_agent mailboxes always group under their mailbox_type key so the
        # "Human Agents" section stays together at the bottom of the sidebar
        # regardless of which department the linked agent belongs to.
        groups: dict[str, list] = {}
        for r in rows:
            if r["mailbox_type"] == "human_agent":
                key = "human_agent"
            else:
                key = r.get("department") or r["mailbox_type"]
            groups.setdefault(key, []).append(r)

        return jsonify({"groups": groups, "mailboxes": rows})

    @bp.route("/api/email/counts", methods=["GET"])
    @login_required
    @admin_required
    def email_counts():
        """Total unread and action-priority counts for header badges."""
        visible = get_visible_mailbox_ids(current_user)
        mailbox_filter = " WHERE mailbox_id = ANY(%s)" if visible is not None else ""
        filter_params = [visible] if visible is not None else []

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT"
                " COUNT(*) FILTER (WHERE is_read = FALSE AND is_archived = FALSE) AS unread,"
                " COUNT(*) FILTER (WHERE ai_priority = 'action' AND is_archived = FALSE) AS action_items"
                " FROM email_messages" + mailbox_filter,
                filter_params,
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

        visible = get_visible_mailbox_ids(current_user)

        # All conditions use the "em" alias to avoid ambiguity when
        # LEFT JOIN email_threads is added to the main SELECT query.
        conditions = ["em.is_archived = FALSE"]
        params: list = []

        if mailbox_id:
            # Guard: COLLABORATOR must not access a mailbox outside their scope.
            if visible is not None and mailbox_id not in visible:
                return jsonify({"error": "Access denied"}), 403
            conditions.append("em.mailbox_id = %s")
            params.append(mailbox_id)
        elif visible is not None:
            # No specific mailbox requested — scope to all accessible mailboxes.
            conditions.append("em.mailbox_id = ANY(%s)")
            params.append(visible)

        if view == "unread":
            conditions.append("em.is_read = FALSE")
        elif view == "action":
            conditions.append("em.ai_priority = 'action'")
        elif view == "review":
            conditions.append("em.ai_priority = 'review'")
        elif view == "starred":
            conditions.append("em.is_starred = TRUE")

        if search:
            conditions.append("(em.subject ILIKE %s OR em.from_address ILIKE %s OR em.body_preview ILIKE %s)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where = " AND ".join(conditions)

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) AS total FROM email_messages em WHERE " + where, params)
            total = cur.fetchone()["total"]

            cur.execute(
                "SELECT em.id, em.mailbox_id, em.from_address, em.to_address, em.subject,"
                " em.body_preview, em.received_at, em.is_read, em.is_starred,"
                " em.is_archived, em.has_attachments, em.ai_priority, em.ai_suggestion,"
                " em.size_bytes, em.thread_id, COALESCE(t.message_count, 1) AS thread_count"
                " FROM email_messages em"
                " LEFT JOIN email_threads t ON t.id = em.thread_id"
                " WHERE " + where + " ORDER BY em.received_at DESC LIMIT %s OFFSET %s",
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
                          mb.display_name AS mailbox_display_name,
                          COALESCE(t.message_count, 1) AS thread_count
                   FROM email_messages m
                   JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                   LEFT JOIN email_threads t ON t.id = m.thread_id
                   WHERE m.id = %s""",
                (message_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": "Message not found"}), 404

        row = dict(row)

        # Guard: COLLABORATOR must not read messages from inaccessible mailboxes.
        visible = get_visible_mailbox_ids(current_user)
        if visible is not None and row["mailbox_id"] not in visible:
            return jsonify({"error": "Access denied"}), 403

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

        # #4523: surface agent replies already sent for this message/thread so the
        # read pane shows both sides of the conversation, not just inbound mail.
        try:
            with get_db_cursor() as (conn, cur):
                result["sent_replies"] = _sent_replies_for(cur, message_id, row.get("thread_id"))
        except Exception as exc:
            logger.debug("[email] sent_replies lookup failed for msg=%s: %s", message_id, exc)
            result["sent_replies"] = []
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

        # Guard: COLLABORATOR must not generate drafts for inaccessible mailboxes.
        visible = get_visible_mailbox_ids(current_user)
        if visible is not None and row["mailbox_id"] not in visible:
            return jsonify({"error": "Access denied"}), 403

        mailbox_type = row["mailbox_type"]
        if mailbox_type not in ("owner", "business", "human_agent"):
            return jsonify({"error": f"Draft reply not available for {mailbox_type} mailboxes"}), 400

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

    @bp.route("/api/email/messages/<int:message_id>/create-task", methods=["POST"])
    @login_required
    @admin_required
    def email_create_task(message_id):
        """Convert an email into a Dev HQ unified_task.

        Dispatches the email to C.O.D.E.X. (capability='documentation') to extract
        a concise task title + summary, then inserts a row into unified_tasks linked
        back to the source email via metadata JSONB. Fails soft — if dispatch fails
        the raw subject is used as the title.

        Returns {success, task_id, title} or {error}.
        """
        from psycopg2.extras import Json
        from tools.department_hq.services.department_dispatcher import dispatch_json

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT m.subject, m.from_address, m.body_text, m.body_preview,
                          m.mailbox_id, mb.mailbox_type, mb.address AS mailbox_address
                   FROM email_messages m
                   JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                   WHERE m.id = %s""",
                (message_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"error": "Message not found"}), 404

        # Guard: COLLABORATOR must not create tasks from inaccessible mailboxes.
        visible = get_visible_mailbox_ids(current_user)
        if visible is not None and row["mailbox_id"] not in visible:
            return jsonify({"error": "Access denied"}), 403

        subject = (row["subject"] or "").strip() or "(no subject)"
        from_address = row["from_address"] or ""
        mailbox_address = row["mailbox_address"] or ""
        body_snippet = (row["body_text"] or row["body_preview"] or "")[:1500]

        # Ask C.O.D.E.X. to extract a concise actionable title + summary.
        prompt = (
            f"Extract a concise, actionable task from this email.\n\n"
            f"From: {from_address}\n"
            f"Subject: {subject}\n"
            f"Body:\n{body_snippet}\n\n"
            f"Respond with exactly two lines:\n"
            f"TITLE: <a short imperative task title, max 80 chars>\n"
            f"SUMMARY: <one or two sentences describing what needs to be done>"
        )

        title = subject[:200]
        summary = ""
        try:
            result = dispatch_json(capability="documentation", prompt=prompt)
            if result.get("success"):
                text = (result.get("response") or "").strip()
                for line in text.splitlines():
                    stripped = line.strip()
                    upper = stripped.upper()
                    if upper.startswith("TITLE:"):
                        extracted = stripped.split(":", 1)[1].strip()
                        if extracted:
                            title = extracted[:200]
                    elif upper.startswith("SUMMARY:"):
                        summary = stripped.split(":", 1)[1].strip()
        except Exception:
            logger.exception("create-task dispatch failed for message %s", message_id)

        description_parts = []
        if summary:
            description_parts.append(summary)
        description_parts.append(f"From: {from_address}")
        description_parts.append(f"Mailbox: {mailbox_address}")
        if body_snippet:
            description_parts.append("\n--- Email excerpt ---\n" + body_snippet[:800])
        description = "\n".join(description_parts)

        metadata = {
            "source": "email",
            "email_message_id": message_id,
            "mailbox_address": mailbox_address,
            "from_address": from_address,
        }

        # Project #359 = Email HQ. Priority 5 = default (INTEGER).
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO unified_tasks
                       (project_id, title, description, task_type, priority, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (359, title, description, "email", 5, Json(metadata)),
            )
            task_id = cur.fetchone()["id"]

        return jsonify({"success": True, "task_id": task_id, "title": title})

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
        ids = [i for i in (data.get("ids") or []) if isinstance(i, int) and i > 0]
        if not ids:
            return jsonify({"error": "ids required"}), 400

        visible = get_visible_mailbox_ids(current_user)
        with get_db_cursor(commit=True) as (conn, cur):
            if visible is not None:
                # Scope the UPDATE to only messages in accessible mailboxes —
                # out-of-scope IDs are silently skipped (not an error).
                cur.execute(
                    "UPDATE email_messages SET is_read = TRUE" " WHERE id = ANY(%s) AND mailbox_id = ANY(%s)",
                    (ids, visible),
                )
            else:
                cur.execute("UPDATE email_messages SET is_read = TRUE WHERE id = ANY(%s)", (ids,))
            updated = cur.rowcount
        return jsonify({"success": True, "updated": updated})

    # ------------------------------------------------------------------
    # Smart views, sync, and thread routes live in messages_routes_views.py
    # ------------------------------------------------------------------
    from .messages_routes_views import register_email_messages_views_routes

    register_email_messages_views_routes(bp, admin_required)
