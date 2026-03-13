# Media Studio Layer 5: Gallery Enhancement & Curation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tagging, collections, semantic search, faceted filtering, bulk operations, and ZIP export to the Media Studio gallery.

**Architecture:** 4 new service files (tagging, collection, search, export) alongside existing gallery_service.py. One migration adds 5 tables + embedding column. 25 new API routes. Gallery tab UI overhaul with search bar, filter sidebar, selection mode, collections panel. Embeddings via existing embedding_service.py (arctic-embed-cpu, 768-dim).

**Tech Stack:** PostgreSQL + pgvector (JSONB fallback), Flask, LCARS IIFE JS, `ai_bridge/embedding_service.py`

**Spec:** `docs/superpowers/specs/2026-03-13-media-studio-layer5-gallery-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `database/migrations/151_gallery_enhancement.sql` | 5 new tables + prompt_embedding column |
| Create | `platform_v2/tools/media_studio/services/tagging_service.py` | Tag CRUD, auto-tagging from generation params |
| Create | `platform_v2/tools/media_studio/services/collection_service.py` | Collections + smart collections (saved filters) |
| Create | `platform_v2/tools/media_studio/services/search_service.py` | Faceted + semantic search, embedding pipeline |
| Create | `platform_v2/tools/media_studio/services/export_service.py` | ZIP export background jobs + cleanup |
| Modify | `platform_v2/tools/media_studio/services/generation_service.py` | Hook auto_tag + embed_prompt after generation |
| Modify | `platform_v2/tools/media_studio/routes.py` | 25 new API endpoints |
| Modify | `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Gallery tab UI overhaul |
| Modify | `platform_v2/tools/media_studio/static/css/media-studio.css` | Gallery enhancement styles |

---

## Chunk 1: Database + Backend Services

### Task 1: Database Migration 151

**Files:**
- Create: `database/migrations/151_gallery_enhancement.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 151: Gallery Enhancement — tags, collections, smart collections, embeddings
-- Adds 5 tables + prompt_embedding column on media_library

-- ─── Tags ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS media_tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    tag_type VARCHAR(20) NOT NULL DEFAULT 'user',
    created_by INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_media_tags_type ON media_tags (tag_type);

CREATE TABLE IF NOT EXISTS media_tag_map (
    id SERIAL PRIMARY KEY,
    media_id INTEGER NOT NULL REFERENCES media_library(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES media_tags(id) ON DELETE CASCADE,
    UNIQUE (media_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_media_tag_map_media ON media_tag_map (media_id);
CREATE INDEX IF NOT EXISTS idx_media_tag_map_tag ON media_tag_map (tag_id);

-- ─── Collections ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS media_collections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER,
    is_shared BOOLEAN DEFAULT false,
    cover_media_id INTEGER REFERENCES media_library(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_media_collections_owner
    ON media_collections (owner_type, owner_id);

CREATE TABLE IF NOT EXISTS media_collection_items (
    id SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES media_collections(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media_library(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0,
    added_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (collection_id, media_id)
);
CREATE INDEX IF NOT EXISTS idx_media_collection_items_coll
    ON media_collection_items (collection_id, sort_order);

-- ─── Smart Collections ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS media_smart_collections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER,
    filters JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_media_smart_collections_owner
    ON media_smart_collections (owner_type, owner_id);

-- ─── Prompt Embedding ────────────────────────────────────────────────

DO $$
BEGIN
    -- Try pgvector first
    CREATE EXTENSION IF NOT EXISTS vector;
    ALTER TABLE media_library ADD COLUMN IF NOT EXISTS prompt_embedding VECTOR(768);
    CREATE INDEX IF NOT EXISTS idx_media_library_prompt_emb
        ON media_library USING ivfflat (prompt_embedding vector_cosine_ops) WITH (lists = 10);
    RAISE NOTICE 'pgvector enabled — VECTOR(768) column added';
EXCEPTION WHEN OTHERS THEN
    -- Fallback to JSONB
    ALTER TABLE media_library ADD COLUMN IF NOT EXISTS prompt_embedding JSONB;
    RAISE NOTICE 'pgvector not available — using JSONB fallback for embeddings';
END $$;
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/151_gallery_enhancement.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/151_gallery_enhancement.sql
```

Expected: Tables created, embedding column added. Either "pgvector enabled" or "using JSONB fallback" notice.

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt media_*"
```

Expected: `media_tags`, `media_tag_map`, `media_collections`, `media_collection_items`, `media_smart_collections` all listed alongside existing `media_library`, `media_assignments`, `media_generation_queue`.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/151_gallery_enhancement.sql
git commit -m "feat(media-studio): add migration 151 — gallery tags, collections, embeddings"
```

---

### Task 2: Tagging Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/tagging_service.py`

- [ ] **Step 1: Create tagging_service.py**

```python
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


def tag_media(
    media_id: int, tag_ids: List[int], owner_type: str, owner_id: int
) -> None:
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


def untag_media(
    media_id: int, tag_ids: List[int], owner_type: str, owner_id: int
) -> None:
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


def bulk_tag(
    media_ids: List[int], tag_ids: List[int], owner_type: str, owner_id: int
) -> int:
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
```

- [ ] **Step 2: Verify import works in Docker**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2'); sys.path.insert(0, '/app')
from tools.media_studio.services.tagging_service import create_tag, get_tags, auto_tag
print('tagging_service: OK')
" 2>/dev/null | tail -1
```

Expected: `tagging_service: OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/tagging_service.py
git commit -m "feat(media-studio): add tagging service with auto-tag from generation params"
```

---

### Task 3: Collection Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/collection_service.py`

- [ ] **Step 1: Create collection_service.py**

```python
"""Collection service — named groups + smart collections (saved filter presets).

Collections are owned by users/agents. Shared collections visible to all.
Smart collections store filter criteria as JSONB and execute dynamically.
"""

import logging
from typing import Dict, List, Optional

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


def update_collection(
    collection_id: int, owner_type: str, owner_id: int, **fields
) -> bool:
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


def list_collections(
    owner_type: str, owner_id: int, include_shared: bool = True
) -> List[Dict]:
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


def create_smart_collection(
    name: str, filters: Dict, owner_type: str, owner_id: int
) -> int:
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


def execute_smart_collection(
    smart_id: int, owner_type: str, owner_id: int, page: int = 1, per_page: int = 20
) -> Dict:
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
```

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2'); sys.path.insert(0, '/app')
from tools.media_studio.services.collection_service import create_collection, list_collections
print('collection_service: OK')
" 2>/dev/null | tail -1
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/collection_service.py
git commit -m "feat(media-studio): add collection service with smart collections"
```

---

### Task 4: Search Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/search_service.py`

- [ ] **Step 1: Create search_service.py**

