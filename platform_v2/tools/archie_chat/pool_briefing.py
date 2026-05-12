"""Live Pool briefing injected into L.E.D.G.E.R. chat context (archie_pool + pool_management)."""

from services.time_utils import now_local_str


def _build_pool_briefing(module_key: str = "archie_pool") -> str:
    from database import get_db_cursor

    now_str = now_local_str()
    label = "ARCHIE POOL" if module_key == "archie_pool" else "POOL MANAGEMENT"
    lines = [f"\n[L.E.D.G.E.R. {label} BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM pool_miners WHERE is_active = true")
                miners = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"Active miners: {miners}")
            except Exception:
                pass

            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM pool_payouts WHERE status='pending'")
                pending = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"Pending payouts: {pending}")
            except Exception:
                pass

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[L.E.D.G.E.R. CONTEXT]\n"
        "L.E.D.G.E.R. oversees the Ravencoin mining pool — miner performance, "
        "payout processing, pool statistics, and financial reporting. "
        "Ask about earnings, miner status, or pool health."
    )
    return "\n".join(lines)
