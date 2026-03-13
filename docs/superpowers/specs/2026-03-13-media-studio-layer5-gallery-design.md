# Media Studio Layer 5: Gallery Enhancement & Curation — Design Spec

**Goal:** Add tagging, collections, semantic search, faceted filtering, bulk operations, and ZIP export to the Media Studio gallery.

**Architecture:** Split-service approach — 4 new service files (tagging, collection, search, export) alongside the existing gallery_service.py. One migration adds 5 tables + 1 embedding column. UI changes are scoped to the Gallery tab only. Embeddings reuse the existing nomic-embed-text infrastructure.

**Tech Stack:** PostgreSQL (pgvector if available, JSONB fallback), nomic-embed-text via embedding_service.py, Flask routes, LCARS UI with IIFE JS pattern.

---

## Database Schema (Migration 151)

### `media_tags` — tag definitions

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | VARCHAR(100) UNIQUE | Tag display name |
| tag_type | VARCHAR(20) NOT NULL | `user`, `system`, or `shared` |
| created_by | INTEGER | user_id for user tags, NULL for system |
| created_at | TIMESTAMPTZ | DEFAULT now() |

Index: `idx_media_tags_type` on `(tag_type)`.

### `media_tag_map` — many-to-many media ↔ tags

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| media_id | INTEGER FK→media_library | ON DELETE CASCADE |
| tag_id | INTEGER FK→media_tags | ON DELETE CASCADE |

Unique constraint: `(media_id, tag_id)`.
Index: `idx_media_tag_map_media` on `(media_id)`, `idx_media_tag_map_tag` on `(tag_id)`.

### `media_collections` — named groups

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | VARCHAR(200) NOT NULL | |
| description | TEXT | |
| owner_type | VARCHAR(20) NOT NULL | `user` or `agent` |
| owner_id | INTEGER | |
| is_shared | BOOLEAN DEFAULT false | Visible to all users |
| cover_media_id | INTEGER FK→media_library | Optional cover image |
| created_at | TIMESTAMPTZ | DEFAULT now() |
| updated_at | TIMESTAMPTZ | DEFAULT now() |

Index: `idx_media_collections_owner` on `(owner_type, owner_id)`.

### `media_collection_items` — collection membership

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| collection_id | INTEGER FK→media_collections | ON DELETE CASCADE |
| media_id | INTEGER FK→media_library | ON DELETE CASCADE |
| sort_order | INTEGER DEFAULT 0 | Manual ordering within collection |
| added_at | TIMESTAMPTZ | DEFAULT now() |

Unique constraint: `(collection_id, media_id)`.
Index: `idx_media_collection_items_coll` on `(collection_id, sort_order)`.

### `media_smart_collections` — saved filter presets

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | VARCHAR(200) NOT NULL | |
| owner_type | VARCHAR(20) NOT NULL | |
| owner_id | INTEGER | |
| filters | JSONB NOT NULL | Stores all filter criteria |
| created_at | TIMESTAMPTZ | DEFAULT now() |

Index: `idx_media_smart_collections_owner` on `(owner_type, owner_id)`.

**Filters JSONB structure:**
```json
{
  "media_type": "image",
  "tags": [1, 3, 7],
  "model": "sdxl",
  "provider": "local",
  "date_from": "2026-01-01",
  "date_to": "2026-03-13",
  "prompt_query": "space battle",
  "min_width": 1024,
  "min_height": 1024
}
```

### New column on `media_library`

- `prompt_embedding VECTOR(768)` if pgvector available, else `JSONB` fallback
- Index: `idx_media_library_prompt_emb` using ivfflat (pgvector) or GIN (JSONB)

Migration checks for pgvector with `CREATE EXTENSION IF NOT EXISTS vector` and falls back gracefully.

**pgvector vs JSONB fallback:** pgvector is required for production semantic search. The JSONB fallback is for dev/small datasets only — capped at 5,000 rows for semantic queries. If the media_library exceeds 5,000 rows without pgvector, `semantic_search()` logs a warning and returns empty results. Text search and faceted filters always work regardless.

---

## Services

### `tagging_service.py` (~120 lines)

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `create_tag` | name, tag_type, created_by | tag_id | Upsert — returns existing if name matches |
| `get_tags` | tag_type=None | list[dict] | All tags, optionally filtered |
| `tag_media` | media_id, tag_ids, owner_type, owner_id | None | Ownership check on media_id |
| `untag_media` | media_id, tag_ids, owner_type, owner_id | None | Ownership check |
| `get_media_tags` | media_id | list[dict] | Tags on a single item |
| `auto_tag` | media_id, params | None | Creates system tags from model/provider/resolution/media_type |
| `bulk_tag` | media_ids, tag_ids, owner_type, owner_id | int (count tagged) | Batch insert with ownership check |

**Auto-tag extraction rules:**
- Media type → tag `image`, `video`, or `audio`
- Model name → tag matching model string (e.g. `sdxl`, `sd15`, `animatediff`, `xtts-v2`)
- Provider → `local`, `comfyui`, or `external`
- Resolution bucket → `512x512`, `768x768`, `1024x1024`, `landscape`, `portrait`, `square`
- Audio mode → `speech`, `sfx`, `music` (if audio media_type)

