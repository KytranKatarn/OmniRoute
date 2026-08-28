"""Edit service — handles media editing (inpaint, outpaint, upscale, img2img, style_transfer).

Submits edit jobs to Bridge dispatcher (Pixel agent) or runs local Lanczos upscale
directly. Supports versioned media library via parent_id chain.
"""

import base64
import logging
import os
import time
from typing import Dict, Optional, Tuple

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MEDIA_ROOT — resolve from known platform_v2 location (works in Docker too)
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")

VALID_EDIT_TYPES = {"inpaint", "outpaint", "upscale", "img2img", "style_transfer"}
VALID_OUTPAINT_DIRECTIONS = {"top", "bottom", "left", "right", "all"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def submit_edit(
    source_id: int,
    edit_type: str,
    params: Optional[Dict],
    mask_data: Optional[str],
    owner_type: str,
    owner_id: Optional[int],
) -> Dict:
    """Submit a media edit request.

    Returns {"edit_id": int, "status": "pending"|"completed"|"error", "error": str}.
    """
    params = params or {}

    # 1. Verify source exists
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM media_library WHERE id = %s AND is_deleted = false",
            (source_id,),
        )
        source_row = cur.fetchone()

    if not source_row:
        return {"error": f"Source media {source_id} not found"}

    # 2. Validate edit_type
    if edit_type not in VALID_EDIT_TYPES:
        return {"error": f"Invalid edit_type '{edit_type}'. Must be one of: {', '.join(sorted(VALID_EDIT_TYPES))}"}

    # 3. Validate params
    validation_error = _validate_edit_params(edit_type, params, mask_data)
    if validation_error:
        return validation_error

    # 4. Save mask if provided
    mask_path = None
    if mask_data:
        try:
            mask_path = _save_mask(mask_data, source_id)
        except Exception as e:
            logger.error(f"Failed to save mask for source {source_id}: {e}")
            return {"error": f"Failed to save mask: {e}"}

    # 5. Insert media_edits row
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_edits
                (source_id, edit_type, params, mask_path, status, owner_type, owner_id)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s)
            RETURNING id
            """,
            (
                source_id,
                edit_type,
                psycopg2.extras.Json(params),
                mask_path,
                owner_type,
                owner_id,
            ),
        )
        edit_id = cur.fetchone()["id"]

    # 6. Lanczos upscale — run locally, no Bridge needed
    if edit_type == "upscale" and params.get("method") == "lanczos":
        source_path = os.path.join(_PLATFORM_DIR, "static", source_row["file_path"])
        scale_factor = int(params.get("scale_factor", 2))
        try:
            output_path = _lanczos_upscale(source_path, scale_factor)
            new_media_id = on_edit_complete(edit_id, output_path)
            return {"edit_id": edit_id, "status": "completed", "media_id": new_media_id}
        except Exception as e:
            logger.error(f"Lanczos upscale failed for edit {edit_id}: {e}")
            on_edit_failed(edit_id, str(e))
            return {"edit_id": edit_id, "status": "failed", "error": str(e)}

    # 7. All other types — dispatch via Bridge
    source_abs = os.path.join(_PLATFORM_DIR, "static", source_row["file_path"])
    bridge_prompt = (
        f"Edit image ({edit_type}): {params.get('prompt', '')}\n" f"Source: {source_abs}\n" f"Edit ID: {edit_id}"
    )

    try:
        from tools.department_hq.services.department_dispatcher import dispatch_json

        dispatch_json(
            capability="image_edit",
            prompt=bridge_prompt,
            module_id="media_studio",
        )

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_edits SET status = 'dispatched' WHERE id = %s",
                (edit_id,),
            )

        return {"edit_id": edit_id, "status": "pending"}

    except Exception as e:
        logger.error(f"Bridge dispatch failed for edit {edit_id}: {e}")
        on_edit_failed(edit_id, str(e))
        return {"edit_id": edit_id, "status": "failed", "error": str(e)}


def get_edit_status(edit_id: int) -> Optional[Dict]:
    """Return edit row as dict, or None if not found."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_edits WHERE id = %s", (edit_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def get_versions(media_id: int) -> list:
    """Return all versions in the parent_id chain (oldest first).

    Walks to root, then fetches all rows with id=root OR parent_id=root,
    ordered by version ascending.
    """
    # Walk to root
    root_id = _find_root(media_id)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, file_path, media_type, version, parent_id,
                   owner_type, owner_id, created_at, thumbnail_path, prompt
            FROM media_library
            WHERE (id = %s OR parent_id = %s) AND is_deleted = false
            ORDER BY version ASC, created_at ASC
            """,
            (root_id, root_id),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows] if rows else []


def on_edit_complete(
    edit_id: int,
    file_path: str,
    seed: Optional[int] = None,
    duration_ms: Optional[int] = None,
) -> Optional[int]:
    """Handle a completed edit — version the result into media_library.

    Returns new media_library ID or None on failure.
    """
    # Load edit row
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_edits WHERE id = %s", (edit_id,))
        edit_row = cur.fetchone()

    if not edit_row:
        logger.error(f"Edit row {edit_id} not found")
        return None

    source_id = edit_row["source_id"]

    # Load source row
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_library WHERE id = %s", (source_id,))
        source_row = cur.fetchone()

    if not source_row:
        logger.error(f"Source media {source_id} not found")
        return None

    # Determine next version
    root_id, next_ver = _next_version(source_id)

    # Compute relative path for DB (from static/)
    if os.path.isabs(file_path):
        rel_path = os.path.relpath(file_path, os.path.join(MEDIA_ROOT, ".."))
    else:
        rel_path = file_path

    # Create thumbnail
    thumb_path = None
    try:
        from PIL import Image

        abs_path = file_path if os.path.isabs(file_path) else os.path.join(_PLATFORM_DIR, "static", file_path)
        img = Image.open(abs_path)
        thumb_w = 256
        thumb_h = int(img.height * (thumb_w / img.width))
        img.thumbnail((thumb_w, thumb_h))
        thumb_filename = f"thumb_edit_{edit_id}_{int(time.time())}.png"
        thumb_dir = os.path.dirname(abs_path)
        thumb_full = os.path.join(thumb_dir, thumb_filename)
        img.save(thumb_full, "PNG")
        thumb_path = os.path.relpath(thumb_full, os.path.join(MEDIA_ROOT, ".."))
    except Exception as e:
        logger.warning(f"Thumbnail generation failed for edit {edit_id}: {e}")

    # Insert new media_library row with version + parent_id
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_library
                (owner_type, owner_id, media_type, file_path, thumbnail_path,
                 parent_id, version, seed, duration_ms, provider)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'edit')
            RETURNING id
            """,
            (
                source_row["owner_type"],
                source_row["owner_id"],
                source_row["media_type"],
                rel_path,
                thumb_path,
                source_id,
                next_ver,
                seed,
                duration_ms,
            ),
        )
        new_media_id = cur.fetchone()["id"]

        # Update edit row
        cur.execute(
            """
            UPDATE media_edits
            SET status = 'completed', result_id = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (new_media_id, edit_id),
        )

    # Cleanup mask
    _cleanup_mask(edit_row.get("mask_path"))

    logger.info(f"Edit {edit_id} complete → media_library {new_media_id} (v{next_ver})")
    return new_media_id


def on_edit_failed(edit_id: int, error_message: str) -> None:
    """Mark edit as failed, cleanup mask."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_edits
            SET status = 'failed', error_message = %s, completed_at = NOW()
            WHERE id = %s
            RETURNING mask_path
            """,
            (error_message, edit_id),
        )
        row = cur.fetchone()

    if row:
        _cleanup_mask(row.get("mask_path"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_edit_params(edit_type: str, params: Dict, mask_data: Optional[str]) -> Optional[Dict]:
    """Validate edit-type-specific params. Returns {"error": "..."} or None."""
    if edit_type == "inpaint":
        if not mask_data:
            return {"error": "inpaint requires mask_data"}

    elif edit_type == "outpaint":
        direction = params.get("direction")
        if direction not in VALID_OUTPAINT_DIRECTIONS:
            return {"error": f"outpaint requires direction in {VALID_OUTPAINT_DIRECTIONS}, got: {direction!r}"}
        pixels = params.get("pixels", 0)
        try:
            pixels = int(pixels)
        except (TypeError, ValueError):
            return {"error": "outpaint 'pixels' must be an integer"}
        if not (64 <= pixels <= 512):
            return {"error": f"outpaint pixels must be 64–512, got {pixels}"}

    elif edit_type == "upscale":
        scale_factor = params.get("scale_factor")
        try:
            scale_factor = int(scale_factor)
        except (TypeError, ValueError):
            return {"error": "upscale requires scale_factor (integer)"}
        if scale_factor not in (2, 4):
            return {"error": f"upscale scale_factor must be 2 or 4, got {scale_factor}"}

    elif edit_type == "img2img":
        prompt = params.get("prompt", "").strip()
        if not prompt:
            return {"error": "img2img requires a non-empty prompt"}

    elif edit_type == "style_transfer":
        if not params.get("style_prompt") and not params.get("reference_image_id"):
            return {"error": "style_transfer requires style_prompt or reference_image_id"}

    else:
        return {"error": f"Unknown edit_type: {edit_type!r}"}

    return None


def _next_version(source_id: int) -> Tuple[int, int]:
    """Return (root_id, next_version_number) for the version chain."""
    root_id = _find_root(source_id)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT MAX(version) as max_ver
            FROM media_library
            WHERE (id = %s OR parent_id = %s) AND is_deleted = false
            """,
            (root_id, root_id),
        )
        row = cur.fetchone()
        max_ver = row["max_ver"] if row and row["max_ver"] is not None else 1

    return root_id, max_ver + 1


