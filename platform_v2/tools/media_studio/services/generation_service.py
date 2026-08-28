"""Generation service — orchestrates media creation through Bridge dispatch.

Submits jobs to Bridge dispatcher which handles agent selection,
GPU-tiered fleet routing, and escalation chain.
"""

import json
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

DEFAULT_AUDIO_PARAMS = {
    "audio_mode": "speech",
    "voice_id": "preset_female_1",
    "speed": 1.0,
    "language": "en",
    "duration": 5,
    "seed": -1,
}

# Audio duration presets per mode
AUDIO_DURATIONS = {
    "speech": [5, 10, 30, 60],
    "sfx": [1, 3, 5, 10],
    "music": [10, 30, 60],
}


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
    """Submit a generation request.

    Creates queue entry, dispatches to Bridge, returns queue_id for polling.
    """
    if media_type not in MEDIA_TYPE_CAPABILITIES:
        return {"error": f"Unsupported media type: {media_type}"}

    if media_type == "video":
        defaults = DEFAULT_VIDEO_PARAMS
    elif media_type == "audio":
        defaults = DEFAULT_AUDIO_PARAMS
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
                (owner_type, owner_id, media_type, status, params, batch_id)
            VALUES (%s, %s, %s, 'pending', %s, %s)
            RETURNING id
            """,
            (actual_owner_type, actual_owner_id, media_type, psycopg2.extras.Json(merged_params), batch_id),
        )
        queue_id = cur.fetchone()["id"]

    # Image gen — local ComfyUI and cloud contractors both go through the
    # media_generation_worker loop. The worker calls generate_via_comfyui()
    # which branches on params.provider (contractor) vs default (local ComfyUI).
    # This avoids the dispatcher sync path which has an unrelated unbound-local
    # bug for image gen and would block the web thread anyway.
    if media_type == "image":
        return {"queue_id": queue_id, "status": "pending"}

    # Non-comfyui (cloud providers): dispatch synchronously through Bridge
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

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
                "image_model": merged_params.get("model") if media_type == "image" else None,
            },
            user_id=user_id,
            priority="normal",
            prefer_gpu=True,
        )

        # Conditional queue update: only stamp 'dispatched' if nothing else
        # has transitioned the row. The dispatcher's _execute_comfyui path
        # calls on_generation_complete() on success, which sets 'completed'
        # and result_media_id — don't clobber that back to 'dispatched'.
        # The `WHERE ... status='pending'` clause makes this idempotent.
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'dispatched', started_at = NOW()
                WHERE id = %s AND status = 'pending'
                """,
                (queue_id,),
            )
            cur.execute(
                "SELECT status FROM media_generation_queue WHERE id = %s",
                (queue_id,),
            )
            final_status = cur.fetchone()["status"]

        return {
            "queue_id": queue_id,
            "status": final_status,
            "agent": getattr(result, "agent_name", None),
        }

    except Exception as e:
        logger.exception(f"Bridge dispatch failed for queue {queue_id}: {e}")
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

    # URL-friendly path for DB storage. Normalize to /static/<rel-to-static>
    # so avatar_url works directly as an <img src>. The old implementation
    # produced awkward `../../static/...` that only worked via the Media
    # Studio's own prefix-stripper. Everyone else (Roster, Directory,
    # Directors page) expects `/static/...` or an absolute URL.
    static_root = os.path.join(MEDIA_ROOT, "..")
    try:
        _rel = os.path.relpath(dest_path, static_root)
        if _rel.startswith(".."):
            # dest_path is outside the static tree — keep absolute ref
            rel_path = dest_path
        else:
            rel_path = "/static/" + _rel.replace(os.sep, "/")
    except ValueError:
        rel_path = dest_path

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

    # Carry classification metadata from the generation params into the
    # media_library row so the gallery asset-type tabs can filter on it.
    # Without this, asset_type set by flows (portrait/lifestyle/social) was
    # silently dropped and every asset rendered as untyped (gallery T3441).
    entry_metadata: Dict = {}
    if params.get("asset_type"):
        entry_metadata["asset_type"] = params["asset_type"]
    for _k in ("theme_id", "scene_id"):
        if params.get(_k) is not None:
            entry_metadata[_k] = params[_k]

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
        metadata=entry_metadata or None,
    )

    # Auto-tag and embed prompt
    try:
        from .tagging_service import auto_tag

        auto_tag(
            media_id,
            {
                "media_type": queue_row["media_type"],
                "model": params.get("model"),
                "provider": provider,
                "width": params.get("width"),
                "height": params.get("height"),
                "audio_mode": params.get("audio_mode"),
            },
        )
    except Exception as e:
        logger.warning(f"Auto-tag failed for media {media_id}: {e}")

    try:
        from .search_service import embed_prompt

        embed_prompt(media_id, params.get("prompt", ""))
    except Exception as e:
        logger.warning(f"Embed prompt failed for media {media_id}: {e}")

    # Update batch counters if this is a batch item
    if queue_row.get("batch_id"):
        try:
            from .batch_service import update_batch_counters

            update_batch_counters(queue_row["batch_id"])
        except Exception:
            logger.warning("batch counter update failed for queue %s", queue_id)

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
    status: Optional[str] = None,
) -> list:
    """Get recent queue entries for polling."""
    with get_db_cursor() as (conn, cur):
        conditions = ["q.owner_type = %s"]
        params: list = [owner_type]
        if owner_id:
            conditions.append("q.owner_id = %s")
            params.append(owner_id)
        if status:
            conditions.append("q.status = %s")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions)
        cur.execute(
            f"""
            SELECT q.*, ml.thumbnail_path,
                   CASE WHEN q.owner_type='agent' THEN a.display_name ELSE NULL END AS agent_name
            FROM media_generation_queue q
            LEFT JOIN media_library ml ON ml.id = q.result_media_id
            LEFT JOIN agents a ON a.id = q.owner_id AND q.owner_type = 'agent'
            {where}
            ORDER BY q.created_at DESC
            LIMIT %s
            """,
            params + [limit],
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

        # Count all active jobs (user + agent portraits)
        cur.execute(
            """
            SELECT COUNT(*) AS active
            FROM media_generation_queue
            WHERE status IN ('pending', 'dispatched', 'generating')
            """
        )
        counts["queue_active"] = cur.fetchone()["active"]

        # Active jobs with agent names for live queue widget
        cur.execute(
            """
            SELECT q.id, q.owner_type, q.owner_id, q.status, q.media_type,
                   q.params->>'prompt' AS prompt,
                   CASE WHEN q.owner_type='agent' THEN a.display_name ELSE 'User' END AS agent_name,
                   ap.canonical_image_path
            FROM media_generation_queue q
            LEFT JOIN agents a ON a.id = q.owner_id AND q.owner_type = 'agent'
            LEFT JOIN agent_portraits ap ON ap.agent_id = q.owner_id AND q.owner_type = 'agent'
            WHERE q.status IN ('pending', 'dispatched', 'generating')
            ORDER BY q.created_at ASC
            LIMIT 10
            """
        )
        counts["active_jobs"] = [dict(row) for row in cur.fetchall()]

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

        # Portraits completed but not yet approved
        cur.execute(
            """
            SELECT a.id AS agent_id, a.name, a.display_name,
                   ap.canonical_image_path, ap.id AS portrait_id,
                   ap.updated_at AS created_at
            FROM agent_portraits ap
            JOIN agents a ON a.id = ap.agent_id
            WHERE ap.canonical_image_path IS NOT NULL AND ap.approved = false
            ORDER BY ap.updated_at DESC LIMIT 5
        """
        )
        counts["pending_approvals"] = [dict(r) for r in cur.fetchall()]
        for item in counts["pending_approvals"]:
            if hasattr(item.get("created_at"), "isoformat"):
                item["created_at"] = item["created_at"].isoformat()

        # Social video queue items (draft + scheduled)
        try:
            cur.execute(
                "SELECT id, title, status, platform, scheduled_at, thumbnail_path "
                "FROM social_video_queue WHERE status IN ('draft','scheduled') "
                "ORDER BY scheduled_at ASC NULLS LAST LIMIT 5"
            )
            raw = cur.fetchall()
        except Exception:
            raw = []
        sq = []
        for r in raw:
            d = dict(r)
            if hasattr(d.get("scheduled_at"), "isoformat"):
                d["scheduled_at"] = d["scheduled_at"].isoformat()
            sq.append(d)
        counts["social_queue"] = sq

    counts["total_generated"] = counts.get("total", 0)
    return counts


def _log_image_contractor_usage(
    provider: str,
    model: Optional[str],
    cost_usd: float,
    response_ms: int,
    success: bool,
    queue_row: Dict,
    error_message: Optional[str] = None,
) -> None:
    """Append a row to cloud_model_usage for contractor image generation.

    Mirrors the dispatcher's _log_cloud_image_usage shape (task_type='image_generation')
    but attributes user_id/agent_id from the queue row's owner. Free providers
    (cost=0) still get a row so we can see provider mix in analytics. Failures
    log success=false with error_message. Inert on DB error — never blocks
    the generation pipeline.
    """
    try:
        owner_type = queue_row.get("owner_type")
        owner_id = queue_row.get("owner_id")
        user_id = owner_id if owner_type == "user" else None
        agent_id = owner_id if owner_type == "agent" else None
        model_name = model or f"{provider}_image"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO cloud_model_usage
                    (model_name, provider, prompt_tokens, completion_tokens,
                     cost_usd, response_ms, success, error_message,
                     user_id, agent_id, task_type)
                VALUES (%s, %s, 0, 0, %s, %s, %s, %s, %s, %s, 'image_generation')
                """,
                (
                    model_name,
                    provider,
                    cost_usd,
                    response_ms,
                    success,
                    (error_message or "")[:1000] if not success else None,
                    user_id,
                    agent_id,
                ),
            )
    except Exception as e:
        logger.debug("[Contractor] cost ledger insert failed: %s", e)


def _generate_via_contractor(queue_id: int, queue_row: Dict, params: Dict, provider_key: str) -> Optional[int]:
    """Generate an image via an external cloud contractor (OpenAI, Pollinations, etc.).

    Mirrors the success shape of the ComfyUI path so the rest of the pipeline
    (gallery, badges, queue status) doesn't need to differ. On success, calls
    on_generation_complete to register the file in media_library; on failure,
    marks the queue row failed with the provider's error message. Both success
    and failure paths log to cloud_model_usage for analytics (#2941).
    """
    from ai_bridge.external_providers import generate_media

    logger.info("[Contractor] Routing queue #%s to provider=%s", queue_id, provider_key)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'generating', started_at = NOW() WHERE id = %s",
            (queue_id,),
        )

    request = {
        "type": "image",
        "prompt": params.get("prompt", ""),
        "params": {
            "model": params.get("model"),
            "width": params.get("width", 1024),
            "height": params.get("height", 1024),
            "seed": params.get("seed", -1),
        },
    }

    start = time.time()
    result = generate_media(provider_key, request)
    duration_ms = int((time.time() - start) * 1000)

    if not result.get("success"):
        err = result.get("error", "Unknown contractor error")
        logger.warning("[Contractor] queue #%s failed: %s", queue_id, err)
        _log_image_contractor_usage(
            provider=provider_key,
            model=params.get("model"),
            cost_usd=0.0,
            response_ms=duration_ms,
            success=False,
            queue_row=queue_row,
            error_message=err,
        )
        on_generation_failed(queue_id, f"{provider_key}: {err}")
        return None

    meta = result.get("metadata", {})
    file_rel_path = result.get("file_path", "")
    # Strip leading slash so on_generation_complete can resolve against MEDIA_ROOT
    if file_rel_path.startswith("/"):
        file_rel_path = file_rel_path[1:]

    media_id = on_generation_complete(
        queue_id=queue_id,
        file_path=file_rel_path,
        seed=params.get("seed"),
        duration_ms=meta.get("duration_ms", duration_ms),
        provider=f"contractor:{provider_key}",
    )
    _log_image_contractor_usage(
        provider=provider_key,
        model=meta.get("model") or params.get("model"),
        cost_usd=float(meta.get("cost_usd", 0.0)),
        response_ms=int(meta.get("duration_ms", duration_ms)),
        success=True,
        queue_row=queue_row,
    )
    logger.info(
        "[Contractor] queue #%s completed: media_id=%s cost=$%.4f",
        queue_id,
        media_id,
        meta.get("cost_usd", 0.0),
    )
    return media_id


def generate_via_comfyui(queue_id: int) -> Optional[int]:
    """Direct ComfyUI generation — called when Bridge routes an image_generation job to a local ComfyUI node.

    Builds workflow, submits to ComfyUI API, polls for completion,
    retrieves output file, calls on_generation_complete.

    If params.provider is set to a non-comfyui contractor (e.g. 'pollinations',
    'openai', 'stability_ai'), routes through external_providers.generate_media
    instead of ComfyUI.
    """
    from ai_bridge.comfyui_service import get_comfyui_service

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}

    # Contractor branch — if a cloud provider was selected, route through external_providers
    # instead of ComfyUI. Local checkpoint flow continues unchanged below when no provider set.
    contractor_key = params.get("provider")
    if contractor_key and contractor_key not in ("comfyui", "ollama_diffuser"):
        # Validate against known providers before passing to adapter
        if contractor_key not in PROVIDER_DEFAULT_MODEL:
            logger.warning("[MediaStudio] Unknown provider '%s' — falling back to ComfyUI", contractor_key)
            # fall through to comfyui path
        else:
            return _generate_via_contractor(queue_id, queue_row, params, contractor_key)

    # Update status
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'generating', started_at = NOW() WHERE id = %s",
            (queue_id,),
        )

    # VRAM coordination state — set when a fleet GPU node is chosen below.
    # Starship-245/246 run Ollama with --gpus all, so ComfyUI must free that
    # node's Ollama VRAM first (via the DHQ dispatcher's node-aware swap) and
    # restore it after, in the finally. No-op on hub/contractor paths. (T3438, ADR)
    _vram_disp = None
    _vram_unloaded = []
    _vram_node_id = None

    try:
        import requests as _http
        import random

        start = time.time()
        prompt_text = params.get("prompt", "")
        model = params.get("model", "sd_xl_base_1.0.safetensors")
        steps = params.get("steps", 25)
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        cfg = params.get("cfg", 7.0)
        sampler = params.get("sampler", "euler_ancestral")
        seed = params.get("seed", -1)
        negative_prompt = params.get("negative_prompt", "")

        # Fleet-aware routing — prefer Starship RTX nodes over hub Quadro M4000.
        # Falls back to hub svc.generate_image() on any fleet failure.
        from tools.media_studio.services.comfyui_manager import (
            build_txt2img_workflow,
            get_best_comfyui_url,
        )

        fleet_url, fleet_node = get_best_comfyui_url(model_name=model)
        is_fleet = fleet_node is not None

        if fleet_node:
            with get_db_cursor(commit=True) as (_c, _cu):
                _cu.execute(
                    "UPDATE media_generation_queue SET params = params || %s::jsonb WHERE id = %s",
                    (json.dumps({"fleet_node": fleet_node}), queue_id),
                )

        # Free the chosen fleet node's Ollama VRAM before ComfyUI runs, so they
        # don't contend on the shared GPU (Starship-245/246 = Ollama --gpus all).
        # DHQ-coordinated via the dispatcher's node-aware swap; restored in finally.
        if is_fleet:
            try:
                with get_db_cursor() as (_c2, _cu2):
                    _cu2.execute(
                        "SELECT id FROM remote_nodes WHERE node_name = %s "
                        "AND gpu_available = TRUE AND status = 'online'",
                        (fleet_node,),
                    )
                    _nrow = _cu2.fetchone()
                if _nrow:
                    _vram_node_id = _nrow["id"]
                    from tools.department_hq.services.department_dispatcher import get_dispatcher

                    _vram_disp = get_dispatcher()
                    _vram_unloaded = _vram_disp._vram_swap_for_comfyui(_vram_node_id) or []
                    if _vram_unloaded:
                        logger.info(
                            "[MediaStudio] VRAM swap on %s freed %d Ollama model(s) for ComfyUI",
                            fleet_node,
                            len(_vram_unloaded),
                        )
            except Exception as _se:
                logger.warning("[MediaStudio] VRAM swap skipped on %s: %s", fleet_node, _se)

        if is_fleet:
            if seed < 0:
                seed = random.randint(0, 2**63)
            workflow = build_txt2img_workflow(
                prompt=prompt_text,
                negative_prompt=negative_prompt,
                model=model,
                width=width,
                height=height,
                seed=seed,
                steps=steps,
                cfg=float(cfg) if cfg is not None else 7.0,
                sampler=sampler,
            )
            resp = _http.post(f"{fleet_url}/prompt", json=workflow, timeout=10)
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]

            # Poll for result — 600s to allow cold SDXL model load on fleet RTX nodes
            # (sd_xl_base_1.0 ~6.9GB can take 7-8 min cold on RTX 3070 disk read)
            max_wait, poll_interval, elapsed = 600, 3, 0
            output_file = None
            while elapsed < max_wait:
                import time as _t

                _t.sleep(poll_interval)
                elapsed += poll_interval
                hist = _http.get(f"{fleet_url}/history/{prompt_id}", timeout=10).json()
                if prompt_id not in hist:
                    continue
                outputs = hist[prompt_id].get("outputs", {})
                for node_out in outputs.values():
                    imgs = node_out.get("images", [])
                    if imgs:
                        output_file = imgs[0].get("filename")
                        break
                if output_file:
                    break

            duration_ms = int((time.time() - start) * 1000)
            if output_file:
                dl = _http.get(
                    f"{fleet_url}/view",
                    params={"filename": output_file, "type": "output"},
                    timeout=30,
                )
                file_path = os.path.join(
                    MEDIA_ROOT,
                    f"images/{time.strftime('%Y-%m-%d')}/{output_file}",
                )
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as fh:
                    fh.write(dl.content)
                rel_path = f"/static/media/images/{time.strftime('%Y-%m-%d')}/{output_file}"
                return on_generation_complete(
                    queue_id=queue_id,
                    file_path=rel_path,
                    seed=seed,
                    duration_ms=duration_ms,
                    provider=f"comfyui_fleet:{fleet_node}",
                )
            else:
                logger.warning("Fleet ComfyUI timed out after %ds — model may still be loading", max_wait)
                on_generation_failed(
                    queue_id,
                    f"Fleet generation timed out after {max_wait}s — model cold-loading on node, will retry automatically",
                )
                return None

        if not is_fleet:
            svc = get_comfyui_service()
            result = svc.generate_image(
                prompt=prompt_text,
                model=model,
                steps=steps,
                width=width,
                height=height,
                cfg=float(cfg) if cfg is not None else 7.0,
                sampler=sampler,
                seed=seed,
                negative_prompt=negative_prompt,
            )
            duration_ms = int((time.time() - start) * 1000)
            if result.success and result.file_path:
                return on_generation_complete(
                    queue_id=queue_id,
                    file_path=result.file_path,
                    seed=seed,
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
    finally:
        # Restore the fleet node's Ollama GPU models after ComfyUI is done
        # (the dispatcher frees ComfyUI VRAM first). No-op on hub/contractor
        # paths where nothing was unloaded. Runs on success, timeout, and error. (T3438)
        if _vram_disp is not None and _vram_unloaded:
            try:
                _vram_disp._vram_restore_after_comfyui(_vram_unloaded, _vram_node_id)
            except Exception as _re:
                logger.warning("[MediaStudio] VRAM restore failed: %s", _re)


def generate_video_via_comfyui(queue_id: int) -> Optional[int]:
    """Direct ComfyUI AnimateDiff generation — called when Bridge routes a video_generation job to a local ComfyUI node.

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


def submit_external_video(queue_id: int, provider: str) -> Optional[str]:
    """Submit video generation to a cloud provider.

    Supports: google_veo, replicate, huggingface, ltx_studio (+ legacy Runway/Kling/Pika).
    Returns external job_id for polling, or None on failure.
    """
    from tools.media_studio.services.video_providers import get_provider

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_generation_queue
               SET status = 'dispatched', started_at = NOW(),
                   params = params || %s
               WHERE id = %s""",
            (psycopg2.extras.Json({"external_provider": provider}), queue_id),
        )

    # Try new provider system first
    vp = get_provider(provider)
    if vp and vp.is_configured:
        try:
            result = vp.submit(params.get("prompt", ""), params)
            job_id = result.get("job_id")

            if result.get("status") == "completed" and result.get("_binary"):
                # HuggingFace direct response — save immediately
                filename = f"video_{provider}_{queue_id}_{int(time.time())}.mp4"
                dest_path = os.path.join(MEDIA_ROOT, "tmp", filename)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(result["_binary"])
                on_generation_complete(queue_id=queue_id, file_path=dest_path, provider=provider)
                return job_id

            if job_id:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """UPDATE media_generation_queue
                           SET params = params || %s
                           WHERE id = %s""",
                        (psycopg2.extras.Json({"external_job_id": job_id}), queue_id),
                    )
                return job_id
            else:
                on_generation_failed(queue_id, f"Provider {provider}: {result.get('error', 'no job_id')}")
                return None
        except Exception as e:
            logger.error(f"Video provider {provider} submission failed: {e}")
            on_generation_failed(queue_id, str(e))
            return None

    # Legacy fallback for old providers (Runway, Kling, Pika)
    try:
        from ai_bridge.external_providers import call_external

        result = call_external(
            provider_key=provider,
            prompt=params.get("prompt", ""),
            model=params.get("external_model"),
        )
        if result and not result.startswith("Error"):
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE media_generation_queue
                       SET params = params || %s
                       WHERE id = %s""",
                    (psycopg2.extras.Json({"external_job_id": result}), queue_id),
                )
            return result
        else:
            on_generation_failed(queue_id, f"External provider {provider} failed: {result}")
            return None
    except Exception as e:
        logger.error(f"External video submission failed: {e}")
        on_generation_failed(queue_id, str(e))
        return None


def poll_external_video(queue_id: int) -> Optional[int]:
    """Poll a video provider for job completion.

    Uses new provider system for google_veo/replicate/huggingface/ltx_studio,
    falls back to legacy call_external for old providers.
    Returns media_library ID on success, None if still pending or failed.
    """
    from tools.media_studio.services.video_providers import get_provider

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}
    provider = params.get("external_provider")
    job_id = params.get("external_job_id")

    if not provider or not job_id:
        logger.warning(f"Queue {queue_id} missing external provider/job_id for polling")
        return None

    # Try new provider system
    vp = get_provider(provider)
    if vp:
        try:
            result = vp.poll(job_id)
            status = result.get("status", "")

            if status == "completed":
                url = result.get("url", "")
                if url:
                    file_path = download_external_result(provider, url, queue_id)
                    if file_path:
                        return on_generation_complete(queue_id=queue_id, file_path=file_path, provider=provider)
                on_generation_failed(queue_id, "Completed but no video URL")
                return None
            elif status in ("failed", "error"):
                on_generation_failed(queue_id, result.get("error", "Provider failed"))
                return None
            return None  # Still processing
        except Exception as e:
            logger.error(f"Video poll failed for {provider}: {e}")
            return None

    # Legacy fallback
    try:
        from ai_bridge.external_providers import call_external

        result = call_external(provider_key=provider, prompt=f"poll:{job_id}", model=None)
        if result and result.startswith("http"):
            file_path = download_external_result(provider, result, queue_id)
            if file_path:
                return on_generation_complete(queue_id=queue_id, file_path=file_path, provider=provider)
            on_generation_failed(queue_id, f"Failed to download from {provider}")
            return None
        elif result == "pending":
            return None
        else:
            on_generation_failed(queue_id, f"External poll failed: {result}")
            return None
    except Exception as e:
        logger.error(f"External video poll failed for queue {queue_id}: {e}")
        return None


