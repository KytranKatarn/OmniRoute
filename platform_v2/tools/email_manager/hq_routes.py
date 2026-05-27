"""Email HQ routes — unified inbox, assign-to-agent, rules, stats, and R.E.S.O.L.V.E. oversight."""

import logging
from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)

# ── R.E.S.O.L.V.E. Oversight ─────────────────────────────────────────────────

_INQUIRY_CATEGORIES = {
    "support": ["help", "issue", "problem", "broken", "not working", "error", "bug", "fail", "ticket"],
    "sales": ["price", "pricing", "cost", "quote", "demo", "trial", "purchase", "buy", "plan", "subscription"],
    "complaint": ["complaint", "frustrated", "unacceptable", "disappointed", "refund", "cancel", "wrong"],
    "inquiry": ["question", "wondering", "could you", "can you", "would you", "how do", "what is", "info"],
}


def _classify_email(subject: str, from_address: str) -> str:
    """Simple keyword classifier — avoids LLM dependency in the scheduled job."""
    text = (subject or "").lower()
    for category, keywords in _INQUIRY_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category
    return "general"


def run_resolve_oversight(threshold_hours: int = 24) -> dict:
    """Scan for unanswered inbound emails, assign to R.E.S.O.L.V.E., auto-create tickets.

    Called by the agent loop job AND the /api/hq/oversight/scan endpoint.
    Returns summary: {scanned, flagged, tickets_created, already_processed}.
    """
    scanned = flagged = tickets = already = 0

    with get_db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT al.id, al.mailbox_address, al.from_address, al.subject, al.logged_at
            FROM email_activity_log al
            WHERE al.direction = 'received'
              AND al.logged_at < NOW() - (%s || ' hours')::interval
              AND al.logged_at > NOW() - INTERVAL '7 days'
              AND al.read_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM email_activity_log reply
                  WHERE reply.direction = 'sent'
                    AND reply.to_address = al.from_address
                    AND reply.logged_at > al.logged_at
              )
            ORDER BY al.logged_at ASC
            LIMIT 50
            """,
            (str(threshold_hours),),
        )
        emails = [dict(r) for r in cur.fetchall()]
        scanned = len(emails)

    for email in emails:
        eid = email["id"]

        # Skip if already assigned by oversight
        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT id FROM email_assignments WHERE email_id=%s AND assigned_by='resolve_oversight'",
                (eid,),
            )
            if cur.fetchone():
                already += 1
                continue

        category = _classify_email(email.get("subject", ""), email.get("from_address", ""))
        note = f"Auto-flagged by R.E.S.O.L.V.E. | Category: {category} | From: {email.get('from_address', '?')}"

        # Assign to R.E.S.O.L.V.E. in email_assignments
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """INSERT INTO email_assignments (email_id, assigned_agent, assigned_by, notes, status)
                   VALUES (%s, 'R.E.S.O.L.V.E.', 'resolve_oversight', %s, 'open')
                   ON CONFLICT DO NOTHING""",
                (eid, note),
            )

        # Auto-create unified_task ticket
        subject_snippet = (email.get("subject") or "(no subject)")[:80]
        task_title = f"Unanswered {category} email: {subject_snippet}"
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """INSERT INTO unified_tasks
                       (title, task_type, priority, status, description, delegation_source)
                   VALUES (%s, 'support', 7, 'pending', %s, 'resolve_oversight')
                   ON CONFLICT DO NOTHING""",
                (
                    task_title,
                    f"From: {email.get('from_address', '?')}\nMailbox: {email.get('mailbox_address', '?')}\nLogged: {email.get('logged_at', '?')}\n\n{note}",
                ),
            )

        flagged += 1
        tickets += 1
        logger.info("[R.E.S.O.L.V.E.] flagged email %s (%s) from %s", eid, category, email.get("from_address"))

    # Telegram alert if new flags raised
    if flagged > 0:
        try:
            from services.telegram_service import send_info

            send_info(
                f"📧 R.E.S.O.L.V.E. Email Oversight\n"
                f"Scanned: {scanned} | Flagged: {flagged} | Tickets created: {tickets}\n"
                f"Review in Email Manager → HQ tab"
            )
        except Exception as exc:
            logger.warning("[R.E.S.O.L.V.E.] Telegram alert failed: %s", exc)

    return {"scanned": scanned, "flagged": flagged, "tickets_created": tickets, "already_processed": already}


def register_hq_routes(bp, admin_required):

    @bp.route("/api/hq/unified-inbox", methods=["GET"])
    @login_required
    def hq_unified_inbox():
        limit = min(int(request.args.get("limit", 50)), 200)
        mailbox_filter = request.args.get("mailbox_id", type=int)
        status_filter = request.args.get("status", "")

        with get_db_cursor() as (_, cur):
            where_clauses = []
            params = []
            if mailbox_filter:
                where_clauses.append("m.id = %s")
                params.append(mailbox_filter)
            if status_filter == "unread":
                where_clauses.append("al.read_at IS NULL")
            elif status_filter == "read":
                where_clauses.append("al.read_at IS NOT NULL")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            params.append(limit)
            cur.execute(
                """
                SELECT al.id, m.id AS mailbox_id, al.direction, al.from_address,
                       al.to_address, al.subject, al.logged_at AS received_at, al.read_at,
                       m.address AS mailbox_address, m.mailbox_type,
                       ea.assigned_agent, ea.status AS assignment_status
                FROM email_activity_log al
                JOIN email_mailboxes m ON m.address = al.mailbox_address
                LEFT JOIN email_assignments ea ON ea.email_id = al.id
                  AND ea.status = 'open'
                """
                + where_sql
                + """
                ORDER BY al.logged_at DESC NULLS LAST
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
        emails = [
            {
                "id": r["id"],
                "mailbox_id": r["mailbox_id"],
                "mailbox_address": r["mailbox_address"],
                "mailbox_type": r["mailbox_type"],
                "direction": r["direction"],
                "from_address": r["from_address"] or "",
                "to_address": r["to_address"] or "",
                "subject": r["subject"] or "(no subject)",
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                "is_read": r["read_at"] is not None,
                "assigned_agent": r["assigned_agent"],
                "assignment_status": r["assignment_status"],
            }
            for r in rows
        ]
        return jsonify({"emails": emails, "count": len(emails)})

    @bp.route("/api/hq/assign", methods=["POST"])
    @login_required
    def hq_assign():
        data = request.get_json(silent=True) or {}
        email_id = data.get("email_id")
        agent_name = str(data.get("agent_name", "")).strip()
        notes = str(data.get("notes", "")).strip()[:500]
        if not email_id or not agent_name:
            return jsonify({"error": "email_id and agent_name required"}), 400
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """
                INSERT INTO email_assignments
                    (email_id, assigned_agent, assigned_by, notes, status)
                VALUES (%s, %s, 'manual', %s, 'open')
                ON CONFLICT DO NOTHING
                """,
                (email_id, agent_name, notes or None),
            )
        logger.info("email_hq.assign: email=%s agent=%s", email_id, agent_name)
        return jsonify({"assigned": True, "email_id": email_id, "agent": agent_name})

    @bp.route("/api/hq/stats", methods=["GET"])
    @login_required
    def hq_stats():
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE logged_at > NOW() - INTERVAL '24h') AS last_24h,
                    COUNT(*) FILTER (WHERE read_at IS NULL
                        AND logged_at > NOW() - INTERVAL '24h') AS unread_24h,
                    COUNT(*) FILTER (WHERE logged_at > NOW() - INTERVAL '24h'
                        AND direction = 'received') AS inbound_24h,
                    COUNT(DISTINCT mailbox_address) AS active_mailboxes
                FROM email_activity_log
                """
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS flagged FROM email_assignments "
                "WHERE status = 'open' AND created_at < NOW() - INTERVAL '24h'"
            )
            flagged_row = cur.fetchone()
        return jsonify(
            {
                "last_24h": int(row["last_24h"] or 0),
                "unread_24h": int(row["unread_24h"] or 0),
                "inbound_24h": int(row["inbound_24h"] or 0),
                "active_mailboxes": int(row["active_mailboxes"] or 0),
                "flagged_unanswered": int(flagged_row["flagged"] or 0),
            }
        )

    @bp.route("/api/hq/rules", methods=["GET"])
    @login_required
    def hq_rules():
        with get_db_cursor() as (_, cur):
            cur.execute("SELECT id, mailbox_id, conditions, actions, enabled " "FROM email_rules ORDER BY id")
            rows = cur.fetchall()
        return jsonify({"rules": [dict(r) for r in rows]})

    # ── R.E.S.O.L.V.E. Oversight Endpoints ───────────────────────────────────

    @bp.route("/api/hq/oversight/unanswered", methods=["GET"])
    @login_required
    def hq_oversight_unanswered():
        """List inbound emails with no reply after threshold hours."""
        threshold = int(request.args.get("threshold_hours", 24))
        limit = min(int(request.args.get("limit", 50)), 200)
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT al.id, al.mailbox_address, al.from_address, al.subject,
                       al.logged_at, ea.assigned_agent, ea.notes
                FROM email_activity_log al
                LEFT JOIN email_assignments ea
                       ON ea.email_id = al.id AND ea.assigned_by = 'resolve_oversight'
                WHERE al.direction = 'received'
                  AND al.logged_at < NOW() - (%s || ' hours')::interval
                  AND al.logged_at > NOW() - INTERVAL '7 days'
                  AND al.read_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM email_activity_log r
                      WHERE r.direction = 'sent'
                        AND r.to_address = al.from_address
                        AND r.logged_at > al.logged_at
                  )
                ORDER BY al.logged_at ASC
                LIMIT %s
                """,
                (str(threshold), limit),
            )
            rows = cur.fetchall()
        emails = [
            {
                "id": r["id"],
                "mailbox": r["mailbox_address"],
                "from": r["from_address"],
                "subject": r["subject"],
                "logged_at": r["logged_at"].isoformat() if r["logged_at"] else None,
                "assigned": r["assigned_agent"] is not None,
                "category": (
                    r["notes"].split("Category: ")[1].split(" |")[0]
                    if r["notes"] and "Category:" in r["notes"]
                    else None
                ),
            }
            for r in rows
        ]
        return jsonify({"unanswered": emails, "count": len(emails), "threshold_hours": threshold})

    @bp.route("/api/hq/oversight/scan", methods=["POST"])
    @login_required
    def hq_oversight_scan():
        """Trigger a manual R.E.S.O.L.V.E. oversight scan."""
        data = request.get_json(silent=True) or {}
        threshold = int(data.get("threshold_hours", 24))
        result = run_resolve_oversight(threshold_hours=threshold)
        return jsonify({"success": True, "result": result})

    @bp.route("/api/hq/oversight/tickets", methods=["GET"])
    @login_required
    def hq_oversight_tickets():
        """List unified_tasks auto-created by R.E.S.O.L.V.E. oversight."""
        limit = min(int(request.args.get("limit", 50)), 200)
        with get_db_cursor() as (_, cur):
            cur.execute(
                """SELECT id, title, status, priority, description, created_at
                   FROM unified_tasks
                   WHERE delegation_source = 'resolve_oversight'
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
        tickets = [
            {
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "priority": r["priority"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
        return jsonify({"tickets": tickets, "count": len(tickets)})
