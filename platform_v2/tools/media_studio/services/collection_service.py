"""Collection service — named groups + smart collections (saved filter presets).

Collections are owned by users/agents. Shared collections visible to all.
Smart collections store filter criteria as JSONB and execute dynamically.
"""

import logging
from typing import Dict, List

from database import get_db_cursor

logger = logging.getLogger(__name__)


def create_collection(
    name: str,
    owner_type: str,
    owner_id: int,
    description: str = "",
    is_shared: bool = False,
) -> int:
    """Create a new collection. Returns collection_id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_collections (name, description, owner_type, owner_id, is_shared)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (name.strip(), description, owner_type, owner_id, is_shared),
        )
        return cur.fetchone()["id"]


def update_collection(collection_id: int, owner_type: str, owner_id: int, **fields) -> bool:
    """Update collection fields. Returns True if updated."""
    allowed = {"name", "description", "is_shared", "cover_media_id"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False

    set_parts = [f"{k} = %s" for k in updates]
    set_parts.append("updated_at = now()")
    values = list(updates.values())

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""
            UPDATE media_collections SET {', '.join(set_parts)}
            WHERE id = %s AND owner_type = %s AND owner_id = %s
            """,
            values + [collection_id, owner_type, owner_id],
        )
        return cur.rowcount > 0


def delete_collection(collection_id: int, owner_type: str, owner_id: int) -> bool:
    """Delete a collection (not the media inside). Returns True if deleted."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM media_collections WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (collection_id, owner_type, owner_id),
        )
        return cur.rowcount > 0


def list_collections(owner_type: str, owner_id: int, include_shared: bool = True) -> List[Dict]:
    """List user's collections + shared ones, with item counts."""
    with get_db_cursor() as (conn, cur):
        if include_shared:
            cur.execute(
                """
                SELECT c.*, COUNT(ci.id) as item_count
                FROM media_collections c
                LEFT JOIN media_collection_items ci ON ci.collection_id = c.id
                WHERE (c.owner_type = %s AND c.owner_id = %s) OR c.is_shared = true
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """,
                (owner_type, owner_id),
            )
        else:
            cur.execute(
                """
                SELECT c.*, COUNT(ci.id) as item_count
                FROM media_collections c
                LEFT JOIN media_collection_items ci ON ci.collection_id = c.id
                WHERE c.owner_type = %s AND c.owner_id = %s
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """,
                (owner_type, owner_id),
            )
        return [dict(row) for row in cur.fetchall()]


def add_to_collection(
    collection_id: int,
    media_ids: List[int],
    owner_type: str,
    owner_id: int,
) -> int:
    """Add media items to a collection. Returns count added."""
    count = 0
    with get_db_cursor(commit=True) as (conn, cur):
        # Verify collection ownership or shared
        cur.execute(
            "SELECT id FROM media_collections WHERE id = %s AND (owner_type = %s AND owner_id = %s OR is_shared = true)",
            (collection_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return 0

        for mid in media_ids:
            cur.execute(
                "INSERT INTO media_collection_items (collection_id, media_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (collection_id, mid),
            )
            count += cur.rowcount
    return count


def remove_from_collection(
    collection_id: int,
    media_ids: List[int],
    owner_type: str,
    owner_id: int,
) -> int:
    """Remove media items from a collection. Returns count removed."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM media_collections WHERE id = %s AND (owner_type = %s AND owner_id = %s OR is_shared = true)",
            (collection_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return 0

        cur.execute(
            "DELETE FROM media_collection_items WHERE collection_id = %s AND media_id = ANY(%s)",
            (collection_id, media_ids),
        )
        return cur.rowcount


def get_collection_items(
    collection_id: int,
    owner_type: str,
    owner_id: int,
    page: int = 1,
    per_page: int = 20,
) -> Dict:
    """Paginated items in a collection."""
    offset = (page - 1) * per_page
    with get_db_cursor() as (conn, cur):
        # Verify access
        cur.execute(
            "SELECT id FROM media_collections WHERE id = %s AND (owner_type = %s AND owner_id = %s OR is_shared = true)",
            (collection_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

        cur.execute(
            "SELECT COUNT(*) as total FROM media_collection_items WHERE collection_id = %s",
            (collection_id,),
        )
        total = cur.fetchone()["total"]

        cur.execute(
            """
            SELECT ml.id, ml.media_type, ml.file_path, ml.thumbnail_path, ml.prompt,
                   ml.model, ml.provider, ml.seed, ml.width, ml.height, ml.is_favorite,
                   ml.created_at, ci.sort_order, ci.added_at
            FROM media_collection_items ci
            JOIN media_library ml ON ml.id = ci.media_id
            WHERE ci.collection_id = %s AND ml.is_deleted = false
            ORDER BY ci.sort_order, ci.added_at DESC
            LIMIT %s OFFSET %s
            """,
            (collection_id, per_page, offset),
        )
        items = [dict(row) for row in cur.fetchall()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


# ─── Smart Collections ───────────────────────────────────────────────


def create_smart_collection(name: str, filters: Dict, owner_type: str, owner_id: int) -> int:
    """Save a filter preset as a smart collection."""
    import psycopg2.extras

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_smart_collections (name, filters, owner_type, owner_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (name.strip(), psycopg2.extras.Json(filters), owner_type, owner_id),
        )
        return cur.fetchone()["id"]


def delete_smart_collection(smart_id: int, owner_type: str, owner_id: int) -> bool:
    """Delete a smart collection."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM media_smart_collections WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (smart_id, owner_type, owner_id),
        )
        return cur.rowcount > 0


def list_smart_collections(owner_type: str, owner_id: int) -> List[Dict]:
    """List user's smart collections."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, name, filters, created_at FROM media_smart_collections WHERE owner_type = %s AND owner_id = %s ORDER BY name",
            (owner_type, owner_id),
        )
        return [dict(row) for row in cur.fetchall()]


def execute_smart_collection(smart_id: int, owner_type: str, owner_id: int, page: int = 1, per_page: int = 20) -> Dict:
    """Execute a smart collection's saved filters and return matching media."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT filters FROM media_smart_collections WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (smart_id, owner_type, owner_id),
        )
        row = cur.fetchone()
        if not row:
            return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    filters = row["filters"]
    # Delegate to search_service which understands filter format
    from .search_service import search_media

    return search_media(
        owner_type=owner_type,
        owner_id=owner_id,
        query=filters.get("prompt_query"),
        filters=filters,
        page=page,
        per_page=per_page,
    )
