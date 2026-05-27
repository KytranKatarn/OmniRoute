"""Email HQ — SLA dashboard: response-time metrics per mailbox (T3282)."""

from __future__ import annotations

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

logger = logging.getLogger(__name__)

_SLA_BREACH_HOURS = 24
_SLA_CRITICAL_HOURS = 48


def register_sla_routes(bp, access_required) -> None:
    @bp.route("/api/email/sla/stats", methods=["GET"])
    @login_required
    @access_required
    def email_sla_stats():
        """SLA metrics: per-mailbox response-time + breach counts.

        Query params:
          window: 7 | 30  (look-back days, default 30)

        Returns:
          summary: platform-wide totals for the window
          mailboxes: per-mailbox breakdown sorted by breach_24h desc
        """
        try:
            window = int(request.args.get("window", 30))
        except (ValueError, TypeError):
            window = 30
        if window not in (7, 30):
            window = 30

        visible = get_visible_mailbox_ids(current_user)

        with get_db_cursor() as (conn, cur):
            # --- per-mailbox breakdown ---
            if visible is not None:
                cur.execute(
                    """
                    SELECT
                      m.id                                                          AS mailbox_id,
                      m.address,
                      m.display_name,
                      COUNT(*) FILTER (WHERE al.direction = 'received')            AS received,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL)                                    AS unread,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL
                        AND al.logged_at < NOW() - INTERVAL '1 hour' * 24)        AS breach_24h,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL
                        AND al.logged_at < NOW() - INTERVAL '1 hour' * 48)        AS breach_48h,
                      ROUND(
                        (AVG(
                          EXTRACT(EPOCH FROM (al.read_at - al.logged_at)) / 3600.0
                        ) FILTER (WHERE al.direction = 'received'
                          AND al.read_at IS NOT NULL))::numeric, 1
                      )                                                            AS avg_read_hours
                    FROM email_mailboxes m
                    LEFT JOIN email_activity_log al
                      ON al.mailbox_address = m.address
                     AND al.logged_at >= NOW() - INTERVAL '1 day' * %s
                    WHERE m.active = TRUE AND m.id = ANY(%s)
                    GROUP BY m.id, m.address, m.display_name
                    ORDER BY breach_24h DESC NULLS LAST, unread DESC NULLS LAST
                    """,
                    (window, visible),
                )
            else:
                cur.execute(
                    """
                    SELECT
                      m.id                                                          AS mailbox_id,
                      m.address,
                      m.display_name,
                      COUNT(*) FILTER (WHERE al.direction = 'received')            AS received,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL)                                    AS unread,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL
                        AND al.logged_at < NOW() - INTERVAL '1 hour' * 24)        AS breach_24h,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL
                        AND al.logged_at < NOW() - INTERVAL '1 hour' * 48)        AS breach_48h,
                      ROUND(
                        (AVG(
                          EXTRACT(EPOCH FROM (al.read_at - al.logged_at)) / 3600.0
                        ) FILTER (WHERE al.direction = 'received'
                          AND al.read_at IS NOT NULL))::numeric, 1
                      )                                                            AS avg_read_hours
                    FROM email_mailboxes m
                    LEFT JOIN email_activity_log al
                      ON al.mailbox_address = m.address
                     AND al.logged_at >= NOW() - INTERVAL '1 day' * %s
                    WHERE m.active = TRUE
                    GROUP BY m.id, m.address, m.display_name
                    ORDER BY breach_24h DESC NULLS LAST, unread DESC NULLS LAST
                    """,
                    (window,),
                )
            rows = cur.fetchall()

            # --- overall summary ---
            if visible is not None:
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE al.direction = 'received')            AS total_received,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL)                                    AS total_unread,
                      COUNT(*) FILTER (WHERE al.direction = 'received'
                        AND al.read_at IS NULL
                        AND al.logged_at < NOW() - INTERVAL '1 hour' * 24)        AS total_breach_24h,
                      ROUND(
                        (AVG(
                          EXTRACT(EPOCH FROM (al.read_at - al.logged_at)) / 3600.0
                        ) FILTER (WHERE al.direction = 'received'
                          AND al.read_at IS NOT NULL))::numeric, 1
                      )                                                            AS avg_read_hours
                    FROM email_activity_log al
                    JOIN email_mailboxes m ON m.address = al.mailbox_address
                    WHERE al.logged_at >= NOW() - INTERVAL '1 day' * %s
                      AND m.id = ANY(%s)
                    """,
                    (window, visible),
                )
            else:
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE direction = 'received')               AS total_received,
                      COUNT(*) FILTER (WHERE direction = 'received'
                        AND read_at IS NULL)                                       AS total_unread,
                      COUNT(*) FILTER (WHERE direction = 'received'
                        AND read_at IS NULL
                        AND logged_at < NOW() - INTERVAL '1 hour' * 24)           AS total_breach_24h,
                      ROUND(
                        (AVG(
                          EXTRACT(EPOCH FROM (read_at - logged_at)) / 3600.0
                        ) FILTER (WHERE direction = 'received'
                          AND read_at IS NOT NULL))::numeric, 1
                      )                                                            AS avg_read_hours
                    FROM email_activity_log
                    WHERE logged_at >= NOW() - INTERVAL '1 day' * %s
                    """,
                    (window,),
                )
            sumrow = cur.fetchone()

        mailboxes = [
            {
                "mailbox_id": r["mailbox_id"],
                "address": r["address"],
                "display_name": r["display_name"] or r["address"],
                "received": int(r["received"] or 0),
                "unread": int(r["unread"] or 0),
                "breach_24h": int(r["breach_24h"] or 0),
                "breach_48h": int(r["breach_48h"] or 0),
                "avg_read_hours": (float(r["avg_read_hours"]) if r["avg_read_hours"] is not None else None),
            }
            for r in rows
        ]

        summary = {
            "total_received": int(sumrow["total_received"] or 0),
            "total_unread": int(sumrow["total_unread"] or 0),
            "total_breach_24h": int(sumrow["total_breach_24h"] or 0),
            "avg_read_hours": (float(sumrow["avg_read_hours"]) if sumrow["avg_read_hours"] is not None else None),
            "window_days": window,
            "sla_threshold_hours": _SLA_BREACH_HOURS,
        }

        return jsonify({"summary": summary, "mailboxes": mailboxes})
