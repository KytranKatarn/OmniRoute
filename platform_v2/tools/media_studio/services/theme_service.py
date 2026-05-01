"""Theme service — manages social content themes and scenes for the Agent Social Presence Engine."""

import logging
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

_THEME_FIELDS = {"name", "tone", "hashtags", "music_mood", "accent_color", "is_active"}
_SCENE_FIELDS = {
    "name",
    "description",
    "visual_prompt_template",
    "style_directive",
    "image_aspect",
    "generation_type",
    "sort_order",
}


def get_all_themes(active_only: bool = True) -> List[Dict]:
    """Return all themes with curator agent display_name and scene count."""
    where = "WHERE t.is_active = TRUE" if active_only else ""
    sql = f"""
        SELECT t.*, a.display_name AS curator_name, COUNT(s.id) AS scene_count
        FROM social_content_themes t
        LEFT JOIN agents a ON a.id = t.curator_agent_id
        LEFT JOIN social_content_scenes s ON s.theme_id = t.id
        {where}
        GROUP BY t.id, a.display_name
        ORDER BY t.id
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def get_theme(theme_id: int) -> Optional[Dict]:
    """Return a single theme with curator name and scene count, or None."""
    sql = """
        SELECT t.*, a.display_name AS curator_name, COUNT(s.id) AS scene_count
        FROM social_content_themes t
        LEFT JOIN agents a ON a.id = t.curator_agent_id
        LEFT JOIN social_content_scenes s ON s.theme_id = t.id
        WHERE t.id = %s
        GROUP BY t.id, a.display_name
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, (theme_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_scenes_for_theme(theme_id: int) -> List[Dict]:
    """Return all scenes for a theme ordered by sort_order then id."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM social_content_scenes WHERE theme_id = %s ORDER BY sort_order, id",
            (theme_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def update_theme(theme_id: int, **kwargs) -> Optional[Dict]:
    """Update allowed theme fields. Returns updated theme dict or None."""
    allowed = {k: v for k, v in kwargs.items() if k in _THEME_FIELDS}
    if not allowed:
        return get_theme(theme_id)
    set_clause = ", ".join(f"{col} = %s" for col in allowed)
    values = list(allowed.values()) + [theme_id]
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE social_content_themes SET {set_clause} WHERE id = %s",
            values,
        )
    return get_theme(theme_id)


def upsert_scene(theme_id: int, scene_id: Optional[int], **kwargs) -> Dict:
    """Create or update a scene. Returns the resulting scene row dict."""
    allowed = {k: v for k, v in kwargs.items() if k in _SCENE_FIELDS}
    if scene_id is not None:
        if not allowed:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT * FROM social_content_scenes WHERE id = %s AND theme_id = %s",
                    (scene_id, theme_id),
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        set_clause = ", ".join(f"{col} = %s" for col in allowed)
        values = list(allowed.values()) + [scene_id, theme_id]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                f"UPDATE social_content_scenes SET {set_clause} WHERE id = %s AND theme_id = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else {}
    else:
        cols = ["theme_id"] + list(allowed.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        values = [theme_id] + list(allowed.values())
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                f"INSERT INTO social_content_scenes ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else {}