def download_external_result(provider: str, url: str, queue_id: int) -> Optional[str]:
    """Fetch completed video from provider URL, save locally."""
    import requests as http_requests

    try:
        resp = http_requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()

        ct = resp.headers.get("content-type", "")
        ext = ".mp4"
        if "gif" in ct:
            ext = ".gif"
        elif "webm" in ct:
            ext = ".webm"

        filename = f"video_{provider}_{queue_id}_{int(time.time())}{ext}"
        dest_path = os.path.join(MEDIA_ROOT, "tmp", filename)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return dest_path
    except Exception as e:
        logger.error(f"Failed to download from {provider}: {e}")
        return None


def get_video_providers() -> list:
    """Return all available video providers with status.

    Combines new cloud providers (Google Veo, Replicate, HuggingFace, LTX Studio)
    with any legacy DB-registered providers.
    """
    from tools.media_studio.services.video_providers import get_provider_status

    providers = get_provider_status()

    # Also include legacy DB providers if any
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT provider_key, display_name, capabilities
                   FROM contractor_providers
                   WHERE is_active = true
                     AND capabilities ? 'video_generation'
                   ORDER BY display_name"""
            )
            for row in cur.fetchall():
                providers.append(
                    {
                        "name": row["provider_key"],
                        "display_name": row["display_name"],
                        "configured": True,
                        "is_free": False,
                        "models": [],
                        "legacy": True,
                    }
                )
    except Exception:
        pass  # contractor_providers may not exist

    return providers


# ─── Audio ────────────────────────────────────────────────────────────


def generate_audio(queue_id: int) -> Optional[str]:
    """Generate audio via local XTTS v2 (speech) or external provider (sfx/music).

    Called by the queue worker when processing an audio generation request.
    Returns the output file path on success, None on failure.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT prompt, params FROM media_generation_queue WHERE id = %s",
            (queue_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.error(f"Audio gen: queue entry {queue_id} not found")
            return None

    prompt = row["prompt"] if "prompt" in row.keys() else (row["params"] or {}).get("prompt", "")
    params = row["params"] or {}
    audio_mode = params.get("audio_mode", "speech")

    if audio_mode == "speech":
        return _generate_speech_local(queue_id, prompt, params)
    else:
        provider = params.get("provider", "auto")
        if provider == "local":
            logger.warning(f"No local provider for audio mode '{audio_mode}'")
            _update_queue_status(queue_id, "failed", error=f"No local provider for {audio_mode}")
            return None
        return _submit_and_poll_external_audio(queue_id, prompt, params, audio_mode)


def _generate_speech_local(queue_id: int, prompt: str, params: dict) -> Optional[str]:
    """Generate speech using local XTTS v2."""
    from .tts_service import generate_speech

    _update_queue_status(queue_id, "processing")

    result = generate_speech(
        text=prompt,
        voice_id=params.get("voice_id", "preset_female_1"),
        speed=params.get("speed", 1.0),
        language=params.get("language", "en"),
    )

    if "error" in result:
        _update_queue_status(queue_id, "failed", error=result["error"])
        return None

    file_path = result["file_path"]
    _update_queue_status(queue_id, "completed", output_path=file_path)
    return file_path


def _submit_and_poll_external_audio(queue_id: int, prompt: str, params: dict, audio_mode: str) -> Optional[str]:
    """Submit to external audio provider and poll for completion."""

    provider = params.get("provider", "auto")

    if provider == "auto":
        providers = get_audio_providers(audio_mode)
        if not providers:
            _update_queue_status(
                queue_id,
                "failed",
                error=f"No external providers available for {audio_mode}",
            )
            return None
        provider = providers[0]["provider_key"]

    _update_queue_status(queue_id, "dispatched")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_generation_queue
               SET params = params || %s
               WHERE id = %s""",
            (psycopg2.extras.Json({"external_provider": provider}), queue_id),
        )

    try:
        job_id = _call_external_audio(
            provider,
            "submit",
            {
                "prompt": prompt,
                "audio_mode": audio_mode,
                "duration": params.get("duration", 5),
            },
        )

        if not job_id:
            _update_queue_status(queue_id, "failed", error=f"External submit to {provider} failed")
            return None

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE media_generation_queue
                   SET params = params || %s
                   WHERE id = %s""",
                (psycopg2.extras.Json({"external_job_id": job_id}), queue_id),
            )

        import time as time_mod

        for _ in range(60):
            time_mod.sleep(5)
            status = _call_external_audio(provider, "poll", {"job_id": job_id})
            if status and status.get("status") == "completed":
                url = status.get("output_url")
                if url:
                    file_path = download_external_result(provider, url, queue_id)
                    if file_path:
                        _update_queue_status(queue_id, "completed", output_path=file_path)
                        return file_path
            elif status and status.get("status") == "failed":
                _update_queue_status(queue_id, "failed", error=status.get("error", "External failed"))
                return None

        _update_queue_status(queue_id, "failed", error=f"External {provider} timed out")
        return None
    except Exception as e:
        logger.error(f"External audio generation failed: {e}")
        _update_queue_status(queue_id, "failed", error=str(e))
        return None


