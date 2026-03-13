"""Generation service — orchestrates media creation through Bridge dispatch.

Submits jobs to Bridge dispatcher which handles agent selection,
GPU-tiered fleet routing, and escalation chain.
"""

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Resolve from known platform_v2 location — works both local and Docker
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")

# Capability map: media type → Bridge capability
MEDIA_TYPE_CAPABILITIES = {
    "image": "image_generation",
    "video": "video_generation",
    "audio": "audio_generation",
}

# Default generation params
DEFAULT_IMAGE_PARAMS = {
    "model": "sd_xl_base_1.0.safetensors",
    "width": 1024,
    "height": 1024,
    "steps": 25,
    "cfg": 7.0,
    "sampler": "euler_ancestral",
    "seed": -1,
}

DEFAULT_VIDEO_PARAMS = {
    "model": "sd_xl_base_1.0.safetensors",
    "motion_model": "mm_sd_v15_v2.safetensors",
    "width": 512,
    "height": 512,
    "duration": 2,
    "fps": 8,
    "steps": 20,
    "cfg": 7.0,
    "sampler": "euler_ancestral",
    "seed": -1,
    "motion_strength": 1.0,
}

# Duration to frame count mapping
DURATION_FRAMES = {2: 16, 4: 32, 6: 48}


def submit_generation(
    user_id: int,
    media_type: str,
    prompt: str,
    negative_prompt: str = "",
    params: Optional[Dict] = None,
    owner_type: str = "user",
    owner_id: Optional[int] = None,
) -> Dict:
    """Submit a generation request.

    Creates queue entry, dispatches to Bridge, returns queue_id for polling.
    """
    if media_type not in MEDIA_TYPE_CAPABILITIES:
        return {"error": f"Unsupported media type: {media_type}"}

    if media_type == "video":
        defaults = DEFAULT_VIDEO_PARAMS
    else:
        defaults = DEFAULT_IMAGE_PARAMS
    merged_params = {**defaults, **(params or {})}

    # Convert duration to frames for video
    if media_type == "video" and "duration" in merged_params:
        merged_params["frames"] = DURATION_FRAMES.get(merged_params["duration"], merged_params["duration"] * 8)

    merged_params["prompt"] = prompt
    merged_params["negative_prompt"] = negative_prompt

    # Use provided owner_type/owner_id, fallback to user
    actual_owner_type = owner_type
    actual_owner_id = owner_id if owner_id is not None else user_id

    # Create queue entry
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_generation_queue
                (owner_type, owner_id, media_type, status, params)
            VALUES (%s, %s, %s, 'pending', %s)
            RETURNING id
            """,
            (actual_owner_type, actual_owner_id, media_type, psycopg2.extras.Json(merged_params)),
        )
        queue_id = cur.fetchone()["id"]

    # Dispatch to Bridge
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        capability = MEDIA_TYPE_CAPABILITIES[media_type]

        # Build a generation-specific prompt for Bridge
        bridge_prompt = (
            f"Generate {media_type}: {prompt}\n"
            f"Model: {merged_params.get('model')}\n"
            f"Size: {merged_params.get('width')}x{merged_params.get('height')}\n"
            f"Steps: {merged_params.get('steps')}"
        )

        result = dispatcher.request_work(
            capability=capability,
            prompt=bridge_prompt,
            module_id="media_studio",
            context={
                "queue_id": queue_id,
                "params": merged_params,
                "media_type": media_type,
            },
            user_id=user_id,
            priority="normal",
            prefer_gpu=True,
            prefer_agent="Pixel",
        )

        # Update queue with Bridge job info
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'dispatched', started_at = NOW()
                WHERE id = %s
                """,
                (queue_id,),
            )

        return {
            "queue_id": queue_id,
            "status": "dispatched",
            "agent": getattr(result, "agent_name", None),
        }

    except Exception as e:
        logger.error(f"Bridge dispatch failed for queue {queue_id}: {e}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'failed', error_message = %s, completed_at = NOW()
                WHERE id = %s
                """,
                (str(e), queue_id),
            )
        return {"queue_id": queue_id, "status": "failed", "error": str(e)}


def on_generation_complete(
    queue_id: int,
    file_path: str,
    seed: Optional[int] = None,
    duration_ms: Optional[int] = None,
    provider: str = "comfyui",
    node_id: Optional[int] = None,
) -> Optional[int]:
    """Handle completed generation — save to library, update queue.

    Returns media_library ID or None on failure.
    """
    from .gallery_service import create_media_entry

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        logger.error(f"Queue entry {queue_id} not found")
        return None

    params = queue_row["params"] or {}

    # Move file to user's media directory
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    owner_dir = os.path.join(
        MEDIA_ROOT,
        f"{queue_row['owner_type']}s",
        str(queue_row["owner_id"] or "system"),
        date_str,
    )
    os.makedirs(owner_dir, exist_ok=True)

    filename = f"media_{queue_id}_{int(time.time())}.png"
    dest_path = os.path.join(owner_dir, filename)

    try:
        shutil.copy2(file_path, dest_path)
    except Exception as e:
        logger.error(f"Failed to copy media file: {e}")
        dest_path = file_path

    # Relative path for DB storage (from static/)
    rel_path = os.path.relpath(dest_path, os.path.join(MEDIA_ROOT, ".."))

    # Create thumbnail (256px wide)
    thumb_path = None
    try:
        from PIL import Image

        img = Image.open(dest_path)
        thumb_w = 256
        thumb_h = int(img.height * (thumb_w / img.width))
        img.thumbnail((thumb_w, thumb_h))
        thumb_filename = f"thumb_{filename}"
        thumb_full = os.path.join(owner_dir, thumb_filename)
        img.save(thumb_full, "PNG")
        thumb_path = os.path.relpath(thumb_full, os.path.join(MEDIA_ROOT, ".."))
    except Exception as e:
        logger.warning(f"Thumbnail generation failed: {e}")

    # Insert into media_library
    media_id = create_media_entry(
        owner_type=queue_row["owner_type"],
        owner_id=queue_row["owner_id"],
        media_type=queue_row["media_type"],
        file_path=rel_path,
        thumbnail_path=thumb_path,
        prompt=params.get("prompt"),
        negative_prompt=params.get("negative_prompt"),
        model=params.get("model"),
        provider=provider,
        node_id=node_id,
        seed=seed,
        width=params.get("width"),
        height=params.get("height"),
        duration_ms=duration_ms,
    )

    # Update queue
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'completed', result_media_id = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (media_id, queue_id),
        )

    return media_id


def on_generation_failed(queue_id: int, error: str) -> None:
    """Handle failed generation — update queue status."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'failed', error_message = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (error, queue_id),
        )


