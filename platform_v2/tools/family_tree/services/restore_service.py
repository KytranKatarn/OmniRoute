"""Family Tree — Photo restoration via ComfyUI upscaling.

Uses the platform's ComfyUI service to upscale/restore old photos via
RealESRGAN model-based upscaling. For heavily degraded photos, an optional
img2img pass with low denoise can clean artifacts before upscaling.

Usage:
    from .restore_service import restore_photo
    result = restore_photo(file_path="/path/to/photo.jpg", doc_id=42, user_id=1)
"""

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# ComfyUI host — same env var used by ai_bridge/comfyui_service.py
_comfyui_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
if not _comfyui_host.startswith("http"):
    _comfyui_host = f"http://{_comfyui_host}"
COMFYUI_HOST = _comfyui_host

POLL_INTERVAL = 3  # seconds
POLL_TIMEOUT = 600  # 10 min max

# Directory for restored photos (alongside originals)
RESTORE_DIR = "/mnt/archie_brain/platform_v2/uploads/family_tree/restored"
COLORIZE_DIR = "/mnt/archie_brain/platform_v2/uploads/family_tree/colorized"


@dataclass
class RestoreResult:
    """Result of a photo restoration operation."""

    success: bool
    restored_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


def _health_check() -> bool:
    """Check if ComfyUI is reachable."""
    try:
        resp = requests.get(f"{COMFYUI_HOST}/system_stats", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _upload_image_to_comfyui(file_path: str) -> Optional[str]:
    """Upload an image to ComfyUI's input directory.

    ComfyUI LoadImage node expects images in its /input folder.
    We upload via the /upload/image API and return the filename.
    """
    if not os.path.isfile(file_path):
        return None

    basename = os.path.basename(file_path)
    # Add unique prefix to avoid collisions
    unique_name = f"ft_restore_{uuid.uuid4().hex[:8]}_{basename}"

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{COMFYUI_HOST}/upload/image",
                files={"image": (unique_name, f, "image/png")},
                data={"overwrite": "true"},
                timeout=30,
            )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("name", unique_name)
        else:
            logger.error(
                "[FamilyTree Restore] Upload failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )
            return None
    except Exception as e:
        logger.error("[FamilyTree Restore] Upload error: %s", e)
        return None


def _build_restore_workflow(
    comfyui_image_name: str,
    upscale_model: str = "RealESRGAN_x4plus.pth",
) -> Dict:
    """Build a ComfyUI workflow for photo restoration.

    Uses model-based upscaling (RealESRGAN) which also cleans noise,
    compression artifacts, and sharpens details -- ideal for old photos.

    Workflow: LoadImage -> ImageUpscaleWithModel -> SaveImage
    """
    return {
        "prompt": {
            "1": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": upscale_model},
            },
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": comfyui_image_name},
            },
            "3": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": ["1", 0], "image": ["2", 0]},
            },
            "4": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["3", 0],
                    "filename_prefix": "ft_restored",
                },
            },
        }
    }