def _call_external_audio(provider: str, action: str, params: dict):
    """Stub for external audio provider API calls.

    Returns job_id string for 'submit', status dict for 'poll'.
    Real implementations will be added when API keys are configured.
    """
    logger.info(f"External audio stub: {provider}/{action} — params={params}")
    return None


def _update_queue_status(queue_id: int, status: str, output_path: str = None, error: str = None):
    """Update queue entry status."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            if output_path:
                cur.execute(
                    """UPDATE media_generation_queue
                       SET status = %s, output_path = %s, completed_at = NOW()
                       WHERE id = %s""",
                    (status, output_path, queue_id),
                )
            elif error:
                cur.execute(
                    """UPDATE media_generation_queue
                       SET status = %s, error_message = %s, completed_at = NOW()
                       WHERE id = %s""",
                    (status, error, queue_id),
                )
            else:
                cur.execute(
                    "UPDATE media_generation_queue SET status = %s WHERE id = %s",
                    (status, queue_id),
                )
    except Exception as e:
        logger.error(f"Failed to update queue status: {e}")


def get_audio_providers(audio_mode: str = "sfx") -> list:
    """Return available external audio providers for a given mode.

    Args:
        audio_mode: 'sfx' or 'music'

    Returns:
        List of provider dicts with provider_key, display_name, capabilities
    """
    cap_key = f"audio_{audio_mode}"
    providers = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT provider_key, display_name, capabilities
                   FROM contractor_providers
                   WHERE is_active = true
                     AND capabilities ? %s
                   ORDER BY display_name""",
                (cap_key,),
            )
            for row in cur.fetchall():
                providers.append(dict(row))
    except Exception as e:
        logger.warning(f"Failed to query audio providers: {e}")
    return providers


