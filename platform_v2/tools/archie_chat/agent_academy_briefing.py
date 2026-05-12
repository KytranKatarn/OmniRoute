"""Live Agent Academy briefing injected into F.O.R.G.E. chat context (academy variant)."""

from services.time_utils import now_local_str


def _build_agent_academy_briefing() -> str:
    """Return plain-text briefing of agent training/benchmark state for F.O.R.G.E."""
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[F.O.R.G.E. AGENT ACADEMY BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM agent_benchmark_results " "WHERE created_at > NOW() - INTERVAL '7 days'"
            )
            recent_benchmarks = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Benchmarks run (7d): {recent_benchmarks}")

            cur.execute(
                "SELECT a.name, s.proficiency_level, s.skill_name "
                "FROM agent_skills s JOIN agents a ON s.agent_id=a.id "
                "WHERE s.proficiency_level >= 4 "
                "ORDER BY s.proficiency_level DESC LIMIT 5"
            )
            top_skills = cur.fetchall()
            if top_skills:
                lines.append("Top Lv4+ skills:")
                for r in top_skills:
                    lines.append(f"  {r['name']}: {r['skill_name']} (Lv{r['proficiency_level']})")

            cur.execute("SELECT COUNT(*) AS cnt FROM agents " "WHERE worker_type='ai' AND shift_state='active'")
            active_agents = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Active AI agents eligible for training: {active_agents}")

            cur.execute("SELECT COUNT(*) AS cnt FROM agent_competency_scores " "WHERE score < 0.5")
            low_scores = (cur.fetchone() or {}).get("cnt", 0)
            if low_scores:
                lines.append(f"Agents with competency score <50%: {low_scores} — training recommended")

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[F.O.R.G.E. ACADEMY CONTEXT]\n"
        "F.O.R.G.E. oversees agent training, benchmarks, and skill development at the Academy. "
        "Ask about benchmark results, Lv4 unlock status, training gaps, or A/B test outcomes."
    )
    return "\n".join(lines)
