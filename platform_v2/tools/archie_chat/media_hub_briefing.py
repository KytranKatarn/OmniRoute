"""Live Media Hub briefing injected into M.A.V.E.N. chat context."""

from services.time_utils import now_local_str


def _build_media_hub_briefing() -> str:
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[M.A.V.E.N. MEDIA HUB BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT COUNT(*) AS cnt FROM media_hub_services WHERE is_active = true")
            services = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Active media services: {services}")

            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt, COUNT(*) FILTER (WHERE status='pending') AS pending "
                    "FROM media_hub_requests"
                )
                row = cur.fetchone() or {}
                lines.append(f"Media requests: {row.get('cnt', 0)} total, {row.get('pending', 0)} pending")
            except Exception:
                pass

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[M.A.V.E.N. CONTEXT]\n"
        "M.A.V.E.N. manages the Media Hub — Plex/Jellyfin libraries, Overseerr requests, "
        "downloads, and media intelligence. Ask about library status, pending requests, or "
        "to add new content."
    )
    return "\n".join(lines)
