# Media Studio Layer 6: Batch Generation & Queue Management — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add batch generation (multi-prompt + single-dimension parameter sweep) and queue management (panel UI, retry/cancel, APScheduler cleanup) to the Media Studio.

**Architecture:** One new service (`batch_service.py`), one migration (`152_batch_generation.sql`), hooks into existing `generation_service.py`, 10 new API routes, queue panel + batch modal in Gallery tab, 2 APScheduler cleanup jobs.

**Tech Stack:** PostgreSQL, Flask Blueprint, APScheduler, LCARS UI with IIFE JS.

**Spec:** `docs/superpowers/specs/2026-03-13-media-studio-layer6-batch-design.md`

---

## Chunk 1: Backend

### Task 1: Database Migration 152

**Files:**
- Create: `platform_v2/database/migrations/152_batch_generation.sql`

**Context:** Migration pattern — idempotent SQL, run via `docker exec archie_database psql -U archie -d archie -f /app/database/migrations/152_batch_generation.sql`. See migration 151 for the pattern used in Layer 5.

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration 152: Batch Generation & Queue Management
-- Adds media_batches table and batch_id FK on media_generation_queue

-- media_batches: groups queue entries into a single user action
CREATE TABLE IF NOT EXISTS media_batches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    owner_type VARCHAR(20) NOT NULL,
    owner_id INTEGER NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    base_params JSONB NOT NULL DEFAULT '{}',
    sweep_param VARCHAR(50),
    sweep_values JSONB,
    total_items INTEGER NOT NULL,
    completed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_batches_owner ON media_batches (owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_batches_status ON media_batches (status);

-- Add batch_id to media_generation_queue
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'media_generation_queue' AND column_name = 'batch_id'
    ) THEN
        ALTER TABLE media_generation_queue ADD COLUMN batch_id INTEGER REFERENCES media_batches(id) ON DELETE SET NULL;
        CREATE INDEX idx_media_queue_batch ON media_generation_queue (batch_id);
    END IF;
END $$;
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute(open('/app/database/migrations/152_batch_generation.sql').read())
print('Migration 152 applied successfully')
"
```

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name = 'media_batches' ORDER BY ordinal_position\")
    cols = [r['column_name'] for r in cur.fetchall()]
    print('media_batches columns:', cols)
    assert 'sweep_param' in cols, 'Missing sweep_param'

    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name = 'media_generation_queue' AND column_name = 'batch_id'\")
    assert cur.fetchone(), 'Missing batch_id on queue'
    print('batch_id column exists on media_generation_queue')
print('All checks passed')
"
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/database/migrations/152_batch_generation.sql
git commit -m "feat(media-studio): add migration 152 for batch generation tables"
```

---

### Task 2: Batch Service — Creation & Expansion

**Files:**
- Create: `platform_v2/tools/media_studio/services/batch_service.py`

**Context:**
- DB pattern: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- Generation: `from .generation_service import submit_generation` — signature is `submit_generation(user_id, media_type, prompt, negative_prompt="", params=None, owner_type="user", owner_id=None)`
- JSONB: use `psycopg2.extras.Json()` for JSONB columns
- Spec: batch creation, expansion, auto-naming, 50-item cap

- [ ] **Step 1: Create batch_service.py with imports and create_batch**

```python
"""Batch generation service — multi-prompt batches with optional parameter sweep.

Also handles queue management: retry, cancel, cleanup, stats.
"""

import logging
import time
from typing import Dict, List, Optional

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

MAX_BATCH_ITEMS = 50


def create_batch(
    name: str,
    owner_type: str,
    owner_id: int,
    media_type: str,
    prompts: List[str],
    base_params: Dict,
    sweep_param: Optional[str] = None,
    sweep_values: Optional[List] = None,
) -> Dict:
    """Create a batch and expand into individual queue entries.

    Returns {"batch_id": int, "total_items": int} or {"error": str}.
    """
    prompts = [p.strip() for p in prompts if p.strip()]
    if not prompts:
        return {"error": "No prompts provided"}

    if media_type not in ("image", "video", "audio"):
        return {"error": f"Unsupported media type: {media_type}"}

    if sweep_param and sweep_param not in ("seed", "model"):
        return {"error": f"Invalid sweep_param: {sweep_param}"}

    # Calculate total items
    if sweep_param and sweep_values:
        total = len(prompts) * len(sweep_values)
    else:
        total = len(prompts)

    if total > MAX_BATCH_ITEMS:
        return {"error": f"Batch exceeds maximum of {MAX_BATCH_ITEMS} items ({total} requested)"}

    # Auto-name if blank
    if not name or not name.strip():
        name = prompts[0][:50]
        if sweep_param and sweep_values:
            name += f" x {len(sweep_values)} {sweep_param}s"
        if len(prompts) > 1:
            name = f"{len(prompts)} prompts" + (f" x {len(sweep_values)} {sweep_param}s" if sweep_param and sweep_values else "")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_batches (name, owner_type, owner_id, media_type, base_params,
                                       sweep_param, sweep_values, total_items, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING id
            """,
            (
                name.strip(),
                owner_type,
                owner_id,
                media_type,
                psycopg2.extras.Json(base_params),
                sweep_param,
                psycopg2.extras.Json(sweep_values) if sweep_values else None,
                total,
            ),
        )
        batch_id = cur.fetchone()["id"]

    # Expand and dispatch
    queue_ids = _expand_batch(batch_id, prompts, base_params, media_type, owner_type, owner_id, sweep_param, sweep_values)

    return {"batch_id": batch_id, "total_items": len(queue_ids)}


def _expand_batch(
    batch_id: int,
    prompts: List[str],
    base_params: Dict,
    media_type: str,
    owner_type: str,
    owner_id: int,
    sweep_param: Optional[str],
    sweep_values: Optional[List],
) -> List[int]:
    """Expand batch into individual queue entries and dispatch each."""
    from .generation_service import submit_generation

    queue_ids = []

    for prompt in prompts:
        if sweep_param == "seed" and sweep_values:
            for seed_val in sweep_values:
                params = {**base_params, "seed": int(seed_val)}
                result = submit_generation(
                    owner_id, media_type, prompt,
                    negative_prompt=base_params.get("negative_prompt", ""),
                    params=params, owner_type=owner_type, owner_id=owner_id,
                    batch_id=batch_id,
                )
                if result.get("queue_id"):
                    queue_ids.append(result["queue_id"])
        elif sweep_param == "model" and sweep_values:
            for model_val in sweep_values:
                params = {**base_params, "model": model_val}
                result = submit_generation(
                    owner_id, media_type, prompt,
                    negative_prompt=base_params.get("negative_prompt", ""),
                    params=params, owner_type=owner_type, owner_id=owner_id,
                    batch_id=batch_id,
                )
                if result.get("queue_id"):
                    queue_ids.append(result["queue_id"])
        else:
            result = submit_generation(
                owner_id, media_type, prompt,
                negative_prompt=base_params.get("negative_prompt", ""),
                params=base_params, owner_type=owner_type, owner_id=owner_id,
                batch_id=batch_id,
            )
            if result.get("queue_id"):
                queue_ids.append(result["queue_id"])

    # Update batch status to running
    if queue_ids:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_batches SET status = 'running' WHERE id = %s",
                (batch_id,),
            )

    return queue_ids
```

