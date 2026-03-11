"""
Portrait Generator — ComfyUI SDXL agent portrait pipeline.

Generates photorealistic headshot portraits for all ARCHIE agents
using ComfyUI's SDXL checkpoint, then crops to 3 sizes:
  - Full portrait (512x512)
  - Avatar (128x128)
  - Icon (32x32)

Usage:
    from ai_bridge.portrait_generator import generate_portrait, generate_all_portraits

    # Single agent
    path = generate_portrait("nexus", "Jin Park")

    # All agents
    results = generate_all_portraits(force=False)
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    from PIL import Image

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_comfyui_host = os.getenv("COMFYUI_HOST", "http://192.168.1.200:8188")
if not _comfyui_host.startswith("http"):
    _comfyui_host = f"http://{_comfyui_host}"
COMFYUI_HOST = _comfyui_host.rstrip("/")

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "platform_v2", "static", "img", "agents"
)
OUTPUT_DIR = os.path.normpath(OUTPUT_DIR)

CHECKPOINT = "sd_xl_base_1.0.safetensors"
POLL_INTERVAL = 3  # seconds
POLL_TIMEOUT = 600  # 10 minutes max

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = (
    "professional headshot portrait of {description}, "
    "studio lighting, neutral background, sharp focus, "
    "photorealistic, 8k uhd, detailed skin texture, "
    "corporate profile photo, Canon EOS R5"
)

NEGATIVE_PROMPT = (
    "cartoon, anime, illustration, painting, drawing, sketch, "
    "low quality, blurry, deformed, ugly, disfigured, "
    "extra limbs, bad anatomy, watermark, text, logo, "
    "frame, border, cropped"
)

# ---------------------------------------------------------------------------
# Agent diversity map — (ethnicity/appearance, age_range)
# ---------------------------------------------------------------------------

AGENT_DIVERSITY: Dict[str, Tuple[str, str]] = {
    # Active agents
    "archie": ("AI holographic entity with translucent blue-tinted skin", "ageless"),
    "pixel": ("Latina woman with warm brown skin and dark curly hair", "late 20s"),
    "nexus": ("Korean man with sharp features and black hair", "early 30s"),
    "scholar": ("Eastern European woman with light brown hair and green eyes", "mid 40s"),
    "spark": ("Japanese woman with short black hair and bright eyes", "mid 20s"),
    "prism": (
        "Latino nonbinary person with medium brown skin and stylish undercut",
        "late 20s",
    ),
    "lens": ("Russian man with fair skin, light stubble, and blue eyes", "mid 30s"),
    "atom": ("South Asian man with dark brown skin and neatly trimmed beard", "early 30s"),
    "wordsmith": ("Latino man with olive skin and dark wavy hair", "late 30s"),
    "opsmaster": (
        "Irish man with fair freckled skin and reddish-brown hair",
        "early 40s",
    ),
    "commrelay": (
        "West African woman with rich dark skin and braided hair",
        "early 30s",
    ),
    "datamind": ("Ghanaian man with dark skin and clean-shaven head", "mid 30s"),
    "codesmith": ("East Asian woman with straight black hair and glasses", "late 20s"),
    "vigil": (
        "ethnically ambiguous person with olive skin and intense dark eyes",
        "mid 30s",
    ),
    "architect": (
        "Mexican-American man with brown skin and short dark hair",
        "late 30s",
    ),
    # Reserve agents
    "atlas": ("Chinese man with tan skin and short black hair", "early 40s"),
    "cipher": ("Nigerian woman with dark brown skin and natural afro", "late 20s"),
    "delphi": ("Greek woman with olive skin and wavy dark hair", "mid 30s"),
    "echo": ("Japanese man with neat black hair and slim features", "late 20s"),
    "forge": ("Polish man with fair skin and strong jaw", "mid 30s"),
    "helix": ("Indian woman with deep brown skin and long dark hair", "early 30s"),
    "iris": ("Swedish woman with blonde hair and light blue eyes", "late 20s"),
    "juno": ("South African woman with dark brown skin and short natural hair", "mid 30s"),
    "koda": (
        "Native American man with warm brown skin and high cheekbones",
        "early 30s",
    ),
    "luna": ("Middle Eastern woman with warm olive skin and dark eyes", "late 20s"),
    "maven": ("French man with light skin and neatly styled brown hair", "mid 30s"),
    "nova": ("Colombian woman with caramel skin and dark brown hair", "early 30s"),
    "onyx": ("Korean woman with fair skin and sleek black bob haircut", "late 20s"),
    "pulse": ("Russian woman with pale skin and auburn hair", "early 30s"),
    "quill": ("Nigerian man with dark skin and short cropped hair", "mid 30s"),
    "rune": ("Scandinavian man with light blond hair and grey eyes", "late 30s"),
    "sage": ("Japanese woman with delicate features and shoulder-length black hair", "mid 30s"),
    "thorn": ("Scottish man with ruddy complexion and short red hair", "early 40s"),
}

# ---------------------------------------------------------------------------
# ComfyUI workflow builder
# ---------------------------------------------------------------------------


def _build_workflow(positive_prompt: str, negative_prompt: str, seed: int) -> dict:
    """Build an SDXL txt2img workflow for the ComfyUI API."""
    return {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": CHECKPOINT},
            },
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 512, "height": 512, "batch_size": 1},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": positive_prompt,
                    "clip": ["1", 1],
                },
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["1", 1],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["2", 0],
                    "seed": seed,
                    "steps": 30,
                    "cfg": 7.0,
                    "sampler_name": "euler_ancestral",
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["5", 0],
                    "vae": ["1", 2],
                },
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["6", 0],
                    "filename_prefix": "archie_portrait",
                },
            },
        }
    }


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def _post_json(url: str, data: dict, timeout: int = 30) -> dict:
    """POST JSON to a URL and return the parsed response."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: int = 30) -> dict:
    """GET JSON from a URL."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_file(url: str, dest: str, timeout: int = 60) -> None:
    """Download a file from URL to local path."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------


