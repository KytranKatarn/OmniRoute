"""Live Consciousness briefing injected into C.O.D.E.X. chat context."""

from services.time_utils import now_local_str


def _build_consciousness_briefing() -> str:
    """Return plain-text briefing of KB state for C.O.D.E.X."""
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[C.O.D.E.X. CONSCIOUSNESS BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded "
                "FROM knowledge_base WHERE is_archived=false"
            )
            row = cur.fetchone() or {}
            total = row.get("total", 0)
            embedded = row.get("embedded", 0)
            pct = round(embedded / total * 100, 1) if total else 0
            lines.append(f"Knowledge Base: {total:,} entries | {embedded:,} embedded ({pct}%)")

            cur.execute(
                "SELECT knowledge_type, COUNT(*) AS cnt FROM knowledge_base "
                "WHERE is_archived=false GROUP BY knowledge_type ORDER BY cnt DESC LIMIT 5"
            )
            types = cur.fetchall()
            type_summary = " | ".join(f"{r['knowledge_type']}: {r['cnt']}" for r in types)
            lines.append(f"By type — {type_summary}")

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_base "
                "WHERE is_archived=false AND created_at > NOW() - INTERVAL '24 hours'"
            )
            recent = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"New entries (24h): {recent}")

            cur.execute(
                "SELECT knowledge_type, title FROM knowledge_base "
                "WHERE is_archived=false ORDER BY created_at DESC LIMIT 3"
            )
            latest = cur.fetchall()
            if latest:
                lines.append("Recent entries:")
                for r in latest:
                    lines.append(f"  [{r['knowledge_type']}] {r['title'][:70]}")

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[C.O.D.E.X. CONTEXT]\n"
        "C.O.D.E.X. manages the knowledge base, documentation, and institutional memory. "
        "Ask about KB coverage, missing documentation, knowledge gaps, or memory quality."
    )
    return "\n".join(lines)
