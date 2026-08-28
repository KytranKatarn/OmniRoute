"""Gallery service — media library CRUD with ownership tracking.

All queries filter by owner for access control. Soft-delete only.
"""

import logging
import os
from typing import Dict, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Resolve from known platform_v2 location — works both local and Docker
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")


def _serialize_row(row: dict) -> dict:
    """Convert a media_library DB row to a JSON-safe dict with url alias."""
    import datetime

    d = dict(row)
    # Add url alias so JS item.url works (JS uses url, DB stores file_path)
    d["url"] = d.get("file_path") or ""
    # Extract steps/cfg_scale from metadata JSONB so JS item.steps works
    meta = d.get("metadata") or {}
    if isinstance(meta, dict):
        d.setdefault("steps", meta.get("steps"))
        d.setdefault("cfg_scale", meta.get("cfg") or meta.get("cfg_scale"))
    # Serialize datetime fields to ISO strings for JSON
    for k, v in d.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            d[k] = v.isoformat()
    return d


# Allowed sort modes → ORDER BY clause. User input is mapped through this
# whitelist — never interpolated into SQL directly.
_GALLERY_SORTS = {
    "newest": "created_at DESC",
    "oldest": "created_at ASC",
    "favorites": "is_favorite DESC, created_at DESC",
    "cost": "cost DESC NULLS LAST, created_at DESC",
}


def get_gallery(
    owner_type: str,
    owner_id: int,
    media_type: Optional[str] = None,
    favorites_only: bool = False,
    page: int = 1,
    per_page: int = 20,
    show_versions: bool = False,
    asset_type: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "newest",
) -> Dict:
    """Paginated media library query with filters, search, and sort."""
    offset = (page - 1) * per_page
    conditions = ["is_deleted = false", "owner_type = %s", "owner_id = %s"]
    params = [owner_type, owner_id]

    if media_type:
        conditions.append("media_type = %s")
        params.append(media_type)
    if favorites_only:
        conditions.append("is_favorite = true")
    if asset_type:
        conditions.append("metadata->>'asset_type' = %s")
        params.append(asset_type)
    if search:
        conditions.append("prompt ILIKE %s")
        params.append(f"%{search.strip()}%")

    where = " AND ".join(conditions)
    order_by = _GALLERY_SORTS.get((sort or "newest").lower(), _GALLERY_SORTS["newest"])

    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) as total FROM media_library WHERE {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                   provider, seed, width, height, duration_ms, cost,
                   is_favorite, metadata, created_at
            FROM media_library
            WHERE {where}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        items = cur.fetchall()

    return {
        "items": [_serialize_row(row) for row in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def get_media_detail(media_id: int, owner_type: str, owner_id: int) -> Optional[Dict]:
    """Full metadata with ownership check.

    Accepts items owned by the calling user OR any agent-owned portrait/
    variant — the Media Studio portrait variant grid clicks land here and
    need agent-owned media to render. Public agent portraits aren't private.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT * FROM media_library
            WHERE id = %s AND is_deleted = false
              AND ((owner_type = %s AND owner_id = %s) OR owner_type = 'agent')
            """,
            (media_id, owner_type, owner_id),
        )
        row = cur.fetchone()
    return _serialize_row(row) if row else None


def create_media_entry(
    owner_type: str,
    owner_id: Optional[int],
    media_type: str,
    file_path: str,
    thumbnail_path: Optional[str] = None,
    prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    node_id: Optional[int] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration_ms: Optional[int] = None,
    cost: float = 0,
    metadata: Optional[Dict] = None,
) -> int:
    """Insert a new media library entry. Returns the new ID."""
    import psycopg2.extras

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_library
                (owner_type, owner_id, media_type, file_path, thumbnail_path,
                 prompt, negative_prompt, model, provider, node_id, seed,
                 width, height, duration_ms, cost, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                owner_type,
                owner_id,
                media_type,
                file_path,
                thumbnail_path,
                prompt,
                negative_prompt,
                model,
                provider,
                node_id,
                seed,
                width,
                height,
                duration_ms,
                cost,
                psycopg2.extras.Json(metadata or {}),
            ),
        )
        return cur.fetchone()["id"]


def delete_media(media_id: int, owner_type: str, owner_id: int) -> bool:
    """Soft delete with ownership verification."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_library SET is_deleted = true
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false
            """,
            (media_id, owner_type, owner_id),
        )
        return cur.rowcount > 0


def toggle_favorite(media_id: int, owner_type: str, owner_id: int) -> Optional[bool]:
    """Toggle is_favorite flag. Returns new state or None if not found."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_library SET is_favorite = NOT is_favorite
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false
            RETURNING is_favorite
            """,
            (media_id, owner_type, owner_id),
        )
        row = cur.fetchone()
    return row["is_favorite"] if row else None


def assign_media(
    media_id: int,
    assignment_type: str,
    target_type: str,
    target_id: Optional[int] = None,
) -> int:
    """Link media to a UI location. Deactivates previous assignment for same target+type."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Deactivate previous
        cur.execute(
            """
            UPDATE media_assignments SET is_active = false
            WHERE assignment_type = %s AND target_type = %s AND target_id = %s
                  AND is_active = true
            """,
            (assignment_type, target_type, target_id),
        )
        # Create new
        cur.execute(
            """
            INSERT INTO media_assignments (media_id, assignment_type, target_type, target_id)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (media_id, assignment_type, target_type, target_id),
        )
        return cur.fetchone()["id"]


def get_active_assignment(assignment_type: str, target_type: str, target_id: Optional[int] = None) -> Optional[Dict]:
    """Get active media assignment for a target."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT ma.*, ml.file_path, ml.thumbnail_path
            FROM media_assignments ma
            JOIN media_library ml ON ml.id = ma.media_id
            WHERE ma.assignment_type = %s AND ma.target_type = %s
                  AND ma.target_id = %s AND ma.is_active = true
            """,
            (assignment_type, target_type, target_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def bulk_set_favorite(media_ids, state, owner_type, owner_id):
    """Bulk set/unset favorite. Returns count updated."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_library SET is_favorite = %s
               WHERE id = ANY(%s) AND owner_type = %s AND owner_id = %s AND is_deleted = false""",
            (state, media_ids, owner_type, owner_id),
        )
        return cur.rowcount


def bulk_soft_delete(media_ids, owner_type, owner_id):
    """Bulk soft-delete. Returns count deleted."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_library SET is_deleted = true
               WHERE id = ANY(%s) AND owner_type = %s AND owner_id = %s AND is_deleted = false""",
            (media_ids, owner_type, owner_id),
        )
        return cur.rowcount


def bulk_reassign(media_ids, new_owner_type, new_owner_id):
    """Bulk reassign ownership (admin only — caller must check). Returns count."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_library SET owner_type = %s, owner_id = %s
               WHERE id = ANY(%s) AND is_deleted = false""",
            (new_owner_type, new_owner_id, media_ids),
        )
        return cur.rowcount
