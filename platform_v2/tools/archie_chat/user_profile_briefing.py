"""Live My Profile briefing injected into R.E.S.O.L.V.E. chat context."""

from services.time_utils import now_local_str


def _build_user_profile_briefing() -> str:
    """Return plain-text briefing of user profile state for R.E.S.O.L.V.E."""
    from database import get_db_cursor
    from flask_login import current_user

    now_str = now_local_str()
    lines = [f"\n[R.E.S.O.L.V.E. MY PROFILE BRIEFING — {now_str}]"]

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None

        with get_db_cursor(commit=False) as (conn, cur):
            if user_id:
                cur.execute(
                    "SELECT username, email, role, subscription_tier, "
                    "created_at, last_login_at FROM users WHERE id=%s",
                    (user_id,),
                )
                row = cur.fetchone()
                if row:
                    lines.append(f"User: {row['username']} ({row['email']})")
                    lines.append(f"Role: {row['role']} | Tier: {row['subscription_tier']}")
                    if row.get("last_login_at"):
                        lines.append(f"Last login: {row['last_login_at']}")

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM active_sessions WHERE user_id=%s",
                (user_id,),
            )
            sessions = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Active sessions: {sessions}")

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[R.E.S.O.L.V.E. PROFILE CONTEXT]\n"
        "R.E.S.O.L.V.E. helps with account settings, preferences, "
        "subscription details, and self-service account management."
    )
    return "\n".join(lines)
