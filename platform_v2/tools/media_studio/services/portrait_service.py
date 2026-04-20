"""Portrait service — agent face generation with IP-Adapter consistency.

Manages canonical portraits, face-consistent variants, approval workflow,
and environment art for hub/node backgrounds.
"""

import base64
import logging
import os
from typing import Dict, List, Optional

from database import get_db_cursor
from services import agent_service

logger = logging.getLogger(__name__)

# Vision-model prompt for deriving an identity_prompt from an imported face.
# Used by the upload flow (#1917) so imported portraits can participate in
# IP-Adapter variant generation — which requires a prompt paired with the
# canonical face reference.
VISION_DESCRIBE_PROMPT = (
    "Describe the person in this portrait for use as a Stable Diffusion / "
    "IP-Adapter prompt. Focus on observable features:\n"
    '- Age range (e.g., "mid-30s", "late 20s")\n'
    "- Ethnicity / appearance (observational, respectful)\n"
    "- Hair (color, length, style)\n"
    "- Facial features (beard, glasses, distinguishing marks)\n"
    "- Eye color if visible\n"
    "- Clothing / attire if visible\n\n"
    "Output ONLY a single comma-separated description phrase, no preamble, "
    "no bullet points. Example output:\n"
    '"mid-30s East Asian man with short black hair, clean-shaven, warm '
    "brown eyes, wearing a dark navy uniform, confident expression, "
    'photorealistic"'
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")
PORTRAITS_DIR = os.path.join(MEDIA_ROOT, "portraits")

# Import diversity map from existing portrait generator
try:
    from ai_bridge.portrait_generator import AGENT_DIVERSITY
except ImportError:
    AGENT_DIVERSITY = {}


def get_all_agent_portraits() -> List[Dict]:
    """Get all agents with their portrait status for the grid view."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.avatar_url,
                   p.id AS portrait_id, p.canonical_image_path, p.identity_prompt,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags, p.updated_at
            FROM agents a
            LEFT JOIN agent_portraits p ON p.agent_id = a.id
            WHERE a.status = 'active'
            ORDER BY a.display_name
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        if not row.get("identity_prompt") and row["name"] in AGENT_DIVERSITY:
            desc, age = AGENT_DIVERSITY[row["name"]]
            row["diversity_desc"] = desc
            row["diversity_age"] = age
        row["has_portrait"] = bool(row.get("canonical_image_path"))
        row["has_ipadapter"] = bool(row.get("ip_adapter_ref_path"))

    return rows


def get_agent_portrait(agent_id: int) -> Optional[Dict]:
    """Get single agent portrait detail with variant gallery."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.avatar_url,
                   p.id AS portrait_id, p.canonical_image_path, p.identity_prompt,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags, p.created_at, p.updated_at
            FROM agents a
            LEFT JOIN agent_portraits p ON p.agent_id = a.id
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        result = dict(row)

        cur.execute(
            """
            SELECT id, file_path, thumbnail_path, prompt, seed,
                   width, height, metadata, created_at
            FROM media_library
            WHERE owner_type = 'agent' AND owner_id = %s
                  AND media_type = 'image' AND is_deleted = false
            ORDER BY created_at DESC
            """,
            (agent_id,),
        )
        result["variants"] = [dict(v) for v in cur.fetchall()]

        if not result.get("identity_prompt") and result["name"] in AGENT_DIVERSITY:
            desc, age = AGENT_DIVERSITY[result["name"]]
            result["default_identity_prompt"] = _build_identity_prompt(result["display_name"], desc, age)

        return result


def _build_identity_prompt(display_name: str, desc: str, age: str) -> str:
    """Build a detailed portrait prompt from diversity data."""
    return (
        f"professional portrait photograph of {display_name}, {desc}, {age}, "
        f"wearing a futuristic LCARS-style uniform, dark background with subtle "
        f"purple and blue lighting, sharp focus, 8k, detailed face, "
        f"photorealistic, studio lighting"
    )


def generate_canonical(agent_id: int, prompt_override: Optional[str] = None) -> Dict:
    """Generate initial canonical portrait without IP-Adapter.

    Uses identity prompt from agent_portraits or diversity map fallback.
    Submits through generation_service for Bridge dispatch.
    """
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.name, a.display_name,
                   p.identity_prompt, p.face_seed
            FROM agents a
            LEFT JOIN agent_portraits p ON p.agent_id = a.id
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Agent not found"}

    agent_name = row["name"]
    display_name = row["display_name"]
    identity_prompt = prompt_override or row.get("identity_prompt")

    if not identity_prompt:
        if agent_name in AGENT_DIVERSITY:
            desc, age = AGENT_DIVERSITY[agent_name]
            identity_prompt = _build_identity_prompt(display_name, desc, age)
        else:
            identity_prompt = _build_identity_prompt(display_name, "person with distinctive features", "adult")

    _ensure_portrait_record(agent_id, identity_prompt)
    seed = row.get("face_seed") or -1

    return submit_generation(
        user_id=None,
        media_type="image",
        prompt=identity_prompt,
        negative_prompt="blurry, deformed, extra limbs, bad anatomy, text, watermark, low quality",
        params={
            "model": "sd_xl_base_1.0.safetensors",
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "cfg": 7.0,
            "sampler": "euler_ancestral",
            "seed": seed,
        },
        owner_type="agent",
        owner_id=agent_id,
    )


def generate_variant(agent_id: int, style: Optional[str] = None, pose: Optional[str] = None) -> Dict:
    """Generate face-consistent variant using IP-Adapter + canonical ref.

    Requires approved canonical with ip_adapter_ref_path.
    """
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT p.identity_prompt, p.ip_adapter_ref_path, p.canonical_image_path,
                   p.face_seed, p.approved, a.name, a.display_name
            FROM agent_portraits p
            JOIN agents a ON a.id = p.agent_id
            WHERE p.agent_id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"error": "No portrait record for this agent"}
    if not row["approved"]:
        return {"error": "Canonical portrait must be approved before generating variants"}
    if not row["ip_adapter_ref_path"]:
        return {"error": "IP-Adapter reference not extracted yet. Approve canonical first."}

    base_prompt = row["identity_prompt"] or ""
    if style:
        base_prompt += f", {style} style"
    if pose:
        base_prompt += f", {pose} pose"

    return submit_generation(
        user_id=None,
        media_type="image",
        prompt=base_prompt,
        negative_prompt="blurry, deformed, extra limbs, bad anatomy, text, watermark",
        params={
            "model": "sd_xl_base_1.0.safetensors",
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "cfg": 7.0,
            "sampler": "euler_ancestral",
            "seed": -1,
            "ip_adapter_ref": row["ip_adapter_ref_path"],
            "ip_adapter_weight": 0.85,
        },
        owner_type="agent",
        owner_id=agent_id,
    )