# ─── Image providers (local checkpoints + cloud contractors) ──────────

IMAGE_CHECKPOINT_DIR = os.environ.get("COMFYUI_CHECKPOINTS_DIR", "/mnt/data2/comfyui/models/checkpoints")

LOCAL_DISPLAY_NAMES = {
    "RealVisXL_V4.0.safetensors": "RealVisXL v4 (photorealistic)",
    "sd_xl_base_1.0.safetensors": "SDXL Base 1.0",
    "sdxl_turbo.safetensors": "SDXL Turbo (fast preview)",
    "juggernautXL_v9.safetensors": "Juggernaut XL v9 (cinematic)",
    "v1-5-pruned-emaonly.safetensors": "Stable Diffusion 1.5",
    "v1-5-pruned-emaonly.ckpt": "Stable Diffusion 1.5",
    "ltx-video-2b-v0.9.safetensors": "LTX Video 2B v0.9",
    "tripo-sr.ckpt": "TripoSR (3D reconstruction)",
}

PROVIDER_DEFAULT_MODEL = {
    "openai": "gpt-image-1",
    "stability_ai": "stable-diffusion-xl-1024-v1-0",
    "replicate": "black-forest-labs/flux-schnell",
    "fal_ai": "fal-ai/flux/schnell",
    "huggingface": "stabilityai/stable-diffusion-xl-base-1.0",
    "cloudflare_ai": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "gemini": "imagen-3.0-generate-002",
    "together": "black-forest-labs/FLUX.1-schnell-Free",
    "pollinations": "flux",
    "comfyui": None,
    "ollama_diffuser": None,
}

