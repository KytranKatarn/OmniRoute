"""Calendar service — weekly content slots, agent voice settings, themed caption generation."""

import logging
from datetime import date, timedelta
from typing import Dict, List

from database import get_db_cursor

logger = logging.getLogger(__name__)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_week_calendar() -> List[Dict]:
    """Return all 7 days with their slots and queue status for the current week."""
    monday = date.today() - timedelta(days=date.today().weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT c.*, t.name AS theme_name, t.accent_color,
                   a.display_name AS agent_name, a.name AS agent_slug
            FROM social_content_calendar c
            LEFT JOIN social_content_themes t ON t.id = c.theme_id
            LEFT JOIN agents a ON a.id = c.featured_agent_id
            WHERE c.is_active = true
            ORDER BY c.day_of_week, c.slot_order
            """
        )
        slots = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT ((EXTRACT(DOW FROM created_at)::int + 6) %% 7) AS dow,
                   status, COUNT(*) AS cnt
            FROM social_video_queue
            WHERE created_at >= %s AND created_at < %s + INTERVAL '7 days'
            GROUP BY dow, status
            """,
            (monday, monday),
        )
        queue_status: Dict = {}
        for r in cur.fetchall():
            dow = int(r["dow"])
            queue_status.setdefault(dow, []).append({"status": r["status"], "count": r["cnt"]})

    slot_by_day: Dict = {}
    for s in slots:
        slot_by_day.setdefault(s["day_of_week"], []).append(s)

    days = []
    for i in range(7):
        days.append(
            {
                "day_of_week": i,
                "day_name": DAY_NAMES[i],
                "date": week_dates[i].isoformat(),
                "slots": slot_by_day.get(i, []),
                "queue_status": queue_status.get(i, []),
            }
        )
    return days


def get_calendar_slots() -> List[Dict]:
    """Return all active calendar slots with theme and agent info."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT c.*, t.name AS theme_name, t.accent_color,
                   a.display_name AS agent_name
            FROM social_content_calendar c
            LEFT JOIN social_content_themes t ON t.id = c.theme_id
            LEFT JOIN agents a ON a.id = c.featured_agent_id
            ORDER BY c.day_of_week, c.slot_order
            """
        )
        return [dict(r) for r in cur.fetchall()]


def upsert_calendar_slot(day_of_week: int, slot_order: int = 0, **kwargs) -> Dict:
    """Create or update a calendar slot by (day_of_week, slot_order)."""
    allowed = {"theme_id", "featured_agent_id", "auto_generate", "time_of_day", "platform", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    insert_cols = ["day_of_week", "slot_order"] + list(fields.keys())
    insert_vals = [day_of_week, slot_order] + list(fields.values())
    placeholders = ", ".join(["%s"] * len(insert_vals))
    set_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields) if fields else "is_active = is_active"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""
            INSERT INTO social_content_calendar ({', '.join(insert_cols)})
            VALUES ({placeholders})
            ON CONFLICT (day_of_week, slot_order) DO UPDATE SET {set_clause}
            RETURNING *
            """,
            insert_vals,
        )
        return dict(cur.fetchone())


def delete_calendar_slot(slot_id: int) -> bool:
    """Delete a calendar slot by id. Returns True if deleted."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM social_content_calendar WHERE id = %s", (slot_id,))
        return cur.rowcount > 0


