"""Email HQ — per-human-agent reply SLA (#3282).

`record_human_reply()` persists one `email_reply_events` row when a human agent replies
FROM a `human_agent` mailbox; `per_agent_stats()` aggregates it for the dashboard. The
small pure helpers (compute_response_seconds / within_sla_pct / fmt_duration) are unit-tested.

Forward-only: rows accrue from deploy — there is no historical reply-time data to backfill.
"""

from __future__ import annotations

import logging

from database import get_db_cursor
from services.time_utils import now_utc

logger = logging.getLogger(__name__)

_DEFAULT_SLA_HOURS = 4.0
_SLA_SETTING_KEY = "mailhq:human_sla:target_hours"


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O) — unit-tested.
# --------------------------------------------------------------------------- #
def compute_response_seconds(received_at, sent_at):
    """Whole seconds between an inbound received_at and the reply sent_at.

    None if either timestamp is missing/unusable, or if the result is negative
    (clock skew / a reply that predates its 'source').
    """
    if received_at is None or sent_at is None:
        return None
    try:
        delta = (sent_at - received_at).total_seconds()
    except (TypeError, AttributeError):
        return None
    if delta < 0:
        return None
    return int(delta)


def within_sla_pct(response_seconds, target_seconds):
    """Percent (0-100, 1dp) of response times within the SLA target. None if no timed replies."""
    vals = [s for s in (response_seconds or []) if s is not None]
    if not vals:
        return None
    within = sum(1 for s in vals if s <= target_seconds)
    return round(100.0 * within / len(vals), 1)


