"""Live DOC briefing injected into V.I.T.A.L. chat context."""

from services.time_utils import now_local_str


def _build_doc_briefing() -> str:
    from database import get_db_cursor
    from flask_login import current_user

    now_str = now_local_str()
    lines = [f"\n[V.I.T.A.L. HEALTH BRIEFING — {now_str}]"]

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        with get_db_cursor(commit=False) as (conn, cur):
            for table, label in [
                ("symptom_logs", "Symptom logs"),
                ("health_logs", "Health logs"),
                ("medications", "Medications tracked"),
                ("appointments", "Appointments"),
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
        "\n[V.I.T.A.L. DOC CONTEXT]\n"
        "V.I.T.A.L. assists with symptom logging, non-diagnostic health analysis, medication tracking, "
        "and appointment preparation. Always includes appropriate medical disclaimers."
    )
    return "\n".join(lines)