def _submit_workflow(workflow: Dict) -> Optional[str]:
    """Submit a workflow to ComfyUI and return the prompt_id."""
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow["prompt"], "client_id": client_id}

    try:
        resp = requests.post(
            f"{COMFYUI_HOST}/prompt",
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("prompt_id")
        else:
            logger.error(
                "[FamilyTree Restore] Submit failed: %s %s",
                resp.status_code,
                resp.text[:500],
            )
            return None
    except Exception as e:
        logger.error("[FamilyTree Restore] Submit error: %s", e)
        return None


def _poll_completion(prompt_id: str) -> Dict:
    """Poll ComfyUI /history/{prompt_id} until complete or timeout."""
    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        try:
            resp = requests.get(f"{COMFYUI_HOST}/history/{prompt_id}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if prompt_id in data:
                    entry = data[prompt_id]
                    status = entry.get("status", {})

                    if status.get("completed", False):
                        images = []
                        outputs = entry.get("outputs", {})
                        for node_id, node_out in outputs.items():
                            for img in node_out.get("images", []):
                                images.append(img)
                        return {"success": True, "images": images}

                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        err = str(msgs) if msgs else "Workflow execution error"
                        return {"success": False, "error": err}

        except Exception as e:
            logger.debug("[FamilyTree Restore] Poll error: %s", e)

        time.sleep(POLL_INTERVAL)

    return {"success": False, "error": f"Timed out after {POLL_TIMEOUT}s"}


def _download_image(filename: str, subfolder: str = "", img_type: str = "output") -> Optional[bytes]:
    """Download an output image from ComfyUI."""
    try:
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": img_type,
        }
        resp = requests.get(f"{COMFYUI_HOST}/view", params=params, timeout=30)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.error("[FamilyTree Restore] Download failed: %s", e)
    return None


def restore_photo(
    file_path: str,
    doc_id: int,
    user_id: int,
    upscale_model: str = "RealESRGAN_x4plus.pth",
) -> RestoreResult:
    """Restore/upscale a photo via ComfyUI.

    Args:
        file_path: Absolute path to the original photo on disk.
        doc_id: The family_documents.id for this photo.
        user_id: Owner user ID (for access control).
        upscale_model: ComfyUI upscale model name.

    Returns:
        RestoreResult with the path to the restored image.
    """
    # 1. Check ComfyUI health
    if not _health_check():
        return RestoreResult(
            success=False,
            error="ComfyUI is not available. Please try again later.",
        )

    # 2. Validate source file
    if not os.path.isfile(file_path):
        return RestoreResult(success=False, error="Original photo not found on disk.")

    # 3. Upload image to ComfyUI input directory
    comfyui_name = _upload_image_to_comfyui(file_path)
    if not comfyui_name:
        return RestoreResult(success=False, error="Failed to upload photo to ComfyUI.")

    # 4. Build and submit the restoration workflow
    workflow = _build_restore_workflow(comfyui_name, upscale_model=upscale_model)

    logger.info(
        "[FamilyTree Restore] Submitting restore for doc_id=%d, model=%s",
        doc_id,
        upscale_model,
    )

    start = time.time()
    prompt_id = _submit_workflow(workflow)
    if not prompt_id:
        return RestoreResult(success=False, error="Failed to submit workflow to ComfyUI.")

    # 5. Poll for completion
    result = _poll_completion(prompt_id)
    duration_ms = int((time.time() - start) * 1000)

    if not result["success"]:
        return RestoreResult(success=False, error=result.get("error", "Unknown error"))

    # 6. Download the restored image
    output_images = result.get("images", [])
    if not output_images:
        return RestoreResult(success=False, error="No output images from ComfyUI.")

    img_info = output_images[0]
    img_data = _download_image(
        img_info["filename"],
        img_info.get("subfolder", ""),
        img_info.get("type", "output"),
    )
    if not img_data:
        return RestoreResult(success=False, error="Failed to download restored image from ComfyUI.")

    # 7. Save restored image alongside the original
    os.makedirs(RESTORE_DIR, exist_ok=True)

    original_basename = os.path.basename(file_path)
    name, ext = os.path.splitext(original_basename)
    restored_filename = f"{name}_restored_{uuid.uuid4().hex[:8]}{ext or '.png'}"
    restored_path = os.path.join(RESTORE_DIR, restored_filename)

    with open(restored_path, "wb") as f:
        f.write(img_data)

    logger.info(
        "[FamilyTree Restore] Completed doc_id=%d in %dms -> %s",
        doc_id,
        duration_ms,
        restored_path,
    )

    return RestoreResult(
        success=True,
        restored_path=restored_path,
        metadata={
            "doc_id": doc_id,
            "upscale_model": upscale_model,
            "duration_ms": duration_ms,
            "file_size_bytes": len(img_data),
            "original_path": file_path,
        },
    )


# ---------------------------------------------------------------------------
# Photo Colorization via ComfyUI img2img
# ---------------------------------------------------------------------------


def _build_colorize_workflow(
    comfyui_image_name: str,
    checkpoint: str = "sd_xl_base_1.0.safetensors",
    denoise: float = 0.45,
) -> Dict:
    """Build a ComfyUI img2img workflow for colorizing B&W photos.

    Workflow: CheckpointLoader + LoadImage → VAEEncode → KSampler → VAEDecode → SaveImage

    Uses a low denoise strength to preserve the original structure while
    adding realistic color to a black-and-white photograph.
    """
    positive_prompt = (
        "colorize this black and white photograph, natural realistic colors, "
        "historical photo, vivid but authentic color grading, detailed skin tones, "
        "realistic environment colors"
    )
    negative_prompt = (
        "oversaturated, cartoon, painting, illustration, artifacts, blurry, " "unrealistic colors, neon, psychedelic"
    )

    return {
        "prompt": {
            # 1 — Load SDXL checkpoint
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            # 2 — Load the input image
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": comfyui_image_name},
            },
            # 3 — Encode image to latent via VAE
            "3": {
                "class_type": "VAEEncode",
                "inputs": {
                    "pixels": ["2", 0],
                    "vae": ["1", 2],
                },
            },
            # 4 — Positive CLIP prompt
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": positive_prompt,
                    "clip": ["1", 1],
                },
            },
            # 5 — Negative CLIP prompt
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["1", 1],
                },
            },
            # 6 — KSampler (img2img with low denoise)
            "6": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "latent_image": ["3", 0],
                    "seed": int(uuid.uuid4().int % (2**32)),
                    "steps": 25,
                    "cfg": 7.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "normal",
                    "denoise": denoise,
                },
            },
            # 7 — Decode latent back to image
            "7": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["6", 0],
                    "vae": ["1", 2],
                },
            },
            # 8 — Save output
            "8": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["7", 0],
                    "filename_prefix": "ft_colorized",
                },
            },
        }
    }


