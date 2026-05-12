"""Live Media Studio briefing injected into M.U.S.E. chat context."""

from services.time_utils import now_local_str


def _build_media_studio_briefing() -> str:
    from database import get_db_cursor

    now_str = now_local_str()
    lines = [f"\n[M.U.S.E. MEDIA STUDIO BRIEFING — {now_str}]"]

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt, COUNT(*) FILTER (WHERE status='pending') AS pending "
                    "FROM media_generation_queue"
                )
                row = cur.fetchone() or {}
                lines.append(f"Generation queue: {row.get('cnt', 0)} total, {row.get('pending', 0)} pending")
            except Exception:
                pass

            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM media_gallery")
                gallery = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"Gallery assets: {gallery}")
            except Exception:
                pass

            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM agent_portraits WHERE approved_at IS NOT NULL")
                portraits = (cur.fetchone() or {}).get("cnt", 0)
                lines.append(f"Approved agent portraits: {portraits}")
            except Exception:
                pass

    except Exception as exc:
        lines.append(f"[briefing data unavailable: {exc}]")

    lines.append(
        "\n[M.U.S.E. CONTEXT]\n"
        "M.U.S.E. manages Media Studio — GPU-aware image/video/audio generation, "
        "portrait pipelines, ComfyUI fleet dispatch, and gallery management. "
        "Ask about generation queues, portrait status, or creative workflows."
    )
    return "\n".join(lines)