def approve_canonical(agent_id: int, media_id: int) -> Dict:
    """Approve image as canonical portrait, update agent avatar.

    Sets canonical_image_path, extracts face_seed from media metadata,
    and updates agent avatar_url.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            SELECT file_path, thumbnail_path, seed, metadata
            FROM media_library
            WHERE id = %s AND owner_type = 'agent' AND owner_id = %s
                  AND is_deleted = false
            """,
            (media_id, agent_id),
        )
        media = cur.fetchone()
        if not media:
            return {"error": "Media not found or not owned by this agent"}

        file_path = media["file_path"]
        seed = media.get("seed")

        cur.execute(
            """
            INSERT INTO agent_portraits (agent_id, canonical_image_path, face_seed, approved, updated_at)
            VALUES (%s, %s, %s, true, NOW())
            ON CONFLICT (agent_id) DO UPDATE SET
                canonical_image_path = EXCLUDED.canonical_image_path,
                face_seed = COALESCE(EXCLUDED.face_seed, agent_portraits.face_seed),
                approved = true,
                updated_at = NOW()
            """,
            (agent_id, file_path, seed),
        )

        thumb = media.get("thumbnail_path") or file_path

    # Single-writer path: agents.avatar_url update goes through
    # agent_service.update_agent so the agents table only has one
    # canonical mutation surface (Project #241 Track C.1).
    agent_service.update_agent(agent_id, avatar_url=thumb)

    return {"status": "approved", "agent_id": agent_id, "media_id": media_id}


