"""Live Email HQ briefing injected into R.E.S.O.L.V.E. chat context."""

from services.time_utils import now_local_str


def _build_email_hq_briefing() -> str:
    """
    Return a plain-text briefing of Email HQ's current state.
    Prepended to every R.E.S.O.L.V.E. message on the email_manager module
    so she can answer email status questions and suggest workflow actions.
    """
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[R.E.S.O.L.V.E. EMAIL HQ BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Overall inbox stats
            cur.execute(
                """SELECT
                     COUNT(*) AS total,
                     COUNT(*) FILTER (WHERE is_read = FALSE AND is_archived = FALSE) AS unread,
                     COUNT(*) FILTER (WHERE ai_priority = 'action' AND is_archived = FALSE) AS action_items,
                     COUNT(*) FILTER (WHERE ai_priority = 'review' AND is_archived = FALSE) AS review_items,
                     COUNT(*) FILTER (WHERE ai_triaged_at IS NOT NULL) AS triaged
                   FROM email_messages"""
            )
            stats = cur.fetchone() or {}
            lines.append(
                f"Messages: {stats.get('total', 0)} total | "
                f"{stats.get('unread', 0)} unread | "
                f"{stats.get('action_items', 0)} action | "
                f"{stats.get('review_items', 0)} review | "
                f"{stats.get('triaged', 0)} triaged"
            )

            # Mailbox health
            cur.execute(
                """SELECT mailbox_type,
                          COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE provisioned = TRUE) AS provisioned
                   FROM email_mailboxes
                   WHERE active = TRUE
                   GROUP BY mailbox_type
                   ORDER BY mailbox_type"""
            )
            for row in cur.fetchall():
                lines.append(
                    f"Mailboxes ({row['mailbox_type'].replace('_', ' ')}): "
                    f"{row['provisioned']}/{row['total']} provisioned"
                )

            # Most recent messages (last 5 across all mailboxes)
            cur.execute(
                """SELECT m.subject, m.from_address, mb.address AS mailbox,
                          m.ai_priority, m.received_at
                   FROM email_messages m
                   JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                   WHERE m.is_archived = FALSE
                   ORDER BY m.received_at DESC
                   LIMIT 5"""
            )
            recent = cur.fetchall()
            if recent:
                lines.append("Recent messages:")
                for r in recent:
                    priority = f" [{r['ai_priority']}]" if r.get("ai_priority") else ""
                    lines.append(f"  • {r['mailbox']} ← {r['from_address']}: {r['subject']}{priority}")

            # Active email rules
            cur.execute("SELECT COUNT(*) AS cnt FROM email_rules WHERE is_active = TRUE")
            rule_count = (cur.fetchone() or {}).get("cnt", 0)
            if rule_count:
                lines.append(f"Active rules: {rule_count}")

    except Exception as exc:
        lines.append(f"(briefing data unavailable: {exc})")

    lines.append(
        "\nYou are R.E.S.O.L.V.E., Customer Success & Support director. "
        "Help manage email workflow: triage decisions, draft replies, provisioning, rules setup."
    )
    return "\n".join(lines) + "\n\n"