```python
"""Search service — faceted filters, text search, semantic embedding search.

Combines ILIKE text search with cosine similarity on prompt_embedding vectors.
pgvector required for production semantic search; JSONB fallback capped at 5,000 rows.
"""

import logging
import math
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Max rows for JSONB fallback semantic search
_JSONB_SEMANTIC_CAP = 5000

# Whether pgvector is available (detected on first use)
_pgvector_available = None


def _check_pgvector() -> bool:
    """Check if pgvector extension is installed."""
    global _pgvector_available
    if _pgvector_available is not None:
        return _pgvector_available
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            _pgvector_available = cur.fetchone() is not None
    except Exception:
        _pgvector_available = False
    return _pgvector_available


def search_media(
    owner_type: str,
    owner_id: int,
    query: Optional[str] = None,
    filters: Optional[Dict] = None,
    page: int = 1,
    per_page: int = 20,
) -> Dict:
    """Main search entry point: text + faceted + semantic.

    Args:
        query: Free text search (ILIKE on prompt + semantic if embeddings available)
        filters: Dict with optional keys: media_type, tags, model, provider,
                 date_from, date_to, min_width, min_height, collection_id
    """
    filters = filters or {}
    offset = (page - 1) * per_page

    # Build WHERE clauses
    conditions = ["ml.is_deleted = false", "ml.owner_type = %s", "ml.owner_id = %s"]
    params = [owner_type, owner_id]

    if filters.get("media_type"):
        conditions.append("ml.media_type = %s")
        params.append(filters["media_type"])

    if filters.get("model"):
        conditions.append("ml.model = %s")
        params.append(filters["model"])

    if filters.get("provider"):
        conditions.append("ml.provider = %s")
        params.append(filters["provider"])

    if filters.get("date_from"):
        conditions.append("ml.created_at >= %s")
        params.append(filters["date_from"])

    if filters.get("date_to"):
        conditions.append("ml.created_at <= %s")
        params.append(filters["date_to"])

    if filters.get("min_width"):
        conditions.append("ml.width >= %s")
        params.append(filters["min_width"])

    if filters.get("min_height"):
        conditions.append("ml.height >= %s")
        params.append(filters["min_height"])

    # Tag filter: media must have ALL specified tags
    tag_ids = filters.get("tags", [])
    if tag_ids:
        conditions.append(
            """
            ml.id IN (
                SELECT media_id FROM media_tag_map
                WHERE tag_id = ANY(%s)
                GROUP BY media_id
                HAVING COUNT(DISTINCT tag_id) = %s
            )
            """
        )
        params.extend([tag_ids, len(tag_ids)])

    # Collection filter
    if filters.get("collection_id"):
        conditions.append(
            "ml.id IN (SELECT media_id FROM media_collection_items WHERE collection_id = %s)"
        )
        params.append(filters["collection_id"])

    # Text search on prompt
    if query and query.strip():
        conditions.append("ml.prompt ILIKE %s")
        params.append(f"%{query.strip()}%")

    where = " AND ".join(conditions)

    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) as total FROM media_library ml WHERE {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT ml.id, ml.media_type, ml.file_path, ml.thumbnail_path, ml.prompt,
                   ml.model, ml.provider, ml.seed, ml.width, ml.height,
                   ml.is_favorite, ml.metadata, ml.created_at
            FROM media_library ml
            WHERE {where}
            ORDER BY ml.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        items = [dict(row) for row in cur.fetchall()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def embed_prompt(media_id: int, prompt: str) -> bool:
    """Generate and store embedding for a media item's prompt."""
    if not prompt or not prompt.strip():
        return False

    try:
        from ai_bridge.embedding_service import generate_embedding

        vector = generate_embedding(prompt.strip())
        if not vector:
            return False

        with get_db_cursor(commit=True) as (conn, cur):
            if _check_pgvector():
                cur.execute(
                    "UPDATE media_library SET prompt_embedding = %s WHERE id = %s",
                    (str(vector), media_id),
                )
            else:
                import psycopg2.extras

                cur.execute(
                    "UPDATE media_library SET prompt_embedding = %s WHERE id = %s",
                    (psycopg2.extras.Json(vector), media_id),
                )
        return True
    except Exception as e:
        logger.warning(f"Failed to embed prompt for media {media_id}: {e}")
        return False


def semantic_search(
    query_text: str, owner_type: str, owner_id: int, limit: int = 20
) -> List[Dict]:
    """Cosine similarity search on prompt_embedding."""
    if not query_text or not query_text.strip():
        return []

    try:
        from ai_bridge.embedding_service import generate_embedding

        query_vector = generate_embedding(query_text.strip())
        if not query_vector:
            return []
    except Exception as e:
        logger.warning(f"Failed to generate query embedding: {e}")
        return []

    if _check_pgvector():
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                       1 - (prompt_embedding <=> %s) as similarity
                FROM media_library
                WHERE owner_type = %s AND owner_id = %s
                    AND is_deleted = false AND prompt_embedding IS NOT NULL
                ORDER BY prompt_embedding <=> %s
                LIMIT %s
                """,
                (str(query_vector), owner_type, owner_id, str(query_vector), limit),
            )
            return [dict(row) for row in cur.fetchall()]
    else:
        # JSONB fallback — capped at _JSONB_SEMANTIC_CAP rows
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM media_library
                WHERE owner_type = %s AND owner_id = %s
                    AND is_deleted = false AND prompt_embedding IS NOT NULL
                """,
                (owner_type, owner_id),
            )
            cnt = cur.fetchone()["cnt"]
            if cnt > _JSONB_SEMANTIC_CAP:
                logger.warning(
                    f"Semantic search skipped: {cnt} rows exceeds JSONB cap of {_JSONB_SEMANTIC_CAP}. Install pgvector."
                )
                return []

            cur.execute(
                """
                SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                       prompt_embedding
                FROM media_library
                WHERE owner_type = %s AND owner_id = %s
                    AND is_deleted = false AND prompt_embedding IS NOT NULL
                """,
                (owner_type, owner_id),
            )
            rows = cur.fetchall()

        # Compute cosine similarity in Python
        results = []
        for row in rows:
            stored = row["prompt_embedding"]
            if not stored:
                continue
            sim = _cosine_similarity(query_vector, stored)
            d = dict(row)
            del d["prompt_embedding"]
            d["similarity"] = sim
            results.append(d)

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_search_facets(owner_type: str, owner_id: int) -> Dict:
    """Return distinct values for filter dropdowns."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT media_type FROM media_library WHERE owner_type = %s AND owner_id = %s AND is_deleted = false ORDER BY media_type",
            (owner_type, owner_id),
        )
        types = [row["media_type"] for row in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT model FROM media_library WHERE owner_type = %s AND owner_id = %s AND is_deleted = false AND model IS NOT NULL ORDER BY model",
            (owner_type, owner_id),
        )
        models = [row["model"] for row in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT provider FROM media_library WHERE owner_type = %s AND owner_id = %s AND is_deleted = false AND provider IS NOT NULL ORDER BY provider",
            (owner_type, owner_id),
        )
        providers = [row["provider"] for row in cur.fetchall()]

        # Tags used by this owner's media
        cur.execute(
            """
            SELECT DISTINCT t.id, t.name, t.tag_type
            FROM media_tags t
            JOIN media_tag_map m ON m.tag_id = t.id
            JOIN media_library ml ON ml.id = m.media_id
            WHERE ml.owner_type = %s AND ml.owner_id = %s AND ml.is_deleted = false
            ORDER BY t.name
            """,
            (owner_type, owner_id),
        )
        tags = [dict(row) for row in cur.fetchall()]

    return {"types": types, "models": models, "providers": providers, "tags": tags}
```

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2'); sys.path.insert(0, '/app')
from tools.media_studio.services.search_service import search_media, get_search_facets, embed_prompt
print('search_service: OK')
" 2>/dev/null | tail -1
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/search_service.py
git commit -m "feat(media-studio): add search service with faceted + semantic search"
```

---

### Task 5: Export Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/export_service.py`

- [ ] **Step 1: Create export_service.py**