def describe_portrait(image_source: str) -> Dict:
    """Generate an identity_prompt for an imported portrait via vision model.

    Dispatches capability='vision' through the Department HQ dispatcher, which
    auto-selects a vision-capable model (moondream by default, qwen2.5vl
    fallback) and handles VRAM swap on the M4000. Returns a description
    suitable for pairing with the IP-Adapter canonical reference in
    generate_variant().

    Args:
        image_source: either a filesystem path, a base64-encoded PNG/JPEG,
            or a data: URL.

    Returns:
        {"success": bool, "prompt": str, "model": str, "error": str}
    """
    # Normalize to base64 — dispatcher's analyze_image helper accepts b64.
    # Order matters: check data URL → filesystem → try as raw b64 (last).
    b64: str
    if image_source.startswith(("data:image/", "data:")):
        b64 = image_source.split(",", 1)[-1]
    elif len(image_source) < 512 and os.path.isfile(image_source):
        # Short enough to be a path AND exists on disk
        with open(image_source, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    else:
        # Assume raw base64. Validate by attempting decode; reject on failure.
        try:
            decoded = base64.b64decode(image_source, validate=True)
            if len(decoded) < 100:
                raise ValueError("decoded payload too small to be an image")
        except Exception as e:
            return {
                "success": False,
                "prompt": "",
                "model": "",
                "error": f"image_source not a valid path or base64 image: {e}",
            }
        b64 = image_source

    try:
        from tools.department_hq.services.department_dispatcher import dispatch
    except ImportError as e:
        return {"success": False, "prompt": "", "model": "", "error": f"dispatcher import failed: {e}"}

    try:
        result = dispatch(
            capability="vision",
            prompt=VISION_DESCRIBE_PROMPT,
            module_id="portrait_service",
            images=[b64],
            local_only=True,
            timeout=180,
        )
    except Exception as e:
        logger.exception("vision dispatch for describe_portrait failed")
        return {"success": False, "prompt": "", "model": "", "error": str(e)}

    if not getattr(result, "success", False):
        return {
            "success": False,
            "prompt": "",
            "model": getattr(result, "model", "") or "",
            "error": getattr(result, "error", "dispatch failed") or "dispatch failed",
        }

    desc = (getattr(result, "response", "") or "").strip()
    # Strip surrounding quotes if the model added them
    if len(desc) > 2 and desc[0] in ('"', "'") and desc[-1] == desc[0]:
        desc = desc[1:-1].strip()

    if not desc:
        return {
            "success": False,
            "prompt": "",
            "model": getattr(result, "model", "") or "",
            "error": "vision model returned empty description",
        }

    return {
        "success": True,
        "prompt": desc,
        "model": getattr(result, "model", "") or "",
        "tier": getattr(result, "tier", "") or "",
    }


def update_identity_prompt(agent_id: int, prompt: str) -> Dict:
    """Update the identity prompt for an agent's portraits."""
    _ensure_portrait_record(agent_id, prompt)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE agent_portraits SET identity_prompt = %s, updated_at = NOW()
            WHERE agent_id = %s
            """,
            (prompt, agent_id),
        )
    return {"status": "updated", "agent_id": agent_id}


def generate_environment(target_type: str, target_id: Optional[int], prompt: str) -> Dict:
    """Generate hub or node background art.

    target_type: 'hub' or 'node'
    target_id: remote_nodes.id for nodes, None for hub
    """
    from .generation_service import submit_generation

    return submit_generation(
        user_id=None,
        media_type="image",
        prompt=prompt,
        negative_prompt="text, watermark, low quality, blurry, people, characters",
        params={
            "model": "sd_xl_base_1.0.safetensors",
            "width": 1920,
            "height": 1080,
            "steps": 30,
            "cfg": 7.0,
            "sampler": "euler_ancestral",
            "seed": -1,
        },
        owner_type="system",
        owner_id=0,
    )


def get_environment_prompts() -> Dict:
    """Return default environment prompt templates."""
    return {
        "hub": (
            "massive orbital space station, Federation starbase style, "
            "multiple docking rings, nebula backdrop, dramatic lighting, "
            "LCARS aesthetic, 8k, cinematic, wide angle"
        ),
        "node": (
            "starship bridge interior, warp-capable vessel, holographic displays, "
            "deep space visible through viewports, LCARS panels, 8k, cinematic"
        ),
    }


def _ensure_portrait_record(agent_id: int, identity_prompt: Optional[str] = None):
    """Create portrait record if it doesn't exist."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO agent_portraits (agent_id, identity_prompt)
            VALUES (%s, %s)
            ON CONFLICT (agent_id) DO NOTHING
            """,
            (agent_id, identity_prompt),
        )
