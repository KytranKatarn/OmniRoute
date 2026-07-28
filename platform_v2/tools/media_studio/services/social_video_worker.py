"""
Social Video Worker — Generation Queue Processor
=================================================
Processes items in "generating" status from social_content_queue.
Routes draft quality to local ComfyUI (Quadro M4000),
standard/high quality to RunPod cloud.
"""

import json
import logging
import os
import subprocess
import time
import uuid

import requests

from . import social_video_service as svs
from .comfyui_manager import get_best_comfyui_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VIDEO_OUTPUT_DIR = os.getenv("SOCIAL_VIDEO_DIR", os.path.join(_APP_ROOT, "static", "social_videos"))
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://archie_comfyui:8188")
LTX_WORKFLOW_PATH = os.path.join(_APP_ROOT, "static", "workflows", "ltx-video-basic.json")

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def process_queue():
    """
    Fetch up to 5 items in 'generating' status and process each.
    On unhandled exception per item, mark status as 'failed'.

    WELFARE-GATED (#5346, #5211 step 2b). This drain used to call the generators
    directly with ZERO dispatcher involvement — no welfare, C.R.E.E.D. or cost
    gating — and hardcoded its attribution to agent 13 ("P.I.X.E.L.") whether or
    not that agent had any capacity. coordinator.select_agent already scores
    candidates on stress / energy / utilisation and returns None when nothing
    qualifies, so asking it and HONOURING the answer is the whole gate.
    """
    agent = None
    try:
        from services.department_coordinator import get_coordinator

        agent = get_coordinator().select_agent("video_generation", "Creative & Design")
        if not agent:
            # DEFER. Items keep status='generating' and the next cycle re-queries
            # them, so nothing is failed and nothing is lost — the queue simply
            # waits for capacity.
            logger.info(
                "social_video_worker: no video_generation agent available (welfare) "
                "— deferring this cycle, items left untouched"
            )
            return
    except Exception as exc:
        # An ERROR is not a refusal. A coordinator fault is infrastructure, not a
        # capacity verdict; denying on it would stall ALL social video generation.
        # Fail OPEN and fall back to the historical attribution.
        logger.warning("social_video_worker: DHQ agent lookup failed (non-blocking): %s", exc)

    items = svs.get_queue_items(status="generating", limit=5)
    for item in items:
        try:
            _process_item(item, agent=agent)
        except Exception as exc:
            logger.exception("Unhandled error processing queue item %s: %s", item.get("id"), exc)
            try:
                svs.update_queue_item(
                    item["id"],
                    status="failed",
                    error_message=str(exc),
                )
            except Exception:
                logger.exception("Failed to mark item %s as failed", item.get("id"))


# ---------------------------------------------------------------------------
# Item processor
# ---------------------------------------------------------------------------


def _process_item(item, agent=None):
    """
    Process a single queue item: route to local or cloud, update status.

    ``agent`` is the DHQ-selected video_generation agent (#5346). It is threaded
    through purely so the task_execution_log row names who actually did the work
    instead of a hardcoded constant; None keeps the historical fallback.
    """
    item_id = item["id"]
    generation_params = item.get("generation_params") or {}
    if isinstance(generation_params, str):
        generation_params = json.loads(generation_params)

    quality = generation_params.get("quality", "standard")
    prompt = item.get("prompt") or generation_params.get("prompt", "")

    logger.info("Processing queue item %s (quality=%s)", item_id, quality)

    _gen_start = time.time()
    if quality == "draft":
        result = _generate_local(prompt, generation_params)
    else:
        result = _generate_cloud(prompt, generation_params)
    _gen_dur_ms = int((time.time() - _gen_start) * 1000)

    if result.get("success"):
        video_path = result["path"]
        # Derive thumbnail path alongside the video
        base, _ = os.path.splitext(video_path)
        thumb_path = base + "_thumb.jpg"
        _extract_thumbnail(video_path, thumb_path)

        update_kwargs = dict(
            status="ready",
            video_path=video_path,
            thumbnail_path=thumb_path if os.path.exists(thumb_path) else None,
            cloud_cost=result.get("cost", 0),
        )
        svs.update_queue_item(item_id, **update_kwargs)

        # Log GPU usage for cloud providers
        if result.get("provider") not in (None, "local"):
            try:
                svs.log_gpu_usage(
                    queue_item_id=item_id,
                    provider=result["provider"],
                    gpu_seconds=result.get("gpu_seconds", 0),
                    cost=result.get("cost", 0),
                )
            except Exception:
                logger.exception("Failed to log GPU usage for item %s", item_id)
    else:
        error_msg = result.get("error", "Unknown generation error")
        logger.error("Generation failed for item %s: %s", item_id, error_msg)
        svs.update_queue_item(item_id, status="failed", error_message=error_msg)

    # DHQ attribution — credited to the agent DHQ actually selected (#5346),
    # falling back to P.I.X.E.L. only when the lookup failed.
    _write_task_log(
        success=result.get("success", False),
        duration_ms=_gen_dur_ms,
        model="ltx-video-2b-v0.9" if result.get("provider") in (None, "local") else result.get("provider", "video-gen"),
        node_name=result.get("node_name"),
        agent=agent,
    )


