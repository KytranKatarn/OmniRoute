"""SIGNAL Calendar live week-view service (Phase 1).

Single source of truth for the GET /api/signal/calendar/live endpoint.
JOINs autonomy_approval_queue + linkedin_post_log over a 7-day window
(Monday->Sunday containing the requested date), groups by date, applies
the status classifier, returns a 7-day array.

linkedin_post_log.approval_id FK confirmed present (2026-05-04).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database import get_db_cursor
from services.signal_post_status import classify

# Map UI account values to autonomy_approval_queue.action_data->>'post_type'
_ACCOUNT_TO_POST_TYPES = {
    "company": ("company", "company_page"),
    "personal": ("personal",),
    "creed": ("creed", "creed_ai"),
}


def compute_week(d: date) -> Tuple[date, date]:
    """Return (Monday, Sunday) of the week containing ``d``."""
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def detect_lang(action_data: Optional[Dict[str, Any]], reason: str) -> str:
    """Return 'en' or 'fr' for a post. Defaults to 'en'."""
    if action_data:
        lang = (action_data.get("language") or "").lower()
        if lang in ("fr", "fr-ca", "français", "francais"):
            return "fr"
        if lang == "en":
            return "en"
    if reason:
        # Quebec marker used in S.I.G.N.A.L. drafts
        if "⚜️" in reason or "Français" in reason or "français" in reason:
            return "fr"
    return "en"


def _row_to_post(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a DB row dict to the calendar response shape."""
    action_data = row.get("action_data") or {}
    if isinstance(action_data, str):
        try:
            action_data = json.loads(action_data)
        except Exception:
            action_data = {}

    reason = row.get("reason") or ""
    lang = detect_lang(action_data, reason)

    # Build the synthetic post_log object the classifier expects
    post_log = None
    if row.get("post_log_status"):
        post_log = {"status": row["post_log_status"]}

    status = classify(approval_row=row, post_log=post_log)

    # Preview = first 200 chars of content
    content = (action_data.get("content") or "").strip()
    preview = content[:200] + ("..." if len(content) > 200 else "")

    # Pull error message — handle both nested {result: {error}} and flat {error}
    error = None
    er = row.get("execution_result")
    if isinstance(er, str):
        try:
            er = json.loads(er)
        except Exception:
            er = None
    if isinstance(er, dict):
        if isinstance(er.get("result"), dict):
            error = er["result"].get("error")
        if error is None:
            error = er.get("error")

    return {
        "approval_id": row["id"],
        "lang": lang,
        "status": status,
        "post_type": row.get("post_type"),
        "drafted_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "approved_at": row["approved_at"].isoformat() if row.get("approved_at") else None,
        "executed_at": row["executed_at"].isoformat() if row.get("executed_at") else None,
        "linkedin_url": row.get("post_url"),
        "preview": preview,
        "telegram_message_id": row.get("telegram_message_id"),
        "error": error,
    }


def get_week_view(
    account: str,
    week_start: Optional[date] = None,
) -> Dict[str, Any]:
    """Return the calendar live week view for ``account``.

    Returns dict with shape::

        {
            "account": str,
            "week_start": "YYYY-MM-DD",
            "today": "YYYY-MM-DD",
            "days": [{date, is_today, posts: [...]} x 7]
        }
    """
    today = date.today()
    if week_start is None:
        week_start, _ = compute_week(today)
    week_end = week_start + timedelta(days=6)

    post_types = _ACCOUNT_TO_POST_TYPES.get(account, (account,))

    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT
                aaq.id,
                aaq.status,
                aaq.action_data,
                aaq.execution_result,
                aaq.reason,
                aaq.created_at,
                aaq.approved_at,
                aaq.executed_at,
                aaq.telegram_message_id,
                COALESCE(aaq.action_data->>'post_type',
                         aaq.action_data->'args'->>'post_type') AS post_type,
                lpl.status                                       AS post_log_status,
                lpl.post_url
            FROM autonomy_approval_queue aaq
            LEFT JOIN linkedin_post_log lpl
                   ON lpl.approval_id = aaq.id
            WHERE aaq.action_type = 'linkedin_post'
              AND COALESCE(aaq.action_data->>'post_type',
                           aaq.action_data->'args'->>'post_type') = ANY(%s)
              AND aaq.created_at >= %s
              AND aaq.created_at <  %s
            ORDER BY aaq.created_at
            """,
            (
                list(post_types),
                datetime.combine(week_start, time.min),
                datetime.combine(week_end + timedelta(days=1), time.min),
            ),
        )
        rows = [dict(r) for r in cur.fetchall()]

    # Group rows by date
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        d_str = r["created_at"].date().isoformat()
        by_date.setdefault(d_str, []).append(_row_to_post(r))

    # Build 7-day array
    days = []
    for offset in range(7):
        d = week_start + timedelta(days=offset)
        d_str = d.isoformat()
        days.append(
            {
                "date": d_str,
                "is_today": d == today,
                "posts": by_date.get(d_str, []),
            }
        )

    return {
        "account": account,
        "week_start": week_start.isoformat(),
        "today": today.isoformat(),
        "days": days,
    }
