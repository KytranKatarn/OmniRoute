"""Live WTF Hub briefing injected into F.A.C.T. chat context."""

from services.time_utils import now_local_str


def _build_wtf_hub_briefing() -> str:
    """Return plain-text briefing of WTF dispatch pipeline state for F.A.C.T."""
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[F.A.C.T. WTF HUB BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM task_execution_log "
                "WHERE module_source='wtf_hub' "
                "AND created_at > NOW() - INTERVAL '24 hours'"
            )
            dispatches_24h = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"WTF Hub dispatches (24h): {dispatches_24h}")

            cur.execute(
                "SELECT capability, COUNT(*) AS cnt, "
                "SUM(CASE WHEN success THEN 1 ELSE 0 END) AS succeeded "
                "FROM task_execution_log "
                "WHERE module_source='wtf_hub' "
                "AND created_at > NOW() - INTERVAL '24 hours' "
                "GROUP BY capability ORDER BY cnt DESC"
            )
            by_cap = cur.fetchall()
            if by_cap:
                lines.append("Pipeline breakdown (24h):")
                for r in by_cap:
                    rate = round(r["succeeded"] / r["cnt"] * 100) if r["cnt"] else 0
                    lines.append(f"  {r['capability']}: {r['cnt']} dispatched, {rate}% success")
            else:
                lines.append("No WTF Hub dispatches in the last 24h")

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[F.A.C.T. CONTEXT]\n"
        "F.A.C.T. is the News & Media director overseeing the WTF Hub bias/factcheck pipeline. "
        "Agents B.I.A.S. (bias), V.E.R.I.F.Y. (factcheck), L.O.C.A.L. (geo) execute the work. "
        "Ask about pipeline status, dispatch failures, article queue, or analysis quality."
    )
    return "\n".join(lines)