# ---------------------------------------------------------------------------
# Local generation (ComfyUI)
# ---------------------------------------------------------------------------


def _generate_local(prompt, params):
    """
    Submit the LTX-Video workflow to local ComfyUI and poll for completion.
    Downloads the output to VIDEO_OUTPUT_DIR.

    Returns dict with keys: success, path (on success) or error (on failure).
    """
    try:
        # Load workflow
        with open(LTX_WORKFLOW_PATH, "r") as f:
            workflow = json.load(f)

        # Inject prompt into the positive CLIPTextEncode node
        for node_id, node in workflow.items():
            if node.get("class_type") == "CLIPTextEncode":
                meta_title = (node.get("_meta") or {}).get("title", "")
                if "positive" in meta_title.lower():
                    node["inputs"]["text"] = prompt
                    break

        # Fleet-aware ComfyUI routing — routes to best available GPU node
        _comfyui_url, _fleet_node_name = get_best_comfyui_url("ltx-video-2b-v0.9")
        logger.info(
            "social_video_worker: ComfyUI → %s (node=%s)",
            _comfyui_url,
            _fleet_node_name or "hub",
        )

        # Submit to ComfyUI
        resp = requests.post(
            f"{_comfyui_url}/prompt",
            json={"prompt": workflow},
            timeout=30,
        )
        resp.raise_for_status()
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            return {"success": False, "error": "ComfyUI did not return a prompt_id"}

        # Poll history
        for _ in range(120):
            time.sleep(5)
            history_resp = requests.get(f"{_comfyui_url}/history/{prompt_id}", timeout=15)
            if history_resp.status_code == 200:
                history = history_resp.json()
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    # Find first image/video output
                    for _node_id, node_out in outputs.items():
                        images = node_out.get("images") or node_out.get("gifs") or []
                        if images:
                            file_info = images[0]
                            filename = file_info.get("filename", "")
                            subfolder = file_info.get("subfolder", "")
                            # Download the file
                            dl_url = f"{_comfyui_url}/view?filename={filename}"
                            if subfolder:
                                dl_url += f"&subfolder={subfolder}"
                            dl_resp = requests.get(dl_url, timeout=60)
                            dl_resp.raise_for_status()

                            os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
                            uid_hex = uuid.uuid4().hex
                            dst = os.path.join(VIDEO_OUTPUT_DIR, f"sv_{uid_hex[:12]}.webp")
                            with open(dst, "wb") as out_f:
                                out_f.write(dl_resp.content)

                            return {
                                "success": True,
                                "path": dst,
                                "provider": "local",
                                "cost": 0,
                                "node_name": _fleet_node_name,
                            }

        return {"success": False, "error": "ComfyUI generation timed out after 10 minutes"}

    except requests.RequestException as exc:
        return {"success": False, "error": f"ComfyUI request error: {exc}"}
    except OSError as exc:
        return {"success": False, "error": f"File I/O error: {exc}"}
    except Exception as exc:
        return {"success": False, "error": f"Local generation error: {exc}"}


# ---------------------------------------------------------------------------
# Cloud generation — cascading provider chain
# ---------------------------------------------------------------------------

# Provider priority: free first, then paid. Each tried in order.
_CLOUD_PROVIDER_ORDER = [
    "google_veo",  # Free (Google AI Studio API key)
    "huggingface",  # Free (rate-limited)
    "replicate",  # Free trial credits, then pay-per-gen
    "ltx_studio",  # Free 800 credits, then paid
    "runpod",  # Pay-per-second GPU
]


def _generate_cloud(prompt, params):
    """
    Try each configured cloud video provider in priority order.
    Falls back to local ComfyUI if none are configured.

    All usage is logged to cloud_model_usage for contractor tracking.

    Returns dict with keys: success, path, provider, cost (on success)
    or error (on failure).
    """
    from .video_providers import get_provider

    errors = []

    for provider_name in _CLOUD_PROVIDER_ORDER:
        provider = get_provider(provider_name)
        if not provider or not provider.is_configured:
            continue

        logger.info("Trying cloud provider: %s", provider_name)

        try:
            result = _try_provider(provider, prompt, params)
            if result.get("success"):
                # Log to cloud_model_usage (same table as LLM contractors)
                _log_cloud_usage(
                    provider=provider_name,
                    model=result.get("model", "video-gen"),
                    cost=result.get("cost", 0),
                )
                return result
            else:
                error = result.get("error", "Unknown error")
                logger.warning("Provider %s failed: %s", provider_name, error)
                errors.append(f"{provider_name}: {error}")
        except Exception as exc:
            logger.warning("Provider %s exception: %s", provider_name, exc)
            errors.append(f"{provider_name}: {exc}")

    # No cloud provider worked — fall back to local
    if errors:
        logger.info("All cloud providers failed, falling back to local. Errors: %s", errors)
    else:
        logger.info("No cloud providers configured, falling back to local")
    return _generate_local(prompt, params)