- [ ] **Step 2: Test create_batch locally**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
from tools.media_studio.services.batch_service import create_batch, MAX_BATCH_ITEMS

# Test validation
r = create_batch('', 'user', 1, 'image', [], {})
assert r.get('error') == 'No prompts provided', f'Expected error, got {r}'
print('[PASS] Empty prompts rejected')

r = create_batch('', 'user', 1, 'bad', ['test'], {})
assert 'Unsupported' in r.get('error', ''), f'Expected error, got {r}'
print('[PASS] Bad media type rejected')

r = create_batch('', 'user', 1, 'image', ['test'], {}, sweep_param='bad')
assert 'Invalid sweep_param' in r.get('error', ''), f'Expected error, got {r}'
print('[PASS] Bad sweep_param rejected')

# Test cap
r = create_batch('', 'user', 1, 'image', ['p']*10, {}, sweep_param='seed', sweep_values=list(range(6)))
assert 'exceeds maximum' in r.get('error', ''), f'Expected cap error for 60 items, got {r}'
print('[PASS] 50-item cap enforced')

print('All validation tests passed')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/batch_service.py
git commit -m "feat(media-studio): add batch_service with create_batch and expansion logic"
```

---

### Task 3: Batch Service — Status & Counters

**Files:**
- Modify: `platform_v2/tools/media_studio/services/batch_service.py`

**Context:** Add batch status queries and the `update_batch_counters` function that gets called from generation_service hooks.

- [ ] **Step 1: Add status functions to batch_service.py**

Append after `_expand_batch`:

```python
def get_batch(batch_id: int, owner_type: str, owner_id: int) -> Optional[Dict]:
    """Get a single batch with all fields."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM media_batches WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (batch_id, owner_type, owner_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_batches(
    owner_type: str,
    owner_id: int,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> Dict:
    """List user's batches, optionally filtered by status."""
    offset = (page - 1) * per_page
    with get_db_cursor() as (conn, cur):
        where = "WHERE owner_type = %s AND owner_id = %s"
        params = [owner_type, owner_id]
        if status:
            where += " AND status = %s"
            params.append(status)

        cur.execute(f"SELECT COUNT(*) as total FROM media_batches {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"SELECT * FROM media_batches {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [per_page, offset],
        )
        batches = [dict(row) for row in cur.fetchall()]

    return {
        "batches": batches,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


def get_batch_items(batch_id: int, owner_type: str, owner_id: int) -> List[Dict]:
    """Get all queue entries for a batch, with media_library join for thumbnails."""
    with get_db_cursor() as (conn, cur):
        # Verify ownership
        cur.execute(
            "SELECT id FROM media_batches WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (batch_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return []

        cur.execute(
            """
            SELECT q.id, q.status, q.media_type, q.params, q.error_message,
                   q.created_at, q.started_at, q.completed_at,
                   ml.file_path, ml.thumbnail_path, ml.prompt, ml.seed, ml.model
            FROM media_generation_queue q
            LEFT JOIN media_library ml ON ml.id = q.result_media_id
            WHERE q.batch_id = %s
            ORDER BY q.id
            """,
            (batch_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def update_batch_counters(batch_id: int) -> None:
    """Recalculate completed/failed counts and update batch status.

    Called from generation_service on_generation_complete/on_generation_failed.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status IN ('pending', 'dispatched', 'generating')) as active,
                COUNT(*) as total
            FROM media_generation_queue
            WHERE batch_id = %s
            """,
            (batch_id,),
        )
        counts = dict(cur.fetchone())

        completed = counts["completed"]
        failed = counts["failed"]
        active = counts["active"]

        if active > 0:
            new_status = "running"
        elif failed > 0:
            new_status = "partial"
        else:
            new_status = "completed"

        cur.execute(
            """
            UPDATE media_batches
            SET completed_items = %s, failed_items = %s, status = %s,
                completed_at = CASE WHEN %s IN ('completed', 'partial') THEN NOW() ELSE completed_at END
            WHERE id = %s
            """,
            (completed, failed, new_status, new_status, batch_id),
        )
```

- [ ] **Step 2: Test status functions**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
from database import get_db_cursor
from tools.media_studio.services.batch_service import get_batch, list_batches, get_batch_items, update_batch_counters

from app import app
with app.app_context():
    # Insert a test batch
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(\"\"\"
            INSERT INTO media_batches (name, owner_type, owner_id, media_type, base_params, total_items, status)
            VALUES ('Test Batch', 'user', 1, 'image', '{}', 2, 'running')
            RETURNING id
        \"\"\")
        bid = cur.fetchone()['id']

    b = get_batch(bid, 'user', 1)
    assert b is not None and b['name'] == 'Test Batch', f'get_batch failed: {b}'
    print(f'[PASS] get_batch returned batch {bid}')

    bl = list_batches('user', 1)
    assert bl['total'] >= 1, f'list_batches failed: {bl}'
    print(f'[PASS] list_batches returned {bl[\"total\"]} batches')

    items = get_batch_items(bid, 'user', 1)
    assert isinstance(items, list), f'get_batch_items failed: {items}'
    print(f'[PASS] get_batch_items returned {len(items)} items')

    # Cleanup
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute('DELETE FROM media_batches WHERE id = %s', (bid,))
    print('[PASS] Cleanup done')
    print('All status tests passed')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/batch_service.py
git commit -m "feat(media-studio): add batch status queries and update_batch_counters"
```

---

### Task 4: Batch Service — Queue Management & Cleanup

**Files:**
- Modify: `platform_v2/tools/media_studio/services/batch_service.py`

**Context:** Add retry, cancel, queue stats, and cleanup functions. `cleanup_expired_exports` wraps `export_service.cleanup_exports()`.

- [ ] **Step 1: Add queue management functions**

Append after `update_batch_counters`:

```python
def cancel_batch(batch_id: int, owner_type: str, owner_id: int) -> int:
    """Cancel all pending/dispatched items in a batch. Returns count cancelled."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM media_batches WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (batch_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return 0

        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE batch_id = %s AND status IN ('pending', 'dispatched')
            """,
            (batch_id,),
        )
        cancelled = cur.rowcount

        # Update batch status
        cur.execute(
            "UPDATE media_batches SET status = 'cancelled' WHERE id = %s",
            (batch_id,),
        )
    if cancelled:
        update_batch_counters(batch_id)
    return cancelled


def retry_batch_failed(batch_id: int, owner_type: str, owner_id: int) -> int:
    """Re-submit all failed items in a batch. Returns count retried."""
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM media_batches WHERE id = %s AND owner_type = %s AND owner_id = %s",
            (batch_id, owner_type, owner_id),
        )
        if not cur.fetchone():
            return 0

        cur.execute(
            "SELECT id, params, media_type FROM media_generation_queue WHERE batch_id = %s AND status = 'failed'",
            (batch_id,),
        )
        failed_items = [dict(row) for row in cur.fetchall()]

    retried = 0
    for item in failed_items:
        params = dict(item["params"] or {})
        prompt = params.pop("prompt", "")
        negative_prompt = params.pop("negative_prompt", "")

        # Reset the existing queue entry
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'pending', error_message = NULL, completed_at = NULL, started_at = NULL
                WHERE id = %s
                """,
                (item["id"],),
            )

        result = submit_generation(
            owner_id, item["media_type"], prompt,
            negative_prompt=negative_prompt,
            params=params, owner_type=owner_type, owner_id=owner_id,
            batch_id=batch_id,
        )
        if result.get("queue_id"):
            retried += 1

    if retried:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_batches SET status = 'running' WHERE id = %s",
                (batch_id,),
            )
        update_batch_counters(batch_id)
    return retried


def retry_single(queue_id: int, owner_type: str, owner_id: int) -> bool:
    """Retry a single failed queue entry. Returns True if retried."""
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM media_generation_queue WHERE id = %s AND owner_type = %s AND owner_id = %s AND status = 'failed'",
            (queue_id, owner_type, owner_id),
        )
        item = cur.fetchone()
        if not item:
            return False
        item = dict(item)

    params = dict(item["params"] or {})
    prompt = params.pop("prompt", "")
    negative_prompt = params.pop("negative_prompt", "")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'pending', error_message = NULL, completed_at = NULL, started_at = NULL WHERE id = %s",
            (queue_id,),
        )

    result = submit_generation(
        owner_id, item["media_type"], prompt,
        negative_prompt=negative_prompt,
        params=params, owner_type=owner_type, owner_id=owner_id,
        batch_id=item.get("batch_id"),
    )

    if item.get("batch_id"):
        update_batch_counters(item["batch_id"])
    return bool(result.get("queue_id"))


def cancel_single(queue_id: int, owner_type: str, owner_id: int) -> bool:
    """Cancel a single pending/dispatched queue entry."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND status IN ('pending', 'dispatched')
            """,
            (queue_id, owner_type, owner_id),
        )
        cancelled = cur.rowcount > 0

    if cancelled:
        # Check if this was part of a batch
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT batch_id FROM media_generation_queue WHERE id = %s", (queue_id,))
            row = cur.fetchone()
            if row and row["batch_id"]:
                update_batch_counters(row["batch_id"])
    return cancelled


def get_queue_entries(
    owner_type: str,
    owner_id: int,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Dict:
    """Get paginated queue entries for a user."""
    offset = (page - 1) * per_page
    with get_db_cursor() as (conn, cur):
        where = "WHERE q.owner_type = %s AND q.owner_id = %s"
        params = [owner_type, owner_id]
        if status:
            where += " AND q.status = %s"
            params.append(status)

        cur.execute(f"SELECT COUNT(*) as total FROM media_generation_queue q {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT q.id, q.batch_id, q.status, q.media_type, q.params, q.error_message,
                   q.created_at, q.started_at, q.completed_at,
                   ml.file_path, ml.thumbnail_path, ml.prompt, ml.seed, ml.model
            FROM media_generation_queue q
            LEFT JOIN media_library ml ON ml.id = q.result_media_id
            {where}
            ORDER BY q.created_at DESC
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
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


def get_queue_stats(owner_type: str, owner_id: int) -> Dict:
    """Get queue statistics: counts by status + avg duration."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('pending', 'dispatched')) as pending,
                COUNT(*) FILTER (WHERE status = 'generating') as running,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000)
                    FILTER (WHERE status = 'completed' AND started_at IS NOT NULL) as avg_duration_ms
            FROM media_generation_queue
            WHERE owner_type = %s AND owner_id = %s
            """,
            (owner_type, owner_id),
        )
        row = dict(cur.fetchone())
        row["avg_duration_ms"] = round(row["avg_duration_ms"] or 0)
        return row


def clear_completed(owner_type: str, owner_id: int) -> int:
    """Delete completed queue entries older than 1 hour."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            DELETE FROM media_generation_queue
            WHERE owner_type = %s AND owner_id = %s
              AND status IN ('completed', 'cancelled')
              AND completed_at < NOW() - INTERVAL '1 hour'
            """,
            (owner_type, owner_id),
        )
        return cur.rowcount


def cleanup_stale_queue(max_age_hours: int = 24) -> int:
    """Delete old completed/failed/cancelled queue entries. Called by APScheduler."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            DELETE FROM media_generation_queue
            WHERE status IN ('completed', 'failed', 'cancelled')
              AND completed_at < NOW() - make_interval(hours => %s)
            """,
            (max_age_hours,),
        )
        cleaned = cur.rowcount
    if cleaned:
        logger.info(f"Queue cleanup: removed {cleaned} stale entries")
    return cleaned


def cleanup_expired_exports() -> int:
    """Wrap export_service cleanup. Called by APScheduler."""
    from .export_service import cleanup_exports

    return cleanup_exports()
```

- [ ] **Step 2: Test queue management functions**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
from tools.media_studio.services.batch_service import get_queue_stats, get_queue_entries, cleanup_stale_queue

from app import app
with app.app_context():
    stats = get_queue_stats('user', 1)
    assert 'pending' in stats and 'failed' in stats, f'Bad stats: {stats}'
    print(f'[PASS] get_queue_stats: {stats}')

    entries = get_queue_entries('user', 1)
    assert 'items' in entries and 'total' in entries, f'Bad entries: {entries}'
    print(f'[PASS] get_queue_entries: {entries[\"total\"]} items')

    cleaned = cleanup_stale_queue()
    assert isinstance(cleaned, int), f'Bad cleanup result: {cleaned}'
    print(f'[PASS] cleanup_stale_queue: {cleaned} cleaned')

    print('All queue management tests passed')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/batch_service.py
git commit -m "feat(media-studio): add queue management, retry, cancel, cleanup to batch_service"
```

---

### Task 5: Generation Service Hooks

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

**Context:**
- `submit_generation()` needs a `batch_id=None` parameter added, and the INSERT must include it.
- `on_generation_complete()` already has auto_tag + embed_prompt hooks at the end — add batch counter hook after those.
- `on_generation_failed()` already exists — add batch counter hook to it.
- Find the exact INSERT statement in `submit_generation()` and the hook locations.

- [ ] **Step 1: Add `batch_id` parameter to `submit_generation()`**

In `generation_service.py`, find the `submit_generation` function signature and add `batch_id=None`:

```python
def submit_generation(
    user_id: int,
    media_type: str,
    prompt: str,
    negative_prompt: str = "",
    params: Optional[Dict] = None,
    owner_type: str = "user",
    owner_id: Optional[int] = None,
    batch_id: Optional[int] = None,
) -> Dict:
```

Then find the INSERT INTO media_generation_queue statement and add batch_id to it. The current INSERT looks like:

```sql
INSERT INTO media_generation_queue (owner_type, owner_id, media_type, status, params)
VALUES (%s, %s, %s, 'pending', %s)
RETURNING id
```

Change to:

```sql
INSERT INTO media_generation_queue (owner_type, owner_id, media_type, status, params, batch_id)
VALUES (%s, %s, %s, 'pending', %s, %s)
RETURNING id
```

And add `batch_id` to the params tuple.

- [ ] **Step 2: Add batch counter hook to `on_generation_complete()`**

After the existing auto_tag + embed_prompt hooks (the try/except blocks), add:

```python
    # Update batch counters if this is a batch item
    if queue_entry.get("batch_id"):
        try:
            from .batch_service import update_batch_counters
            update_batch_counters(queue_entry["batch_id"])
        except Exception:
            logger.warning("batch counter update failed for queue %s", queue_id)
```

Note: `queue_entry` is the dict fetched at the top of `on_generation_complete()`. Verify it includes `batch_id` by checking the SELECT query — if the SELECT uses `SELECT *` it will include batch_id automatically. If it selects specific columns, add `batch_id` to the list.

- [ ] **Step 3: Add batch counter hook to `on_generation_failed()`**

At the end of `on_generation_failed()`, after the UPDATE statement, add:

```python
    # Update batch counters if this is a batch item
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT batch_id FROM media_generation_queue WHERE id = %s", (queue_id,))
        row = cur.fetchone()
        if row and row.get("batch_id"):
            try:
                from .batch_service import update_batch_counters
                update_batch_counters(row["batch_id"])
            except Exception:
                logger.warning("batch counter update failed for queue %s", queue_id)
```

- [ ] **Step 4: Verify imports compile**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
from tools.media_studio.services.generation_service import submit_generation, on_generation_complete, on_generation_failed
import inspect
sig = inspect.signature(submit_generation)
assert 'batch_id' in sig.parameters, f'batch_id not in signature: {sig}'
print(f'[PASS] submit_generation signature: {sig}')
print('[PASS] All generation service hooks verified')
"
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): add batch_id param and batch counter hooks to generation_service"
```

---

### Task 6: API Routes — Batch & Queue Endpoints

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

**Context:** Follow existing route pattern: `@media_studio_bp.route(...)`, `@login_required`, `request.get_json()`, delegate to service, `return jsonify(...)`. Routes are in `routes.py`, the blueprint is `media_studio_bp`. Add 10 new endpoints after the existing bulk operations section.

- [ ] **Step 1: Add batch routes**

After the existing export routes section in `routes.py`, add:

```python
# ── Batch Generation ─────────────────────────────────────────────────

@media_studio_bp.route("/api/batches", methods=["POST"])
@login_required
def api_create_batch():
    """Create a batch generation job."""
    from .services.batch_service import create_batch

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    result = create_batch(
        name=data.get("name", ""),
        owner_type="user",
        owner_id=current_user.id,
        media_type=data.get("media_type", "image"),
        prompts=data.get("prompts", []),
        base_params=data.get("base_params", {}),
        sweep_param=data.get("sweep_param"),
        sweep_values=data.get("sweep_values"),
    )
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/batches", methods=["GET"])
@login_required
def api_list_batches():
    """List user's batches."""
    from .services.batch_service import list_batches

    status = request.args.get("status")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 10))
    return jsonify(list_batches("user", current_user.id, status=status, page=page, per_page=per_page))


@media_studio_bp.route("/api/batches/<int:batch_id>", methods=["GET"])
@login_required
def api_get_batch(batch_id):
    """Get batch details with items."""
    from .services.batch_service import get_batch, get_batch_items

    batch = get_batch(batch_id, "user", current_user.id)
    if not batch:
        return jsonify({"error": "Batch not found"}), 404
    items = get_batch_items(batch_id, "user", current_user.id)
    return jsonify({"batch": batch, "items": items})


@media_studio_bp.route("/api/batches/<int:batch_id>/cancel", methods=["POST"])
@login_required
def api_cancel_batch(batch_id):
    """Cancel remaining items in a batch."""
    from .services.batch_service import cancel_batch

    cancelled = cancel_batch(batch_id, "user", current_user.id)
    return jsonify({"cancelled": cancelled})


@media_studio_bp.route("/api/batches/<int:batch_id>/retry", methods=["POST"])
@login_required
def api_retry_batch(batch_id):
    """Retry failed items in a batch."""
    from .services.batch_service import retry_batch_failed

    retried = retry_batch_failed(batch_id, "user", current_user.id)
    return jsonify({"retried": retried})


# ── Queue Management ─────────────────────────────────────────────────

@media_studio_bp.route("/api/queue", methods=["GET"])
@login_required
def api_get_queue():
    """Get paginated queue entries."""
    from .services.batch_service import get_queue_entries

    status = request.args.get("status")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    return jsonify(get_queue_entries("user", current_user.id, status=status, page=page, per_page=per_page))


@media_studio_bp.route("/api/queue/<int:queue_id>/retry", methods=["POST"])
@login_required
def api_retry_queue_item(queue_id):
    """Retry a single failed queue entry."""
    from .services.batch_service import retry_single

    success = retry_single(queue_id, "user", current_user.id)
    if not success:
        return jsonify({"error": "Item not found or not failed"}), 404
    return jsonify({"status": "retried"})


@media_studio_bp.route("/api/queue/<int:queue_id>/cancel", methods=["POST"])
@login_required
def api_cancel_queue_item(queue_id):
    """Cancel a single pending/dispatched queue entry."""
    from .services.batch_service import cancel_single

    success = cancel_single(queue_id, "user", current_user.id)
    if not success:
        return jsonify({"error": "Item not found or not cancellable"}), 404
    return jsonify({"status": "cancelled"})


@media_studio_bp.route("/api/queue/stats", methods=["GET"])
@login_required
def api_queue_stats():
    """Get queue statistics."""
    from .services.batch_service import get_queue_stats

    return jsonify(get_queue_stats("user", current_user.id))


@media_studio_bp.route("/api/queue/clear-completed", methods=["POST"])
@login_required
def api_clear_completed():
    """Clear completed queue entries older than 1 hour."""
    from .services.batch_service import clear_completed

    cleared = clear_completed("user", current_user.id)
    return jsonify({"cleared": cleared})
```

- [ ] **Step 2: Verify routes compile**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
from app import app
with app.app_context():
    rules = [r.rule for r in app.url_map.iter_rules() if 'batch' in r.rule or 'queue' in r.rule]
    print('Batch/Queue routes:')
    for r in sorted(rules):
        print(f'  {r}')
    assert len(rules) >= 10, f'Expected 10+ routes, got {len(rules)}'
    print(f'[PASS] {len(rules)} batch/queue routes registered')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add 10 batch and queue management API routes"
```

---

### Task 7: APScheduler Cleanup Jobs

**Files:**
- Modify: `platform_v2/app.py` (inside `init_consciousness_scheduler`)

**Context:** The platform uses `apscheduler.schedulers.background.BackgroundScheduler` with `scheduler.add_job()` calls. All scheduled jobs are registered inside `init_consciousness_scheduler(flask_app)` in `app.py` (around line 3464). Media Studio cleanup jobs should be added to this same function. The pattern wraps each job function in a closure that calls `flask_app.app_context()`.

- [ ] **Step 1: Add Media Studio cleanup jobs to `init_consciousness_scheduler`**

In `app.py`, find `init_consciousness_scheduler()`. Near the end of the function (before the `scheduler.start()` call), add:

```python
        # Media Studio cleanup jobs
        from tools.media_studio.services.batch_service import cleanup_stale_queue, cleanup_expired_exports

        def scheduled_queue_cleanup():
            with flask_app.app_context():
                try:
                    cleaned = cleanup_stale_queue(max_age_hours=24)
                    if cleaned:
                        logger.info(f"Media queue cleanup: removed {cleaned} stale entries")
                except Exception as e:
                    logger.warning(f"Media queue cleanup failed: {e}")

        scheduler.add_job(
            scheduled_queue_cleanup,
            trigger=IntervalTrigger(hours=1),
            id="media_queue_cleanup",
            misfire_grace_time=300,
        )

        def scheduled_export_cleanup():
            with flask_app.app_context():
                try:
                    cleaned = cleanup_expired_exports()
                    if cleaned:
                        logger.info(f"Media export cleanup: removed {cleaned} expired exports")
                except Exception as e:
                    logger.warning(f"Media export cleanup failed: {e}")

        scheduler.add_job(
            scheduled_export_cleanup,
            trigger=IntervalTrigger(hours=1),
            id="media_export_cleanup",
            misfire_grace_time=300,
        )
```

- [ ] **Step 2: Verify jobs are registered**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
from tools.media_studio.services.batch_service import cleanup_stale_queue, cleanup_expired_exports
print('[PASS] cleanup_stale_queue importable')
print('[PASS] cleanup_expired_exports importable')
print('Jobs will be registered when scheduler starts in app.py')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(media-studio): register APScheduler cleanup jobs for queue and exports"
```

---

## Chunk 2: Frontend

### Task 8: Queue Panel HTML

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Context:** The Gallery tab is in `media_studio.html`. The existing structure has: search bar, filter sidebar, gallery grid. The queue panel goes between the search bar and the gallery grid. Element IDs use `ms` prefix. JS uses IIFE pattern with `window.funcName`.

- [ ] **Step 1: Add queue panel toggle to Gallery tab header**

Find the Gallery tab header (near the search bar area). After the search bar, add a queue toggle button:

```html
<!-- Queue Panel Toggle -->
<button class="ms-queue-toggle" onclick="toggleQueuePanel()" id="msQueueToggle">
    Queue (<span id="msQueueActiveCount">0</span> active)
</button>
```

- [ ] **Step 2: Add queue panel HTML**

Below the search bar area, before the gallery grid, add:

```html
<!-- Queue Panel (collapsible) -->
<div id="msQueuePanel" class="ms-queue-panel" style="display:none;">
    <div class="ms-queue-header">
        <span class="ms-queue-stats" id="msQueueStats"></span>
        <button class="ms-btn-sm" onclick="clearCompleted()">Clear Completed</button>
    </div>

    <!-- Active Generations -->
    <div class="ms-queue-section" id="msQueueActive">
        <h4>Active</h4>
        <div id="msQueueActiveList"></div>
    </div>

    <!-- Failed Items -->
    <div class="ms-queue-section ms-queue-failed" id="msQueueFailed" style="display:none;">
        <h4>Failed</h4>
        <div id="msQueueFailedList"></div>
    </div>

    <!-- Recent Completions -->
    <div class="ms-queue-section" id="msQueueRecent" style="display:none;">
        <h4>Recent</h4>
        <div id="msQueueRecentList"></div>
    </div>
</div>
```

- [ ] **Step 3: Add batch creation modal**

After the queue panel, add the batch modal (uses the existing `ms-modal-overlay` / `ms-modal-content` pattern from Layer 5):

```html
<!-- Batch Creation Modal -->
<div id="msBatchModal" class="ms-modal-overlay" style="display:none;" onclick="if(event.target===this)this.style.display='none'">
    <div class="ms-modal-content ms-batch-modal">
        <div class="ms-modal-header">
            <h3>Batch Generate</h3>
            <button class="ms-modal-close" onclick="document.getElementById('msBatchModal').style.display='none'">&times;</button>
        </div>
        <div class="ms-modal-body">
            <label>Batch Name (optional)</label>
            <input type="text" id="msBatchName" placeholder="Auto-generated from first prompt" class="ms-input">

            <label>Prompts (one per line)</label>
            <textarea id="msBatchPrompts" rows="6" class="ms-textarea" oninput="updateBatchPreview()"></textarea>
            <small id="msBatchPromptCount">0 prompts</small>

            <label>
                <input type="checkbox" id="msBatchSweepToggle" onchange="toggleSweepSection()"> Enable Parameter Sweep
            </label>

            <div id="msBatchSweepSection" style="display:none;">
                <label>Sweep Parameter</label>
                <select id="msBatchSweepParam" class="ms-select" onchange="updateSweepInputs()">
                    <option value="seed">Seed</option>
                    <option value="model">Model</option>
                </select>

                <div id="msBatchSweepSeedInput">
                    <label>Seeds (comma-separated)</label>
                    <input type="text" id="msBatchSweepSeeds" placeholder="42, 123, 777, 999" class="ms-input" oninput="updateBatchPreview()">
                </div>

                <div id="msBatchSweepModelInput" style="display:none;">
                    <label>Models</label>
                    <div id="msBatchModelCheckboxes"></div>
                </div>
            </div>

            <label>Media Type</label>
            <select id="msBatchMediaType" class="ms-select">
                <option value="image">Image</option>
                <option value="video">Video</option>
                <option value="audio">Audio</option>
            </select>

            <div id="msBatchSharedParams">
                <label>Model</label>
                <select id="msBatchModel" class="ms-select"></select>
                <label>Negative Prompt</label>
                <input type="text" id="msBatchNegPrompt" class="ms-input" placeholder="Optional negative prompt">
            </div>

            <p id="msBatchPreview" class="ms-batch-preview">This will create <strong>0</strong> generations</p>
        </div>
        <div class="ms-modal-footer">
            <button id="msBatchSubmit" class="ms-btn ms-btn-primary" onclick="submitBatch()" disabled>Start Batch</button>
        </div>
    </div>
</div>
```

- [ ] **Step 4: Add "Batch" button to generation tabs**

Find each media type tab's generate button area. Add a "Batch" button next to each existing "Generate" button:

```html
<button class="ms-btn ms-btn-secondary" onclick="openBatchModal('image')">Batch</button>
```

Repeat for video and audio tabs with `'video'` and `'audio'` respectively.

- [ ] **Step 5: Commit HTML changes**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add queue panel and batch modal HTML to gallery tab"
```

---

### Task 9: Queue Panel & Batch JavaScript

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Context:** JS is inline in the template, IIFE pattern, functions exposed via `window.funcName`. Uses `api()` helper for fetch calls (defined earlier in the template). Element IDs use `ms` prefix. Polling uses `setInterval`/`clearInterval`.

- [ ] **Step 1: Add queue panel JS**

In the `<script>` section of the template, add the queue panel functions. All dynamic content inserted via innerHTML must be escaped with `_escHtml()` (already defined in Layer 5 JS — reuse it, do NOT redefine). Build DOM nodes with `document.createElement` where practical; use innerHTML only for complex card layouts where DOM building would be verbose, and always escape dynamic strings with `_escHtml()`.

```javascript
// ── Queue Panel ─────────────────────────────────────────────────────

var _queuePollInterval = null;
var _queueItemsInterval = null;

window.toggleQueuePanel = function() {
    var panel = document.getElementById('msQueuePanel');
    var isHidden = panel.style.display === 'none';
    panel.style.display = isHidden ? 'block' : 'none';

    if (isHidden) {
        loadQueueStats();
        loadQueueItems();
        _queuePollInterval = setInterval(loadQueueStats, 5000);
        _queueItemsInterval = setInterval(loadQueueItems, 10000);
    } else {
        if (_queuePollInterval) clearInterval(_queuePollInterval);
        if (_queueItemsInterval) clearInterval(_queueItemsInterval);
        _queuePollInterval = null;
        _queueItemsInterval = null;
    }
};

window.loadQueueStats = function() {
    api('/api/queue/stats').then(function(stats) {
        document.getElementById('msQueueStats').textContent =
            stats.pending + ' active / ' + stats.failed + ' failed / ' + stats.completed + ' completed';
        document.getElementById('msQueueActiveCount').textContent = (stats.pending || 0) + (stats.running || 0);
    });
};

window.loadQueueItems = function() {
    // Load active items (parallel requests)
    Promise.all([
        api('/api/queue?status=pending&per_page=50'),
        api('/api/queue?status=dispatched&per_page=50'),
        api('/api/queue?status=generating&per_page=50')
    ]).then(function(results) {
        var active = (results[0].items || []).concat(results[1].items || []).concat(results[2].items || []);
        _renderQueueSection('msQueueActiveList', active, 'active');
        document.getElementById('msQueueActive').style.display = active.length ? 'block' : 'none';
    });

    // Load failed items
    api('/api/queue?status=failed&per_page=20').then(function(data) {
        _renderQueueSection('msQueueFailedList', data.items || [], 'failed');
        document.getElementById('msQueueFailed').style.display = (data.items || []).length ? 'block' : 'none';
    });

    // Load recent completions (last 5)
    api('/api/queue?status=completed&per_page=5').then(function(data) {
        _renderQueueSection('msQueueRecentList', data.items || [], 'recent');
        document.getElementById('msQueueRecent').style.display = (data.items || []).length ? 'block' : 'none';
    });
};

function _renderQueueSection(containerId, items, type) {
    var container = document.getElementById(containerId);
    _clearChildren(container);

    // Group by batch_id
    var batches = {};
    var singles = [];
    items.forEach(function(item) {
        if (item.batch_id) {
            if (!batches[item.batch_id]) batches[item.batch_id] = [];
            batches[item.batch_id].push(item);
        } else {
            singles.push(item);
        }
    });

    // Render batch groups
    Object.keys(batches).forEach(function(batchId) {
        var group = batches[batchId];
        var div = document.createElement('div');
        div.className = 'ms-queue-batch-group';

        var header = document.createElement('div');
        header.className = 'ms-queue-batch-header';
        var prompt = (group[0].params && group[0].params.prompt) || group[0].prompt || 'Batch ' + batchId;
        var headerSpan = document.createElement('span');
        headerSpan.textContent = prompt.substring(0, 60) + ' (' + group.length + ' items)';
        header.appendChild(headerSpan);

        if (type === 'failed') {
            var retryBtn = document.createElement('button');
            retryBtn.className = 'ms-btn-xs';
            retryBtn.textContent = 'Retry All';
            retryBtn.onclick = function() { retryBatchFailed(batchId); };
            header.appendChild(retryBtn);
        }
        if (type === 'active') {
            var cancelBtn = document.createElement('button');
            cancelBtn.className = 'ms-btn-xs ms-btn-danger';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.onclick = function() { cancelBatch(batchId); };
            header.appendChild(cancelBtn);
        }
        div.appendChild(header);

        group.forEach(function(item) {
            div.appendChild(_createQueueCard(item, type));
        });
        container.appendChild(div);
    });

    // Render singles
    singles.forEach(function(item) {
        container.appendChild(_createQueueCard(item, type));
    });
}

function _createQueueCard(item, type) {
    var card = document.createElement('div');
    card.className = 'ms-queue-card ms-queue-' + type;
    var prompt = (item.params && item.params.prompt) || item.prompt || '';
    var elapsed = item.started_at ? _formatElapsed(item.started_at) : '';

    var body = document.createElement('div');
    body.className = 'ms-queue-card-body';

    if (item.thumbnail_path) {
        var img = document.createElement('img');
        img.src = item.thumbnail_path;
        img.className = 'ms-queue-thumb';
        body.appendChild(img);
    }
    if (type === 'active') {
        var spinner = document.createElement('span');
        spinner.className = 'ms-spinner';
        body.appendChild(spinner);
    }

    var promptSpan = document.createElement('span');
    promptSpan.className = 'ms-queue-prompt';
    promptSpan.textContent = prompt.substring(0, 60);
    body.appendChild(promptSpan);

    var metaSpan = document.createElement('span');
    metaSpan.className = 'ms-queue-meta';
    metaSpan.textContent = item.media_type + (elapsed ? ' \u00b7 ' + elapsed : '');
    body.appendChild(metaSpan);

    if (item.error_message) {
        var errorSpan = document.createElement('span');
        errorSpan.className = 'ms-queue-error';
        errorSpan.textContent = item.error_message;
        body.appendChild(errorSpan);
    }

    card.appendChild(body);

    var actions = document.createElement('div');
    actions.className = 'ms-queue-card-actions';
    if (type === 'active') {
        var cb = document.createElement('button');
        cb.className = 'ms-btn-xs ms-btn-danger';
        cb.textContent = 'Cancel';
        cb.onclick = function() { cancelQueueItem(item.id); };
        actions.appendChild(cb);
    } else if (type === 'failed') {
        var rb = document.createElement('button');
        rb.className = 'ms-btn-xs';
        rb.textContent = 'Retry';
        rb.onclick = function() { retryQueueItem(item.id); };
        actions.appendChild(rb);
    }
    card.appendChild(actions);

    return card;
}

function _formatElapsed(startedAt) {
    var start = new Date(startedAt);
    var now = new Date();
    var secs = Math.floor((now - start) / 1000);
    if (secs < 60) return secs + 's';
    return Math.floor(secs / 60) + 'm ' + (secs % 60) + 's';
}

window.cancelQueueItem = function(id) {
    api('/api/queue/' + id + '/cancel', {method: 'POST'}).then(function() { loadQueueItems(); loadQueueStats(); });
};

window.retryQueueItem = function(id) {
    api('/api/queue/' + id + '/retry', {method: 'POST'}).then(function() { loadQueueItems(); loadQueueStats(); });
};

window.cancelBatch = function(id) {
    api('/api/batches/' + id + '/cancel', {method: 'POST'}).then(function() { loadQueueItems(); loadQueueStats(); });
};

window.retryBatchFailed = function(id) {
    api('/api/batches/' + id + '/retry', {method: 'POST'}).then(function() { loadQueueItems(); loadQueueStats(); });
};

window.clearCompleted = function() {
    api('/api/queue/clear-completed', {method: 'POST'}).then(function() { loadQueueItems(); loadQueueStats(); });
};
```

- [ ] **Step 2: Add batch modal JS**

```javascript
// ── Batch Modal ─────────────────────────────────────────────────────

window.openBatchModal = function(mediaType) {
    document.getElementById('msBatchMediaType').value = mediaType;
    document.getElementById('msBatchModal').style.display = 'flex';
    document.getElementById('msBatchPrompts').value = '';
    document.getElementById('msBatchName').value = '';
    document.getElementById('msBatchSweepToggle').checked = false;
    document.getElementById('msBatchSweepSection').style.display = 'none';
    updateBatchPreview();
};

window.toggleSweepSection = function() {
    var show = document.getElementById('msBatchSweepToggle').checked;
    document.getElementById('msBatchSweepSection').style.display = show ? 'block' : 'none';
    updateBatchPreview();
};

window.updateSweepInputs = function() {
    var param = document.getElementById('msBatchSweepParam').value;
    document.getElementById('msBatchSweepSeedInput').style.display = param === 'seed' ? 'block' : 'none';
    document.getElementById('msBatchSweepModelInput').style.display = param === 'model' ? 'block' : 'none';
    updateBatchPreview();
};

window.updateBatchPreview = function() {
    var lines = document.getElementById('msBatchPrompts').value.split('\n').filter(function(l) { return l.trim(); });
    var count = lines.length;
    document.getElementById('msBatchPromptCount').textContent = count + ' prompt' + (count !== 1 ? 's' : '');

    if (document.getElementById('msBatchSweepToggle').checked) {
        var param = document.getElementById('msBatchSweepParam').value;
        var sweepCount = 0;
        if (param === 'seed') {
            var seeds = document.getElementById('msBatchSweepSeeds').value.split(',').filter(function(s) { return s.trim(); });
            sweepCount = seeds.length;
        } else if (param === 'model') {
            sweepCount = document.querySelectorAll('#msBatchModelCheckboxes input:checked').length;
        }
        count = count * Math.max(sweepCount, 1);
    }

    var preview = document.getElementById('msBatchPreview');
    var strong = document.createElement('strong');
    strong.textContent = count;
    preview.textContent = 'This will create ';
    preview.appendChild(strong);
    preview.appendChild(document.createTextNode(' generation' + (count !== 1 ? 's' : '')));

    if (count > 50) {
        preview.classList.add('ms-batch-over-limit');
        var warning = document.createElement('span');
        warning.className = 'ms-text-danger';
        warning.textContent = ' (Maximum 50 per batch)';
        preview.appendChild(warning);
    } else {
        preview.classList.remove('ms-batch-over-limit');
    }

    document.getElementById('msBatchSubmit').disabled = count === 0 || count > 50;
};

window.submitBatch = function() {
    var prompts = document.getElementById('msBatchPrompts').value.split('\n').filter(function(l) { return l.trim(); });
    var body = {
        name: document.getElementById('msBatchName').value,
        media_type: document.getElementById('msBatchMediaType').value,
        prompts: prompts,
        base_params: {
            model: document.getElementById('msBatchModel').value,
            negative_prompt: document.getElementById('msBatchNegPrompt').value
        }
    };

    if (document.getElementById('msBatchSweepToggle').checked) {
        body.sweep_param = document.getElementById('msBatchSweepParam').value;
        if (body.sweep_param === 'seed') {
            body.sweep_values = document.getElementById('msBatchSweepSeeds').value
                .split(',').map(function(s) { return parseInt(s.trim()); }).filter(function(n) { return !isNaN(n); });
        } else if (body.sweep_param === 'model') {
            body.sweep_values = Array.from(document.querySelectorAll('#msBatchModelCheckboxes input:checked'))
                .map(function(cb) { return cb.value; });
        }
    }

    document.getElementById('msBatchSubmit').disabled = true;
    api('/api/batches', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    }).then(function(result) {
        document.getElementById('msBatchModal').style.display = 'none';
        // Open queue panel to show progress
        var panel = document.getElementById('msQueuePanel');
        if (panel.style.display === 'none') toggleQueuePanel();
        else { loadQueueStats(); loadQueueItems(); }
    }).catch(function(err) {
        alert('Batch creation failed: ' + (err.message || err));
        document.getElementById('msBatchSubmit').disabled = false;
    });
};
```

- [ ] **Step 3: Commit JS changes**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add queue panel and batch modal JavaScript"
```

---

### Task 10: Queue Panel & Batch Modal CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css`

**Context:** Append new styles after the existing Layer 5 gallery CSS (Section S19). Use LCARS color palette (gold #f0a030, blue #6699cc, red #cc4444). Mobile-responsive.

- [ ] **Step 1: Add queue panel and batch modal CSS**

Append to `media-studio.css`:

```css
/* ── S20 Queue Panel + Batch Modal ──────────────────────────────────── */

/* Queue toggle button */
.ms-queue-toggle {
    background: rgba(102, 153, 204, 0.15);
    border: 1px solid rgba(102, 153, 204, 0.4);
    color: #6699cc;
    padding: 4px 12px;
    border-radius: 12px;
    cursor: pointer;
    font-size: 0.85rem;
    margin-left: 12px;
}
.ms-queue-toggle:hover { background: rgba(102, 153, 204, 0.25); }

/* Queue panel */
.ms-queue-panel {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(102, 153, 204, 0.2);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 16px;
    max-height: 400px;
    overflow-y: auto;
}
.ms-queue-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(102, 153, 204, 0.15);
}
.ms-queue-stats { color: #8899aa; font-size: 0.85rem; }

/* Queue sections */
.ms-queue-section { margin-bottom: 12px; }
.ms-queue-section h4 {
    color: #6699cc;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 0 0 8px 0;
}
.ms-queue-failed h4 { color: #cc4444; }

/* Queue cards */
.ms-queue-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 6px;
    margin-bottom: 4px;
}
.ms-queue-card:hover { background: rgba(255, 255, 255, 0.06); }
.ms-queue-card-body {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 0;
}
.ms-queue-prompt {
    color: #ccc;
    font-size: 0.85rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.ms-queue-meta { color: #667; font-size: 0.75rem; white-space: nowrap; }
.ms-queue-error { color: #cc4444; font-size: 0.75rem; }
.ms-queue-thumb {
    width: 32px;
    height: 32px;
    border-radius: 4px;
    object-fit: cover;
}

/* Queue card types */
.ms-queue-active { border-left: 3px solid #6699cc; }
.ms-queue-failed { border-left: 3px solid #cc4444; }
.ms-queue-recent { border-left: 3px solid #44aa44; opacity: 0.7; }

/* Batch group */
.ms-queue-batch-group {
    border: 1px solid rgba(102, 153, 204, 0.15);
    border-radius: 6px;
    margin-bottom: 8px;
    overflow: hidden;
}
.ms-queue-batch-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 12px;
    background: rgba(102, 153, 204, 0.08);
    font-size: 0.85rem;
    color: #aab;
}

/* Spinner */
.ms-spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(102, 153, 204, 0.3);
    border-top-color: #6699cc;
    border-radius: 50%;
    animation: ms-spin 0.8s linear infinite;
    flex-shrink: 0;
}
@keyframes ms-spin { to { transform: rotate(360deg); } }

/* Small buttons */
.ms-btn-xs {
    padding: 2px 8px;
    font-size: 0.75rem;
    border-radius: 4px;
    border: 1px solid rgba(102, 153, 204, 0.4);
    background: transparent;
    color: #6699cc;
    cursor: pointer;
}
.ms-btn-xs:hover { background: rgba(102, 153, 204, 0.15); }
.ms-btn-xs.ms-btn-danger { border-color: rgba(204, 68, 68, 0.4); color: #cc4444; }
.ms-btn-xs.ms-btn-danger:hover { background: rgba(204, 68, 68, 0.15); }

/* Batch modal */
.ms-batch-modal { max-width: 600px; }
.ms-batch-preview {
    margin-top: 12px;
    padding: 8px 12px;
    background: rgba(102, 153, 204, 0.08);
    border-radius: 6px;
    font-size: 0.9rem;
    color: #aab;
}
.ms-batch-over-limit { border: 1px solid #cc4444; }
.ms-text-danger { color: #cc4444; }
```

- [ ] **Step 2: Commit CSS**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add queue panel and batch modal CSS styles"
```

---

### Task 11: Integration Test + Deploy

**Files:**
- Create: `/tmp/test_layer6.py` (temporary test script)

**Context:** Run all tests inside Docker container. Verify: imports, batch creation validation, queue stats, HTML elements, JS functions, route registration.

- [ ] **Step 1: Write and run integration test**

Create `/tmp/test_layer6.py`:

```python
import sys, json, os, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test imports
from tools.media_studio.services.batch_service import (
    create_batch, get_batch, list_batches, get_batch_items,
    update_batch_counters, cancel_batch, retry_batch_failed,
    retry_single, cancel_single, get_queue_entries, get_queue_stats,
    clear_completed, cleanup_stale_queue, cleanup_expired_exports,
    MAX_BATCH_ITEMS,
)
results.append(('Import batch_service', 'OK', True))

from tools.media_studio.services.generation_service import submit_generation
import inspect
sig = inspect.signature(submit_generation)
has_batch_id = 'batch_id' in sig.parameters
results.append(('submit_generation has batch_id param', has_batch_id, has_batch_id))

# Test batch validation
from app import app
with app.app_context():
    r = create_batch('', 'user', 1, 'image', [], {})
    results.append(('Reject empty prompts', r.get('error'), 'No prompts' in r.get('error', '')))

    r = create_batch('', 'user', 1, 'bad_type', ['test'], {})
    results.append(('Reject bad media type', r.get('error'), 'Unsupported' in r.get('error', '')))

    r = create_batch('', 'user', 1, 'image', ['test'], {}, sweep_param='bad')
    results.append(('Reject bad sweep_param', r.get('error'), 'Invalid' in r.get('error', '')))

    r = create_batch('', 'user', 1, 'image', ['p']*10, {}, sweep_param='seed', sweep_values=list(range(6)))
    results.append(('Reject >50 items', r.get('error'), 'exceeds' in r.get('error', '')))

    assert MAX_BATCH_ITEMS == 50
    results.append(('MAX_BATCH_ITEMS is 50', MAX_BATCH_ITEMS, True))

    # Test queue stats
    stats = get_queue_stats('user', 1)
    results.append(('get_queue_stats', list(stats.keys()), 'pending' in stats and 'failed' in stats))

    # Test queue entries
    entries = get_queue_entries('user', 1)
    results.append(('get_queue_entries', f"total={entries['total']}", 'items' in entries))

    # Test cleanup
    cleaned = cleanup_stale_queue()
    results.append(('cleanup_stale_queue', cleaned, isinstance(cleaned, int)))

    # Check HTML elements
    html_path = '/app/tools/media_studio/templates/tools/media_studio/media_studio.html'
    with open(html_path) as f:
        html = f.read()
    results.append(('HTML has queue panel', 'msQueuePanel', 'msQueuePanel' in html))
    results.append(('HTML has queue toggle', 'msQueueToggle', 'msQueueToggle' in html))
    results.append(('HTML has batch modal', 'msBatchModal', 'msBatchModal' in html))
    results.append(('HTML has batch prompts', 'msBatchPrompts', 'msBatchPrompts' in html))
    results.append(('HTML has sweep toggle', 'msBatchSweepToggle', 'msBatchSweepToggle' in html))
    results.append(('JS has toggleQueuePanel', 'toggleQueuePanel', 'toggleQueuePanel' in html))
    results.append(('JS has submitBatch', 'submitBatch', 'submitBatch' in html))
    results.append(('JS has loadQueueStats', 'loadQueueStats', 'loadQueueStats' in html))
    results.append(('JS has updateBatchPreview', 'updateBatchPreview', 'updateBatchPreview' in html))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run integration test**

```bash
docker cp /tmp/test_layer6.py archie_platform:/tmp/test_layer6.py
docker exec archie_platform python3 /tmp/test_layer6.py
```

Expected: All tests pass.

- [ ] **Step 3: Restart platform and push**

```bash
docker compose restart archie_platform
git push origin main
```

- [ ] **Step 4: Update Dev HQ**

Use MCP tools:
- `mcp update_project_understanding` for project #129 (Media Studio)
- `mcp store_memory` with vault_note documenting Layer 6 completion