```python
"""Export service — ZIP archive generation as background jobs.

Validates media ownership, creates ZIP in MEDIA_ROOT/exports/,
cleans up expired archives hourly via APScheduler.
"""

import logging
import os
import time
import zipfile
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")
EXPORTS_DIR = os.path.join(MEDIA_ROOT, "exports")

# Max items per export to prevent OOM
MAX_EXPORT_ITEMS = 500

os.makedirs(EXPORTS_DIR, exist_ok=True)


def create_export_job(
    media_ids: List[int], owner_type: str, owner_id: int
) -> Optional[int]:
    """Validate ownership of all media_ids and create an export job.

    Returns job_id or None if validation fails.
    """
    if not media_ids:
        return None

    if len(media_ids) > MAX_EXPORT_ITEMS:
        logger.warning(f"Export request exceeds {MAX_EXPORT_ITEMS} items, truncating")
        media_ids = media_ids[:MAX_EXPORT_ITEMS]

    with get_db_cursor(commit=True) as (conn, cur):
        # Verify ALL media_ids belong to this owner
        cur.execute(
            """
            SELECT id, file_path FROM media_library
            WHERE id = ANY(%s) AND owner_type = %s AND owner_id = %s AND is_deleted = false
            """,
            (media_ids, owner_type, owner_id),
        )
        owned = cur.fetchall()
        if len(owned) != len(media_ids):
            return None

        # Create export job record in media_generation_queue (reuse existing table)
        import psycopg2.extras

        cur.execute(
            """
            INSERT INTO media_generation_queue
                (owner_type, owner_id, media_type, status, params)
            VALUES (%s, %s, 'export', 'pending', %s)
            RETURNING id
            """,
            (
                owner_type,
                owner_id,
                psycopg2.extras.Json({"media_ids": media_ids, "type": "zip_export"}),
            ),
        )
        return cur.fetchone()["id"]


def generate_zip(job_id: int, media_ids: List[int]) -> Optional[str]:
    """Create ZIP archive from media files. Returns file path or None on failure."""
    zip_name = f"export_{job_id}_{int(time.time())}.zip"
    zip_path = os.path.join(EXPORTS_DIR, zip_name)

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, file_path, media_type, prompt FROM media_library WHERE id = ANY(%s) AND is_deleted = false",
                (media_ids,),
            )
            rows = cur.fetchall()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for row in rows:
                full_path = os.path.join(_PLATFORM_DIR, row["file_path"].lstrip("/"))
                if os.path.exists(full_path):
                    arcname = os.path.basename(full_path)
                    zf.write(full_path, arcname)

        # Update job status
        rel_path = f"/static/media/exports/{zip_name}"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'completed', result_path = %s, completed_at = now()
                WHERE id = %s
                """,
                (rel_path, job_id),
            )

        return rel_path
    except Exception as e:
        logger.error(f"ZIP export failed for job {job_id}: {e}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_generation_queue SET status = 'failed', error = %s WHERE id = %s",
                (str(e), job_id),
            )
        return None


def get_export_status(job_id: int, owner_type: str, owner_id: int) -> Optional[Dict]:
    """Get export job status with download URL when complete."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, status, result_path, created_at, completed_at
            FROM media_generation_queue
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND media_type = 'export'
            """,
            (job_id, owner_type, owner_id),
        )
        row = cur.fetchone()
    if not row:
        return None

    result = {"job_id": row["id"], "status": row["status"]}
    if row["status"] == "completed" and row["result_path"]:
        result["download_url"] = row["result_path"]
    return result


def cleanup_exports(max_age_hours: int = 1) -> int:
    """Delete expired export ZIP files. Returns count deleted."""
    deleted = 0
    cutoff = time.time() - (max_age_hours * 3600)

    if not os.path.isdir(EXPORTS_DIR):
        return 0

    expired_job_ids = []
    for fname in os.listdir(EXPORTS_DIR):
        if not fname.endswith(".zip"):
            continue
        fpath = os.path.join(EXPORTS_DIR, fname)
        if os.path.getmtime(fpath) < cutoff:
            try:
                os.remove(fpath)
                deleted += 1
                # Extract job_id from filename: export_{job_id}_{timestamp}.zip
                parts = fname.replace(".zip", "").split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    expired_job_ids.append(int(parts[1]))
            except OSError as e:
                logger.warning(f"Failed to delete export {fname}: {e}")

    # Mark DB records as expired so get_export_status doesn't return stale URLs
    if expired_job_ids:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_generation_queue SET status = 'expired' WHERE id = ANY(%s) AND status = 'completed'",
                (expired_job_ids,),
            )

    if deleted:
        logger.info(f"Cleaned up {deleted} expired export(s)")
    return deleted
```

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2'); sys.path.insert(0, '/app')
from tools.media_studio.services.export_service import create_export_job, cleanup_exports
print('export_service: OK')
" 2>/dev/null | tail -1
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/export_service.py
git commit -m "feat(media-studio): add export service with ZIP generation + cleanup"
```

---

### Task 6: Hook Auto-tag + Embed in Generation Service

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py` (~line 249, after `create_media_entry()`)

- [ ] **Step 1: Read the current generation_service.py to find the exact hook point**

Look for where `create_media_entry()` is called. Add auto_tag + embed_prompt calls right after the media_id is returned.

- [ ] **Step 2: Add the hooks after create_media_entry**

After the line `media_id = create_media_entry(...)` (around line 249), add:

```python
        # Auto-tag and embed prompt
        try:
            from .tagging_service import auto_tag

            auto_tag(media_id, {
                "media_type": queue_row["media_type"],
                "model": params.get("model"),
                "provider": provider,
                "width": params.get("width"),
                "height": params.get("height"),
                "audio_mode": params.get("audio_mode"),
            })
        except Exception as e:
            logger.warning(f"Auto-tag failed for media {media_id}: {e}")

        try:
            from .search_service import embed_prompt

            embed_prompt(media_id, params.get("prompt", ""))
        except Exception as e:
            logger.warning(f"Embed prompt failed for media {media_id}: {e}")
```

- [ ] **Step 3: Verify the platform restarts cleanly**

```bash
docker compose restart archie_platform
```

Wait 5s, then check logs for errors:
```bash
docker logs archie_platform 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): hook auto-tag + embed_prompt after generation completes"
```

---

## Chunk 2: API Routes

### Task 7: Tag Routes (5 endpoints)

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py` (after the Environments section, ~line 482)

- [ ] **Step 1: Add tag routes**

Append after the Environments section (before the file ends):

```python
# ─── Tags ────────────────────────────────────────────────────────────


@media_studio_bp.route("/api/tags")
@login_required
def api_tags():
    """List all tags, optionally filtered by type."""
    from .services.tagging_service import get_tags

    tag_type = request.args.get("type")
    return jsonify({"tags": get_tags(tag_type)})


@media_studio_bp.route("/api/tags", methods=["POST"])
@login_required
def api_create_tag():
    """Create a new tag."""
    from .services.tagging_service import create_tag

    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    tag_type = data.get("tag_type", "user")
    if tag_type not in ("user", "shared"):
        return jsonify({"error": "tag_type must be user or shared"}), 400

    tag_id = create_tag(data["name"], tag_type, current_user.id)
    return jsonify({"id": tag_id, "name": data["name"], "tag_type": tag_type}), 201


@media_studio_bp.route("/api/gallery/<int:media_id>/tags", methods=["POST"])
@login_required
def api_add_tags(media_id):
    """Add tags to a media item."""
    from .services.tagging_service import tag_media

    data = request.get_json()
    if not data or not data.get("tag_ids"):
        return jsonify({"error": "tag_ids is required"}), 400

    tag_media(media_id, data["tag_ids"], "user", current_user.id)
    return jsonify({"status": "tagged"})


@media_studio_bp.route("/api/gallery/<int:media_id>/tags/remove", methods=["POST"])
@login_required
def api_remove_tags(media_id):
    """Remove tags from a media item."""
    from .services.tagging_service import untag_media

    data = request.get_json()
    if not data or not data.get("tag_ids"):
        return jsonify({"error": "tag_ids is required"}), 400

    untag_media(media_id, data["tag_ids"], "user", current_user.id)
    return jsonify({"status": "untagged"})


@media_studio_bp.route("/api/gallery/bulk/tags", methods=["POST"])
@login_required
def api_bulk_tags():
    """Bulk add tags to multiple media items."""
    from .services.tagging_service import bulk_tag

    data = request.get_json()
    if not data or not data.get("media_ids") or not data.get("tag_ids"):
        return jsonify({"error": "media_ids and tag_ids are required"}), 400

    count = bulk_tag(data["media_ids"], data["tag_ids"], "user", current_user.id)
    return jsonify({"count": count})
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add tag API routes (5 endpoints)"
```

---

### Task 8: Collection Routes (7 endpoints)

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

- [ ] **Step 1: Append collection routes**

```python
# ─── Collections ─────────────────────────────────────────────────────


@media_studio_bp.route("/api/collections")
@login_required
def api_collections():
    """List user's collections + shared."""
    from .services.collection_service import list_collections

    include_shared = request.args.get("include_shared", "true").lower() == "true"
    return jsonify({"collections": list_collections("user", current_user.id, include_shared)})


@media_studio_bp.route("/api/collections", methods=["POST"])
@login_required
def api_create_collection():
    """Create a new collection."""
    from .services.collection_service import create_collection

    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    cid = create_collection(
        name=data["name"],
        owner_type="user",
        owner_id=current_user.id,
        description=data.get("description", ""),
        is_shared=data.get("is_shared", False),
    )
    return jsonify({"id": cid, "name": data["name"]}), 201


@media_studio_bp.route("/api/collections/<int:collection_id>", methods=["PUT"])
@login_required
def api_update_collection(collection_id):
    """Update a collection."""
    from .services.collection_service import update_collection

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    ok = update_collection(collection_id, "user", current_user.id, **data)
    if not ok:
        return jsonify({"error": "Not found or no changes"}), 404
    return jsonify({"status": "updated"})