def _try_provider(provider, prompt, params):
    """
    Submit to a provider, poll for completion, download result.
    Works with the standard VideoProvider interface (submit/poll/download).
    """
    submit_result = provider.submit(prompt, params)

    # Check for immediate failure
    if submit_result.get("status") == "failed":
        return {"success": False, "error": submit_result.get("error", "Submit failed")}

    # HuggingFace can return binary directly on submit
    if submit_result.get("_binary"):
        os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
        uid = uuid.uuid4().hex[:12]
        dst = os.path.join(VIDEO_OUTPUT_DIR, f"sv_{uid}.mp4")
        with open(dst, "wb") as f:
            f.write(submit_result["_binary"])
        return {
            "success": True,
            "path": dst,
            "provider": provider.name,
            "model": "ltx-video",
            "cost": 0,
        }

    job_id = submit_result.get("job_id")
    if not job_id:
        return {"success": False, "error": f"{provider.name} did not return a job_id"}

    # If already completed on submit (some providers)
    if submit_result.get("status") == "completed":
        url = submit_result.get("url", "")
        if url:
            return _download_video(provider, url)

    # Poll for completion (max 5 min)
    for _ in range(60):
        time.sleep(5)
        poll_result = provider.poll(job_id)
        status = poll_result.get("status", "").lower()

        if status == "completed":
            url = poll_result.get("url", "")
            if not url:
                return {"success": False, "error": f"{provider.name} completed but no URL"}
            return _download_video(provider, url)

        if status in ("failed", "error"):
            return {"success": False, "error": poll_result.get("error", "Generation failed")}

    return {"success": False, "error": f"{provider.name} timed out after 5 minutes"}


def _download_video(provider, url):
    """Download video from provider URL to local storage."""
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    uid = uuid.uuid4().hex[:12]
    ext = ".mp4" if "mp4" in url.lower() else ".webp"
    dst = os.path.join(VIDEO_OUTPUT_DIR, f"sv_{uid}{ext}")

    content = provider.download(url)
    if not content:
        return {"success": False, "error": f"Failed to download from {provider.name}"}

    with open(dst, "wb") as f:
        f.write(content)

    return {
        "success": True,
        "path": dst,
        "provider": provider.name,
        "model": "video-gen",
        "cost": 0 if provider.is_free else 0.05,  # Estimate for paid providers
    }


def _log_cloud_usage(provider, model, cost):
    """Log video generation to cloud_model_usage table (same as LLM contractors)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO cloud_model_usage
                    (model_name, provider, prompt_tokens, completion_tokens, cost_usd, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (model, provider, 0, 0, cost),
            )
    except Exception as exc:
        logger.debug("Failed to log cloud video usage: %s", exc)


# ---------------------------------------------------------------------------
# DHQ attribution
# ---------------------------------------------------------------------------


def _write_task_log(success: bool, duration_ms: int, model: str, node_name=None, agent=None):
    """Write DHQ attribution to task_execution_log — non-fatal.

    ``agent`` is the video_generation agent DHQ selected for this cycle (#5346).
    It used to be hardcoded to (13, "P.I.X.E.L.") unconditionally, which credited
    an agent that may have had no capacity and made the Token Economy's per-agent
    view fiction. P.I.X.E.L. remains the fallback for the fail-open path, where
    the coordinator lookup errored and we genuinely do not know who ran it.

    ⚠️ This is the ONLY attribution write on this path — the drain already logs
    here, so do NOT add telemetry_writer.log_marker alongside it or social video
    generation double-counts on the Token Economy / A.R.M.A.D.A. surfaces (the
    same trap documented on #5345).
    """
    try:
        from database import get_db_cursor

        node_db_id = None
        if node_name:
            try:
                with get_db_cursor() as (_, nc):
                    nc.execute(
                        "SELECT id FROM remote_nodes WHERE node_name = %s LIMIT 1",
                        (node_name,),
                    )
                    row = nc.fetchone()
                    if row:
                        node_db_id = row["id"]
            except Exception:
                pass

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """INSERT INTO task_execution_log
                   (agent_id, agent_name, model_used, duration_ms, success,
                    capability, node_used_id, module_source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    (agent or {}).get("id") or 13,
                    (agent or {}).get("name") or "P.I.X.E.L.",
                    model,
                    duration_ms,
                    success,
                    "video_generation",
                    node_db_id,
                    "media_studio",
                ),
            )
    except Exception as exc:
        logger.debug("social_video_worker: task_execution_log write failed: %s", exc)


# ---------------------------------------------------------------------------
# Thumbnail extraction
# ---------------------------------------------------------------------------


def _extract_thumbnail(video_path, thumb_path):
    """
    Extract a single frame thumbnail from the video using ffmpeg.
    Logs a warning on failure — does not raise.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vframes",
                "1",
                "-vf",
                "scale=320:-1",
                thumb_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "ffmpeg thumbnail extraction failed for %s: %s",
                video_path,
                result.stderr.decode(errors="replace"),
            )
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg thumbnail extraction timed out for %s", video_path)
    except Exception as exc:
        logger.warning("ffmpeg thumbnail extraction error for %s: %s", video_path, exc)
