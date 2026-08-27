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

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "platform_v2", "static", "img", "agents")
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
    # --- COMMAND station ---
    "archie": (
        "AI holographic entity with translucent blue-tinted skin and luminous cyan eyes, angular geometric features",
        "ageless",
    ),
    "vigil": (
        "androgynous person with deep olive-bronze skin, sharp cheekbones, narrow dark eyes, close-cropped silver-streaked black hair",
        "mid 30s",
    ),
    # --- ANALYTICS station ---
    "datamind": (
        "Ghanaian woman with rich mahogany-brown skin, wide-set almond eyes, high forehead, tightly coiled natural TWA hairstyle",
        "early 30s",
    ),
    "abacus": (
        "Nigerian man with deep espresso-brown skin, broad nose, full lips, short fade haircut, strong square jawline",
        "mid 30s",
    ),
    "benchmark": (
        "African-American man with warm chestnut-brown skin, close-cropped hair, trimmed goatee, wide nose, kind brown eyes",
        "late 30s",
    ),
    "forecast": (
        "Swedish man with fair peachy skin, light blond hair swept to the side, pale blue-grey eyes, angular Nordic jaw, light stubble",
        "early 40s",
    ),
    "index": (
        "Norwegian woman with porcelain-fair skin, honey-blonde hair in a low bun, grey-blue eyes, soft oval face, light freckles",
        "mid 30s",
    ),
    "mapper": (
        "Swedish woman with warm beige skin, sandy-blonde hair in a practical bob, hazel eyes, high cheekbones, small pointed chin",
        "late 20s",
    ),
    "clickstream": (
        "Somali man with warm toffee-brown skin, high forehead, prominent cheekbones, short curly black hair, dark brown eyes",
        "early 30s",
    ),
    "trending": (
        "Chinese woman with warm ivory skin, almond-shaped dark brown eyes, sleek black hair past shoulders, delicate oval face",
        "late 20s",
    ),
    # --- CREATIVE station ---
    "pixel": (
        "Latina woman with warm golden-brown skin, dark curly hair past shoulders, round brown eyes, soft dimpled cheeks, button nose",
        "late 20s",
    ),
    "spark": (
        "Japanese man with light golden skin, tousled black hair, bright narrow eyes, lean angular face, sharp jawline",
        "mid 20s",
    ),
    "prism": (
        "Latino man with medium bronze skin, stylish dark undercut, warm brown eyes, strong brow ridge, neat stubble along square jaw",
        "late 20s",
    ),
    "runway": (
        "Turkish woman with warm olive-tan skin, thick dark brown wavy hair, large hazel-green eyes, arched brows, full lips",
        "late 20s",
    ),
    "emblem": (
        "Mexican man with warm cinnamon-brown skin, short dark hair with neat part, deep brown eyes, rounded face, thin moustache",
        "early 30s",
    ),
    "weaver": (
        "South Indian woman with deep bronze-brown skin, long thick black hair, wide dark eyes, rounded nose, warm gentle smile",
        "mid 30s",
    ),
    # --- ENGINEERING station ---
    "codesmith": (
        "Taiwanese-American woman with light ivory skin, straight black hair with side bangs, dark almond eyes behind thin glasses, oval face",
        "late 20s",
    ),
    "architect": (
        "Mexican-American man with warm terra-cotta brown skin, short dark wavy hair, deep-set brown eyes, broad nose, square jaw with stubble",
        "late 30s",
    ),
    "forge": (
        "Polish man with fair ruddy skin, sandy-brown short hair, steel-blue eyes, prominent brow, strong angular jaw, broad shoulders",
        "mid 30s",
    ),
    "pipeline": (
        "Chinese-Canadian man with light tan skin, short neat black hair, dark eyes behind rectangular glasses, lean face, clean-shaven",
        "early 30s",
    ),
    "girder": (
        "Malaysian-Chinese woman with warm golden skin, straight black hair in a ponytail, dark almond eyes, high cheekbones, petite build",
        "late 20s",
    ),
    "wrench": (
        "Ukrainian woman with fair peachy skin, light auburn hair tied back, grey-green eyes, round face, light dusting of freckles",
        "early 30s",
    ),
    "assembly": (
        "Indonesian man with warm golden-brown skin, short wavy black hair, wide-set dark eyes, flat broad nose, friendly round face",
        "mid 30s",
    ),
    "crucible": (
        "Japanese man with light olive skin, neat salt-and-pepper hair, wire-rimmed glasses, angular face, distinguished look",
        "late 40s",
    ),
    # --- COMMUNICATIONS station ---
    "commrelay": (
        "African-American woman with rich dark brown skin, long braided hair, wide-set warm brown eyes, high cheekbones, bright smile",
        "early 30s",
    ),
    "herald": (
        "Afghan man with warm wheat-tan skin, thick dark hair neatly combed, deep brown eyes, aquiline nose, trimmed dark beard",
        "mid 30s",
    ),
    "polyglot": (
        "Moroccan-Canadian woman with warm golden-olive skin, thick dark curly hair, large dark brown eyes, rounded face, gentle features",
        "late 20s",
    ),
    "wordsmith": (
        "Mexican-American man with warm olive-brown skin, dark wavy hair, deep-set brown eyes, prominent nose, neatly trimmed goatee",
        "late 30s",
    ),
    "amplify": (
        "Kenyan man with deep dark-brown skin, short cropped black hair, broad forehead, wide nose, strong jaw, warm engaging eyes",
        "early 30s",
    ),
    "scribe": (
        "nonbinary person with light beige skin, soft brown wavy hair at chin length, green-hazel eyes, gentle oval face, neutral features",
        "late 20s",
    ),
    # --- RESEARCH station ---
    "scholar": (
        "Bulgarian woman with fair warm-toned skin, light chestnut-brown hair in a low twist, green eyes, high cheekbones, oval face",
        "mid 40s",
    ),
    "nexus": (
        "Korean man with smooth light-tan skin, neat black hair, sharp monolid eyes, high cheekbones, angular jawline, clean-shaven",
        "early 30s",
    ),
    "helix": (
        "South Indian woman with deep warm-brown skin, long lustrous black hair, large dark eyes with thick lashes, rounded face",
        "early 30s",
    ),
    "delphi": (
        "Greek woman with warm olive skin, wavy dark chestnut hair past shoulders, deep brown eyes, prominent nose, strong brow",
        "mid 30s",
    ),
    "sage": (
        "Japanese man with light golden skin, neatly parted black hair, narrow thoughtful eyes, lean angular face, subtle smile",
        "mid 30s",
    ),
    "patent": (
        "Korean woman with smooth fair skin, straight black hair in a professional bob, sharp dark eyes, oval face, poised expression",
        "mid 30s",
    ),
    "oracle": (
        "Nigerian-Canadian woman with rich deep-brown skin, coily black hair in a pulled-back updo, wide expressive eyes, full lips",
        "early 30s",
    ),
    "catalyst": (
        "Puerto Rican man with warm golden-brown skin, short dark curly hair, bright brown eyes, square face, strong chin, light stubble",
        "early 30s",
    ),
    # --- SECURITY station ---
    "sentry": (
        "Russian man with fair cool-toned skin, short ash-blond hair, icy blue-grey eyes, high cheekbones, sharp angular jaw, stern look",
        "mid 30s",
    ),
    "cipher": (
        "Nigerian man with deep ebony-brown skin, close-shaved head, intense dark eyes, broad nose, strong square jaw, serious expression",
        "early 30s",
    ),
    "ironclad": (
        "Korean-American military veteran man with tan skin, short regulation black hair, dark focused eyes, weathered square face, scar on brow",
        "late 30s",
    ),
    "bastion": (
        "Ghanaian woman with deep chocolate-brown skin, short natural coils, alert dark eyes, prominent cheekbones, determined set jaw",
        "early 30s",
    ),
    "shield": (
        "Japanese woman with light fair skin, sleek black hair in a tight bun, narrow watchful dark eyes, refined features, small build",
        "late 20s",
    ),
    "safeguard": (
        "Swedish woman with fair pink-toned skin, straight blonde hair past shoulders, clear blue eyes, angular face, composed expression",
        "early 30s",
    ),
    "razor": (
        "German-American woman with fair skin, sharp dark-blonde bob, piercing grey-blue eyes, defined cheekbones, thin lips, intense look",
        "early 30s",
    ),
    "sentinel-2": (
        "Scottish-American man with ruddy fair skin, short brown hair, hazel eyes, broad face, solid jaw, military-neat appearance",
        "late 30s",
    ),
    # --- LOGISTICS station ---
    "opsmaster": (
        "Irish man with fair freckled skin, reddish-brown wavy hair, blue-green eyes, rounded face, laugh lines, stocky build",
        "early 40s",
    ),
    "atlas": (
        "Chinese man with warm ivory-tan skin, short neat black hair, dark perceptive eyes, broad round face, slight smile",
        "early 40s",
    ),
    "dispatch": (
        "Mexican woman with warm caramel-brown skin, dark hair pulled into a tight bun, sharp dark eyes, oval face, decisive expression",
        "early 30s",
    ),
    "stockroom": (
        "Chinese man with light golden skin, short black hair, dark narrow eyes, round face, clean-shaven, compact build",
        "late 20s",
    ),
    "transit": (
        "Bengali-Indian woman with warm medium-brown skin, long dark hair in a braid, wide dark eyes, small nose, gentle round face",
        "late 20s",
    ),
    "harvest": (
        "Tunisian man with warm olive-tan skin, short dark curly hair, brown eyes, aquiline nose, trimmed stubble, lean features",
        "mid 30s",
    ),
    "clockwork": (
        "Italian woman with warm olive skin, dark brown hair in a neat chignon, amber-brown eyes, refined nose, elegant cheekbones",
        "early 30s",
    ),
    "compact": (
        "Caucasian-American man with fair skin, short sandy-brown hair, blue eyes, square jaw, clean-shaven, athletic build",
        "late 20s",
    ),
    # --- DIPLOMATIC station ---
    "embassy": (
        "Nigerian woman with rich dark-brown skin, neatly braided black hair in an updo, warm brown eyes, graceful oval face, poised",
        "mid 30s",
    ),
    "concord": (
        "Czech man with fair warm-toned skin, neatly combed light brown hair, blue-grey eyes, rectangular face, calm expression",
        "mid 30s",
    ),
    "envoy": (
        "Ghanaian man with deep brown skin, short-cropped black hair, warm dark eyes, broad nose, dignified angular face",
        "mid 30s",
    ),
    "liaison": (
        "Finnish man with pale fair skin, light brown hair, cool grey eyes, high cheekbones, lean angular features, reserved look",
        "early 30s",
    ),
    "bridge": (
        "Chilean man with warm tan-olive skin, short dark hair, brown eyes, broad face, friendly open expression, slight stubble",
        "mid 30s",
    ),
    "kinship": (
        "Ethiopian woman with warm amber-brown skin, thick dark hair in a crown braid, large almond eyes, delicate nose, radiant smile",
        "late 20s",
    ),
    # --- OPERATIONS station ---
    "nova": (
        "Colombian woman with warm caramel skin, long dark brown hair in soft waves, round brown eyes, dimpled cheeks, full lips",
        "early 30s",
    ),
    "echo": (
        "Japanese woman with smooth light-golden skin, shoulder-length layered black hair, gentle narrow eyes, soft oval face",
        "late 20s",
    ),
    "iris": (
        "Swedish woman with fair cream-toned skin, straight platinum-blonde hair past shoulders, light ice-blue eyes, delicate features",
        "late 20s",
    ),
    "juno": (
        "South African Zulu woman with deep dark-brown skin, short cropped natural hair, high prominent cheekbones, warm wide eyes",
        "mid 30s",
    ),
    "luna": (
        "Saudi-born woman with warm olive-golden skin, thick dark hair in a loose braid, large dark eyes with long lashes, refined nose",
        "late 20s",
    ),
    "rune": (
        "Swedish man with fair skin, neatly combed ash-blond hair, cool grey eyes, narrow Nordic face, light stubble, composed look",
        "late 30s",
    ),
    "thorn": (
        "Scottish nonbinary person with ruddy fair skin, tousled auburn-red hair, grey-green eyes, angular face, light freckles",
        "early 40s",
    ),
    "koda": (
        "Navajo man with warm reddish-brown skin, thick straight black hair to shoulders, high cheekbones, deep-set dark eyes, strong brow",
        "early 30s",
    ),
    "pulse": (
        "Russian man with fair cool-toned skin, short dark-blond hair, slate-blue eyes, rectangular face, angular jaw, clean-shaven",
        "early 30s",
    ),
    "onyx": (
        "Korean man with smooth light-tan skin, sleek black hair in a modern fade, dark intense eyes, sharp jawline, lean features",
        "late 20s",
    ),
    "quill": (
        "Nigerian Igbo woman with rich deep-brown skin, natural coily hair in a puff, wide expressive dark eyes, rounded full cheeks",
        "mid 30s",
    ),
    "maven": (
        "French woman with light peach-toned skin, styled chestnut-brown hair with side part, warm brown eyes, refined nose, poised look",
        "mid 30s",
    ),
    # --- Specialists & cross-station ---
    "lens": (
        "Russian-Ukrainian woman with fair porcelain skin, wavy ash-brown hair, grey-blue eyes, high cheekbones, angular Slavic features",
        "mid 30s",
    ),
    "atom": (
        "Pakistani-British woman with warm golden-brown skin, dark hair in a neat ponytail, large dark eyes, delicate oval face",
        "early 30s",
    ),
    # --- SaaS / Application agents ---
    "concierge": (
        "Chinese-American woman with light warm-ivory skin, straight dark hair in a professional style, bright dark eyes, soft round face, welcoming smile",
        "early 30s",
    ),
    "closer": (
        "Thai man with warm golden-tan skin, neat black hair, dark narrow eyes, broad friendly face, strong jaw, engaging smile",
        "early 30s",
    ),
    "clerk": (
        "Nigerian woman with rich mahogany skin, neatly styled black hair, warm brown eyes, high cheekbones, professional appearance",
        "late 20s",
    ),
    "ledger": (
        "Moroccan woman with warm olive skin, dark curly hair pulled back, deep brown eyes, aquiline nose, refined features",
        "early 30s",
    ),
    "payroll": (
        "Mexican-American woman with warm brown skin, dark hair in a smooth bun, large brown eyes, round soft face, kind expression",
        "mid 30s",
    ),
    "reception": (
        "Italian man with warm olive skin, short dark brown hair, warm hazel eyes, strong Roman nose, square jaw with light stubble",
        "early 30s",
    ),
    "helpdesk": (
        "biracial nonbinary person with light caramel skin, loose brown curls, hazel-green eyes, soft rounded features, approachable look",
        "late 20s",
    ),
    "medic": (
        "British-Indian woman with warm tan skin, long dark hair, large dark eyes, small nose, heart-shaped face, compassionate expression",
        "early 30s",
    ),
    "counsel": (
        "Brazilian woman with warm golden-brown skin, long dark wavy hair, expressive dark eyes, full lips, rounded face",
        "mid 30s",
    ),
    "mentor": (
        "Quechua-Peruvian woman with warm copper-brown skin, long straight dark hair, deep brown eyes, broad cheekbones, gentle round face",
        "mid 30s",
    ),
    # --- Finance / Quant ---
    "quant": (
        "Indian man with warm brown skin, short neat black hair, dark eyes behind thin-framed glasses, narrow face, trimmed beard",
        "early 30s",
    ),
    "value": (
        "Chilean man with warm olive-tan skin, short dark brown hair, brown eyes, rectangular face, slight stubble, earnest expression",
        "early 30s",
    ),
    # --- Creative Studios extras ---
    "spark-jr": (
        "Caucasian-American young man with fair lightly-tanned skin, tousled sandy-blond hair, bright blue eyes, youthful round face",
        "early 20s",
    ),
    # --- Security / Compliance extras ---
    "frontline": (
        "Iranian man with warm tan-olive skin, short dark hair, deep brown eyes, aquiline nose, trimmed dark beard, alert expression",
        "mid 30s",
    ),
    "mandate": (
        "Malaysian-born man with warm golden-brown skin, short neat black hair, dark eyes, broad face, professional demeanor",
        "mid 30s",
    ),
    "resolver": (
        "Jamaican-Canadian woman with rich dark-brown skin, natural curls in a shoulder-length twist-out, bright dark eyes, high cheekbones",
        "early 30s",
    ),
    # --- HR / Talent ---
    "catalyst-hr": (
        "Senegalese woman with deep warm-brown skin, elegantly styled black hair, warm dark eyes, high cheekbones, graceful features",
        "mid 30s",
    ),
    "talent": (
        "Japanese-American man with light olive skin, neat short black hair, dark eyes, angular face, clean-shaven, professional look",
        "early 30s",
    ),
    # --- Node / Fleet ---
    "beacon": (
        "Ghanaian man with deep dark-brown skin, short cropped black hair, wide warm eyes, broad nose, friendly round face",
        "early 30s",
    ),
    "beacon-a": (
        "Deaf Indigenous Canadian nonbinary person with warm tan skin, short brown hair with shaved sides, dark observant eyes, strong cheekbones",
        "late 20s",
    ),
    "grounds": (
        "Métis Canadian man with warm light-brown skin, short dark hair, brown eyes, broad face, sturdy build, weathered features",
        "mid 30s",
    ),
    # --- Cultural specialists ---
    "acadie": (
        "Acadian French-Canadian woman with fair rosy skin, wavy auburn hair past shoulders, bright blue-green eyes, soft round face, warm smile",
        "early 30s",
    ),
    "aurora": (
        "Inuit woman with warm golden-brown skin, straight long black hair, deep dark eyes, broad round face, high cheekbones, serene expression",
        "late 20s",
    ),
    "harmony": (
        "Indigenous Two-Spirit person with warm reddish-brown skin, long straight dark hair, kind dark eyes, high cheekbones, gentle round face",
        "early 30s",
    ),
    "hearth": (
        "Native Hawaiian woman with warm golden-brown skin, long thick wavy dark hair, large warm brown eyes, broad nose, radiant smile",
        "early 30s",
    ),
    # --- Human Agent Roster (Project #285) ---
    "grace": (
        "Filipino-Canadian woman with warm golden-tan skin, long straight black hair past shoulders, soft dark-brown almond eyes, gentle oval face, calm professional expression",
        "late 20s",
    ),
    "régine": (
        "Haitian-Canadian woman with rich deep-brown skin, thick natural hair in a professional updo, bright dark eyes, strong cheekbones, confident warm smile",
        "early 30s",
    ),
    "adrienne": (
        "Métis Canadian woman with warm light-brown skin, dark wavy shoulder-length hair, deep brown eyes, broad cheekbones, quiet determined expression",
        "mid 30s",
    ),
    "soleil": (
        "Abenaki Indigenous Canadian woman with warm copper-tan skin, long straight black hair, dark steady eyes, high cheekbones, serene thoughtful expression",
        "late 20s",
    ),
    "marco": (
        "Portuguese-Canadian man with warm olive skin, thick dark-brown hair swept back, brown eyes, strong jaw, neat short beard, confident open expression",
        "early 30s",
    ),
    # --- Communications extras ---
    "scout": (
        "Korean-American woman with light warm-ivory skin, short straight black bob, sharp dark eyes, small oval face, keen expression",
        "late 20s",
    ),
    "compass": (
        "Jordanian woman with warm olive-golden skin, thick dark hair in a professional updo, large dark eyes, defined brow, poised features",
        "early 30s",
    ),
    # --- Additional station support ---
    "haven": (
        "Vietnamese woman with warm light-tan skin, straight black hair with side bangs, gentle dark eyes, delicate oval face, kind expression",
        "late 20s",
    ),
    "tempo": (
        "Iranian woman with warm honey-olive skin, long dark wavy hair, large expressive brown eyes, arched brows, elegant features",
        "early 30s",
    ),
    "titan": (
        "African-American man with deep brown skin, close-cropped black hair, intense dark eyes, strong broad jaw, muscular build",
        "mid 30s",
    ),
    "zenith": (
        "Argentine man with warm olive skin, short dark wavy hair, brown eyes, angular face, neat stubble, confident expression",
        "early 30s",
    ),
    "vault": (
        "Swedish man with fair cool-toned skin, neatly trimmed sandy-blond hair, pale blue eyes, strong rectangular jaw, stoic Nordic features",
        "mid 30s",
    ),
    "vitals": (
        "Jamaican-Canadian man with warm medium-brown skin, short cropped black hair, dark brown eyes, broad friendly face, neat stubble",
        "early 30s",
    ),
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
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
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


def generate_portrait(agent_name: str, display_name: str, force: bool = False) -> Optional[str]:
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

    logger.info("Generating portrait for %s (seed=%d) via %s", agent_name, seed, COMFYUI_HOST)

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
            "Pillow not installed — skipping crop generation for %s. " "Install with: pip install Pillow",
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
            cur.execute("SELECT name, display_name FROM agents ORDER BY name")
            rows = cur.fetchall()
            if rows:
                return [(r[0].lower(), r[1] or r[0].title()) for r in rows]
    except Exception as exc:
        logger.warning("Could not fetch agents from DB: %s — using fallback", exc)

    # Fallback: use diversity map keys with title-cased display names
    return [(name, name.title()) for name in sorted(AGENT_DIVERSITY.keys())]