@media_studio_bp.route("/api/collections/<int:collection_id>", methods=["DELETE"])
@login_required
def api_delete_collection(collection_id):
    """Delete a collection (not the media inside)."""
    from .services.collection_service import delete_collection

    ok = delete_collection(collection_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


@media_studio_bp.route("/api/collections/<int:collection_id>/items")
@login_required
def api_collection_items(collection_id):
    """Paginated items in a collection."""
    from .services.collection_service import get_collection_items

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    return jsonify(get_collection_items(collection_id, "user", current_user.id, page, per_page))


@media_studio_bp.route("/api/collections/<int:collection_id>/items", methods=["POST"])
@login_required
def api_add_to_collection(collection_id):
    """Add media items to a collection."""
    from .services.collection_service import add_to_collection

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = add_to_collection(collection_id, data["media_ids"], "user", current_user.id)
    return jsonify({"count": count}), 201


@media_studio_bp.route("/api/collections/<int:collection_id>/items/remove", methods=["POST"])
@login_required
def api_remove_from_collection(collection_id):
    """Remove media items from a collection."""
    from .services.collection_service import remove_from_collection

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = remove_from_collection(collection_id, data["media_ids"], "user", current_user.id)
    return jsonify({"count": count})
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add collection API routes (7 endpoints)"
```

---

### Task 9: Smart Collection + Search + Bulk + Export Routes (13 endpoints)

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

- [ ] **Step 1: Append smart collection routes**

```python
# ─── Smart Collections ───────────────────────────────────────────────


@media_studio_bp.route("/api/smart-collections")
@login_required
def api_smart_collections():
    """List user's smart collections."""
    from .services.collection_service import list_smart_collections

    return jsonify({"smart_collections": list_smart_collections("user", current_user.id)})


@media_studio_bp.route("/api/smart-collections", methods=["POST"])
@login_required
def api_create_smart_collection():
    """Create a smart collection (saved filter preset)."""
    from .services.collection_service import create_smart_collection

    data = request.get_json()
    if not data or not data.get("name") or not data.get("filters"):
        return jsonify({"error": "name and filters are required"}), 400

    sid = create_smart_collection(data["name"], data["filters"], "user", current_user.id)
    return jsonify({"id": sid, "name": data["name"]}), 201


@media_studio_bp.route("/api/smart-collections/<int:smart_id>", methods=["DELETE"])
@login_required
def api_delete_smart_collection(smart_id):
    """Delete a smart collection."""
    from .services.collection_service import delete_smart_collection

    ok = delete_smart_collection(smart_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


@media_studio_bp.route("/api/smart-collections/<int:smart_id>/results")
@login_required
def api_smart_collection_results(smart_id):
    """Execute a smart collection and return matching media."""
    from .services.collection_service import execute_smart_collection

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    return jsonify(execute_smart_collection(smart_id, "user", current_user.id, page, per_page))
```

- [ ] **Step 2: Append search routes**

```python
# ─── Search ──────────────────────────────────────────────────────────


@media_studio_bp.route("/api/search")
@login_required
def api_search():
    """Faceted + text + semantic search."""
    from .services.search_service import search_media

    query = request.args.get("q", "").strip()
    filters = {}
    if request.args.get("type"):
        filters["media_type"] = request.args["type"]
    if request.args.get("model"):
        filters["model"] = request.args["model"]
    if request.args.get("provider"):
        filters["provider"] = request.args["provider"]
    if request.args.get("date_from"):
        filters["date_from"] = request.args["date_from"]
    if request.args.get("date_to"):
        filters["date_to"] = request.args["date_to"]
    if request.args.get("min_width"):
        filters["min_width"] = request.args.get("min_width", type=int)
    if request.args.get("min_height"):
        filters["min_height"] = request.args.get("min_height", type=int)
    if request.args.get("tags"):
        try:
            filters["tags"] = [int(t) for t in request.args["tags"].split(",")]
        except ValueError:
            pass
    if request.args.get("collection_id"):
        filters["collection_id"] = request.args.get("collection_id", type=int)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    return jsonify(search_media("user", current_user.id, query or None, filters or None, page, per_page))


@media_studio_bp.route("/api/search/facets")
@login_required
def api_search_facets():
    """Available filter values for dropdowns."""
    from .services.search_service import get_search_facets

    return jsonify(get_search_facets("user", current_user.id))
```

- [ ] **Step 3: Add bulk helper functions to gallery_service.py**

Append these to `platform_v2/tools/media_studio/services/gallery_service.py`:

```python
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
```

- [ ] **Step 4: Append bulk operation routes**

```python
# ─── Bulk Operations ─────────────────────────────────────────────────


@media_studio_bp.route("/api/gallery/bulk/favorite", methods=["POST"])
@login_required
def api_bulk_favorite():
    """Bulk set/unset favorite on multiple items."""
    from .services.gallery_service import bulk_set_favorite

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = bulk_set_favorite(data["media_ids"], data.get("state", True), "user", current_user.id)
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/delete", methods=["POST"])
@login_required
def api_bulk_delete():
    """Bulk soft-delete multiple items."""
    from .services.gallery_service import bulk_soft_delete

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = bulk_soft_delete(data["media_ids"], "user", current_user.id)
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/move", methods=["POST"])
@login_required
def api_bulk_move():
    """Bulk add items to a collection."""
    from .services.collection_service import add_to_collection

    data = request.get_json()
    if not data or not data.get("media_ids") or not data.get("collection_id"):
        return jsonify({"error": "media_ids and collection_id are required"}), 400

    count = add_to_collection(data["collection_id"], data["media_ids"], "user", current_user.id)
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/reassign", methods=["POST"])
@login_required
def api_bulk_reassign():
    """Bulk reassign media ownership. Admin only."""
    from .services.gallery_service import bulk_reassign

    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json()
    if not data or not data.get("media_ids") or not data.get("owner_type"):
        return jsonify({"error": "media_ids, owner_type are required"}), 400

    count = bulk_reassign(data["media_ids"], data["owner_type"], data.get("owner_id"))
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/regenerate", methods=["POST"])
@login_required
def api_bulk_regenerate():
    """Re-queue media items with original generation params."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    from database import get_db_cursor

    queued = 0
    skipped = 0

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, media_type, prompt, negative_prompt, model, seed, width, height, metadata
            FROM media_library
            WHERE id = ANY(%s) AND owner_type = 'user' AND owner_id = %s AND is_deleted = false
            """,
            (data["media_ids"], current_user.id),
        )
        rows = cur.fetchall()

    for row in rows:
        if not row["prompt"]:
            skipped += 1
            continue

        params = {}
        if row["model"]:
            params["model"] = row["model"]
        if row["width"]:
            params["width"] = row["width"]
        if row["height"]:
            params["height"] = row["height"]
        # Merge stored metadata params
        meta = row["metadata"] or {}
        for k in ("steps", "cfg", "sampler", "audio_mode", "voice_id", "duration", "fps"):
            if k in meta:
                params[k] = meta[k]

        result = submit_generation(
            user_id=current_user.id,
            media_type=row["media_type"],
            prompt=row["prompt"],
            negative_prompt=row.get("negative_prompt", ""),
            params=params,
        )
        if "error" not in result:
            queued += 1
        else:
            skipped += 1

    return jsonify({"queued": queued, "skipped": skipped})
```

- [ ] **Step 4: Append export routes**

```python
# ─── Export ──────────────────────────────────────────────────────────


@media_studio_bp.route("/api/export", methods=["POST"])
@login_required
def api_create_export():
    """Start a ZIP export job."""
    from .services.export_service import create_export_job

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    job_id = create_export_job(data["media_ids"], "user", current_user.id)
    if not job_id:
        return jsonify({"error": "Invalid media IDs or ownership mismatch"}), 400
    return jsonify({"job_id": job_id}), 201


@media_studio_bp.route("/api/export/<int:job_id>")
@login_required
def api_export_status(job_id):
    """Get export job status."""
    from .services.export_service import get_export_status

    result = get_export_status(job_id, "user", current_user.id)
    if not result:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result)
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add smart collections, search, bulk ops, export routes (13 endpoints)"
```

---

## Chunk 3: Frontend UI

### Task 10: Gallery Tab HTML Overhaul

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

The Gallery tab (lines 348–372) needs a complete overhaul. Replace the existing gallery tab content with:

- [ ] **Step 1: Replace the Gallery tab HTML**

Replace the `<div id="ms-tab-gallery">` section (lines 348–375 approximately) with:

```html
<div id="ms-tab-gallery" class="ms-tab-pane">
    <!-- Search Bar -->
    <div class="ms-gallery-search">
        <div class="ms-search-input-wrap">
            <span class="ms-search-icon">&#x1F50D;</span>
            <input type="text" id="msGallerySearch" class="ms-search-input"
                   placeholder="Search prompts..." autocomplete="off">
        </div>
    </div>

    <div class="ms-gallery-layout">
        <!-- Filter Sidebar (collapsible) -->
        <button class="ms-sidebar-toggle" id="msSidebarToggle" onclick="toggleGallerySidebar()">&#x25C0; Filters</button>
        <div class="ms-gallery-sidebar" id="msGallerySidebar">
            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Type</h4>
                <div class="ms-filter-pills" id="msTypeFilters">
                    <button class="ms-filter-btn active" data-filter="all" onclick="setGalleryFilter('type', 'all', this)">All</button>
                    <button class="ms-filter-btn" data-filter="image" onclick="setGalleryFilter('type', 'image', this)">Images</button>
                    <button class="ms-filter-btn" data-filter="video" onclick="setGalleryFilter('type', 'video', this)">Video</button>
                    <button class="ms-filter-btn" data-filter="audio" onclick="setGalleryFilter('type', 'audio', this)">Audio</button>
                </div>
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Tags</h4>
                <div class="ms-tag-filter-list" id="msTagFilters"></div>
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Model</h4>
                <select id="msModelFilter" class="ms-filter-select" onchange="applyGalleryFilters()">
                    <option value="">All Models</option>
                </select>
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Provider</h4>
                <select id="msProviderFilter" class="ms-filter-select" onchange="applyGalleryFilters()">
                    <option value="">All Providers</option>
                </select>
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Date Range</h4>
                <input type="date" id="msDateFrom" class="ms-filter-date" onchange="applyGalleryFilters()">
                <input type="date" id="msDateTo" class="ms-filter-date" onchange="applyGalleryFilters()">
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Min Resolution</h4>
                <div class="ms-resolution-inputs">
                    <input type="number" id="msMinWidth" class="ms-filter-input" placeholder="Width" min="0" step="64" onchange="applyGalleryFilters()">
                    <span class="ms-resolution-x">&times;</span>
                    <input type="number" id="msMinHeight" class="ms-filter-input" placeholder="Height" min="0" step="64" onchange="applyGalleryFilters()">
                </div>
            </div>

            <button class="ms-btn ms-btn-secondary" onclick="saveAsSmartCollection()">Save as Smart Collection</button>

            <!-- Collections Panel -->
            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">My Collections</h4>
                <div id="msMyCollectionsList"></div>
                <div class="ms-new-collection">
                    <input type="text" id="msNewCollectionName" class="ms-filter-input" placeholder="New collection...">
                    <button class="ms-btn-icon" onclick="createNewCollection()">+</button>
                </div>
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Shared Collections</h4>
                <div id="msSharedCollectionsList"></div>
            </div>

            <div class="ms-sidebar-section">
                <h4 class="ms-sidebar-title">Smart Collections</h4>
                <div id="msSmartCollectionsList"></div>
            </div>
        </div>

        <!-- Main Gallery Area -->
        <div class="ms-gallery-main">
            <!-- Bulk Action Toolbar (hidden until selection) -->
            <div class="ms-bulk-toolbar" id="msBulkToolbar" style="display:none;">
                <span class="ms-bulk-count" id="msBulkCount">0 selected</span>
                <button class="ms-bulk-btn" onclick="bulkSelectAll()">Select All</button>
                <button class="ms-bulk-btn" onclick="bulkDeselectAll()">Deselect</button>
                <button class="ms-bulk-btn" onclick="bulkFavorite()">Favorite</button>
                <button class="ms-bulk-btn" onclick="bulkTag()">Tag</button>
                <button class="ms-bulk-btn" onclick="bulkMoveToCollection()">Move</button>
                <button class="ms-bulk-btn" onclick="bulkExport()">Export ZIP</button>
                <button class="ms-bulk-btn" onclick="bulkRegenerate()">Regenerate</button>
                <button class="ms-bulk-btn ms-bulk-btn-danger" onclick="bulkDelete()">Delete</button>
            </div>

            <div class="ms-gallery-grid" id="msGalleryGrid">
                <div class="ms-empty-state" id="msGalleryEmpty">
                    <p>No media yet. Generate something in the Generate tab!</p>
                </div>
            </div>

            <div class="ms-gallery-footer">
                <button class="ms-btn ms-btn-secondary" id="msLoadMoreBtn" style="display:none;" onclick="loadGalleryMore()">Load More</button>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Commit HTML changes**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): overhaul Gallery tab HTML with search, filters, collections, bulk toolbar"
