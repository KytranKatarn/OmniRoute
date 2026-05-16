"""Portrait service — agent face generation with IP-Adapter consistency.

Manages canonical portraits, face-consistent variants, approval workflow,
and environment art for hub/node backgrounds.
"""

import base64
import logging
import os
import shutil
import threading
from typing import Dict, List, Optional

from database import get_db_cursor
from services import agent_service
from services.deploy_service import run_deploy_pipeline

logger = logging.getLogger(__name__)

# Vision-model prompt for deriving an identity_prompt from an imported face.
# Used by the upload flow (#1917) so imported portraits can participate in
# IP-Adapter variant generation — which requires a prompt paired with the
# canonical face reference.
VISION_DESCRIBE_PROMPT = (
    "Describe the person in this portrait in detail: their appearance, "
    "age, hair, eyes, clothing, and any distinctive features."
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")
PORTRAITS_DIR = os.path.join(MEDIA_ROOT, "portraits")

# Website thumbs — public-facing 400x400 JPEGs that the directory page
# loads same-origin from Hostinger. Mirrors `scripts/generate_portrait_thumbnails.py`
# (kept for batch backfills); approve_canonical invokes the inline helper
# below so approval produces the website-visible thumb in one step.
#
# Constraint: archie_platform container mounts /mnt/archie_brain/website
# as read-only (see docker-compose.yml). When the direct path isn't
# writable we fall through to a hub-local staging tree
# (/app/static/media/thumbs) which publish_website.sh syncs on deploy.
# The website copy is the authoritative one consumed by the directory
# page; the staging copy exists so the hub side of the flow always
# succeeds even if the container is sandboxed.
WEBSITE_THUMB_PRIMARY = os.getenv(
    "PORTRAIT_WEBSITE_THUMB_DIR",
    "/mnt/archie_brain/website/kytranempowerment.com/assets/portraits",
)
CREED_PORTRAIT_DIR = os.getenv(
    "PORTRAIT_CREED_THUMB_DIR",
    "/mnt/archie_brain/website/creed-ai.org/assets/portraits",
)
WEBSITE_THUMB_STAGING = os.path.join(_PLATFORM_DIR, "static", "media", "thumbs")

# Source path roots for full-site deploys (deploy_service zips the entire tree)
KYTRAN_DEPLOY_SOURCE = os.getenv(
    "KYTRAN_DEPLOY_SOURCE",
    "/mnt/archie_brain/website/kytranempowerment.com",
)
CREED_DEPLOY_SOURCE = os.getenv(
    "CREED_DEPLOY_SOURCE",
    "/mnt/archie_brain/website/creed-ai.org",
)
_PORTRAIT_DEPLOY_SITES = [
    {
        "domain": "kytranempowerment.com",
        "source_path": KYTRAN_DEPLOY_SOURCE,
    },
    {
        "domain": "creed-ai.org",
        "source_path": CREED_DEPLOY_SOURCE,
    },
]
WEBSITE_THUMB_SIZE = (400, 400)
WEBSITE_THUMB_JPEG_QUALITY = 82


def _sync_website_thumb(canonical_db_path: str) -> Optional[str]:
    """Generate the public 400x400 JPEG thumb for the website repo.

    Accepts the canonical_image_path stored in agent_portraits (a URL-style
    path starting with ``/static/…``) and writes the thumb to the website
    assets tree when writable, otherwise stages it under the hub's static
    tree. Returns the path written on success or None on failure — the
    helper never raises so approve_canonical stays resilient if Pillow or
    either target is unavailable.
    """
    try:
        from PIL import Image  # lazy import — media_studio already depends on Pillow
    except Exception:
        logger.warning("PIL not available — skipping website thumb sync")
        return None

    if not canonical_db_path:
        return None

    # /static/media/images/2026-04-22/e64da74f-03e.png  →  /app/static/media/images/2026-04-22/e64da74f-03e.png
    rel = canonical_db_path.lstrip("/")
    src_fs = os.path.join(_PLATFORM_DIR, rel) if rel.startswith("static/") else canonical_db_path
    if not os.path.isfile(src_fs):
        logger.warning("website thumb source missing: %s", src_fs)
        return None

    stem = os.path.splitext(os.path.basename(src_fs))[0]

    # Try primary (website repo) first, fall back to staging if RO.
    for target_dir, label in (
        (WEBSITE_THUMB_PRIMARY, "website"),
        (WEBSITE_THUMB_STAGING, "hub-staging"),
    ):
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as exc:
            logger.warning("cannot ensure %s thumb dir %s: %s", label, target_dir, exc)
            continue
        dst = os.path.join(target_dir, f"{stem}.jpg")
        try:
            with Image.open(src_fs) as im:
                if im.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.thumbnail(WEBSITE_THUMB_SIZE, Image.LANCZOS)
                im.save(
                    dst,
                    "JPEG",
                    quality=WEBSITE_THUMB_JPEG_QUALITY,
                    optimize=True,
                    progressive=True,
                )
            logger.info("website thumb written (%s): %s", label, dst)
            return dst
        except PermissionError:
            logger.info("%s thumb dir read-only, falling through: %s", label, target_dir)
            continue
        except Exception as exc:
            logger.warning("website thumb generation failed at %s: %s", dst, exc)
            continue

    logger.warning("could not write website thumb for %s to any target", stem)
    return None


def _sync_all_site_thumbs(
    canonical_db_path: str,
) -> tuple[Optional[str], list[str]]:
    """Copy approved portrait JPEG to every public site that displays agent portraits.

    Calls _sync_website_thumb for kytranempowerment.com (primary), then copies
    to creed-ai.org. Returns (primary_path, sites_written). On partial failure
    still returns the primary so the deploy can proceed for the sites that worked.
    """
    primary = _sync_website_thumb(canonical_db_path)
    if not primary:
        return None, []

    stem = os.path.splitext(os.path.basename(primary))[0]
    sites_written: list[str] = ["kytranempowerment.com"]

    # Copy to creed-ai.org
    try:
        os.makedirs(CREED_PORTRAIT_DIR, exist_ok=True)
        creed_dst = os.path.join(CREED_PORTRAIT_DIR, f"{stem}.jpg")
        shutil.copy2(primary, creed_dst)
        sites_written.append("creed-ai.org")
        logger.info("[Portrait] Synced thumb to creed-ai.org: %s", creed_dst)
    except Exception as exc:
        logger.warning("[Portrait] Could not sync thumb to creed-ai.org: %s", exc)

    return primary, sites_written


def _deploy_portrait_to_sites(stem: str, agent_name: str) -> None:
    """Deploy portrait JPEG to all public sites via deploy_service pipeline.

    Runs inside a background thread (called from approve_canonical). Never
    raises — errors are logged and run_deploy_pipeline handles Telegram
    alerting + Repair Bay proposal on failure.
    """
    try:
        for cfg in _PORTRAIT_DEPLOY_SITES:
            portrait_path = os.path.join(cfg["source_path"], "assets", "portraits", f"{stem}.jpg")
            if not os.path.isfile(portrait_path):
                logger.info(
                    "[Portrait] Skipping %s — portrait not present at %s",
                    cfg["domain"],
                    portrait_path,
                )
                continue

            try:
                result = run_deploy_pipeline(
                    "deploy_static",
                    {
                        "domain": cfg["domain"],
                        "source_path": cfg["source_path"],
                        "changed_files": [f"assets/portraits/{stem}.jpg"],
                        "verify_url": f"https://{cfg['domain']}/assets/portraits/{stem}.jpg",
                        "reason": f"Portrait approved for agent {agent_name}",
                    },
                )
                if result.success:
                    logger.info(
                        "[Portrait] Deploy to %s succeeded for %s",
                        cfg["domain"],
                        agent_name,
                    )
                else:
                    logger.error(
                        "[Portrait] Deploy to %s failed for %s: %s",
                        cfg["domain"],
                        agent_name,
                        result.error,
                    )
            except Exception as exc:
                logger.error(
                    "[Portrait] Unexpected error deploying to %s for %s: %s",
                    cfg["domain"],
                    agent_name,
                    exc,
                )
    except Exception as exc:
        logger.error(
            "[Portrait] Unexpected error in _deploy_portrait_to_sites for %s: %s",
            agent_name,
            exc,
        )


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
            SELECT a.id, a.name, a.first_name, a.last_name, a.display_name,
                   a.worker_type, a.avatar_url,
                   a.updated_at AS avatar_updated_at,
                   p.id AS portrait_id, p.canonical_image_path, p.identity_prompt,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags, p.updated_at
            FROM agents a
            LEFT JOIN agent_portraits p ON p.agent_id = a.id
            WHERE a.shift_state != 'decommissioned'
            ORDER BY COALESCE(a.display_name, a.first_name || ' ' || a.last_name, a.name)
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
                   a.bio, a.title, a.department,
                   a.updated_at AS avatar_updated_at,
                   p.id AS portrait_id, p.canonical_image_path, p.identity_prompt,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags, p.refinement_draft, p.created_at, p.updated_at
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
            SELECT ml.id, ml.file_path, ml.thumbnail_path, ml.prompt, ml.seed,
                   ml.width, ml.height, ml.metadata, ml.created_at,
                   q.params->>'model' AS model_name,
                   q.params->>'fleet_node' AS fleet_node,
                   q.params->>'provider' AS provider
            FROM media_library ml
            LEFT JOIN media_generation_queue q ON q.result_media_id = ml.id
            WHERE ml.owner_type = 'agent' AND ml.owner_id = %s
                  AND ml.media_type = 'image' AND ml.is_deleted = false
            ORDER BY created_at DESC
            """,
            (agent_id,),
        )
        result["variants"] = [dict(v) for v in cur.fetchall()]

        if not result.get("identity_prompt"):
            if result["name"] in AGENT_DIVERSITY:
                desc, age = AGENT_DIVERSITY[result["name"]]
                result["default_identity_prompt"] = _build_identity_prompt(result["display_name"], desc, age)
            elif result.get("bio"):
                # Fall back to DHQ Roster bio as a starting point for editing
                result["default_identity_prompt"] = result["bio"]

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
            SELECT a.name, a.display_name, a.first_name, a.last_name,
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
    # Resolve the display label: prefer display_name, then first+last, then code name
    full_name = (
        row["display_name"]
        or (f"{row['first_name']} {row['last_name']}" if row.get("first_name") and row.get("last_name") else None)
        or agent_name
    )
    identity_prompt = prompt_override or row.get("identity_prompt")

    # Regenerate if stored prompt still contains the legacy "None" placeholder
    if identity_prompt and "of None," in identity_prompt:
        identity_prompt = None

    if not identity_prompt:
        # No prompt set — generation is blocked by the API gate before reaching here.
        # Return an error rather than generating with a generic fallback.
        return {"success": False, "error": f"No identity_prompt set for agent {agent_id}. Set one in DHQ Roster first."}

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


def _parse_provider_or_model(value: Optional[str], model_override: Optional[str] = None) -> Dict:
    """Parse a model selector value into provider/model components.

    Returns {"provider": str|None, "model": str|None}. Provider keys come from
    contractor_providers; model is a local checkpoint filename. When neither is
    set, the caller falls back to defaults (Auto / fleet-aware).

    When `value` is a "provider:<key>" selector AND `model_override` is supplied,
    the override wins over PROVIDER_DEFAULT_MODEL — this is the per-provider
    model picker (#2942). Override is ignored for local-checkpoint selections
    since those values ARE the model.
    """
    from .generation_service import PROVIDER_DEFAULT_MODEL

    if not value:
        return {"provider": None, "model": None}
    if value.startswith("provider:"):
        key = value[len("provider:") :]
        model = model_override or PROVIDER_DEFAULT_MODEL.get(key)
        return {"provider": key, "model": model}
    return {"provider": None, "model": value}


def generate_variant(
    agent_id: int,
    style: Optional[str] = None,
    pose: Optional[str] = None,
    model: Optional[str] = None,
    model_override: Optional[str] = None,
) -> Dict:
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

    base_prompt = row["identity_prompt"] or ""
    if style:
        base_prompt += f", {style} style"
    if pose:
        base_prompt += f", {pose} pose"

    parsed = _parse_provider_or_model(model, model_override=model_override)
    params: Dict = {
        "model": parsed["model"] or "sd_xl_base_1.0.safetensors",
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "cfg": 7.0,
        "sampler": "euler_ancestral",
        "seed": -1,
    }
    if parsed["provider"]:
        params["provider"] = parsed["provider"]
    if row["ip_adapter_ref_path"] and not parsed["provider"]:
        # IP-Adapter face anchoring only works on local ComfyUI today
        params["ip_adapter_ref"] = row["ip_adapter_ref_path"]
        params["ip_adapter_weight"] = 0.85

    return submit_generation(
        user_id=None,
        media_type="image",
        prompt=base_prompt,
        negative_prompt="blurry, deformed, extra limbs, bad anatomy, text, watermark",
        params=params,
        owner_type="agent",
        owner_id=agent_id,
    )


_FANOUT_STYLES = [
    "",
    "cinematic lighting, dramatic shadows",
    "soft studio lighting, professional headshot",
]


def generate_fanout(
    agent_id: int,
    prompt_override: Optional[str] = None,
    model: Optional[str] = None,
    model_override: Optional[str] = None,
) -> Dict:
    """Submit N portrait generation jobs in one click.

    If agent has an approved canonical with ip_adapter_ref_path, generates
    IP-Adapter style variants.  Otherwise generates N canonical attempts with
    different style suffixes and random seeds.

    Returns {"success": True, "queue_ids": [...], "count": N}
    """
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.name, a.display_name, a.first_name, a.last_name,
                   p.identity_prompt, p.face_seed,
                   p.approved, p.ip_adapter_ref_path
            FROM agents a
            LEFT JOIN agent_portraits p ON p.agent_id = a.id
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"success": False, "error": "Agent not found"}

    identity_prompt = prompt_override or (row.get("identity_prompt") or "")
    if not identity_prompt.strip():
        return {"success": False, "error": "No identity prompt set. Add one in DHQ Roster first."}

    queue_ids = []
    use_ip_adapter = bool(row.get("approved") and row.get("ip_adapter_ref_path"))

    parsed = _parse_provider_or_model(model, model_override=model_override)
    _model = parsed["model"] or "sd_xl_base_1.0.safetensors"
    for style in _FANOUT_STYLES:
        prompt = identity_prompt + (f", {style}" if style else "")
        params: Dict = {
            "model": _model,
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "cfg": 7.0,
            "sampler": "euler_ancestral",
            "seed": -1,
        }
        if parsed["provider"]:
            params["provider"] = parsed["provider"]
        if use_ip_adapter and not parsed["provider"]:
            params["ip_adapter_ref"] = row["ip_adapter_ref_path"]
            params["ip_adapter_weight"] = 0.85

        result = submit_generation(
            user_id=None,
            media_type="image",
            prompt=prompt,
            negative_prompt="blurry, deformed, extra limbs, bad anatomy, text, watermark, low quality",
            params=params,
            owner_type="agent",
            owner_id=agent_id,
        )
        if "queue_id" in result:
            queue_ids.append(result["queue_id"])

    if not queue_ids:
        return {"success": False, "error": "Fan-out submitted 0 jobs — check generation service logs"}
    return {"success": True, "queue_ids": queue_ids, "count": len(queue_ids)}


def _load_refinement_context(agent_id: int) -> Optional[Dict]:
    """Load agent portrait context needed for the refinement pipeline."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT ap.identity_prompt, ap.canonical_image_path,
                      a.name, a.display_name, a.model, a.system_prompt,
                      a.title, a.department
               FROM agent_portraits ap
               JOIN agents a ON a.id = ap.agent_id
               WHERE ap.agent_id = %s""",
            (agent_id,),
        )
        return cur.fetchone()


def _step_vision_analysis(canonical_image_path: str) -> str:
    """Run vision model on the canonical portrait. Returns visual description or empty string."""
    if not canonical_image_path:
        return ""
    rel = canonical_image_path.lstrip("/")
    src = os.path.join(_PLATFORM_DIR, rel) if rel.startswith("static/") else canonical_image_path
    if not os.path.isfile(src):
        return ""
    try:
        # No timeout — DHQ orchestration handles cold boot and VRAM swap.
        # moondream may take 60-90s on first load; that is expected and correct.
        result = describe_portrait(src)
        return result.get("prompt") or ""
    except Exception as exc:
        logger.warning("[Refine] vision step failed: %s", exc)
        return ""


def _step_consult_agent(
    agent_name: str,
    model: str,
    system_prompt: str,
    title: str,
    department: str,
    current_prompt: str,
    vision_desc: str,
    feedback: str,
) -> str:
    """Ask the agent themselves what matters about their visual representation.

    Routes through Department HQ dispatcher so VRAM management, welfare
    checks, and orchestration logging all apply — same path as all other
    inference on the platform (ADR-013).
    """
    context_lines = []
    if vision_desc:
        context_lines.append(f"Current portrait shows: {vision_desc}")
    if current_prompt:
        context_lines.append(f"Current generation prompt: {current_prompt}")
    context_lines.append(f"User wants to refine: {feedback}")

    consultation_prompt = (
        f"PERSONA: You are {agent_name}, {title}, {department}.\n"
        f"YOUR IDENTITY: {system_prompt[:400] if system_prompt else ''}\n\n"
        f"CONTEXT:\n" + "\n".join(context_lines) + "\n\n"
        f"TASK: Your visual portrait is being updated. "
        "What aspects of your appearance are most important to you? "
        "What should your portrait communicate about who you are and what you do? "
        "Answer in 2-3 sentences in your own voice."
    )

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            capability="general",
            prompt=consultation_prompt,
            module_id="media_studio",
            context={
                "task": "agent_portrait_consultation",
                "agent_name": agent_name,
                "preferred_model": model,
            },
            user_id=None,
        )
        if result.success:
            return (result.response or "").strip()
        logger.warning("[Refine] agent consultation dispatch failed: %s", result.error)
    except Exception as exc:
        logger.warning("[Refine] agent consultation failed for %s: %s", agent_name, exc)
    return ""


def _step_muse_synthesize(
    agent_name: str,
    current_prompt: str,
    vision_desc: str,
    agent_perspective: str,
    feedback: str,
    history: Optional[list] = None,
) -> Dict:
    """M.U.S.E. synthesizes vision + agent perspective + user feedback into refined prompt.

    Returns {refined_prompt, explanation} or {error}.
    """
    parts = [f"You are M.U.S.E., Creative & Design Director. Refine {agent_name}'s portrait prompt.\n"]

    if vision_desc:
        parts.append(f"## What the current portrait shows (vision analysis)\n{vision_desc}\n")

    parts.append(f"## Current generation prompt\n{current_prompt}\n")

    if agent_perspective:
        parts.append(f"## {agent_name}'s own perspective\n{agent_perspective}\n")

    if history:
        rounds = "\n".join(
            f"Round {i+1}: feedback='{h.get('feedback', '')[:80]}' → '{h.get('refined_prompt', '')[:80]}'"
            for i, h in enumerate(history[-3:])
        )
        parts.append(f"## Previous refinement rounds\n{rounds}\n")

    parts.append(f"## User's current feedback\n{feedback}\n")
    parts.append(
        "Return a JSON object with exactly two keys:\n"
        '{"refined_prompt": "<single paragraph for image generation>", '
        '"explanation": "<1-2 sentences explaining what changed and why>"}\n'
        "No other text. Keep the agent's visual identity elements unless explicitly asked to change them."
    )

    synthesis_prompt = "\n".join(parts)

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher
        import json as _json

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            capability="creative",
            prompt=synthesis_prompt,
            module_id="media_studio",
            context={"agent_id": None, "task": "prompt_synthesis"},
            user_id=None,
        )
        if not result.success:
            return {"error": f"M.U.S.E. dispatch failed: {result.error}"}

        raw = (result.response or "").strip()
        # Try to parse JSON response
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = _json.loads(raw[start:end])
                return {
                    "refined_prompt": parsed.get("refined_prompt", "").strip(),
                    "explanation": parsed.get("explanation", "").strip(),
                }
        except Exception:
            pass
        # Fallback: treat raw as the prompt (old behaviour)
        return {"refined_prompt": raw, "explanation": ""}

    except Exception as exc:
        logger.exception("[Refine] M.U.S.E. synthesis failed: %s", exc)
        return {"error": str(exc)}


def refine_identity_prompt(agent_id: int, feedback: str, history: Optional[list] = None) -> Dict:
    """Full M.U.S.E. portrait refinement pipeline (synchronous).

    Steps: vision analysis → agent self-consultation → M.U.S.E. synthesis.
    Returns {refined_prompt, explanation, vision_description, agent_perspective,
    original_prompt} or {error}.
    """
    if not feedback or not feedback.strip():
        return {"error": "Feedback is required"}

    ctx = _load_refinement_context(agent_id)
    if not ctx:
        return {"error": "Agent portrait not found"}

    current_prompt = ctx.get("identity_prompt") or ""
    if not current_prompt:
        return {"error": "No identity prompt set yet — set one in DHQ Roster first"}

    agent_name = ctx.get("display_name") or ctx.get("name") or f"Agent {agent_id}"

    vision_desc = _step_vision_analysis(ctx.get("canonical_image_path") or "")
    agent_perspective = _step_consult_agent(
        agent_name=agent_name,
        model=ctx.get("model") or "qwen2.5:7b",
        system_prompt=ctx.get("system_prompt") or "",
        title=ctx.get("title") or "",
        department=ctx.get("department") or "",
        current_prompt=current_prompt,
        vision_desc=vision_desc,
        feedback=feedback,
    )
    synthesis = _step_muse_synthesize(
        agent_name=agent_name,
        current_prompt=current_prompt,
        vision_desc=vision_desc,
        agent_perspective=agent_perspective,
        feedback=feedback,
        history=history or [],
    )
    if "error" in synthesis:
        return synthesis

    return {
        "refined_prompt": synthesis.get("refined_prompt", ""),
        "explanation": synthesis.get("explanation", ""),
        "vision_description": vision_desc,
        "agent_perspective": agent_perspective,
        "agent_name": agent_name,
        "original_prompt": current_prompt,
    }


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

    # Sync portrait JPEG to all sites (kytranempowerment.com + creed-ai.org)
    # and dispatch deploy_service pipeline for each in a background thread.
    website_thumb, sites_synced = _sync_all_site_thumbs(file_path)

    if website_thumb and sites_synced:
        # Refresh directory snapshot so the deploy zip includes current agent data.
        try:
            from services.public_roster_service import write_directory_snapshot

            write_directory_snapshot()
        except Exception as _exc:
            logger.warning("[Portrait] directory snapshot refresh failed: %s", _exc)

        # Thumb written to website repo — full-site deploy is handled by the
        # website_deploy_worker scheduled job (daily 03:00) or manually via
        # Repair Bay → Ship → Website tab.
        logger.info("[Portrait] thumb written for %s — queued for next scheduled website deploy", agent_id)

    return {
        "status": "approved",
        "agent_id": agent_id,
        "media_id": media_id,
        "website_thumb": website_thumb,
        "sites_queued": sites_synced,
    }


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

    # Direct-to-moondream call (bypasses agent selection via
    # capability='vision'). Rationale: Pixel / V.I.S.A.G.E. are configured
    # with qwen2.5vl:7b (8.3B params, CPU-bound on M4000, 5+ min per
    # inference). moondream:latest (1.8B, fits on GPU VRAM, ~11s) is 20x
    # faster and sufficient for face-describe — small input, small output.
    # This is a utility function (no creative welfare/cost logging needed);
    # going direct keeps the pipeline fast and predictable.
    vision_model = os.getenv("PORTRAIT_DESCRIBE_MODEL", "moondream:latest")

    try:
        from ai_bridge.archie_bridge import analyze_image
    except ImportError as e:
        return {
            "success": False,
            "prompt": "",
            "model": "",
            "error": f"analyze_image import failed: {e}",
        }

    try:
        result = analyze_image(
            image_base64=b64,
            prompt=VISION_DESCRIBE_PROMPT,
            model=vision_model,
            timeout=180,
        )
    except Exception as e:
        logger.exception("analyze_image for describe_portrait failed")
        return {"success": False, "prompt": "", "model": vision_model, "error": str(e)}

    if not result.get("success"):
        return {
            "success": False,
            "prompt": "",
            "model": result.get("model", vision_model),
            "error": result.get("error") or "analyze_image returned failure",
        }

    desc = (result.get("response") or "").strip()
    # Strip surrounding quotes if the model added them
    if len(desc) > 2 and desc[0] in ('"', "'") and desc[-1] == desc[0]:
        desc = desc[1:-1].strip()

    if not desc:
        return {
            "success": False,
            "prompt": "",
            "model": result.get("model", vision_model),
            "error": "vision model returned empty description",
        }

    return {
        "success": True,
        "prompt": desc,
        "model": result.get("model", vision_model),
        "provider": result.get("provider", "ollama_vision"),
    }


ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
UPLOAD_MAX_DIM = 1024  # Resize longest edge to this if larger


def upload_canonical(
    agent_id: int,
    file_bytes: bytes,
    content_type: str,
    identity_prompt: str,
    original_filename: Optional[str] = None,
) -> Dict:
    """Accept an uploaded portrait image, save as canonical, update agents.avatar_url.

    Resizes to fit UPLOAD_MAX_DIM if the longest edge exceeds it, then saves
    as PNG at platform_v2/static/media/portraits/<code_stem>.png (stable name
    per agent — overwrites prior uploads/generates for this agent).

    Creates a media_library entry + insert/upsert agent_portraits row
    (approved=True since the user explicitly uploaded) and updates
    agents.avatar_url via agent_service.update_agent (single-writer).
    """
    if content_type not in ALLOWED_UPLOAD_TYPES:
        return {"error": f"unsupported content_type: {content_type}"}
    if not file_bytes or len(file_bytes) > MAX_UPLOAD_BYTES:
        return {"error": f"file size out of range (0 < size <= {MAX_UPLOAD_BYTES})"}
    if not identity_prompt or not identity_prompt.strip():
        return {"error": "identity_prompt is required"}

    # Look up agent to get a stable filename stem
    agent = agent_service.get_agent(agent_id)
    if not agent:
        return {"error": f"agent {agent_id} not found"}
    code_name = agent.get("name") or f"agent_{agent_id}"
    stem = code_name.replace(".", "").lower()
    dest_rel = f"static/media/portraits/{stem}.png"
    dest_abs = os.path.join(_PLATFORM_DIR, dest_rel)
    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)

    # Load via Pillow, resize if needed, re-encode as PNG for consistency.
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        return {"error": "Pillow not installed in platform runtime"}

    try:
        im = Image.open(BytesIO(file_bytes))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > UPLOAD_MAX_DIM:
            im.thumbnail((UPLOAD_MAX_DIM, UPLOAD_MAX_DIM), Image.LANCZOS)
        im.save(dest_abs, "PNG", optimize=True)
        final_w, final_h = im.size
    except Exception as e:
        logger.exception("portrait upload decode/save failed for agent_id=%s", agent_id)
        return {"error": f"image decode/save failed: {e}"}

    # URL the platform serves the file at (same shape as other avatar_urls)
    avatar_url_relative = f"/{dest_rel}"

    # media_library insert (history + provenance)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_library
                (owner_type, owner_id, media_type, file_path, prompt,
                 provider, width, height, metadata)
            VALUES
                ('agent', %s, 'image', %s, %s,
                 'upload', %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                agent_id,
                dest_rel,
                identity_prompt,
                final_w,
                final_h,
                '{"source":"user_upload","original_filename":'
                + ('"' + (original_filename or "") + '"}' if original_filename else "null}"),
            ),
        )
        media_id = cur.fetchone()["id"]

        # Manual upsert — agent_portraits has no unique constraint on agent_id
        # (and existing data has duplicate rows per agent), so ON CONFLICT
        # isn't available. UPDATE existing row(s); INSERT only if none.
        cur.execute(
            """
            UPDATE agent_portraits
            SET canonical_image_path = %s,
                identity_prompt      = %s,
                approved             = true,
                provider             = 'upload',
                resolution_w         = %s,
                resolution_h         = %s,
                updated_at           = NOW()
            WHERE agent_id = %s
            """,
            (dest_rel, identity_prompt, final_w, final_h, agent_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO agent_portraits
                    (agent_id, canonical_image_path, identity_prompt, approved,
                     provider, resolution_w, resolution_h, updated_at)
                VALUES
                    (%s, %s, %s, true, 'upload', %s, %s, NOW())
                """,
                (agent_id, dest_rel, identity_prompt, final_w, final_h),
            )

    # Single-writer path for agents.avatar_url.
    agent_service.update_agent(agent_id, avatar_url=avatar_url_relative)

    return {
        "success": True,
        "agent_id": agent_id,
        "media_id": media_id,
        "avatar_url": avatar_url_relative,
        "width": final_w,
        "height": final_h,
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
