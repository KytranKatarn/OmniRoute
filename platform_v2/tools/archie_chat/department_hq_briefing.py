"""Live Department HQ briefing injected into K.I.N. chat context."""

from services.time_utils import now_local_str


def _build_department_hq_briefing() -> str:
    """Return plain-text briefing of org/agent state for K.I.N."""
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[K.I.N. DEPARTMENT HQ BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT shift_state, COUNT(*) AS cnt FROM agents "
                "WHERE worker_type='ai' AND shift_state != 'decommissioned' "
                "GROUP BY shift_state ORDER BY cnt DESC"
            )
            states = cur.fetchall()
            state_summary = ", ".join(f"{r['shift_state']}: {r['cnt']}" for r in states)
            lines.append(f"AI Agent shift states — {state_summary}")

            cur.execute("SELECT COUNT(*) AS cnt FROM agents " "WHERE worker_type='ai' AND shift_state='active'")
            active = (cur.fetchone() or {}).get("cnt", 0)

            cur.execute("SELECT COUNT(*) AS cnt FROM agents " "WHERE worker_type='ai' AND shift_state='barracked'")
            barracked = (cur.fetchone() or {}).get("cnt", 0)

            lines.append(f"Active: {active} | Barracked: {barracked}")

            cur.execute("SELECT COUNT(DISTINCT department) AS cnt FROM agents " "WHERE shift_state != 'decommissioned'")
            depts = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Departments with staff: {depts}/17")

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM agents "
                "WHERE worker_type='ai' AND is_department_ai=true "
                "AND shift_state='active'"
            )
            active_directors = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Active directors: {active_directors}/17")

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[K.I.N. WELFARE CONTEXT]\n"
        "K.I.N. manages agent welfare, shift transitions, and HR culture. "
        "Ask about agent workload, welfare flags, shift recommendations, or department health."
    )
    return "\n".join(lines)