All auto-tags use `tag_type='system'`, created on first use, reused thereafter.

### `collection_service.py` (~150 lines)

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `create_collection` | name, description, owner_type, owner_id, is_shared | collection_id | |
| `update_collection` | collection_id, owner_type, owner_id, **fields | bool | Rename, cover, shared toggle |
| `delete_collection` | collection_id, owner_type, owner_id | bool | Deletes collection, not media |
| `list_collections` | owner_type, owner_id, include_shared=True | list[dict] | User's + shared, with item counts |
| `add_to_collection` | collection_id, media_ids, owner_type, owner_id | int (count added) | Bulk add, ownership check |
| `remove_from_collection` | collection_id, media_ids, owner_type, owner_id | int (count removed) | |
| `get_collection_items` | collection_id, owner_type, owner_id, page, per_page | paginated dict | Same format as gallery |
| `create_smart_collection` | name, filters, owner_type, owner_id | smart_id | |
| `delete_smart_collection` | smart_id, owner_type, owner_id | bool | |
| `list_smart_collections` | owner_type, owner_id | list[dict] | |
| `execute_smart_collection` | smart_id, owner_type, owner_id, page, per_page | paginated dict | Builds query from saved filters |

### `search_service.py` (~130 lines)

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `search_media` | owner_type, owner_id, query, filters, page, per_page | paginated dict | Main entry: text + faceted + semantic |
| `embed_prompt` | media_id, prompt | bool | Generate + store nomic-embed-text vector |
| `semantic_search` | query_text, owner_type, owner_id, limit | list[dict] | Cosine similarity on prompt_embedding |
| `get_search_facets` | owner_type, owner_id | dict | Distinct models, providers, types, tags |

**Search blending:**
1. If `query` provided and embeddings exist → run both ILIKE and semantic search
2. Semantic results get similarity score (0.0–1.0)
3. Text matches get 1.0 (exact) or 0.8 (partial ILIKE)
4. Merge by media_id, take max score, sort descending
5. Apply faceted filters as SQL WHERE clauses on top

**Embedding pipeline:**
- Uses `ai_bridge/embedding_service.py` with nomic-embed-text (768-dim)
- Called after generation completes (in generation_service, after media_library INSERT)
- pgvector cosine distance: `prompt_embedding <=> %s` operator
- JSONB fallback: load vectors in Python, compute cosine similarity — dev/small datasets only, capped at 5,000 rows (returns empty if exceeded)

### `export_service.py` (~100 lines)

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `create_export_job` | media_ids, owner_type, owner_id | job_id | Validates ALL media_ids belong to owner, creates Bridge job |
| `generate_zip` | job_id, media_ids | file_path | Reads files, creates ZIP in MEDIA_ROOT/exports/ |
| `get_export_status` | job_id, owner_type, owner_id | dict | Status + download URL when complete |
| `cleanup_exports` | max_age_hours=1 | int (deleted) | APScheduler calls this hourly |

ZIP is generated as a background Bridge job. File saved to `MEDIA_ROOT/exports/export_{job_id}.zip`. Cleanup runs hourly via APScheduler to delete exports older than 1 hour.

---

## API Routes (25 new endpoints)

### Tags

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| GET | `/api/tags` | `?type=user\|system\|shared` | `{tags: [...]}` |
| POST | `/api/tags` | `{name, tag_type}` | `{id, name, tag_type}` 201 |
| POST | `/api/gallery/<media_id>/tags` | `{tag_ids: [...]}` | `{status: "tagged"}` |
| POST | `/api/gallery/<media_id>/tags/remove` | `{tag_ids: [...]}` | `{status: "untagged"}` |
| POST | `/api/gallery/bulk/tags` | `{media_ids: [...], tag_ids: [...]}` | `{count: N}` |

### Collections

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| GET | `/api/collections` | `?include_shared=true` | `{collections: [...]}` |
| POST | `/api/collections` | `{name, description, is_shared}` | `{id, name}` 201 |
| PUT | `/api/collections/<id>` | `{name?, description?, is_shared?, cover_media_id?}` | `{status: "updated"}` |
| DELETE | `/api/collections/<id>` | | `{status: "deleted"}` |
| GET | `/api/collections/<id>/items` | `?page=1&per_page=20` | paginated items |
| POST | `/api/collections/<id>/items` | `{media_ids: [...]}` | `{count: N}` 201 |
| POST | `/api/collections/<id>/items/remove` | `{media_ids: [...]}` | `{count: N}` |

### Smart Collections

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| GET | `/api/smart-collections` | | `{smart_collections: [...]}` |
| POST | `/api/smart-collections` | `{name, filters: {...}}` | `{id, name}` 201 |
| DELETE | `/api/smart-collections/<id>` | | `{status: "deleted"}` |
| GET | `/api/smart-collections/<id>/results` | `?page=1&per_page=20` | paginated items |