FREE_PROVIDERS = {"comfyui", "ollama_diffuser", "pollinations", "cloudflare_ai", "together"}

# Per-provider model catalog. Each entry is (model_id, display_label).
# Only well-known, validated model IDs — silent failures from wrong IDs
# are worse than a smaller list. Add more as users validate them.
PROVIDER_MODELS = {
    "openai": [
        ("dall-e-3", "DALL-E 3"),
        ("dall-e-2", "DALL-E 2 (legacy)"),
    ],
    "gemini": [
        ("imagen-3.0-generate-002", "Imagen 3"),
    ],
    "replicate": [
        ("black-forest-labs/flux-schnell", "FLUX Schnell (fast)"),
        ("black-forest-labs/flux-dev", "FLUX Dev (quality)"),
    ],
    "fal_ai": [
        ("fal-ai/flux/schnell", "FLUX Schnell (fast)"),
        ("fal-ai/flux/dev", "FLUX Dev (quality)"),
    ],
    "stability_ai": [
        ("stable-diffusion-xl-1024-v1-0", "SDXL 1.0"),
    ],
    "huggingface": [
        ("stabilityai/stable-diffusion-xl-base-1.0", "SDXL Base"),
    ],
    "cloudflare_ai": [
        ("@cf/stabilityai/stable-diffusion-xl-base-1.0", "SDXL Base"),
        ("@cf/black-forest-labs/flux-1-schnell", "FLUX Schnell"),
    ],
    "together": [
        ("black-forest-labs/FLUX.1-schnell-Free", "FLUX Schnell (free)"),
    ],
    "pollinations": [
        ("flux", "FLUX"),
        ("flux-realism", "FLUX Realism"),
        ("flux-anime", "FLUX Anime"),
        ("turbo", "Turbo (fast)"),
    ],
}