def cancel_generation(queue_id: int, user_id: int) -> bool:
    """Cancel a pending/dispatched generation. Returns True if cancelled."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE id = %s AND owner_type = 'user' AND owner_id = %s
                  AND status IN ('pending', 'dispatched')
            """,
            (queue_id, user_id),
        )
        return cur.rowcount > 0


def get_queue_status(
    owner_type: str = "user",
    owner_id: Optional[int] = None,
    limit: int = 20,
) -> list:
    """Get recent queue entries for polling."""
    with get_db_cursor() as (conn, cur):
        if owner_id:
            cur.execute(
                """
                SELECT q.*, ml.thumbnail_path
                FROM media_generation_queue q
                LEFT JOIN media_library ml ON ml.id = q.result_media_id
                WHERE q.owner_type = %s AND q.owner_id = %s
                ORDER BY q.created_at DESC
                LIMIT %s
                """,
                (owner_type, owner_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT q.*, ml.thumbnail_path
                FROM media_generation_queue q
                LEFT JOIN media_library ml ON ml.id = q.result_media_id
                ORDER BY q.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]


def get_dashboard_stats(user_id: int) -> Dict:
    """Aggregate stats for the dashboard tab."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE media_type = 'image') AS images,
                COUNT(*) FILTER (WHERE media_type = 'video') AS videos,
                COUNT(*) FILTER (WHERE media_type = 'audio') AS audio
            FROM media_library
            WHERE owner_type = 'user' AND owner_id = %s AND is_deleted = false
            """,
            (user_id,),
        )
        counts = dict(cur.fetchone())

        cur.execute(
            """
            SELECT COUNT(*) AS active
            FROM media_generation_queue
            WHERE owner_type = 'user' AND owner_id = %s
                  AND status IN ('pending', 'dispatched', 'generating')
            """,
            (user_id,),
        )
        counts["queue_active"] = cur.fetchone()["active"]

        # Recent 8 items for dashboard grid
        cur.execute(
            """
            SELECT id, media_type, file_path, thumbnail_path, prompt, created_at
            FROM media_library
            WHERE owner_type = 'user' AND owner_id = %s AND is_deleted = false
            ORDER BY created_at DESC
            LIMIT 8
            """,
            (user_id,),
        )
        counts["recent"] = [dict(row) for row in cur.fetchall()]

    return counts