def generate_portrait(
    agent_name: str, display_name: str, force: bool = False
) -> Optional[str]:
    """
    Generate a portrait for a single agent via ComfyUI SDXL.

    Args:
        agent_name: Lowercase code name (e.g. "nexus").
        display_name: Human-readable name for the prompt (e.g. "Jin Park").
        force: If True, regenerate even if file exists.

    Returns:
        Path to the generated portrait, or None on failure.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    portrait_path = os.path.join(OUTPUT_DIR, f"{agent_name}.png")
    if os.path.exists(portrait_path) and not force:
        logger.info("Portrait already exists for %s, skipping", agent_name)
        return None

    # Build prompt description
    diversity = AGENT_DIVERSITY.get(agent_name.lower())
    if diversity:
        ethnicity, age_range = diversity
        description = f"a {age_range} {ethnicity} named {display_name}"
    else:
        description = f"a professional person named {display_name}"

    positive = PROMPT_TEMPLATE.format(description=description)
    seed = hash(agent_name.lower()) % (2**32)

    workflow = _build_workflow(positive, NEGATIVE_PROMPT, seed)

    logger.info(
        "Generating portrait for %s (seed=%d) via %s", agent_name, seed, COMFYUI_HOST
    )

    # Submit to ComfyUI
    try:
        result = _post_json(f"{COMFYUI_HOST}/prompt", workflow, timeout=30)
    except (urllib.error.URLError, OSError) as exc:
        logger.error("Failed to submit prompt for %s: %s", agent_name, exc)
        return None

    prompt_id = result.get("prompt_id")
    if not prompt_id:
        logger.error("No prompt_id returned for %s: %s", agent_name, result)
        return None

    # Poll for completion
    elapsed = 0
    output_images = None
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        try:
            history = _get_json(f"{COMFYUI_HOST}/history/{prompt_id}", timeout=15)
        except (urllib.error.URLError, OSError):
            continue

        entry = history.get(prompt_id)
        if not entry:
            continue

        status = entry.get("status", {})
        if status.get("status_str") == "error":
            logger.error("ComfyUI generation failed for %s: %s", agent_name, status)
            return None

        outputs = entry.get("outputs", {})
        # Find the SaveImage node output
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                output_images = node_output["images"]
                break

        if output_images:
            break

    if not output_images:
        logger.error("Timed out waiting for portrait of %s", agent_name)
        return None

    # Download the image
    img_info = output_images[0]
    filename = img_info["filename"]
    subfolder = img_info.get("subfolder", "")
    img_type = img_info.get("type", "output")

    view_url = (
        f"{COMFYUI_HOST}/view?"
        f"filename={urllib.request.quote(filename)}"
        f"&subfolder={urllib.request.quote(subfolder)}"
        f"&type={urllib.request.quote(img_type)}"
    )

    try:
        _download_file(view_url, portrait_path, timeout=60)
    except (urllib.error.URLError, OSError) as exc:
        logger.error("Failed to download portrait for %s: %s", agent_name, exc)
        return None

    logger.info("Portrait saved: %s", portrait_path)

    # Generate cropped sizes
    _generate_crops(agent_name, portrait_path)

    return portrait_path


def _generate_crops(agent_name: str, portrait_path: str) -> None:
    """
    Create avatar (128x128) and icon (32x32) crops from the full portrait.

    Requires Pillow. If not installed, logs a warning and skips.
    """
    if not HAS_PILLOW:
        logger.warning(
            "Pillow not installed — skipping crop generation for %s. "
            "Install with: pip install Pillow",
            agent_name,
        )
        return

    try:
        img = Image.open(portrait_path)

        # Avatar — 128x128
        avatar = img.resize((128, 128), Image.LANCZOS)
        avatar_path = os.path.join(OUTPUT_DIR, f"{agent_name}_avatar.png")
        avatar.save(avatar_path, "PNG")
        logger.info("Avatar saved: %s", avatar_path)

        # Icon — 32x32
        icon = img.resize((32, 32), Image.LANCZOS)
        icon_path = os.path.join(OUTPUT_DIR, f"{agent_name}_icon.png")
        icon.save(icon_path, "PNG")
        logger.info("Icon saved: %s", icon_path)

    except Exception as exc:
        logger.error("Failed to generate crops for %s: %s", agent_name, exc)


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------


def generate_all_portraits(force: bool = False) -> Dict:
    """
    Generate portraits for all agents found in the database.

    Returns:
        dict with keys: success (list), failed (list), skipped (list)
    """
    results: Dict = {"success": [], "failed": [], "skipped": []}

    agents = _get_all_agents()
    if not agents:
        logger.warning("No agents found — nothing to generate")
        return results

    total = len(agents)
    logger.info("Generating portraits for %d agents (force=%s)", total, force)

    for i, (name, display_name) in enumerate(agents, 1):
        logger.info("[%d/%d] Processing %s (%s)", i, total, name, display_name)

        portrait_path = os.path.join(OUTPUT_DIR, f"{name}.png")
        if os.path.exists(portrait_path) and not force:
            logger.info("Skipping %s — portrait exists", name)
            results["skipped"].append(name)
            continue

        path = generate_portrait(name, display_name, force=force)
        if path:
            results["success"].append(name)
        else:
            results["failed"].append(name)

    logger.info(
        "Portrait generation complete: %d success, %d failed, %d skipped",
        len(results["success"]),
        len(results["failed"]),
        len(results["skipped"]),
    )
    return results


def _get_all_agents() -> list:
    """
    Fetch all agents from the database.

    Returns list of (name, display_name) tuples.
    Falls back to AGENT_DIVERSITY keys if DB is unavailable.
    """
    try:
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT name, display_name FROM agents ORDER BY name"
            )
            rows = cur.fetchall()
            if rows:
                return [(r[0].lower(), r[1] or r[0].title()) for r in rows]
    except Exception as exc:
        logger.warning("Could not fetch agents from DB: %s — using fallback", exc)

    # Fallback: use diversity map keys with title-cased display names
    return [(name, name.title()) for name in sorted(AGENT_DIVERSITY.keys())]
