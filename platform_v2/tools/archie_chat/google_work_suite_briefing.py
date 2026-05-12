"""Live Google Work Suite briefing injected into R.E.S.O.L.V.E. chat context."""

from services.time_utils import now_local_str


def _build_google_work_suite_briefing() -> str:
    """Return plain-text briefing of Google integration state for R.E.S.O.L.V.E."""
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[R.E.S.O.L.V.E. GOOGLE WORK SUITE BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT COUNT(*) AS cnt FROM google_accounts WHERE is_active=true")
            connected = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Connected Google accounts: {connected}")

            cur.execute("SELECT COUNT(*) AS cnt FROM email_labels")
            labels = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Gmail labels synced: {labels}")

            cur.execute("SELECT COUNT(*) AS cnt, MAX(fetched_at) AS last_sync " "FROM drive_files")
            row = cur.fetchone() or {}
            drive_files = row.get("cnt", 0)
            lines.append(f"Drive files indexed: {drive_files}")

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[R.E.S.O.L.V.E. GOOGLE CONTEXT]\n"
        "R.E.S.O.L.V.E. manages Google Workspace integrations — Gmail sync, "
        "Calendar (coming), and Drive (coming). Ask about account status, "
        "sync health, or email intelligence results."
    )
    return "\n".join(lines)
