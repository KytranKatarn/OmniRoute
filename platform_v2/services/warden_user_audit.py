"""W.A.R.D.E.N. daily user-account audit — computed from the database.

The audit used to hand a 7B model a prompt with NO data ("check for inactive
users, locked accounts, stale invites") and log whatever came back as a
successful audit. It cannot know any of it: the 2026-09-28 "success" was a
template full of ``[Insert Number]``, and the 2026-09-26/27 reports claimed 42
inactive users on a platform that has 35 user rows in total. Worse, it told the
model to read an ``auth_events`` table that does not exist.

This module answers the three questions with SQL and renders the result as
text. Read-only, no LLM, no dispatch queue — so it cannot time out, cannot
invent a number, and a real failure raises instead of logging an empty success.

Definitions match the code that enforces them:

* **inactive** — an ACTIVE user whose last login (or, if they never logged in,
  account creation) is older than ``INACTIVE_DAYS``.
* **locked** — mirrors ``auth_service.is_account_locked``: ``failed_login_count``
  has reached ``MAX_FAILED_ATTEMPTS`` AND the newest ``failed_logins`` row for
  that username is inside the ``LOCKOUT_MINUTES`` window.
* **stale invites** — ``user_invites`` still ``pending`` after
  ``STALE_INVITE_DAYS``, and pending invites already past ``expires_at`` (which
  nothing has flipped to ``expired`` yet).
"""

from __future__ import annotations

from typing import Any, Dict, List

from services.auth_service import LOCKOUT_MINUTES, MAX_FAILED_ATTEMPTS

INACTIVE_DAYS = 30
STALE_INVITE_DAYS = 7
NAME_LIST_LIMIT = 10  # usernames named in the report; the count is always exact


def _names(rows: List[Dict[str, Any]]) -> List[str]:
    return [str(r["username"]) for r in rows[:NAME_LIST_LIMIT]]


def collect_user_audit(cur) -> Dict[str, Any]:
    """Return the audit facts. ``cur`` must be a RealDictCursor. Raises on DB error."""
    cur.execute(
        """
        SELECT username
        FROM users
        WHERE is_active
          AND COALESCE(last_login, created_at) < NOW() - make_interval(days => %s)
        ORDER BY COALESCE(last_login, created_at), username
        """,
        (INACTIVE_DAYS,),
    )
    inactive = cur.fetchall()

    cur.execute(
        """
        SELECT u.username
        FROM users u
        WHERE u.failed_login_count >= %s
          AND EXISTS (
              SELECT 1 FROM failed_logins f
              WHERE f.username = u.username
                AND f.attempted_at > NOW() - make_interval(mins => %s)
          )
        ORDER BY u.username
        """,
        (MAX_FAILED_ATTEMPTS, LOCKOUT_MINUTES),
    )
    locked = cur.fetchall()

    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE status = 'pending'
                  AND created_at < NOW() - make_interval(days => %s)
            ) AS stale_pending,
            COUNT(*) FILTER (
                WHERE status = 'pending' AND expires_at < NOW()
            ) AS past_expiry
        FROM user_invites
        """,
        (STALE_INVITE_DAYS,),
    )
    invites = cur.fetchone()

    cur.execute("SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_active) AS active FROM users")
    users = cur.fetchone()

    return {
        "users_total": int(users["total"]),
        "users_active": int(users["active"]),
        "inactive_count": len(inactive),
        "inactive_names": _names(inactive),
        "locked_count": len(locked),
        "locked_names": _names(locked),
        "stale_pending_invites": int(invites["stale_pending"] or 0),
        "pending_invites_past_expiry": int(invites["past_expiry"] or 0),
    }


def needs_attention(facts: Dict[str, Any]) -> bool:
    """True when anything in the audit warrants a human look."""
    return bool(
        facts["inactive_count"]
        or facts["locked_count"]
        or facts["stale_pending_invites"]
        or facts["pending_invites_past_expiry"]
    )


def _listed(count: int, names: List[str]) -> str:
    if not count:
        return "none"
    shown = ", ".join(names)
    more = f" (+{count - len(names)} more)" if count > len(names) else ""
    return f"{count}: {shown}{more}"


def format_report(facts: Dict[str, Any]) -> str:
    """Plain-text report. Every figure comes straight from ``facts``."""
    lines = [
        "Daily user account audit",
        f"Users: {facts['users_active']} active of {facts['users_total']} total.",
        f"Inactive >{INACTIVE_DAYS} days (active accounts): "
        f"{_listed(facts['inactive_count'], facts['inactive_names'])}",
        f"Locked now ({MAX_FAILED_ATTEMPTS}+ failed logins, last within {LOCKOUT_MINUTES} min): "
        f"{_listed(facts['locked_count'], facts['locked_names'])}",
        f"Invites pending >{STALE_INVITE_DAYS} days: {facts['stale_pending_invites']}",
        f"Invites pending but past expiry: {facts['pending_invites_past_expiry']}",
        "Attention needed." if needs_attention(facts) else "Nothing needs attention.",
    ]
    return "\n".join(lines)