def get_agent_voice(agent_id: int) -> Dict:
    """Return combined voice settings from agents table + agent_social_voice."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.writing_tone, a.writing_style, a.social_topics,
                   v.post_frequency_per_week, v.sample_phrases
            FROM agents a
            LEFT JOIN agent_social_voice v ON v.agent_id = a.id
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "tone": row["writing_tone"] or "professional",
            "style": row["writing_style"] or "",
            "social_topics": row["social_topics"] or [],
            "post_frequency_per_week": row["post_frequency_per_week"] or 2,
            "sample_phrases": row["sample_phrases"] or [],
        }


def upsert_agent_voice(agent_id: int, **kwargs) -> Dict:
    """Create or update agent_social_voice extended fields."""
    allowed = {"post_frequency_per_week", "sample_phrases"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_agent_voice(agent_id)
    cols = list(fields.keys())
    vals = [agent_id] + list(fields.values())
    set_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in cols)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""
            INSERT INTO agent_social_voice (agent_id, {', '.join(cols)})
            VALUES ({', '.join(['%s'] * len(vals))})
            ON CONFLICT (agent_id) DO UPDATE SET {set_clause}, updated_at = NOW()
            """,
            vals,
        )
    return get_agent_voice(agent_id)


def generate_themed_caption(agent_id: int, theme_id: int, scene_description: str = "") -> str:
    """Generate a social media caption for an agent using the theme's tone via S.I.G.N.A.L. dispatch."""
    from services.agent_service import get_agent
    from services.agent_social_service import get_writing_voice

    from .theme_service import get_theme

    agent = get_agent(agent_id)
    theme = get_theme(theme_id)
    if not agent or not theme:
        return ""

    voice = get_writing_voice(agent_id) or {}
    name = agent.get("display_name") or agent.get("name", "")
    dept = agent.get("department", "")
    tone = voice.get("tone", "professional")
    theme_tone = theme.get("tone", "")
    hashtags = " ".join((theme.get("hashtags") or [])[:3])
    scene_hint = f" Scene: {scene_description}." if scene_description else ""

    prompt = (
        f"Write a short social media post (2-3 sentences max) as {name}, "
        f"who works in {dept}. "
        f"Theme: {theme.get('name', '')}. "
        f"Tone: {theme_tone or tone}.{scene_hint} "
        f"Write in first person. Be authentic, human, and engaging. "
        f"End with these hashtags: {hashtags}"
    )

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch("content_writing", prompt, module_id="calendar_service")
        if result and result.success:
            return (result.response or "").strip()
    except Exception as exc:
        logger.warning("[calendar] generate_themed_caption failed for agent %s: %s", agent_id, exc)
    return ""


def get_slots_due_for_generation(days_ahead: int = 3) -> List[Dict]:
    """Return auto_generate=true slots that have no queued item in the next N days."""
    today = date.today()
    due = []
    for offset in range(days_ahead):
        target = today + timedelta(days=offset)
        dow = target.weekday()
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT c.*, t.name AS theme_name, t.slug AS theme_slug,
                       t.accent_color, t.tone AS theme_tone, t.hashtags,
                       a.display_name AS agent_name, a.id AS agent_id_val
                FROM social_content_calendar c
                JOIN social_content_themes t ON t.id = c.theme_id
                LEFT JOIN agents a ON a.id = c.featured_agent_id
                WHERE c.day_of_week = %s AND c.auto_generate = true AND c.is_active = true
                """,
                (dow,),
            )
            slots = [dict(r) for r in cur.fetchall()]
            for slot in slots:
                cur.execute(
                    """
                    SELECT id FROM social_video_queue
                    WHERE theme_id = %s AND created_at::date = %s
                    """,
                    (slot["theme_id"], target.isoformat()),
                )
                if not cur.fetchone():
                    slot["target_date"] = target.isoformat()
                    due.append(slot)
    return due


def get_empty_days_this_week() -> List[int]:
    """Return day_of_week values (Mon=0) with no social_video_queue items this week."""
    monday = date.today() - timedelta(days=date.today().weekday())
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT DISTINCT ((EXTRACT(DOW FROM created_at)::int + 6) %% 7) AS dow
            FROM social_video_queue
            WHERE created_at >= %s AND created_at < %s + INTERVAL '7 days'
            """,
            (monday, monday),
        )
        posted_days = {int(r["dow"]) for r in cur.fetchall()}
    return [d for d in range(7) if d not in posted_days]