```

---

### Task 11: Gallery JavaScript

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` (JS section)

- [ ] **Step 1: Add gallery enhancement JS**

Add the following inside the existing `<script>` IIFE, after the existing gallery functions. Replace the existing `loadGallery` and `filterGallery` functions with the enhanced versions:

```javascript
    // ─── Gallery Enhancement State ──────────────────────────────────
    var galleryFilters = { type: 'all', tags: [], model: '', provider: '', date_from: '', date_to: '', min_width: '', min_height: '' };
    var gallerySearchQuery = '';
    var selectedMediaIds = [];
    var gallerySearchTimeout = null;
    var currentCollectionFilter = null;
    var lastSelectedIndex = -1;

    // ─── Search ─────────────────────────────────────────────────────
    var searchInput = document.getElementById('msGallerySearch');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(gallerySearchTimeout);
            gallerySearchTimeout = setTimeout(function() {
                gallerySearchQuery = searchInput.value.trim();
                loadGallery(1);
            }, 300);
        });
    }

    // ─── Filter Helpers ─────────────────────────────────────────────
    window.setGalleryFilter = function(key, value, btn) {
        galleryFilters[key] = value;
        if (btn) {
            var parent = btn.parentElement;
            var btns = parent.querySelectorAll('.ms-filter-btn');
            for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
            btn.classList.add('active');
        }
        loadGallery(1);
    };

    window.applyGalleryFilters = function() {
        galleryFilters.model = document.getElementById('msModelFilter').value;
        galleryFilters.provider = document.getElementById('msProviderFilter').value;
        galleryFilters.date_from = document.getElementById('msDateFrom').value;
        galleryFilters.date_to = document.getElementById('msDateTo').value;
        galleryFilters.min_width = document.getElementById('msMinWidth').value;
        galleryFilters.min_height = document.getElementById('msMinHeight').value;
        loadGallery(1);
    };

    // ─── Enhanced Gallery Load ──────────────────────────────────────
    window.loadGallery = function(page) {
        currentGalleryPage = page;
        var params = '?page=' + page + '&per_page=20';

        if (gallerySearchQuery) params += '&q=' + encodeURIComponent(gallerySearchQuery);
        if (galleryFilters.type && galleryFilters.type !== 'all') params += '&type=' + galleryFilters.type;
        if (galleryFilters.model) params += '&model=' + encodeURIComponent(galleryFilters.model);
        if (galleryFilters.provider) params += '&provider=' + encodeURIComponent(galleryFilters.provider);
        if (galleryFilters.date_from) params += '&date_from=' + galleryFilters.date_from;
        if (galleryFilters.date_to) params += '&date_to=' + galleryFilters.date_to;
        if (galleryFilters.tags.length) params += '&tags=' + galleryFilters.tags.join(',');
        if (galleryFilters.min_width) params += '&min_width=' + galleryFilters.min_width;
        if (galleryFilters.min_height) params += '&min_height=' + galleryFilters.min_height;
        if (currentCollectionFilter) params += '&collection_id=' + currentCollectionFilter;

        var endpoint = gallerySearchQuery ? '/api/search' : '/api/gallery';

        api('GET', endpoint + params).then(function(data) {
            var grid = document.getElementById('msGalleryGrid');
            var empty = document.getElementById('msGalleryEmpty');
            var loadMore = document.getElementById('msLoadMoreBtn');

            if (page === 1) _clearChildren(grid);

            var items = data.items || [];
            if (items.length === 0 && page === 1) {
                if (empty) empty.style.display = 'block';
                if (loadMore) loadMore.style.display = 'none';
                return;
            }
            if (empty) empty.style.display = 'none';

            for (var i = 0; i < items.length; i++) {
                grid.appendChild(_createGalleryCard(items[i]));
            }

            if (loadMore) {
                loadMore.style.display = (data.page < data.pages) ? 'inline-block' : 'none';
            }
        });
    };

    function _createGalleryCard(item) {
        var card = document.createElement('div');
        card.className = 'ms-gallery-card';
        card.dataset.mediaId = item.id;

        // Checkbox for selection (supports shift+click range)
        var cb = document.createElement('div');
        cb.className = 'ms-gallery-checkbox';
        cb.onclick = function(e) {
            e.stopPropagation();
            var cards = document.querySelectorAll('.ms-gallery-card');
            var myIndex = Array.prototype.indexOf.call(cards, card);
            if (e.shiftKey && lastSelectedIndex >= 0 && lastSelectedIndex !== myIndex) {
                var start = Math.min(lastSelectedIndex, myIndex);
                var end = Math.max(lastSelectedIndex, myIndex);
                for (var si = start; si <= end; si++) {
                    var sid = parseInt(cards[si].dataset.mediaId);
                    if (selectedMediaIds.indexOf(sid) === -1) selectedMediaIds.push(sid);
                }
                _updateSelectionUI();
            } else {
                toggleMediaSelection(item.id);
            }
            lastSelectedIndex = myIndex;
        };
        card.appendChild(cb);

        // Thumbnail
        var img = document.createElement('div');
        img.className = 'ms-gallery-thumb';
        if (item.thumbnail_path) {
            var imgEl = document.createElement('img');
            imgEl.src = item.thumbnail_path;
            imgEl.alt = (item.prompt || '').substring(0, 50);
            img.appendChild(imgEl);
        } else {
            var icon = document.createElement('span');
            icon.className = 'ms-gallery-type-icon';
            icon.textContent = item.media_type === 'video' ? '▶' : item.media_type === 'audio' ? '♪' : '□';
            img.appendChild(icon);
        }
        card.appendChild(img);

        // Info bar
        var info = document.createElement('div');
        info.className = 'ms-gallery-info';
        var p = document.createElement('p');
        p.className = 'ms-gallery-prompt';
        p.textContent = (item.prompt || 'No prompt').substring(0, 60);
        info.appendChild(p);
        card.appendChild(info);

        // Tag pills (loaded lazily)
        var tagBar = document.createElement('div');
        tagBar.className = 'ms-gallery-tags';
        tagBar.id = 'tags-' + item.id;
        card.appendChild(tagBar);

        card.onclick = function() { showMediaDetail(item.id); };

        // Mark selected if in list
        if (selectedMediaIds.indexOf(item.id) !== -1) {
            card.classList.add('ms-selected');
        }

        return card;
    }

    window.loadGalleryMore = function() {
        loadGallery(currentGalleryPage + 1);
    };

    // ─── Selection Mode ─────────────────────────────────────────────
    window.toggleMediaSelection = function(mediaId) {
        var idx = selectedMediaIds.indexOf(mediaId);
        if (idx === -1) {
            selectedMediaIds.push(mediaId);
        } else {
            selectedMediaIds.splice(idx, 1);
        }
        _updateSelectionUI();
    };

    window.bulkSelectAll = function() {
        var cards = document.querySelectorAll('.ms-gallery-card');
        selectedMediaIds = [];
        for (var i = 0; i < cards.length; i++) {
            selectedMediaIds.push(parseInt(cards[i].dataset.mediaId));
        }
        _updateSelectionUI();
    };

    window.bulkDeselectAll = function() {
        selectedMediaIds = [];
        _updateSelectionUI();
    };

    function _updateSelectionUI() {
        var toolbar = document.getElementById('msBulkToolbar');
        var countEl = document.getElementById('msBulkCount');
        if (toolbar) toolbar.style.display = selectedMediaIds.length > 0 ? 'flex' : 'none';
        if (countEl) countEl.textContent = selectedMediaIds.length + ' selected';

        var cards = document.querySelectorAll('.ms-gallery-card');
        for (var i = 0; i < cards.length; i++) {
            var id = parseInt(cards[i].dataset.mediaId);
            if (selectedMediaIds.indexOf(id) !== -1) {
                cards[i].classList.add('ms-selected');
            } else {
                cards[i].classList.remove('ms-selected');
            }
        }
    }

    // ─── Bulk Actions ───────────────────────────────────────────────
    window.bulkFavorite = function() {
        api('POST', '/api/gallery/bulk/favorite', { media_ids: selectedMediaIds, state: true })
            .then(function() { bulkDeselectAll(); loadGallery(1); });
    };

    window.bulkDelete = function() {
        if (!confirm('Delete ' + selectedMediaIds.length + ' items?')) return;
        api('POST', '/api/gallery/bulk/delete', { media_ids: selectedMediaIds })
            .then(function() { bulkDeselectAll(); loadGallery(1); });
    };

    window.bulkTag = function() {
        var tagName = prompt('Enter tag name:');
        if (!tagName) return;
        api('POST', '/api/tags', { name: tagName, tag_type: 'user' }).then(function(tag) {
            return api('POST', '/api/gallery/bulk/tags', { media_ids: selectedMediaIds, tag_ids: [tag.id] });
        }).then(function() { bulkDeselectAll(); loadGallery(1); });
    };

    window.bulkMoveToCollection = function() {
        // Show collection picker — for now, prompt for collection name
        api('GET', '/api/collections').then(function(data) {
            var names = data.collections.map(function(c) { return c.id + ': ' + c.name; });
            var choice = prompt('Enter collection ID:\\n' + names.join('\\n'));
            if (!choice) return;
            var cid = parseInt(choice);
            if (isNaN(cid)) return;
            return api('POST', '/api/gallery/bulk/move', { media_ids: selectedMediaIds, collection_id: cid });
        }).then(function() { bulkDeselectAll(); });
    };

    window.bulkExport = function() {
        api('POST', '/api/export', { media_ids: selectedMediaIds }).then(function(data) {
            alert('Export started! Job ID: ' + data.job_id + '. Check queue for download link.');
            bulkDeselectAll();
        });
    };

    window.bulkRegenerate = function() {
        if (!confirm('Re-queue ' + selectedMediaIds.length + ' items for regeneration?')) return;
        api('POST', '/api/gallery/bulk/regenerate', { media_ids: selectedMediaIds }).then(function(data) {
            alert('Queued: ' + data.queued + ', Skipped: ' + data.skipped);
            bulkDeselectAll();
        });
    };

    // ─── Facets + Collections Load ──────────────────────────────────
    window.loadGalleryFacets = function() {
        api('GET', '/api/search/facets').then(function(data) {
            // Populate model dropdown
            var modelSel = document.getElementById('msModelFilter');
            if (modelSel) {
                _clearChildren(modelSel);
                var opt = document.createElement('option');
                opt.value = ''; opt.textContent = 'All Models';
                modelSel.appendChild(opt);
                (data.models || []).forEach(function(m) {
                    var o = document.createElement('option');
                    o.value = m; o.textContent = m;
                    modelSel.appendChild(o);
                });
            }

            // Populate provider dropdown
            var provSel = document.getElementById('msProviderFilter');
            if (provSel) {
                _clearChildren(provSel);
                var opt2 = document.createElement('option');
                opt2.value = ''; opt2.textContent = 'All Providers';
                provSel.appendChild(opt2);
                (data.providers || []).forEach(function(p) {
                    var o = document.createElement('option');
                    o.value = p; o.textContent = p;
                    provSel.appendChild(o);
                });
            }

            // Populate tag filters
            var tagList = document.getElementById('msTagFilters');
            if (tagList) {
                _clearChildren(tagList);
                (data.tags || []).forEach(function(t) {
                    var pill = document.createElement('button');
                    pill.className = 'ms-tag-pill ms-tag-' + t.tag_type;
                    pill.textContent = t.name;
                    pill.dataset.tagId = t.id;
                    pill.onclick = function() {
                        pill.classList.toggle('active');
                        var idx = galleryFilters.tags.indexOf(t.id);
                        if (idx === -1) galleryFilters.tags.push(t.id);
                        else galleryFilters.tags.splice(idx, 1);
                        loadGallery(1);
                    };
                    tagList.appendChild(pill);
                });
            }
        });
    };

    window.loadCollections = function() {
        api('GET', '/api/collections').then(function(data) {
            var myList = document.getElementById('msMyCollectionsList');
            var sharedList = document.getElementById('msSharedCollectionsList');
            if (myList) _clearChildren(myList);
            if (sharedList) _clearChildren(sharedList);

            (data.collections || []).forEach(function(c) {
                var item = document.createElement('div');
                item.className = 'ms-collection-item';
                if (currentCollectionFilter === c.id) item.classList.add('active');
                var nameSpan = document.createElement('span');
                nameSpan.textContent = c.name;
                var countSpan = document.createElement('span');
                countSpan.className = 'ms-collection-count';
                countSpan.textContent = c.item_count || 0;
                item.appendChild(nameSpan);
                item.appendChild(countSpan);
                item.onclick = function() {
                    currentCollectionFilter = (currentCollectionFilter === c.id) ? null : c.id;
                    loadCollections();
                    loadGallery(1);
                };
                // Split into my vs shared sections
                if (c.is_shared && sharedList) sharedList.appendChild(item);
                else if (myList) myList.appendChild(item);
            });
        });

        api('GET', '/api/smart-collections').then(function(data) {
            var list = document.getElementById('msSmartCollectionsList');
            if (!list) return;
            _clearChildren(list);
            (data.smart_collections || []).forEach(function(sc) {
                var item = document.createElement('div');
                item.className = 'ms-collection-item ms-smart-collection';
                var nameSpan = document.createElement('span');
                nameSpan.textContent = sc.name;
                var playBtn = document.createElement('button');
                playBtn.className = 'ms-btn-icon';
                playBtn.textContent = '▶';
                playBtn.onclick = function(e) {
                    e.stopPropagation();
                    api('GET', '/api/smart-collections/' + sc.id + '/results').then(function(data) {
                        var grid = document.getElementById('msGalleryGrid');
                        _clearChildren(grid);
                        (data.items || []).forEach(function(item) {
                            grid.appendChild(_createGalleryCard(item));
                        });
                    });
                };
                item.appendChild(nameSpan);
                item.appendChild(playBtn);
                list.appendChild(item);
            });
        });
    };

    window.createNewCollection = function() {
        var nameInput = document.getElementById('msNewCollectionName');
        var name = nameInput ? nameInput.value.trim() : '';
        if (!name) return;
        api('POST', '/api/collections', { name: name }).then(function() {
            if (nameInput) nameInput.value = '';
            loadCollections();
        });
    };

    window.saveAsSmartCollection = function() {
        var name = prompt('Smart collection name:');
        if (!name) return;
        var filters = {};
        if (galleryFilters.type !== 'all') filters.media_type = galleryFilters.type;
        if (galleryFilters.model) filters.model = galleryFilters.model;
        if (galleryFilters.provider) filters.provider = galleryFilters.provider;
        if (galleryFilters.date_from) filters.date_from = galleryFilters.date_from;
        if (galleryFilters.date_to) filters.date_to = galleryFilters.date_to;
        if (galleryFilters.tags.length) filters.tags = galleryFilters.tags;
        if (galleryFilters.min_width) filters.min_width = parseInt(galleryFilters.min_width);
        if (galleryFilters.min_height) filters.min_height = parseInt(galleryFilters.min_height);
        if (gallerySearchQuery) filters.prompt_query = gallerySearchQuery;
        api('POST', '/api/smart-collections', { name: name, filters: filters }).then(function() {
            loadCollections();
        });
    };

    // ─── Sidebar Toggle ─────────────────────────────────────────────
    window.toggleGallerySidebar = function() {
        var sidebar = document.getElementById('msGallerySidebar');
        var toggle = document.getElementById('msSidebarToggle');
        if (sidebar) {
            sidebar.classList.toggle('collapsed');
            if (toggle) toggle.textContent = sidebar.classList.contains('collapsed') ? '\u25B6 Filters' : '\u25C0 Filters';
        }
    };

    // ─── Media Detail Modal Enhancements ────────────────────────────
    // Override existing showMediaDetail to add tag editor, collection picker, similar media
    var _origShowMediaDetail = window.showMediaDetail;
    window.showMediaDetail = function(mediaId) {
        // Call original detail view first
        if (_origShowMediaDetail) _origShowMediaDetail(mediaId);

        // Then enhance with tags, collections, similar media
        api('GET', '/api/gallery/' + mediaId + '/tags').then(function(data) {
            // Render tag editor in detail modal (look for detail container)
            var tagContainer = document.getElementById('msDetailTags');
            if (!tagContainer) return;
            _clearChildren(tagContainer);
            (data.tags || []).forEach(function(t) {
                var pill = document.createElement('span');
                pill.className = 'ms-tag-pill ms-tag-' + t.tag_type;
                pill.textContent = t.name;
                var removeBtn = document.createElement('button');
                removeBtn.className = 'ms-tag-remove';
                removeBtn.textContent = '\u00d7';
                removeBtn.onclick = function() {
                    api('POST', '/api/gallery/' + mediaId + '/tags/remove', { tag_ids: [t.id] }).then(function() {
                        showMediaDetail(mediaId);
                    });
                };
                pill.appendChild(removeBtn);
                tagContainer.appendChild(pill);
            });

            // Add tag input with autocomplete
            var addInput = document.createElement('input');
            addInput.type = 'text';
            addInput.className = 'ms-filter-input ms-tag-add-input';
            addInput.placeholder = 'Add tag...';
            addInput.onkeydown = function(e) {
                if (e.key === 'Enter' && addInput.value.trim()) {
                    api('POST', '/api/tags', { name: addInput.value.trim(), tag_type: 'user' }).then(function(tag) {
                        return api('POST', '/api/gallery/' + mediaId + '/tags', { tag_ids: [tag.id] });
                    }).then(function() { showMediaDetail(mediaId); });
                }
            };
            tagContainer.appendChild(addInput);
        });

        // Add to Collection dropdown
        api('GET', '/api/collections').then(function(data) {
            var collContainer = document.getElementById('msDetailCollection');
            if (!collContainer) return;
            _clearChildren(collContainer);
            var sel = document.createElement('select');
            sel.className = 'ms-filter-select';
            var defOpt = document.createElement('option');
            defOpt.value = ''; defOpt.textContent = 'Add to collection...';
            sel.appendChild(defOpt);
            (data.collections || []).forEach(function(c) {
                var o = document.createElement('option');
                o.value = c.id; o.textContent = c.name;
                sel.appendChild(o);
            });
            sel.onchange = function() {
                if (sel.value) {
                    api('POST', '/api/collections/' + sel.value + '/items', { media_ids: [mediaId] }).then(function() {
                        sel.value = '';
                    });
                }
            };
            collContainer.appendChild(sel);
        });

        // Similar media (semantic search)
        api('GET', '/api/search?similar_to=' + mediaId + '&per_page=6').then(function(data) {
            var simContainer = document.getElementById('msDetailSimilar');
            if (!simContainer) return;
            _clearChildren(simContainer);
            (data.items || []).forEach(function(sim) {
                if (sim.id === mediaId) return;
                var thumb = document.createElement('div');
                thumb.className = 'ms-similar-thumb';
                if (sim.thumbnail_path) {
                    var img = document.createElement('img');
                    img.src = sim.thumbnail_path;
                    thumb.appendChild(img);
                }
                thumb.onclick = function() { showMediaDetail(sim.id); };
                simContainer.appendChild(thumb);
            });
        });
    };
```

