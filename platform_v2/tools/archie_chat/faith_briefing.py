"""Live Faith briefing injected into F.A.I.T.H. chat context."""

from services.time_utils import now_local_str


def _build_faith_briefing() -> str:
    from database import get_db_cursor
    from flask_login import current_user

    now_str = now_local_str()
    lines = [f"\n[F.A.I.T.H. BRIEFING — {now_str}]"]

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        with get_db_cursor(commit=False) as (conn, cur):
            for table, label in [
                ("faith_sessions", "Sessions"),
                ("faith_journal", "Journal entries"),
                ("faith_checkins", "Check-ins"),
            ]:
                try:
                    if user_id:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_id=%s", (user_id,))
                    else:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                    cnt = (cur.fetchone() or {}).get("cnt", 0)
                    if cnt > 0:
                        lines.append(f"{label}: {cnt}")
                except Exception:
                    continue

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[F.A.I.T.H. CONTEXT]\n"
        "F.A.I.T.H. supports devotional practice, scripture reflection, spiritual journaling, "
        "and faith-based guidance. Ask about devotionals, reflections, or share what's on your heart."
    )
    return "\n".join(lines)
