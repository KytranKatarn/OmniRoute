"""Email HQ morning digest builder — T3288."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from database import get_db_cursor

logger = logging.getLogger(__name__)

_GROUP_ORDER = ["ai_agent", "business", "human_agent", "owner"]
_GROUP_LABELS = {
    "ai_agent": "🤖 AI Agents",
    "business": "🏢 Business",
    "human_agent": "👥 Human Agents",
    "owner": "👤 Owner",
}


def build_morning_digest() -> tuple[str, str]:
    """Return (title, message) for the daily Telegram email digest.

    Groups unread counts by mailbox_type (ai_agent / business / human_agent / owner).
    Surfaces top 3 action-priority unread emails per group.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT m.mailbox_type, COUNT(*) AS unread
            FROM email_messages em
            JOIN email_mailboxes m ON m.id = em.mailbox_id
            WHERE em.is_read = FALSE AND m.active = TRUE
            GROUP BY m.mailbox_type
            """
        )
        unread_by_type = {r["mailbox_type"]: int(r["unread"]) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT m.mailbox_type, em.subject, em.from_address, m.display_name
            FROM email_messages em
            JOIN email_mailboxes m ON m.id = em.mailbox_id
            WHERE em.is_read = FALSE AND em.ai_priority = 'action' AND m.active = TRUE
            ORDER BY m.mailbox_type, em.received_at ASC
            """
        )
        action_rows = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM email_messages em
            JOIN email_mailboxes m ON m.id = em.mailbox_id
            WHERE em.is_read = FALSE AND em.ai_priority = 'action' AND m.active = TRUE
            """
        )
        total_action = int((cur.fetchone() or {}).get("cnt", 0))

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %-d")

    lines: list[str] = [f"📅 {date_str}\n"]

    for group_key in _GROUP_ORDER:
        label = _GROUP_LABELS.get(group_key, group_key)
        unread = unread_by_type.get(group_key, 0)
        if unread == 0:
            continue
        lines.append(f"{label}: {unread} unread")
        group_actions = [r for r in action_rows if r["mailbox_type"] == group_key][:3]
        for r in group_actions:
            subj = (r["subject"] or "(no subject)")[:55]
            sender = (r["from_address"] or "unknown").split("@")[0]
            lines.append(f"  ⚡ {subj} — {sender}")
        lines.append("")

    if total_action:
        lines.append(f"🚨 Action items requiring attention: {total_action}")
    else:
        lines.append("✅ No action items flagged")

    # Slice 5: surface replies the agents drafted that are awaiting approval.
    try:
        from . import mailhq_settings

        if mailhq_settings.digest_include_drafts():
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT count(*) AS n FROM autonomy_approval_queue
                       WHERE action_type = 'email_reply' AND status = 'pending'"""
                )
                n_drafts = int((cur.fetchone() or {}).get("n", 0))
                cur.execute(
                    """SELECT action_data->>'to_address' AS to_addr,
                              action_data->>'subject'    AS subj
                       FROM autonomy_approval_queue
                       WHERE action_type = 'email_reply' AND status = 'pending'
                       ORDER BY created_at DESC LIMIT 3"""
                )
                draft_rows = cur.fetchall()
            if n_drafts:
                lines.append("")
                lines.append(f"📝 {n_drafts} repl{'y' if n_drafts == 1 else 'ies'} drafted, awaiting approval:")
                for r in draft_rows:
                    to_addr = (r["to_addr"] or "?").split("@")[0]
                    subj = (r["subj"] or "(no subject)")[:45]
                    lines.append(f"  ✉️ {subj} → {to_addr}")
    except Exception as _de:
        logger.debug("[email_digest] drafts section skipped: %s", _de)

    # Slice 5 / #4525: SLA breaches — action mail unread > 24h. List the oldest items
    # with their age so the digest is actionable, not just a bare count.
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT em.subject, em.from_address,
                          EXTRACT(EPOCH FROM (NOW() - em.received_at)) / 3600.0 AS age_h
                   FROM email_messages em
                   JOIN email_mailboxes m ON m.id = em.mailbox_id
                   WHERE em.is_read = FALSE AND em.ai_priority = 'action'
                     AND m.active = TRUE
                     AND em.received_at < NOW() - INTERVAL '24 hours'
                   ORDER BY em.received_at ASC"""
            )
            overdue_rows = cur.fetchall()
        if overdue_rows:
            lines.append("")
            lines.append(f"⏰ {len(overdue_rows)} action item(s) overdue (SLA >24h):")
            for r in overdue_rows[:3]:
                subj = (r["subject"] or "(no subject)")[:45]
                sender = (r["from_address"] or "unknown").split("@")[0]
                age = int(r["age_h"] or 0)
                lines.append(f"  ⌛ {subj} — {sender} ({age}h)")
            if len(overdue_rows) > 3:
                lines.append(f"  …and {len(overdue_rows) - 3} more")
    except Exception as _oe:
        logger.debug("[email_digest] overdue section skipped: %s", _oe)

    total_unread = sum(unread_by_type.values())
    title = f"Email HQ — {total_unread} unread"

    return title, "\n".join(lines)