def _find_root(media_id: int) -> int:
    """Walk parent_id chain to find the root entry (max 50 hops for safety)."""
    current_id = media_id
    for _ in range(50):
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT parent_id FROM media_library WHERE id = %s",
                (current_id,),
            )
            row = cur.fetchone()
        if not row or row["parent_id"] is None:
            return current_id
        current_id = row["parent_id"]
    # Safety fallback — return last found id
    logger.warning(f"parent_id chain exceeded 50 hops from media {media_id}, returning {current_id}")
    return current_id


def _lanczos_upscale(source_path: str, scale_factor: int) -> str:
    """Upscale image using PIL LANCZOS filter. Returns output file path."""
    from PIL import Image

    img = Image.open(source_path)
    new_w = img.width * scale_factor
    new_h = img.height * scale_factor
    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

    base, ext = os.path.splitext(source_path)
    output_path = f"{base}_upscaled_{scale_factor}x{ext or '.png'}"
    upscaled.save(output_path, "PNG")
    logger.info(f"Lanczos upscale {scale_factor}x → {output_path}")
    return output_path


def _save_mask(mask_data: str, source_id: int) -> str:
    """Decode base64 mask and save to MEDIA_ROOT/masks/. Returns absolute path."""
    # Strip data URI prefix if present
    if "," in mask_data and mask_data.startswith("data:"):
        mask_data = mask_data.split(",", 1)[1]

    mask_bytes = base64.b64decode(mask_data)

    masks_dir = os.path.join(MEDIA_ROOT, "masks")
    os.makedirs(masks_dir, exist_ok=True)

    timestamp = int(time.time())
    filename = f"mask_{source_id}_{timestamp}.png"
    mask_path = os.path.join(masks_dir, filename)

    with open(mask_path, "wb") as f:
        f.write(mask_bytes)

    logger.debug(f"Saved mask → {mask_path}")
    return mask_path


def _cleanup_mask(mask_path: Optional[str]) -> None:
    """Remove mask file silently."""
    if not mask_path:
        return
    try:
        os.remove(mask_path)
    except Exception:
        pass
