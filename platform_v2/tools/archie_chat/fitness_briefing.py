"""Live Fitness briefing injected into V.I.T.A.L. chat context."""

from services.time_utils import now_local_str


def _build_fitness_briefing() -> str:
    from database import get_db_cursor
    from flask_login import current_user

    now_str = now_local_str()
    lines = [f"\n[V.I.T.A.L. FITNESS BRIEFING — {now_str}]"]

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        with get_db_cursor(commit=False) as (conn, cur):
            # Try common fitness table names — resilient across schema variations
            for table in ("fitness_logs", "workout_logs", "fitness_sessions"):
                try:
                    col = "user_id" if user_id else "id"
                    if user_id:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_id=%s", (user_id,))
                    else:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                    cnt = (cur.fetchone() or {}).get("cnt", 0)
                    lines.append(f"Workout sessions logged: {cnt}")
                    break
                except Exception:
                    continue

            for table in ("fitness_goals", "user_goals"):
                try:
                    if user_id:
                        cur.execute(
                            f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_id=%s AND status='active'",
                            (user_id,),
                        )
                    else:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE status='active'")
                    cnt = (cur.fetchone() or {}).get("cnt", 0)
                    lines.append(f"Active goals: {cnt}")
                    break
                except Exception:
                    continue

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[V.I.T.A.L. FITNESS CONTEXT]\n"
        "V.I.T.A.L. supports fitness tracking, AI workout generation, form guidance, "
        "goal setting, and macro calculation. Ask about your progress, request a workout plan, "
        "or get guidance on nutrition."
    )
    return "\n".join(lines)