def get_image_providers() -> dict:
    """Return merged list of local checkpoints + active image_gen contractors.

    Shape:
    {
      "auto": {"value": "", "label": "Auto (fleet-aware)"},
      "local": [{"value": "local:<filename>", "label": str, "free": True}, ...],
      "cloud_free": [{"value": "provider:<key>", "label": str, "free": True}, ...],
      "cloud_paid": [{"value": "provider:<key>", "label": str, "free": False}, ...],
    }
    """
    result = {
        "auto": {"value": "", "label": "Auto (fleet-aware)"},
        "local": [],
        "cloud_free": [],
        "cloud_paid": [],
    }

    try:
        for fname in sorted(os.listdir(IMAGE_CHECKPOINT_DIR)):
            if not (fname.endswith(".safetensors") or fname.endswith(".ckpt")):
                continue
            label = LOCAL_DISPLAY_NAMES.get(fname, fname.replace(".safetensors", "").replace(".ckpt", ""))
            result["local"].append({"value": fname, "label": f"{label} (free)", "free": True})
    except OSError as e:
        logger.warning(f"Could not list local checkpoints at {IMAGE_CHECKPOINT_DIR}: {e}")

    try:
        with get_db_cursor() as (conn, cur):
            # Active API keys — used to decide which paid providers should be
            # selectable in the dropdown. Free providers (Pollinations, etc.)
            # bypass the key check.
            cur.execute(
                "SELECT provider FROM external_api_keys "
                "WHERE is_active = true AND api_key_encrypted IS NOT NULL "
                "AND api_key_encrypted != ''"
            )
            active_keys = {r["provider"] for r in cur.fetchall()}

            cur.execute(
                """SELECT provider_key, display_name
                   FROM contractor_providers
                   WHERE is_active = true AND capabilities ? 'image_gen'
                   ORDER BY display_name"""
            )
            for row in cur.fetchall():
                pk = row["provider_key"]
                if pk in ("comfyui", "ollama_diffuser"):
                    continue
                is_free = pk in FREE_PROVIDERS
                needs_key = (not is_free) and (pk not in active_keys)
                if is_free:
                    suffix = " (free)"
                elif needs_key:
                    suffix = " ($) — needs API key"
                else:
                    suffix = " ($)"
                models = [{"value": m, "label": lbl} for m, lbl in PROVIDER_MODELS.get(pk, [])]
                entry = {
                    "value": f"provider:{pk}",
                    "label": f"{row['display_name']}{suffix}",
                    "free": is_free,
                    "needs_key": needs_key,
                    "models": models,
                    "default_model": PROVIDER_DEFAULT_MODEL.get(pk),
                }
                target = result["cloud_free"] if is_free else result["cloud_paid"]
                target.append(entry)
    except Exception as e:
        logger.warning(f"Failed to query image providers: {e}")

    return result