### Search

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| GET | `/api/search` | `?q=...&type=...&model=...&tags=1,2&date_from=...&date_to=...` | paginated items with scores |
| GET | `/api/search/facets` | | `{models: [...], providers: [...], types: [...], tags: [...]}` |

### Bulk Operations

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| POST | `/api/gallery/bulk/favorite` | `{media_ids: [...], state: bool}` | `{count: N}` |
| POST | `/api/gallery/bulk/delete` | `{media_ids: [...]}` | `{count: N}` |
| POST | `/api/gallery/bulk/move` | `{media_ids: [...], collection_id: int}` | `{count: N}` |
| POST | `/api/gallery/bulk/reassign` | `{media_ids: [...], owner_type, owner_id}` | `{count: N}` | **Admin only** |
| POST | `/api/gallery/bulk/regenerate` | `{media_ids: [...]}` | `{queued: N}` |

**`bulk/reassign`**: Admin-only endpoint (checks `current_user.is_admin`). Transfers media ownership to a different owner_type/owner_id.

**`bulk/regenerate`**: Re-queues each media item with its original generation params (read from `media_library.metadata` + prompt/model/seed columns). Creates new `media_generation_queue` entries and new `media_library` rows on completion — does NOT overwrite originals. Works for all media types (image, video, audio). Items without stored params are skipped (count returned separately as `skipped`).

### Export

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| POST | `/api/export` | `{media_ids: [...]}` | `{job_id: N}` 201 |
| GET | `/api/export/<job_id>` | | `{status, download_url?}` |

All routes use `owner_type="user"` and `owner_id=current_user.id` from the route layer. Export validates all `media_ids` belong to the requesting user before creating the job.

---

## UI Changes (Gallery Tab Only)

### Search Bar
- Text input at top of Gallery tab with search icon
- Debounced (300ms) → `GET /api/search?q=...`
- Results replace gallery grid, blending text + semantic matches

### Filter Sidebar (collapsible, left of gallery grid)
- Media type pills: All / Image / Video / Audio
- Tags multi-select grouped by type (system=blue, user=green, shared=orange)
- Model dropdown (populated from `/api/search/facets`)
- Provider dropdown
- Date range (from/to inputs)
- Resolution filter (min width/height)
- "Save as Smart Collection" button

### Selection Mode
- Checkbox overlay on gallery cards (click to toggle, shift+click for range)
- Bulk action toolbar appears when >=1 item selected:
  - Select All / Deselect All
  - Tag | Favorite | Move to Collection | Delete | Export ZIP | Regenerate
  - Item count badge ("12 selected")

### Collections Panel (sidebar section)
- "My Collections" list with item counts
- "Shared Collections" section
- "Smart Collections" with play icon to execute
- "+ New Collection" inline name input
- Click collection → filter gallery to its items

### Tag Pills on Gallery Cards
- Small colored badges on thumbnails
- System tags: blue, User tags: green, Shared tags: orange

### Media Detail Modal Enhancements
- Tag editor: add/remove tags inline with autocomplete
- "Add to Collection" dropdown
- "Similar Media" section: 4-6 semantic search results as thumbnails

---

## Embedding Pipeline

- **Model:** nomic-embed-text via `ai_bridge/embedding_service.py` (768-dim vectors)
- **Trigger:** After generation completes, in `generation_service.py` after `create_media_entry()`
- **Storage:** `media_library.prompt_embedding` — `VECTOR(768)` with pgvector, `JSONB` fallback
- **Similarity:** pgvector cosine distance operator `<=>`, or Python cosine for JSONB fallback
- **Backfill:** Out of scope for Layer 5 (no existing media data yet). When media accumulates, a one-time backfill script can be added as a follow-up task.

## Auto-tagging

- Called automatically after generation completes, same hook as embedding
- Extracts tags from generation params (no LLM inference, zero cost):
  - media_type, model name, provider, resolution bucket, audio mode
- Creates `tag_type='system'` tags on first use, reuses thereafter

## Export Pipeline

- User selects media → clicks Export ZIP → `POST /api/export`
- Creates a Bridge background job
- Worker calls `generate_zip()` — reads files, creates ZIP in `MEDIA_ROOT/exports/`
- Frontend polls `GET /api/export/<job_id>` until complete
- Download URL returned, valid for 1 hour
- APScheduler cleanup job deletes expired exports hourly

---

## Files Summary

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/151_gallery_enhancement.sql` | 5 tables + embedding column |
| Create | `services/tagging_service.py` | Tag CRUD + auto-tagging |
| Create | `services/collection_service.py` | Collections + smart collections |
| Create | `services/search_service.py` | Faceted + semantic search |
| Create | `services/export_service.py` | ZIP export background jobs |
| Modify | `services/generation_service.py` | Hook auto_tag + embed_prompt after generation |
| Modify | `routes.py` | 25 new API endpoints |
| Modify | `templates/.../media_studio.html` | Gallery tab UI overhaul |
| Modify | `static/css/media-studio.css` | New gallery component styles |