def colorize_photo(
    file_path: str,
    doc_id: int,
    user_id: int,
    checkpoint: str = "sd_xl_base_1.0.safetensors",
    denoise: float = 0.45,
) -> RestoreResult:
    """Colorize a black-and-white photo via ComfyUI img2img.

    Args:
        file_path: Absolute path to the original photo on disk.
        doc_id: The family_documents.id for this photo.
        user_id: Owner user ID (for access control).
        checkpoint: SDXL checkpoint filename in ComfyUI.
        denoise: Denoising strength (0.4-0.5 recommended to preserve structure).

    Returns:
        RestoreResult with the path to the colorized image.
    """
    # 1. Check ComfyUI health
    if not _health_check():
        return RestoreResult(
            success=False,
            error="ComfyUI is not available. Please try again later.",
        )

    # 2. Validate source file
    if not os.path.isfile(file_path):
        return RestoreResult(success=False, error="Original photo not found on disk.")

    # 3. Upload image to ComfyUI input directory
    comfyui_name = _upload_image_to_comfyui(file_path)
    if not comfyui_name:
        return RestoreResult(success=False, error="Failed to upload photo to ComfyUI.")

    # 4. Build and submit the colorization workflow
    workflow = _build_colorize_workflow(comfyui_name, checkpoint=checkpoint, denoise=denoise)

    logger.info(
        "[FamilyTree Colorize] Submitting colorize for doc_id=%d, checkpoint=%s, denoise=%.2f",
        doc_id,
        checkpoint,
        denoise,
    )

    start = time.time()
    prompt_id = _submit_workflow(workflow)
    if not prompt_id:
        return RestoreResult(success=False, error="Failed to submit workflow to ComfyUI.")

    # 5. Poll for completion
    result = _poll_completion(prompt_id)
    duration_ms = int((time.time() - start) * 1000)

    if not result["success"]:
        return RestoreResult(success=False, error=result.get("error", "Unknown error"))

    # 6. Download the colorized image
    output_images = result.get("images", [])
    if not output_images:
        return RestoreResult(success=False, error="No output images from ComfyUI.")

    img_info = output_images[0]
    img_data = _download_image(
        img_info["filename"],
        img_info.get("subfolder", ""),
        img_info.get("type", "output"),
    )
    if not img_data:
        return RestoreResult(success=False, error="Failed to download colorized image from ComfyUI.")

    # 7. Save colorized image to dedicated directory
    os.makedirs(COLORIZE_DIR, exist_ok=True)

    original_basename = os.path.basename(file_path)
    name, ext = os.path.splitext(original_basename)
    colorized_filename = f"{name}_colorized_{uuid.uuid4().hex[:8]}{ext or '.png'}"
    colorized_path = os.path.join(COLORIZE_DIR, colorized_filename)

    with open(colorized_path, "wb") as f:
        f.write(img_data)

    logger.info(
        "[FamilyTree Colorize] Completed doc_id=%d in %dms -> %s",
        doc_id,
        duration_ms,
        colorized_path,
    )

    return RestoreResult(
        success=True,
        restored_path=colorized_path,
        metadata={
            "doc_id": doc_id,
            "checkpoint": checkpoint,
            "denoise": denoise,
            "duration_ms": duration_ms,
            "file_size_bytes": len(img_data),
            "original_path": file_path,
        },
    )
