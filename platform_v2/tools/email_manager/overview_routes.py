"""Email HQ — Overview tab: stats cards + activity feed."""

import logging

from database import get_db_cursor
from flask import jsonify
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

logger = logging.getLogger(__name__)


def register_overview_routes(bp, admin_required):

    @bp.route("/api/email/overview/stats", methods=["GET"])
    @login_required
    @admin_required
    def email_overview_stats():
        """Stats: unread, sent today, provisioned, not provisioned.

        Scoped to the caller's visible mailboxes when called by a COLLABORATOR.
        Admins see platform-wide totals.
        """
        visible = get_visible_mailbox_ids(current_user)
        with get_db_cursor() as (conn, cur):
            if visible is not None:
                # Activity stats scoped to visible mailboxes
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE al.direction='received'
                        AND al.read_at IS NULL)                                             AS unread,
                      COUNT(*) FILTER (WHERE al.direction='sent'
                        AND al.logged_at >= NOW() - INTERVAL '24 hours')                   AS sent_today
                    FROM email_activity_log al
                    JOIN email_mailboxes m ON m.address = al.mailbox_address
                    WHERE m.id = ANY(%s)
                    """,
                    (visible,),
                )
                row_activity = cur.fetchone()
                # Mailbox provisioning counts scoped to visible mailboxes
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE provisioned = TRUE AND active = TRUE)  AS provisioned,
                      COUNT(*) FILTER (WHERE provisioned = FALSE AND active = TRUE) AS not_provisioned
                    FROM email_mailboxes
                    WHERE id = ANY(%s)
                    """,
                    (visible,),
                )
                row_mailboxes = cur.fetchone()
                return jsonify(
                    {
                        "unread": int(row_activity["unread"] or 0),
                        "sent_today": int(row_activity["sent_today"] or 0),
                        "provisioned": int(row_mailboxes["provisioned"] or 0),
                        "not_provisioned": int(row_mailboxes["not_provisioned"] or 0),
                    }
                )

            # Admin fast path — global counters
            cur.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM email_activity_log
                   WHERE direction='received' AND read_at IS NULL)        AS unread,
                  (SELECT COUNT(*) FROM email_activity_log
                   WHERE direction='sent'
                     AND logged_at >= NOW() - INTERVAL '24 hours')        AS sent_today,
                  (SELECT COUNT(*) FROM email_mailboxes
                   WHERE provisioned = TRUE AND active = TRUE)            AS provisioned,
                  (SELECT COUNT(*) FROM email_mailboxes
                   WHERE provisioned = FALSE AND active = TRUE)           AS not_provisioned
                """
            )
            row = cur.fetchone()
        return jsonify(
            {
                "unread": row["unread"],
                "sent_today": row["sent_today"],
                "provisioned": row["provisioned"],
                "not_provisioned": row["not_provisioned"],
            }
        )

    @bp.route("/api/email/overview/feed", methods=["GET"])
    @login_required
    @admin_required
    def email_overview_feed():
        """Last 50 email events across the caller's visible mailboxes."""
        visible = get_visible_mailbox_ids(current_user)
        with get_db_cursor() as (conn, cur):
            if visible is not None:
                cur.execute(
                    """
                    SELECT al.id, al.mailbox_address, al.direction,
                           al.from_address, al.to_address, al.subject,
                           al.logged_at,
                           m.display_name AS mailbox_display
                    FROM email_activity_log al
                    JOIN email_mailboxes m ON m.address = al.mailbox_address
                    WHERE m.id = ANY(%s)
                    ORDER BY al.logged_at DESC
                    LIMIT 50
                    """,
                    (visible,),
                )
            else:
                cur.execute(
                    """
                    SELECT al.id, al.mailbox_address, al.direction,
                           al.from_address, al.to_address, al.subject,
                           al.logged_at,
                           m.display_name AS mailbox_display
                    FROM email_activity_log al
                    LEFT JOIN email_mailboxes m ON m.address = al.mailbox_address
                    ORDER BY al.logged_at DESC
                    LIMIT 50
                    """
                )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("logged_at"):
                    r["logged_at"] = r["logged_at"].isoformat()
        return jsonify({"events": rows})
