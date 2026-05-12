"""Live Therapy briefing injected into V.I.T.A.L. chat context."""

from services.time_utils import now_local_str


def _build_therapy_briefing() -> str:
    from database import get_db_cursor
    from flask_login import current_user

    now_str = now_local_str()
    lines = [f"\n[V.I.T.A.L. WELLNESS BRIEFING — {now_str}]"]

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        with get_db_cursor(commit=False) as (conn, cur):
            for table in ("therapy_sessions", "wellness_sessions", "mood_entries"):
                try:
                    if user_id:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_id=%s", (user_id,))
                    else:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                    cnt = (cur.fetchone() or {}).get("cnt", 0)
                    lines.append(f"Sessions recorded: {cnt}")
                    break
                except Exception:
                    continue

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[V.I.T.A.L. THERAPY CONTEXT]\n"
        "V.I.T.A.L. provides a supportive wellness space — mood tracking, grounding exercises, "
        "breathing techniques, and compassionate conversation. Crisis resources (988/Crisis Text Line) "
        "are always available if needed."
    )
    return "\n".join(lines)
