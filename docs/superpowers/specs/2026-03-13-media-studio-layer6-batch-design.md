# Media Studio Layer 6: Batch Generation & Queue Management — Design Spec

**Goal:** Add batch generation (multi-prompt + single-dimension parameter sweep) and queue management (panel UI, retry/cancel, APScheduler cleanup) to the Media Studio.

**Architecture:** One new service file (`batch_service.py`) handles batch creation/expansion, status tracking, queue management, and cleanup. One migration adds the `media_batches` table and a `batch_id` FK on `media_generation_queue`. Queue panel is a collapsible section in the Gallery tab. Batch creation is a modal triggered from each media type tab. Two APScheduler jobs handle hourly cleanup.

**Tech Stack:** PostgreSQL, Flask routes, APScheduler, LCARS UI with IIFE JS pattern.

---

## Database Schema (Migration 152)

### `media_batches` — groups queue entries into a single user action

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | VARCHAR(200) | Auto-generated or user-provided |
| owner_type | VARCHAR(20) NOT NULL | `user` or `agent` |
| owner_id | INTEGER NOT NULL | |
| media_type | VARCHAR(20) NOT NULL | `image`, `video`, `audio` |
| base_params | JSONB NOT NULL | Shared params (model, size, negative_prompt, etc.) |
| sweep_param | VARCHAR(50) | Which param varies: `seed`, `model`, `prompt`, or NULL |
| sweep_values | JSONB | Array of sweep values, e.g., `[42, 123, 777, 999]` |
| total_items | INTEGER NOT NULL | Pre-computed count |
| completed_items | INTEGER DEFAULT 0 | Incremented on each completion |
| failed_items | INTEGER DEFAULT 0 | Incremented on each failure |
| status | VARCHAR(20) DEFAULT 'pending' | `pending`, `running`, `completed`, `partial`, `cancelled` |
| created_at | TIMESTAMPTZ DEFAULT now() | |
| completed_at | TIMESTAMPTZ | Set when all items finish |

Index: `idx_media_batches_owner` on `(owner_type, owner_id)`, `idx_media_batches_status` on `(status)`.

**Status transitions:**
- `pending` — all items still pending (just created)
- `running` — at least one item dispatched
- `completed` — all items completed successfully
- `partial` — all items done but some failed
- `cancelled` — user cancelled remaining items

### New column on `media_generation_queue`

- `batch_id INTEGER REFERENCES media_batches(id) ON DELETE SET NULL`
- NULL for single generations, set for batch items
- Index: `idx_media_queue_batch` on `(batch_id)`

---

## Service

### `batch_service.py` (~200 lines)

#### Batch Creation

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `create_batch` | name, owner_type, owner_id, media_type, prompts, base_params, sweep_param=None, sweep_values=None | batch_id | Validates, creates batch row, calls expand_batch, dispatches all items |
| `expand_batch` | batch_id, prompts, base_params, media_type, owner_type, owner_id, sweep_param, sweep_values | list[queue_ids] | Internal — generates combinations and inserts into media_generation_queue via submit_generation() |

**Expansion logic:**
- If `sweep_param` is NULL: one queue entry per prompt (N prompts = N items)
- If `sweep_param` is `seed`: each prompt x each seed value (N prompts x M seeds)
- If `sweep_param` is `model`: each prompt x each model (N prompts x M models)
- **Cap: 50 items max per batch.** Reject with error if expansion exceeds 50.

Each expanded entry calls `submit_generation()` from generation_service.py with the merged params and gets `batch_id` set on the resulting queue entry.

**Auto-naming:** If `name` is empty, auto-generate from first prompt truncated to 50 chars + sweep summary. E.g., "A space battle scene... x 4 seeds".

#### Batch Status

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `get_batch` | batch_id, owner_type, owner_id | dict | Batch row with all fields |
| `list_batches` | owner_type, owner_id, status=None, page=1, per_page=10 | paginated dict | User's batches, optionally filtered by status |
| `get_batch_items` | batch_id, owner_type, owner_id | list[dict] | All queue entries for this batch, LEFT JOIN media_library for thumbnails |
| `update_batch_counters` | batch_id | None | COUNT completed/failed from queue entries, update batch row, set batch status accordingly |

**`update_batch_counters` status logic:**
- If any item is dispatched/pending → `running`
- If all items done and failed_items == 0 → `completed`
- If all items done and failed_items > 0 → `partial`
- Sets `completed_at` when transitioning to `completed` or `partial`

#### Queue Management

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `cancel_batch` | batch_id, owner_type, owner_id | int (cancelled count) | Sets pending/dispatched queue entries to `cancelled`, updates batch status |
| `retry_batch_failed` | batch_id, owner_type, owner_id | int (retried count) | Re-submits failed entries via `submit_generation()`, resets batch counters |
| `retry_single` | queue_id, owner_type, owner_id | bool | Retry one failed queue entry |
| `cancel_single` | queue_id, owner_type, owner_id | bool | Cancel one pending/dispatched entry |
| `get_queue_entries` | owner_type, owner_id, status=None, page=1, per_page=20 | paginated dict | All queue entries for user, filterable by status |
| `get_queue_stats` | owner_type, owner_id | dict | Counts by status + avg_duration_ms for completed items |
| `clear_completed` | owner_type, owner_id | int (cleared count) | Deletes completed queue entries older than 1 hour |
| `cleanup_stale_queue` | max_age_hours=24 | int (cleaned count) | Deletes completed/failed/cancelled entries older than max_age. Called by APScheduler. |
| `cleanup_expired_exports` | | int (cleaned count) | Wraps `export_service.cleanup_exports()`. Called by APScheduler. |

---

## API Routes (10 new endpoints)