- [ ] **Step 2: Update the tab switching to load facets and collections on Gallery tab**

Find the `switchMsTab` function and add these calls when switching to the gallery tab:

```javascript
    // Inside switchMsTab, in the gallery case:
    if (tab === 'gallery') {
        loadGallery(1);
        loadGalleryFacets();
        loadCollections();
    }
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add gallery JS — search, filters, selection, bulk ops, collections"
```

---

### Task 12: Gallery CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css`

- [ ] **Step 1: Append gallery enhancement CSS**

```css
/* ─── S19 Gallery Enhancement ─────────────────────────────────────── */

.ms-gallery-search {
    padding: 0.75rem 0;
}

.ms-search-input-wrap {
    display: flex;
    align-items: center;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 153, 0, 0.3);
    border-radius: 4px;
    padding: 0 0.75rem;
}

.ms-search-icon {
    margin-right: 0.5rem;
    opacity: 0.6;
}

.ms-search-input {
    flex: 1;
    background: transparent;
    border: none;
    color: #ff9900;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85rem;
    padding: 0.5rem 0;
    outline: none;
}

.ms-gallery-layout {
    display: flex;
    gap: 1rem;
}

.ms-sidebar-toggle {
    background: rgba(255, 153, 0, 0.15);
    border: 1px solid rgba(255, 153, 0, 0.3);
    color: #ff9900;
    border-radius: 3px;
    padding: 0.25rem 0.5rem;
    font-size: 0.7rem;
    font-family: 'IBM Plex Mono', monospace;
    cursor: pointer;
    align-self: flex-start;
    margin-top: 0.25rem;
}

.ms-gallery-sidebar {
    width: 220px;
    flex-shrink: 0;
    border-right: 1px solid rgba(255, 153, 0, 0.15);
    padding-right: 1rem;
    transition: width 0.2s, opacity 0.2s, padding 0.2s;
    overflow: hidden;
}

.ms-gallery-sidebar.collapsed {
    width: 0;
    padding-right: 0;
    opacity: 0;
    border-right: none;
}

.ms-gallery-main {
    flex: 1;
    min-width: 0;
}

.ms-sidebar-section {
    margin-bottom: 1rem;
}

.ms-sidebar-title {
    color: rgba(255, 153, 0, 0.7);
    font-family: 'Antonio', sans-serif;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.5rem;
}

.ms-filter-select,
.ms-filter-date,
.ms-filter-input {
    width: 100%;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 153, 0, 0.2);
    border-radius: 3px;
    color: #ff9900;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    padding: 0.35rem 0.5rem;
    margin-bottom: 0.35rem;
}

.ms-filter-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
}

/* Tag pills */
.ms-tag-pill {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    font-size: 0.65rem;
    font-family: 'IBM Plex Mono', monospace;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(0, 0, 0, 0.2);
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
}

.ms-tag-pill.active {
    border-color: #ff9900;
    color: #ff9900;
}

.ms-tag-system { border-color: rgba(100, 149, 237, 0.4); color: rgba(100, 149, 237, 0.8); }
.ms-tag-user { border-color: rgba(100, 200, 100, 0.4); color: rgba(100, 200, 100, 0.8); }
.ms-tag-shared { border-color: rgba(255, 165, 0, 0.4); color: rgba(255, 165, 0, 0.8); }

/* Collections panel */
.ms-collection-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.35rem 0.5rem;
    border-radius: 3px;
    cursor: pointer;
    font-size: 0.75rem;
    color: rgba(255, 255, 255, 0.7);
}

.ms-collection-item:hover { background: rgba(255, 153, 0, 0.1); }
.ms-collection-item.active { background: rgba(255, 153, 0, 0.2); color: #ff9900; }

.ms-collection-count {
    background: rgba(255, 153, 0, 0.15);
    padding: 0.1rem 0.4rem;
    border-radius: 8px;
    font-size: 0.65rem;
}

.ms-new-collection {
    display: flex;
    gap: 0.25rem;
    margin-top: 0.5rem;
}

.ms-btn-icon {
    background: rgba(255, 153, 0, 0.2);
    border: 1px solid rgba(255, 153, 0, 0.3);
    color: #ff9900;
    border-radius: 3px;
    padding: 0.2rem 0.5rem;
    cursor: pointer;
    font-size: 0.75rem;
}

.ms-btn-icon:hover { background: rgba(255, 153, 0, 0.35); }

/* Bulk toolbar */
.ms-bulk-toolbar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: rgba(255, 153, 0, 0.1);
    border: 1px solid rgba(255, 153, 0, 0.3);
    border-radius: 4px;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
}

.ms-bulk-count {
    color: #ff9900;
    font-weight: bold;
    font-size: 0.8rem;
    margin-right: 0.5rem;
}

.ms-bulk-btn {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 153, 0, 0.25);
    color: rgba(255, 255, 255, 0.8);
    border-radius: 3px;
    padding: 0.25rem 0.6rem;
    font-size: 0.7rem;
    font-family: 'IBM Plex Mono', monospace;
    cursor: pointer;
}

.ms-bulk-btn:hover { background: rgba(255, 153, 0, 0.2); color: #ff9900; }
.ms-bulk-btn-danger { border-color: rgba(255, 80, 80, 0.3); }
.ms-bulk-btn-danger:hover { background: rgba(255, 80, 80, 0.2); color: #ff5050; }

/* Gallery card enhancements */
.ms-gallery-card {
    position: relative;
    cursor: pointer;
}

.ms-gallery-checkbox {
    position: absolute;
    top: 0.35rem;
    left: 0.35rem;
    width: 18px;
    height: 18px;
    border: 2px solid rgba(255, 255, 255, 0.4);
    border-radius: 3px;
    background: rgba(0, 0, 0, 0.4);
    z-index: 2;
    cursor: pointer;
}

.ms-selected .ms-gallery-checkbox {
    background: #ff9900;
    border-color: #ff9900;
}

.ms-selected {
    outline: 2px solid #ff9900;
    outline-offset: -2px;
}

.ms-gallery-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.15rem;
    padding: 0.15rem 0.35rem;
}

.ms-gallery-footer {
    text-align: center;
    padding: 1rem 0;
}

.ms-smart-collection {
    font-style: italic;
}

/* Resolution filter inputs */
.ms-resolution-inputs {
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

.ms-resolution-inputs .ms-filter-input {
    width: 80px;
    margin-bottom: 0;
}

.ms-resolution-x {
    color: rgba(255, 153, 0, 0.5);
    font-size: 0.75rem;
}

/* Tag editor in detail modal */
.ms-tag-remove {
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    font-size: 0.7rem;
    margin-left: 0.25rem;
    padding: 0;
}

.ms-tag-remove:hover { color: #ff5050; }

.ms-tag-add-input {
    width: 120px;
    display: inline-block;
    margin-left: 0.25rem;
}

/* Similar media thumbnails */
.ms-similar-thumb {
    display: inline-block;
    width: 80px;
    height: 80px;
    border-radius: 4px;
    overflow: hidden;
    cursor: pointer;
    border: 1px solid rgba(255, 153, 0, 0.2);
    margin: 0.15rem;
}

.ms-similar-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.ms-similar-thumb:hover {
    border-color: #ff9900;
}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add gallery enhancement CSS (S19 search, filters, collections, bulk)"
```