def generate_via_comfyui(queue_id: int) -> Optional[int]:
    """Direct ComfyUI generation — called when Bridge assigns to local Pixel.

    Builds workflow, submits to ComfyUI API, polls for completion,
    retrieves output file, calls on_generation_complete.
    """
    from ai_bridge.comfyui_service import get_comfyui_service

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}

    # Update status
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'generating', started_at = NOW() WHERE id = %s",
            (queue_id,),
        )

    try:
        start = time.time()
        svc = get_comfyui_service()

        result = svc.generate_image(
            prompt=params.get("prompt", ""),
            model=params.get("model", "sd_xl_base_1.0.safetensors"),
            steps=params.get("steps", 25),
            width=params.get("width", 1024),
            height=params.get("height", 1024),
            cfg=params.get("cfg", 7.0),
            sampler=params.get("sampler", "euler_ancestral"),
            seed=params.get("seed", -1),
            negative_prompt=params.get("negative_prompt", ""),
        )

        duration_ms = int((time.time() - start) * 1000)

        if result.success and result.file_path:
            return on_generation_complete(
                queue_id=queue_id,
                file_path=result.file_path,
                seed=params.get("seed"),
                duration_ms=duration_ms,
                provider="comfyui",
            )
        else:
            on_generation_failed(queue_id, result.error or "Unknown ComfyUI error")
            return None

    except Exception as e:
        logger.error(f"ComfyUI generation failed for queue {queue_id}: {e}")
        on_generation_failed(queue_id, str(e))
        return None


def generate_video_via_comfyui(queue_id: int) -> Optional[int]:
    """Direct ComfyUI AnimateDiff generation — called when Bridge assigns video to local Pixel.

    Builds AnimateDiff workflow, submits to ComfyUI API, polls for completion,
    retrieves output file, calls on_generation_complete.
    """
    from ai_bridge.comfyui_service import get_comfyui_service

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'generating', started_at = NOW() WHERE id = %s",
            (queue_id,),
        )

    try:
        from .comfyui_manager import build_animatediff_workflow

        start = time.time()
        svc = get_comfyui_service()

        workflow = build_animatediff_workflow(
            prompt=params.get("prompt", ""),
            negative_prompt=params.get("negative_prompt", ""),
            model=params.get("model", "sd_xl_base_1.0.safetensors"),
            motion_model=params.get("motion_model", "mm_sd_v15_v2.safetensors"),
            width=params.get("width", 512),
            height=params.get("height", 512),
            frames=params.get("frames", 16),
            fps=params.get("fps", 8),
            seed=params.get("seed", -1),
            steps=params.get("steps", 20),
            cfg=params.get("cfg", 7.0),
            sampler=params.get("sampler", "euler_ancestral"),
            motion_strength=params.get("motion_strength", 1.0),
            ref_image=params.get("ref_image"),
        )

        # Submit workflow directly to ComfyUI /prompt API
        import requests as http_requests

        comfyui_url = svc.base_url
        resp = http_requests.post(
            f"{comfyui_url}/prompt",
            json=workflow,
            timeout=10,
        )
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        # Poll for completion (video takes longer — up to 5 min)
        import time as time_mod

        max_wait = 300
        poll_interval = 3
        elapsed = 0
        output_file = None

        while elapsed < max_wait:
            time_mod.sleep(poll_interval)
            elapsed += poll_interval
            hist_resp = http_requests.get(f"{comfyui_url}/history/{prompt_id}", timeout=10)
            if hist_resp.status_code != 200:
                continue
            hist = hist_resp.json()
            if prompt_id not in hist:
                continue
            outputs = hist[prompt_id].get("outputs", {})
            # VHS_VideoCombine outputs gifs/videos in node "7"
            node_out = outputs.get("7", {})
            gifs = node_out.get("gifs", [])
            if gifs:
                output_file = gifs[0].get("filename")
                break

        duration_ms = int((time.time() - start) * 1000)

        if output_file:
            # Download from ComfyUI
            dl_resp = http_requests.get(
                f"{comfyui_url}/view",
                params={"filename": output_file, "type": "output"},
                timeout=30,
            )
            tmp_path = os.path.join(MEDIA_ROOT, f"tmp_video_{queue_id}.mp4")
            with open(tmp_path, "wb") as f:
                f.write(dl_resp.content)

            return on_generation_complete(
                queue_id=queue_id,
                file_path=tmp_path,
                seed=params.get("seed"),
                duration_ms=duration_ms,
                provider="comfyui",
            )
        else:
            on_generation_failed(queue_id, "AnimateDiff generation timed out or produced no output")
            return None

    except Exception as e:
        logger.error(f"AnimateDiff generation failed for queue {queue_id}: {e}")
        on_generation_failed(queue_id, str(e))
        return None
