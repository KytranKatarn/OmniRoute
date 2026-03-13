"""Tagging service — tag CRUD, auto-tagging from generation params.

Tags have three types: system (auto-generated), user (manual), shared (cross-user).
All writes verify media ownership before tagging.
"""

import logging
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)


def create_tag(name: str, tag_type: str = "user", created_by: Optional[int] = None) -> int:
    """Upsert a tag. Returns tag_id (existing or new)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_tags (name, tag_type, created_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (name.strip().lower(), tag_type, created_by),
        )
        return cur.fetchone()["id"]


def get_tags(tag_type: Optional[str] = None) -> List[Dict]:
    """List all tags, optionally filtered by type."""
    with get_db_cursor() as (conn, cur):
        if tag_type:
            cur.execute(
                "SELECT id, name, tag_type, created_by, created_at FROM media_tags WHERE tag_type = %s ORDER BY name",
                (tag_type,),
            )
        else:
            cur.execute("SELECT id, name, tag_type, created_by, created_at FROM media_tags ORDER BY name")
        return [dict(row) for row in cur.fetchall()]


def get_media_tags(media_id: int) -> List[Dict]:
    """Get all tags on a media item."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT t.id, t.name, t.tag_type
            FROM media_tags t
            JOIN media_tag_map m ON m.tag_id = t.id
            WHERE m.media_id = %s
            ORDER BY t.name
            """,
            (media_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def tag_media(media_id: int, tag_ids: List[int], owner_type: str, owner_id: int) -> None:
    """Add tags to a media item (with ownership check)."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Ownership check
        cur.execute(
            "SELECT id FROM media_library WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false",
            (media_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return

        for tag_id in tag_ids:
            cur.execute(
                "INSERT INTO media_tag_map (media_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (media_id, tag_id),
            )


def untag_media(media_id: int, tag_ids: List[int], owner_type: str, owner_id: int) -> None:
    """Remove tags from a media item (with ownership check)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM media_library WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false",
            (media_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return

        cur.execute(
            "DELETE FROM media_tag_map WHERE media_id = %s AND tag_id = ANY(%s)",
            (media_id, tag_ids),
        )


def bulk_tag(media_ids: List[int], tag_ids: List[int], owner_type: str, owner_id: int) -> int:
    """Add tags to multiple media items. Returns count of items tagged."""
    count = 0
    with get_db_cursor(commit=True) as (conn, cur):
        # Get owned media IDs
        cur.execute(
            "SELECT id FROM media_library WHERE id = ANY(%s) AND owner_type = %s AND owner_id = %s AND is_deleted = false",
            (media_ids, owner_type, owner_id),
        )
        owned_ids = [row["id"] for row in cur.fetchall()]

        for mid in owned_ids:
            for tid in tag_ids:
                cur.execute(
                    "INSERT INTO media_tag_map (media_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (mid, tid),
                )
            count += 1
    return count


def auto_tag(media_id: int, params: Dict) -> None:
    """Create system tags from generation params. Called after generation completes."""
    tags_to_create = []

    # Media type
    media_type = params.get("media_type")
    if media_type:
        tags_to_create.append(media_type)

    # Model
    model = params.get("model", "")
    if model:
        tags_to_create.append(model.lower().replace(" ", "-"))

    # Provider
    provider = params.get("provider", "")
    if provider:
        tags_to_create.append(provider.lower())

    # Resolution bucket — snap to spec buckets, not raw dimensions
    width = params.get("width")
    height = params.get("height")
    if width and height:
        # Orientation tag
        if width > height:
            tags_to_create.append("landscape")
        elif height > width:
            tags_to_create.append("portrait")
        else:
            tags_to_create.append("square")
        # Size bucket — snap to nearest standard
        size = max(width, height)
        if size <= 640:
            tags_to_create.append("512x512")
        elif size <= 896:
            tags_to_create.append("768x768")
        else:
            tags_to_create.append("1024x1024")

    # Audio mode
    audio_mode = params.get("audio_mode")
    if audio_mode:
        tags_to_create.append(audio_mode)

    # Create system tags and link
    tag_ids = []
    for tag_name in tags_to_create:
        if tag_name:
            tid = create_tag(tag_name, tag_type="system")
            tag_ids.append(tid)

    if tag_ids:
        with get_db_cursor(commit=True) as (conn, cur):
            for tid in tag_ids:
                cur.execute(
                    "INSERT INTO media_tag_map (media_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (media_id, tid),
                )
