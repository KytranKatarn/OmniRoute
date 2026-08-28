"""Batch generation service — multi-prompt batches with optional parameter sweep.

Also handles queue management: retry, cancel, cleanup, stats.
"""

import logging
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
            name = f"{len(prompts)} prompts" + (
                f" x {len(sweep_values)} {sweep_param}s" if sweep_param and sweep_values else ""
            )

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
    queue_ids = _expand_batch(
        batch_id, prompts, base_params, media_type, owner_type, owner_id, sweep_param, sweep_values
    )

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
                    owner_id,
                    media_type,
                    prompt,
                    negative_prompt=base_params.get("negative_prompt", ""),
                    params=params,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    batch_id=batch_id,
                )
                if result.get("queue_id"):
                    queue_ids.append(result["queue_id"])
        elif sweep_param == "model" and sweep_values:
            for model_val in sweep_values:
                params = {**base_params, "model": model_val}
                result = submit_generation(
                    owner_id,
                    media_type,
                    prompt,
                    negative_prompt=base_params.get("negative_prompt", ""),
                    params=params,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    batch_id=batch_id,
                )
                if result.get("queue_id"):
                    queue_ids.append(result["queue_id"])
        else:
            result = submit_generation(
                owner_id,
                media_type,
                prompt,
                negative_prompt=base_params.get("negative_prompt", ""),
                params=base_params,
                owner_type=owner_type,
                owner_id=owner_id,
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
    """Recalculate completed/failed counts and update batch status."""
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
            owner_id,
            item["media_type"],
            prompt,
            negative_prompt=negative_prompt,
            params=params,
            owner_type=owner_type,
            owner_id=owner_id,
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
        owner_id,
        item["media_type"],
        prompt,
        negative_prompt=negative_prompt,
        params=params,
        owner_type=owner_type,
        owner_id=owner_id,
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