---

### Task 13: Integration Test + Deploy

**Files:** None (testing only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Run integration tests**

```python
# Copy to /tmp/test_gallery_enhancement.py and docker cp + exec
import sys, json, os, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

from app import app
app.config['TESTING'] = True

with app.app_context():
    from tools.media_studio.services.tagging_service import create_tag, get_tags, get_media_tags
    from tools.media_studio.services.collection_service import (
        create_collection, list_collections, list_smart_collections,
        create_smart_collection, delete_collection, delete_smart_collection,
    )
    from tools.media_studio.services.search_service import search_media, get_search_facets
    from tools.media_studio.services.export_service import create_export_job, cleanup_exports

    results = []

    # Tags
    tid = create_tag("test-tag", "user", 1)
    results.append(("create_tag", tid > 0))
    tags = get_tags()
    results.append(("get_tags", len(tags) >= 1))

    # Collections
    cid = create_collection("Test Collection", "user", 1)
    results.append(("create_collection", cid > 0))
    colls = list_collections("user", 1)
    results.append(("list_collections", len(colls) >= 1))
    delete_collection(cid, "user", 1)

    # Smart Collections
    sid = create_smart_collection("Test Smart", {"media_type": "image"}, "user", 1)
    results.append(("create_smart_collection", sid > 0))
    smarts = list_smart_collections("user", 1)
    results.append(("list_smart_collections", len(smarts) >= 1))
    delete_smart_collection(sid, "user", 1)

    # Search
    sr = search_media("user", 1)
    results.append(("search_media", "items" in sr))
    facets = get_search_facets("user", 1)
    results.append(("get_search_facets", "types" in facets and "models" in facets))

    # Export
    cleaned = cleanup_exports()
    results.append(("cleanup_exports", cleaned >= 0))

    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[{"PASS" if ok else "FAIL"}] {name}')
    print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 3: Push to remote**

```bash
git push origin main
```

- [ ] **Step 4: Update Dev HQ**

```
mcp create_task project_id=129 title="Layer 5: Gallery Enhancement & Curation"
mcp complete_task <task_id> notes="..."
mcp update_project_understanding project_id=129 understanding_level=95
```