### Batches

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| POST | `/api/batches` | `{name?, media_type, prompts: [...], base_params: {...}, sweep_param?, sweep_values?: [...]}` | `{batch_id, total_items}` 201 |
| GET | `/api/batches` | `?status=running&page=1&per_page=10` | `{batches: [...], total, page, pages}` |
| GET | `/api/batches/<id>` | | `{batch: {...}, items: [...]}` |
| POST | `/api/batches/<id>/cancel` | | `{cancelled: N}` |
| POST | `/api/batches/<id>/retry` | | `{retried: N}` |

### Queue Management

| Method | Path | Body/Params | Returns |
|--------|------|-------------|---------|
| GET | `/api/queue` | `?status=failed&page=1&per_page=20` | `{items: [...], total, page, pages}` |
| POST | `/api/queue/<id>/retry` | | `{status: "retried"}` |
| POST | `/api/queue/<id>/cancel` | | `{status: "cancelled"}` |
| GET | `/api/queue/stats` | | `{pending: N, running: N, completed: N, failed: N, avg_duration_ms: N}` |
| POST | `/api/queue/clear-completed` | | `{cleared: N}` |

All routes use `owner_type="user"` and `owner_id=current_user.id` from the route layer.

---

## APScheduler Jobs

Registered in `__init__.py` during blueprint initialization.

| Job ID | Schedule | Function | Notes |
|--------|----------|----------|-------|
| `media_queue_cleanup` | `trigger='interval', hours=1` | `batch_service.cleanup_stale_queue(max_age_hours=24)` | Deletes old completed/failed/cancelled queue entries |
| `media_export_cleanup` | `trigger='interval', hours=1` | `batch_service.cleanup_expired_exports()` | Deletes expired ZIP exports via export_service |

Both use `misfire_grace_time=300`. Jobs run inside `app.app_context()`.

---

## Generation Service Hook

In `on_generation_complete()`, after the existing auto_tag + embed_prompt hooks (added in Layer 5):

```python
# Update batch counters if this is a batch item
if queue_entry.get("batch_id"):
    try:
        from .batch_service import update_batch_counters
        update_batch_counters(queue_entry["batch_id"])
    except Exception:
        logger.warning("batch counter update failed for queue %s", queue_id)
```

Same pattern needed for failure handling — if a queue entry transitions to `failed`, also call `update_batch_counters`.

---

## UI Changes (Gallery Tab)

### Queue Panel (collapsible, above gallery grid)

Toggle button in Gallery tab header: "Queue (N active)" with count badge. Collapsed by default.

**When expanded, three sections:**

1. **Active generations** — cards with spinner, prompt snippet (truncated 60 chars), media type icon, elapsed time (live-updating). Batch items grouped under collapsible batch header: "Space battle (7/10)" with progress bar.

2. **Failed items** — red-highlighted cards with error message, individual "Retry" button. Batch failures show "Retry All Failed" on the batch group header.

3. **Recent completions** — last 5 completed items with thumbnail preview. Auto-dismissed after 30 seconds.

**Controls:**
- "Clear Completed" button — calls `POST /api/queue/clear-completed`
- Stats badge in panel header: "2 active / 1 failed / 47 completed today"
- Cancel button on individual pending items and on batch groups

**Polling:** Queue panel polls `GET /api/queue/stats` every 5 seconds when expanded. Full item list refreshes every 10 seconds. Polling stops when panel is collapsed.

### Batch Creation Modal

Triggered from a "Batch" button next to existing "Generate" button on each media type tab (Image, Video, Audio).

**Modal layout:**
- **Batch name** — optional text input, placeholder "Auto-generated from first prompt"
- **Prompts textarea** — one per line, live line count: "3 prompts"
- **Sweep section** — toggle off by default. When toggled on:
  - Sweep parameter dropdown: `Seed` / `Model`
  - If Seed: text input for comma-separated values (e.g., "42, 123, 777")
  - If Model: checkboxes populated from available models (reuse existing model dropdown data)
- **Shared params** — same controls as single generation (model selector, size, negative prompt, etc.). Hidden when sweep_param is `model` (models come from sweep values instead).
- **Preview line** — "This will create **N** generations" — updates live. Turns red if >50: "Maximum 50 per batch"
- **Submit button** — "Start Batch" — disabled if >50 items or 0 prompts

### Queue Panel JS Functions

| Function | Purpose |
|----------|---------|
| `toggleQueuePanel()` | Show/hide queue panel, start/stop polling |
| `loadQueueStats()` | Fetch stats, update badge |
| `loadQueueItems()` | Fetch active + failed + recent items, render cards |
| `submitBatch()` | Collect modal form → POST /api/batches |
| `cancelQueueItem(id)` | POST /api/queue/<id>/cancel, refresh |
| `retryQueueItem(id)` | POST /api/queue/<id>/retry, refresh |
| `cancelBatch(id)` | POST /api/batches/<id>/cancel, refresh |
| `retryBatchFailed(id)` | POST /api/batches/<id>/retry, refresh |
| `clearCompleted()` | POST /api/queue/clear-completed, refresh |
| `openBatchModal(mediaType)` | Open batch modal pre-set to media type |

---

## Files Summary

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/152_batch_generation.sql` | `media_batches` table + `batch_id` column on queue |
| Create | `services/batch_service.py` | Batch creation, expansion, status, queue mgmt, cleanup |
| Modify | `services/generation_service.py` | Hook `update_batch_counters` in completion/failure callbacks |
| Modify | `routes.py` | 10 new API endpoints (batches + queue) |
| Modify | `__init__.py` | Register 2 APScheduler cleanup jobs |
| Modify | `templates/.../media_studio.html` | Queue panel + batch creation modal + JS |
| Modify | `static/css/media-studio.css` | Queue panel + batch modal styles |