def fmt_duration(seconds):
    """Human duration: None->'—', 45->'45s', 125->'2m', 9000->'2h 30m'."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


# --------------------------------------------------------------------------- #
# Capture — called from the compose/send path after a successful human reply.
# --------------------------------------------------------------------------- #
def record_human_reply(from_address, source_message_id, sender_user_id=None):
    """Persist one email_reply_events row for a human-agent reply. Best-effort (never raises).

    Only records when `from_address` is a `human_agent` mailbox. Resolves the source inbound
    message → received_at + thread_id, computes response_time_seconds, and stores the sending
    user + the mailbox's owner_agent_id. Returns the new row id, or None if not recorded.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT id, owner_agent_id FROM email_mailboxes " "WHERE address = %s AND mailbox_type = 'human_agent'",
                (from_address,),
            )
            mb = cur.fetchone()
            if not mb:
                return None  # only human_agent mailboxes are tracked here

            received_at = None
            thread_id = None
            if source_message_id:
                cur.execute(
                    "SELECT received_at, thread_id FROM email_messages WHERE id = %s",
                    (source_message_id,),
                )
                src = cur.fetchone()
                if src:
                    received_at = src["received_at"]
                    thread_id = src["thread_id"]

            sent_at = now_utc()
            response_seconds = compute_response_seconds(received_at, sent_at)
            cur.execute(
                """
                INSERT INTO email_reply_events
                    (source_message_id, thread_id, mailbox_id, owner_agent_id,
                     sender_user_id, received_at, sent_at, response_time_seconds)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    source_message_id or None,
                    thread_id,
                    mb["id"],
                    mb["owner_agent_id"],
                    sender_user_id,
                    received_at,
                    sent_at,
                    response_seconds,
                ),
            )
            return cur.fetchone()["id"]
    except Exception as exc:  # never let SLA logging break a successful send
        logger.warning("[human-sla] record_human_reply failed (%s): %s", from_address, exc)
        return None


# --------------------------------------------------------------------------- #
# Metrics — powers GET /api/email/human-sla/stats.
# --------------------------------------------------------------------------- #
def get_sla_target_hours():
    """Configured reply-SLA target in hours (platform_settings), default 4."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (_SLA_SETTING_KEY,))
            row = cur.fetchone()
            if row and row.get("value"):
                return float(row["value"])
    except Exception as exc:
        logger.warning("[human-sla] sla target lookup failed: %s", exc)
    return _DEFAULT_SLA_HOURS


def per_agent_stats(days=7, visible_mailbox_ids=None):
    """Per-human-agent reply SLA for the look-back window.

    Returns {"sla_target_hours": float, "days": int, "agents": [ {...}, ... ]}, one row per
    active human_agent mailbox (agents with no activity still appear, with zero counts).
    `visible_mailbox_ids` scopes to a COLLABORATOR's accessible mailboxes (None = all).
    """
    target_hours = get_sla_target_hours()
    target_seconds = int(target_hours * 3600)
    scoped = visible_mailbox_ids is not None
    mb_clause = "AND m.id = ANY(%s)" if scoped else ""

    with get_db_cursor() as (conn, cur):
        # 1) reply metrics per human_agent mailbox
        reply_params = [target_seconds, days] + ([visible_mailbox_ids] if scoped else [])
        cur.execute(
            f"""
            SELECT m.id AS mailbox_id, m.address, m.owner_agent_id,
                   COALESCE(a.display_name, a.name, m.address) AS agent_name,
                   COUNT(e.id)                                              AS reply_count,
                   ROUND(AVG(e.response_time_seconds))::int                 AS avg_response_seconds,
                   COUNT(e.id) FILTER (WHERE e.response_time_seconds IS NOT NULL
                                         AND e.response_time_seconds <= %s) AS within_sla,
                   COUNT(e.id) FILTER (WHERE e.response_time_seconds IS NOT NULL) AS timed_count
            FROM email_mailboxes m
            LEFT JOIN agents a ON a.id = m.owner_agent_id
            LEFT JOIN email_reply_events e
              ON e.mailbox_id = m.id
             AND e.sent_at >= NOW() - INTERVAL '1 day' * %s
            WHERE m.mailbox_type = 'human_agent' AND m.active = TRUE {mb_clause}
            GROUP BY m.id, m.address, m.owner_agent_id, a.display_name, a.name
            """,
            reply_params,
        )
        reply_rows = {r["mailbox_id"]: dict(r) for r in cur.fetchall()}

        # 2) inbound + open (unreplied) per human_agent mailbox in the window
        inbound_params = [days] + ([visible_mailbox_ids] if scoped else [])
        cur.execute(
            f"""
            SELECT im.mailbox_id,
                   COUNT(*)                             AS inbound_count,
                   COUNT(*) FILTER (WHERE e.id IS NULL) AS open_threads
            FROM email_messages im
            JOIN email_mailboxes m ON m.id = im.mailbox_id
            LEFT JOIN email_reply_events e ON e.source_message_id = im.id
            WHERE m.mailbox_type = 'human_agent' AND m.active = TRUE {mb_clause}
              AND im.received_at >= NOW() - INTERVAL '1 day' * %s
            GROUP BY im.mailbox_id
            """,
            inbound_params,
        )
        inbound_rows = {r["mailbox_id"]: dict(r) for r in cur.fetchall()}

    agents = []
    for mailbox_id, r in reply_rows.items():
        inb = inbound_rows.get(mailbox_id, {})
        inbound_count = int(inb.get("inbound_count") or 0)
        open_threads = int(inb.get("open_threads") or 0)
        timed = int(r.get("timed_count") or 0)
        within = int(r.get("within_sla") or 0)
        avg_sec = r.get("avg_response_seconds")
        avg_sec = int(avg_sec) if avg_sec is not None else None
        reply_rate = round(100.0 * (inbound_count - open_threads) / inbound_count, 1) if inbound_count else None
        agents.append(
            {
                "agent_id": r.get("owner_agent_id"),
                "mailbox_id": mailbox_id,
                "agent_name": r.get("agent_name") or r.get("address"),
                "address": r.get("address"),
                "reply_count": int(r.get("reply_count") or 0),
                "avg_response_seconds": avg_sec,
                "avg_response_display": fmt_duration(avg_sec),
                "within_sla_pct": (round(100.0 * within / timed, 1) if timed else None),
                "open_threads": open_threads,
                "inbound_count": inbound_count,
                "reply_rate_pct": reply_rate,
            }
        )

    agents.sort(key=lambda a: (-a["open_threads"], -a["reply_count"], a["address"] or ""))
    return {"sla_target_hours": target_hours, "days": days, "agents": agents}
