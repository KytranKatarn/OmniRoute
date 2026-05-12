"""Live Family Tree briefing injected into H.E.R.I.T.A.G.E. chat context."""

from services.time_utils import now_local_str


def _build_family_tree_briefing() -> str:
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[H.E.R.I.T.A.G.E. FAMILY TREE BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT COUNT(*) AS cnt FROM family_persons")
            persons = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Persons on record: {persons}")

            cur.execute("SELECT COUNT(*) AS cnt FROM family_relationships")
            rels = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Relationships mapped: {rels}")

            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM family_events")
                events = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"Family events: {events}")
            except Exception:
                pass

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[H.E.R.I.T.A.G.E. CONTEXT]\n"
        "H.E.R.I.T.A.G.E. specializes in genealogy research, lineage tracing, "
        "GEDCOM import/export, photo analysis, and DNA matching. "
        "Ask about family connections, research hints, or document analysis."
    )
    return "\n".join(lines)
