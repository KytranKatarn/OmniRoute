"""Portrait service — agent face generation with IP-Adapter consistency.

Manages canonical portraits, face-consistent variants, approval workflow,
and environment art for hub/node backgrounds.
"""

import base64
import hashlib
import logging
import os
import shutil
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

# NOTE ON BRANDING: the mark itself is NEVER asked for in a prompt. Diffusion
# models cannot render a legible brand mark, so requesting one yields invented
# gibberish — a prior revision said "subtle embossed Kytran Empowerment RAM mark
# integrated into the background" here, and the model painted a fake logo on the
# blazer lapel (media_library #498) while the negative prompt simultaneously
# banned "fake logo". The real mark is composited deterministically after
# generation instead — see generation_service.apply_ke_branding.
KYTRAN_PORTRAIT_BRAND = (
    "professional human corporate portrait, clean studio lighting, "
    "subtle AI technology accents, uncluttered neutral background"
)
# Stable substring of KYTRAN_PORTRAIT_BRAND used to detect "already applied".
_CORPORATE_BRAND_MARKER = "professional human corporate portrait"
# Photographic, not abstract. "clean architectural branding accents" and
# "no readable generated text" are not visual tokens — SD ignored them and
# returned a plain gradient. Concrete nouns (glass wall, skyline bokeh, depth
# of field) are what the checkpoint actually responds to.
KE_CORPORATE_BACKGROUND = (
    "modern corporate office interior, blurred glass partition wall and city "
    "skyline bokeh behind the subject, soft diffused key light, navy and cyan "
    "color grading, tailored business professional attire, shallow depth of field, "
    "clean uncluttered background"
)
VARIANT_PRESET_PROMPTS = {
    "ai": "AI-inspired professional portrait, restrained futuristic cyan and violet interface accents, natural human skin and facial features, preserve identity, no costume, no cyberpunk makeup",
    "ke_corporate": KE_CORPORATE_BACKGROUND,
    "action": "natural mid-action professional portrait, candid gesture and movement, expressive face, realistic anatomy, preserve identity",
    "professional": "professional corporate portrait, natural expression, clean lighting",
    "casual": "approachable casual portrait, relaxed natural setting and expression",
    "lcars": "subtle LCARS-inspired holographic interface accents, professional human portrait, preserve identity, no costume",
}
VARIANT_FRAMING_PROMPTS = {
    "portrait": "head-and-shoulders portrait framing",
    "bust": "chest-up portrait framing",
    "half_body": "waist-up half-body framing",
    "full_body": "full-body framing with the entire subject visible",
}
DEFAULT_PORTRAIT_MODEL = os.getenv("MEDIA_STUDIO_PORTRAIT_MODEL", "RealVisXL_V4.0.safetensors")


def compose_variant_prompt(
    preset=None, style=None, scene=None, action=None, framing=None, expression=None, ke_background=False
):
    parts = []
    preset_key = str(preset or "").strip().lower()
    style_text = str(style or "").strip()[:500]
    style_key = style_text.lower()
    if preset_key in VARIANT_PRESET_PROMPTS:
        parts.append(VARIANT_PRESET_PROMPTS[preset_key])
    if style_key in VARIANT_PRESET_PROMPTS and style_key != preset_key:
        parts.append(VARIANT_PRESET_PROMPTS[style_key])
    elif style_text and style_key not in VARIANT_PRESET_PROMPTS:
        parts.append(style_text)
    scene_text = str(scene or "").strip()[:500]
    action_text = str(action or "").strip()[:500]
    framing_text = str(framing or "").strip().lower()
    expression_text = str(expression or "").strip()[:200]
    if scene_text:
        parts.append(scene_text)
    if action_text:
        parts.append("action: " + action_text)
    if framing_text in VARIANT_FRAMING_PROMPTS:
        parts.append(VARIANT_FRAMING_PROMPTS[framing_text])
    if expression_text:
        parts.append("expression: " + expression_text)
    if ke_background and str(preset or "").strip().lower() != "ke_corporate":
        parts.append(KE_CORPORATE_BACKGROUND)
    return ", ".join(parts)


def _apply_corporate_brand(prompt: str) -> str:
    prompt = (prompt or "").strip()
    # Idempotence guard. This keyed on the literal "Kytran Empowerment RAM
    # mark" until the mark moved to post-generation compositing — removing that
    # phrase silently broke the guard and the brand text was appended twice.
    # Key on a marker that is part of the brand string itself.
    if not prompt or _CORPORATE_BRAND_MARKER in prompt:
        return prompt
    return f"{prompt}, {KYTRAN_PORTRAIT_BRAND}"


def _compose_identity_prompt(
    prompt: str,
    display_name: str = "",
    gender: str = "",
    ethnicity: str = "",
    age_range: str = "",
    appearance_notes: str = "",
) -> str:
    prompt = _apply_corporate_brand(prompt or "")
    details = []
    if display_name:
        details.append(f"subject: {display_name}")
    if gender:
        details.append(f"gender presentation: {gender}")
    if age_range:
        details.append(f"age: {age_range}")
    if ethnicity:
        skin_hint = agent_service._get_skin_tone_hint(ethnicity)
        details.append(f"ethnicity and skin tone: {skin_hint or ethnicity}")
    if appearance_notes:
        details.append(f"fixed appearance details: {appearance_notes}")
    identity_lock = (
        "identity lock: preserve the same person across every generation; "
        "same face shape, facial proportions, hairline, hair color, eye color, "
        "skin tone, age, gender presentation, ethnicity, and distinctive features"
    )
    if details:
        identity_lock += "; " + "; ".join(details)
    identity_lock += (
        "; photorealistic natural skin texture, realistic eyes and anatomy, "
        "accurate age lines, no beautification, no identity drift"
    )
    if "identity lock:" in prompt.lower():
        return prompt
    return f"{prompt}, {identity_lock}" if prompt else ""


def _stable_face_seed(agent_id: int, existing_seed: Optional[int]) -> int:
    if existing_seed not in (None, -1, 0):
        return int(existing_seed)
    digest = hashlib.sha256(f"archie-portrait:{agent_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 2147483647


def _portrait_negative_prompt() -> str:
    return (
        "blurry, deformed, extra limbs, bad anatomy, text, large logo, logo over face, "
        "busy background, low quality, different person, identity drift, changed gender, "
        "changed age, changed ethnicity, altered facial structure, plastic skin, waxy skin, "
        "over-smoothed skin, uncanny eyes, signature, caption, gibberish lettering, "
        "fake logo, stock-photo overlay"
    )


def _portrait_reference_path(row: Dict) -> str:
    if not row.get("approved"):
        return ""
    return row.get("ip_adapter_ref_path") or row.get("canonical_image_path") or ""


def _get_voice_profile(agent_id: int) -> Optional[Dict]:
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT profile_name, speaker, speed, pitch_shift, warmth,
                       default_emotion, emotion_overrides, is_active, updated_at
                FROM agent_voice_profiles avp
                WHERE avp.agent_id = %s AND avp.is_active = TRUE
                ORDER BY avp.updated_at DESC NULLS LAST, avp.id DESC
                LIMIT 1
                """,
                (agent_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        profile = dict(row)
        for key in ("speed", "pitch_shift", "warmth"):
            if profile.get(key) is not None:
                profile[key] = float(profile[key])
        if profile.get("updated_at"):
            profile["updated_at"] = profile["updated_at"].isoformat()
        return profile
    except Exception as exc:
        logger.warning("Could not load voice profile for agent %s: %s", agent_id, exc)
        return None


def _portrait_identity_context(row: Dict, voice_profile: Optional[Dict]) -> Dict:
    appearance = (row.get("appearance_notes") or "").strip()
    bio = (row.get("bio") or "").strip()
    pronouns = (row.get("pronouns") or "").strip()
    personality_prompt = row.get("personality_prompt") or ""
    writing_voice = {
        "tone": row.get("writing_tone") or "",
        "communication_style": row.get("communication_style") or "",
        "has_personality_prompt": bool(personality_prompt),
    }
    missing = []
    for field, value in (
        ("pronouns", pronouns),
        ("bio", bio),
        ("appearance_notes", appearance),
        ("writing_tone", writing_voice["tone"]),
        ("communication_style", writing_voice["communication_style"]),
        ("personality_prompt", personality_prompt),
        ("gender", row.get("gender")),
        ("ethnicity", row.get("ethnicity")),
        ("age_range", row.get("age_range")),
    ):
        if not value:
            missing.append(field)
    if not row.get("identity_prompt"):
        missing.append("identity_prompt")
    if not row.get("current_grade"):
        missing.append("current_grade")
    if not voice_profile:
        missing.append("tts_voice_profile")
    return {
        "bio": bio,
        "pronouns": pronouns,
        "gender": row.get("gender") or "",
        "ethnicity": row.get("ethnicity") or "",
        "age_range": row.get("age_range") or "",
        "appearance_notes": appearance,
        "writing_voice": writing_voice,
        "voice_profile": voice_profile,
        "grade_status": row.get("current_grade") or "Unrated",
        "missing_fields": missing,
    }


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
                   a.title, a.department, a.worker_type, a.avatar_url,
                   a.updated_at AS avatar_updated_at,
                   p.id AS portrait_id, p.canonical_image_path,
                   COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(p.identity_prompt, ''))
                       AS identity_prompt,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags,
                   p.created_at AS portrait_created_at,
                   p.updated_at AS portrait_updated_at,
                   COALESCE(p.updated_at, a.updated_at) AS updated_at,
                   latest.latest_media_at, latest.latest_model, latest.latest_provider,
                   latest.latest_variant_name, latest.latest_media_thumbnail, latest.latest_media_path
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT ap.id, ap.canonical_image_path, ap.identity_prompt,
                       ap.face_seed, ap.ip_adapter_ref_path, ap.approved,
                       ap.style_tags, ap.created_at, ap.updated_at
                FROM agent_portraits ap
                WHERE ap.agent_id = a.id
                ORDER BY ap.approved DESC NULLS LAST, ap.is_primary DESC NULLS LAST,
                         ap.updated_at DESC NULLS LAST, ap.id DESC
                LIMIT 1
            ) p ON TRUE
            LEFT JOIN LATERAL (
                SELECT ml.created_at AS latest_media_at, ml.model AS latest_model,
                       ml.provider AS latest_provider,
                       ml.metadata->>'variant_name' AS latest_variant_name,
                       ml.thumbnail_path AS latest_media_thumbnail,
                       ml.file_path AS latest_media_path
                FROM media_library ml
                WHERE ml.owner_type = 'agent' AND ml.owner_id = a.id
                  AND ml.media_type = 'image' AND ml.is_deleted = false
                  AND COALESCE(ml.metadata->>'asset_type', 'portrait') = 'portrait'
                ORDER BY ml.created_at DESC NULLS LAST, ml.id DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE a.shift_state != 'decommissioned'
            ORDER BY COALESCE(latest.latest_media_at, p.updated_at, a.updated_at) DESC NULLS LAST,
                     a.id
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        if not row.get("identity_prompt") and row["name"] in AGENT_DIVERSITY:
            desc, age = AGENT_DIVERSITY[row["name"]]
            row["diversity_desc"] = desc
            row["diversity_age"] = age
        row["has_canonical"] = bool(row.get("canonical_image_path"))
        row["has_portrait"] = bool(row.get("canonical_image_path") or row.get("latest_media_path"))
        row["has_ipadapter"] = bool(_portrait_reference_path(row))
        row["pending_review"] = bool(row.get("latest_media_path") and not row.get("approved"))

    return rows


def get_identity_audit() -> Dict:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.department, a.worker_type,
                   a.is_department_ai, a.pronouns, a.current_grade, a.bio,
                   a.writing_tone, a.communication_style, a.personality_prompt,
                   a.appearance_notes, a.gender, a.ethnicity, a.age_range,
                   a.avatar_url, a.updated_at,
                   COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(ap.identity_prompt, ''))
                       AS identity_prompt,
                   ap.canonical_image_path, ap.ip_adapter_ref_path, ap.approved
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT portrait.canonical_image_path, portrait.identity_prompt,
                       portrait.ip_adapter_ref_path, portrait.approved
                FROM agent_portraits portrait
                WHERE portrait.agent_id = a.id
                ORDER BY portrait.approved DESC NULLS LAST,
                         portrait.is_primary DESC NULLS LAST,
                         portrait.updated_at DESC NULLS LAST,
                         portrait.id DESC
                LIMIT 1
            ) ap ON TRUE
            WHERE COALESCE(a.shift_state, '') != 'decommissioned'
            ORDER BY a.department NULLS LAST, a.display_name NULLS LAST, a.id
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
        voice_profiles = {}
        try:
            cur.execute(
                """
                SELECT agent_id, profile_name, speaker, speed, pitch_shift, warmth,
                       default_emotion, emotion_overrides, is_active, updated_at
                FROM agent_voice_profiles avp
                WHERE avp.is_active = TRUE
                ORDER BY avp.agent_id, avp.updated_at DESC NULLS LAST, avp.id DESC
                """
            )
            for row in cur.fetchall():
                profile = dict(row)
                profile.pop("agent_id", None)
                for key in ("speed", "pitch_shift", "warmth"):
                    if profile.get(key) is not None:
                        profile[key] = float(profile[key])
                if profile.get("updated_at"):
                    profile["updated_at"] = profile["updated_at"].isoformat()
                voice_profiles.setdefault(row["agent_id"], profile)
        except Exception as exc:
            logger.warning("Identity audit could not load voice profiles: %s", exc)

    agents = []
    for row in rows:
        context = _portrait_identity_context(row, voice_profiles.get(row["id"]))
        missing = list(context["missing_fields"])
        agents.append(
            {
                "id": row["id"],
                "name": row.get("name"),
                "display_name": row.get("display_name") or row.get("name"),
                "department": row.get("department"),
                "worker_type": row.get("worker_type"),
                "is_department_ai": bool(row.get("is_department_ai")),
                "identity_prompt": row.get("identity_prompt") or "",
                "identity_context": context,
                "avatar_url": row.get("avatar_url"),
                "canonical_image_path": row.get("canonical_image_path"),
                "approved": bool(row.get("approved")),
                "has_reference": bool(
                    row.get("approved") and (row.get("ip_adapter_ref_path") or row.get("canonical_image_path"))
                ),
                "missing_fields": missing,
                "review_status": "complete" if not missing else "needs_review",
                "updated_at": row.get("updated_at"),
            }
        )

    missing_counts = {}
    for agent in agents:
        for field in agent["missing_fields"]:
            missing_counts[field] = missing_counts.get(field, 0) + 1
    return {
        "agents": agents,
        "summary": {
            "total": len(agents),
            "complete": sum(1 for agent in agents if agent["review_status"] == "complete"),
            "needs_review": sum(1 for agent in agents if agent["review_status"] == "needs_review"),
            "missing_field_counts": missing_counts,
        },
    }


def get_agent_portrait(agent_id: int) -> Optional[Dict]:
    """Get single agent portrait detail with variant gallery."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.avatar_url,
                   a.title, a.department, a.worker_type, a.is_department_ai,
                   a.updated_at AS avatar_updated_at,
                   p.id AS portrait_id, p.canonical_image_path,
                   COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(p.identity_prompt, ''))
                       AS identity_prompt,
                   a.pronouns, a.current_grade, a.bio, a.writing_tone,
                   a.communication_style, a.personality_prompt,
                   a.gender, a.ethnicity, a.age_range, a.appearance_notes,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags, p.refinement_draft,
                   p.created_at AS portrait_created_at,
                   p.updated_at AS portrait_updated_at,
                   COALESCE(p.updated_at, a.updated_at) AS updated_at
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT ap.id, ap.canonical_image_path, ap.identity_prompt,
                       ap.face_seed, ap.ip_adapter_ref_path, ap.approved,
                       ap.style_tags, ap.refinement_draft, ap.created_at, ap.updated_at
                FROM agent_portraits ap
                WHERE ap.agent_id = a.id
                ORDER BY ap.approved DESC NULLS LAST, ap.is_primary DESC NULLS LAST,
                         ap.updated_at DESC NULLS LAST, ap.id DESC
                LIMIT 1
            ) p ON TRUE
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
                   COALESCE(ml.model, q.params->>'model') AS model_name,
                   q.params->>'fleet_node' AS fleet_node,
                   COALESCE(ml.provider, q.params->>'provider') AS provider
            FROM media_library ml
            LEFT JOIN media_generation_queue q ON q.result_media_id = ml.id
            WHERE ml.owner_type = 'agent' AND ml.owner_id = %s
                  AND ml.media_type = 'image' AND ml.is_deleted = false
                  AND COALESCE(ml.metadata->>'asset_type', 'portrait') = 'portrait'
            ORDER BY ml.created_at DESC NULLS LAST, ml.id DESC
            """,
            (agent_id,),
        )
        result["variants"] = [dict(v) for v in cur.fetchall()]
        result["has_canonical"] = bool(result.get("canonical_image_path"))
        result["has_portrait"] = bool(result.get("canonical_image_path") or result["variants"])
        if result["variants"]:
            latest = result["variants"][0]
            result["latest_media_at"] = latest.get("created_at")
            result["latest_model"] = latest.get("model_name")
            result["latest_provider"] = latest.get("provider")
            latest_metadata = latest.get("metadata") or {}
            result["latest_variant_name"] = (
                latest_metadata.get("variant_name") if isinstance(latest_metadata, dict) else None
            )
            result["latest_media_thumbnail"] = latest.get("thumbnail_path") or latest.get("file_path")
        result["pending_review"] = bool(result["variants"] and not result.get("approved"))
        voice_profile = _get_voice_profile(agent_id)
        result["identity_context"] = _portrait_identity_context(result, voice_profile)
        result["reference_path"] = _portrait_reference_path(result)
        result["has_reference"] = bool(result["reference_path"])

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


def generate_canonical(
    agent_id: int,
    prompt_override: Optional[str] = None,
    model: Optional[str] = None,
    model_override: Optional[str] = None,
    identity_mode: Optional[str] = "auto",
    identity_weight: Optional[float] = None,
) -> Dict:
    """Generate a canonical portrait from the structured agent identity."""
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.name, a.display_name, a.first_name, a.last_name,
                   a.gender, a.pronouns, a.ethnicity, a.age_range, a.appearance_notes,
                   COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(p.identity_prompt, ''))
                       AS identity_prompt,
                   p.face_seed, p.approved, p.ip_adapter_ref_path, p.canonical_image_path
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT ap.identity_prompt, ap.face_seed, ap.approved,
                       ap.ip_adapter_ref_path, ap.canonical_image_path
                FROM agent_portraits ap
                WHERE ap.agent_id = a.id
                ORDER BY ap.approved DESC NULLS LAST, ap.is_primary DESC NULLS LAST,
                         ap.updated_at DESC NULLS LAST, ap.id DESC
                LIMIT 1
            ) p ON TRUE
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Agent not found"}

    identity_prompt = prompt_override or row.get("identity_prompt")
    if identity_prompt and "of None," in identity_prompt:
        identity_prompt = None

    identity_prompt = _compose_identity_prompt(
        identity_prompt or "",
        display_name=row.get("display_name") or row.get("name") or "",
        gender=row.get("gender") or "",
        ethnicity=row.get("ethnicity") or "",
        age_range=row.get("age_range") or "",
        appearance_notes=row.get("appearance_notes") or "",
    )
    if not identity_prompt:
        return {"success": False, "error": f"No identity_prompt set for agent {agent_id}. Set one in DHQ Roster first."}

    _ensure_portrait_record(agent_id, identity_prompt)
    seed = _stable_face_seed(agent_id, row.get("face_seed"))
    params = {
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "cfg": 7.0,
        "sampler": "euler_ancestral",
        "seed": seed,
        "asset_type": "portrait",
    }
    model_params = _portrait_model_params(model, model_override)
    reference_path = _portrait_reference_path(row)
    identity_params = _identity_generation_params(
        identity_mode,
        identity_weight,
        has_reference=bool(reference_path),
        model_params=model_params,
    )
    if identity_params.get("error"):
        return {"error": identity_params["error"]}
    params.update(model_params)
    params.update(identity_params)
    if reference_path and not params.get("provider"):
        params["ip_adapter_ref"] = reference_path
        params["ip_adapter_weight"] = params["identity_weight"]

    return submit_generation(
        user_id=None,
        media_type="image",
        prompt=identity_prompt,
        negative_prompt=_portrait_negative_prompt(),
        params=params,
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
    if value.startswith("local:"):
        return {"provider": None, "model": value[len("local:") :]}
    return {"provider": None, "model": value}


def _portrait_model_params(model: Optional[str] = None, model_override: Optional[str] = None) -> Dict:
    parsed = _parse_provider_or_model(model, model_override=model_override)
    params = {"model": parsed["model"] or DEFAULT_PORTRAIT_MODEL}
    if parsed["provider"]:
        params["provider"] = parsed["provider"]
    return params


def _identity_generation_params(
    identity_mode: Optional[str],
    identity_weight: Optional[float],
    has_reference: bool,
    model_params: Dict,
) -> Dict:
    from .comfyui_manager import normalize_identity_mode

    try:
        mode = normalize_identity_mode(
            value=identity_mode,
            has_reference=has_reference,
            provider=model_params.get("provider"),
            model=model_params.get("model"),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    try:
        weight = float(identity_weight) if identity_weight is not None else 0.85
    except (TypeError, ValueError):
        weight = 0.85
    return {
        "identity_mode": mode,
        "identity_weight": max(0.1, min(1.2, weight)),
    }


def generate_variant(
    agent_id: int,
    style: Optional[str] = None,
    pose: Optional[str] = None,
    model: Optional[str] = None,
    model_override: Optional[str] = None,
    identity_mode: Optional[str] = "auto",
    identity_weight: Optional[float] = None,
    preset: Optional[str] = None,
    scene: Optional[str] = None,
    action: Optional[str] = None,
    framing: Optional[str] = None,
    expression: Optional[str] = None,
    ke_background: Optional[bool] = False,
    variant_name: Optional[str] = None,
) -> Dict:
    """Generate a face-consistent variant from the approved canonical reference."""
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT p.identity_prompt, p.ip_adapter_ref_path, p.canonical_image_path,
                   p.face_seed, p.approved, a.name, a.display_name,
                   a.gender, a.pronouns, a.ethnicity, a.age_range, a.appearance_notes
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT ap.identity_prompt, ap.ip_adapter_ref_path,
                       ap.canonical_image_path, ap.face_seed, ap.approved
                FROM agent_portraits ap
                WHERE ap.agent_id = a.id
                ORDER BY ap.approved DESC NULLS LAST, ap.is_primary DESC NULLS LAST,
                         ap.updated_at DESC NULLS LAST, ap.id DESC
                LIMIT 1
            ) p ON TRUE
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"error": "No portrait record for this agent"}
    if not row["approved"]:
        return {"error": "Canonical portrait must be approved before generating variants"}

    base_prompt = _compose_identity_prompt(
        row["identity_prompt"] or "",
        display_name=row.get("display_name") or row.get("name") or "",
        gender=row.get("gender") or "",
        ethnicity=row.get("ethnicity") or "",
        age_range=row.get("age_range") or "",
        appearance_notes=row.get("appearance_notes") or "",
    )
    scene_prompt = compose_variant_prompt(
        preset=preset,
        style=style,
        scene=scene,
        action=action,
        framing=framing,
        expression=expression,
        ke_background=bool(ke_background),
    )
    if pose:
        scene_prompt = ", ".join(part for part in (scene_prompt, str(pose) + " pose") if part)
    if scene_prompt:
        base_prompt += ", " + scene_prompt

    params: Dict = {
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "cfg": 7.0,
        "sampler": "euler_ancestral",
        "seed": -1,
    }
    model_params = _portrait_model_params(model, model_override=model_override)
    reference_path = _portrait_reference_path(row)
    identity_params = _identity_generation_params(
        identity_mode,
        identity_weight,
        has_reference=bool(reference_path),
        model_params=model_params,
    )
    if identity_params.get("error"):
        return {"error": identity_params["error"]}
    params.update(model_params)
    params.update(identity_params)
    if reference_path and not params.get("provider"):
        params["ip_adapter_ref"] = reference_path
        params["ip_adapter_weight"] = params["identity_weight"]
    params.setdefault("asset_type", "portrait")
    resolved_variant_name = str(variant_name or action or scene or preset or style or "Custom").strip()[:100]
    params["variant_name"] = resolved_variant_name or "Custom"
    if preset:
        params["variant_preset"] = str(preset).strip().lower()
    if ke_background:
        params["variant_branding"] = "ke_corporate"
    elif preset and str(preset).strip().lower() == "ke_corporate":
        params["variant_branding"] = "ke_corporate"
    for key, value in (("scene", scene), ("action", action), ("framing", framing), ("expression", expression)):
        if value:
            params[key] = str(value).strip()

    return submit_generation(
        user_id=None,
        media_type="image",
        prompt=base_prompt,
        negative_prompt=_portrait_negative_prompt(),
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
    identity_mode: Optional[str] = "auto",
    identity_weight: Optional[float] = None,
) -> Dict:
    """Submit N portrait generation jobs in one click.

    If an approved canonical reference exists, generates identity-consistent
    style variants. Otherwise generates canonical attempts with different
    style suffixes and random seeds.

    Returns {"success": True, "queue_ids": [...], "count": N}
    """
    from .generation_service import submit_generation

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.name, a.display_name, a.first_name, a.last_name,
                   a.gender, a.pronouns, a.ethnicity, a.age_range, a.appearance_notes,
                   COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(p.identity_prompt, ''))
                       AS identity_prompt,
                   p.face_seed, p.approved, p.ip_adapter_ref_path, p.canonical_image_path
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT ap.identity_prompt, ap.face_seed, ap.approved,
                       ap.ip_adapter_ref_path, ap.canonical_image_path
                FROM agent_portraits ap
                WHERE ap.agent_id = a.id
                ORDER BY ap.approved DESC NULLS LAST, ap.is_primary DESC NULLS LAST,
                         ap.updated_at DESC NULLS LAST, ap.id DESC
                LIMIT 1
            ) p ON TRUE
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"success": False, "error": "Agent not found"}

    identity_prompt = _compose_identity_prompt(
        prompt_override or row.get("identity_prompt") or "",
        display_name=row.get("display_name") or row.get("name") or "",
        gender=row.get("gender") or "",
        ethnicity=row.get("ethnicity") or "",
        age_range=row.get("age_range") or "",
        appearance_notes=row.get("appearance_notes") or "",
    )
    if not identity_prompt.strip():
        return {"success": False, "error": "No identity prompt set. Add one in DHQ Roster first."}

    queue_ids = []
    reference_path = _portrait_reference_path(row)

    model_params = _portrait_model_params(model, model_override=model_override)
    identity_params = _identity_generation_params(
        identity_mode,
        identity_weight,
        has_reference=bool(reference_path),
        model_params=model_params,
    )
    if identity_params.get("error"):
        return {"success": False, "error": identity_params["error"]}
    for style in _FANOUT_STYLES:
        prompt = identity_prompt + (f", {style}" if style else "")
        params: Dict = {
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "cfg": 7.0,
            "sampler": "euler_ancestral",
            "seed": -1,
            "asset_type": "portrait",
        }
        params.update(model_params)
        params.update(identity_params)
        if reference_path and not params.get("provider"):
            params["ip_adapter_ref"] = reference_path
            params["ip_adapter_weight"] = params["identity_weight"]

        result = submit_generation(
            user_id=None,
            media_type="image",
            prompt=prompt,
            negative_prompt=_portrait_negative_prompt(),
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


def _poll_dispatch_queue(queue_id: int, timeout_s: int = 200) -> Optional[str]:
    """Poll dispatch_pending_queue for a cold-load-queued dispatch's result.

    Shared by _fleet_dispatch and the vision path (describe_portrait). When a
    model is cold the dispatcher defers the work to the fleet queue; the
    model_dispatch_worker routes it to a warm node and writes result_response.
    Returns the response text on 'done', or None on failed/expired/timeout.
    """
    import time as _t
    from database import get_db_cursor

    deadline = _t.time() + timeout_s
    while _t.time() < deadline:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, result_response FROM dispatch_pending_queue WHERE id = %s",
                (queue_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        if row["status"] == "done":
            return (row["result_response"] or "").strip()
        if row["status"] in ("failed", "expired"):
            return None
        _t.sleep(3)
    return None


def _fleet_dispatch(
    capability: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    context: Optional[Dict] = None,
    prefer_model: Optional[str] = None,
    prefer_agent: Optional[str] = None,
    poll_timeout_s: int = 200,
) -> str:
    """Dispatch an LLM step through DHQ with fleet-aware cold-load handling.

    request_work() runs inline when the needed model is warm on ANY node — the
    diagnostic showed capability='creative' served from M.U.S.E.@outpost-uk in
    3.5s, not the hub. When the model is cold it ENQUEUES to
    dispatch_pending_queue and returns queued=True; the model_dispatch_worker
    then routes that row to whichever node has the model warm (multi-node,
    ADR-017) and writes result_response.

    The pre-orchestration refine code treated queued=True as a FAILURE, so a
    cold model meant the whole refine failed. This instead POLLS the queue for
    the worker's result — so each stage round-trips across the fleet and the
    traffic appears in A.R.M.A.D.A. Dispatches, exactly like image generation.

    Returns the response text. Raises on hard failure / poll timeout; callers
    decide the fallback (vision/agent steps fall back to empty, M.U.S.E.
    synthesis surfaces the error so the task fails cleanly rather than hangs).
    """
    import time as _t
    import re as _re
    from tools.department_hq.services.department_dispatcher import get_dispatcher
    from database import get_db_cursor

    dispatcher = get_dispatcher()
    result = dispatcher.request_work(
        capability=capability,
        prompt=prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        module_id="media_studio",
        context=context or {"task": "portrait_refinement"},
        prefer_model=prefer_model,
        prefer_agent=prefer_agent,
        # local_only: portrait refinement is a background, non-urgent task. Never
        # escalate it to cloud contractor models when the local agent is
        # busy — that produces spurious Telegram approval prompts for what should
        # be local CPU/GPU work. routing_mode='local_only' makes the dispatcher
        # queue for local instead of firing cloud_throughput_escalation.
        local_only=True,
        user_id=None,
    )
    if result.success:
        return (result.response or "").strip()
    if not getattr(result, "queued", False):
        raise RuntimeError(result.error or "dispatch failed")

    # Queued to the fleet cold-load queue — poll for the worker's result so the
    # task routes to a warm node instead of being treated as a failure.
    m = _re.search(r"id=(\d+)", result.error or "")
    if not m:
        raise RuntimeError(f"queued without a parseable queue id: {result.error}")
    qid = int(m.group(1))
    deadline = _t.time() + poll_timeout_s
    while _t.time() < deadline:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, result_response, error FROM dispatch_pending_queue WHERE id = %s",
                (qid,),
            )
            row = cur.fetchone()
        if not row:
            raise RuntimeError(f"fleet queue row {qid} disappeared")
        status = row["status"]
        if status == "done":
            return (row["result_response"] or "").strip()
        if status in ("failed", "expired"):
            raise RuntimeError(f"fleet dispatch {status}: {row.get('error') or ''}")
        _t.sleep(3)
    raise TimeoutError(f"fleet dispatch poll timed out after {poll_timeout_s}s (queue id={qid}, cap={capability})")


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
        "TASK: Your visual portrait is being updated. "
        "What aspects of your appearance are most important to you? "
        "What should your portrait communicate about who you are and what you do? "
        "Answer in 2-3 sentences in your own voice."
    )

    try:
        # prefer_agent pins the consultation to the agent whose profile is open
        # (e.g. V.I.G.I.L.), so the agent answers in their OWN voice on their
        # own model and shows in A.R.M.A.D.A. as that agent — instead of a
        # generic 'general' agent (P.R.O.B.E.) merely role-playing the persona.
        return _fleet_dispatch(
            capability="general",
            prompt=consultation_prompt,
            context={
                "task": "agent_portrait_consultation",
                "agent_name": agent_name,
                "preferred_model": model,
            },
            prefer_model=model,
            prefer_agent=agent_name,
            poll_timeout_s=120,
        )
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
        import json as _json

        # T3481/#3454: synthesis reliability — COMPLETION over speed (owner
        # directive). capability='creative' routes to M.U.S.E. on mistral:7b. With
        # the geo_backlog flood fixed (geo no longer hogs hub mistral) synthesis
        # runs INLINE and completes — but mistral is variable on the 8GB hub
        # Quadro: ~20-25s when GPU-resident, ~260s when CPU-resident/contended
        # (observed 261s inline-success that the old 240s cap killed 21s short).
        # So give it room to FINISH: poll up to 540s. The fast case still returns
        # in ~25s and never approaches this ceiling.
        raw = _fleet_dispatch(
            capability="creative",
            prompt=synthesis_prompt,
            context={"agent_id": None, "task": "prompt_synthesis"},
            poll_timeout_s=540,
        )
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


def _run_with_timeout(fn, timeout_s: int, default, label: str):
    """Run fn() with a hard wall-clock timeout; return default on timeout/error.

    The refine pipeline runs in a max_instances=1 worker. Pre-orchestration,
    each step dispatched synchronously with NO timeout, so a step whose LLM/
    vision dispatch never returned (cold-load stall on the hub GPU) wedged the
    whole feature — every later refine was skipped 'max instances reached'
    (observed 2026-05-29, task 3453 hung 6+ min). A try/except can't catch a
    hang. This bounds each step: on timeout the worker thread returns the
    fallback and frees its slot. The orphaned sub-thread is harmless and ends
    when the dispatch finally returns.

    NOTE: do NOT use ThreadPoolExecutor as a context manager — its __exit__
    calls shutdown(wait=True), which would block on the hung task and defeat
    the timeout. shutdown(wait=False) returns immediately.
    """
    import concurrent.futures

    _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = _ex.submit(fn)
    try:
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        logger.warning("[Refine] %s timed out after %ss — using fallback", label, timeout_s)
        return default
    except Exception as exc:
        logger.warning("[Refine] %s failed: %s — using fallback", label, exc)
        return default
    finally:
        _ex.shutdown(wait=False)


def refine_identity_prompt(agent_id: int, feedback: str, history: Optional[list] = None) -> Dict:
    """Full M.U.S.E. portrait refinement pipeline (synchronous).

    Steps: vision analysis → agent self-consultation → M.U.S.E. synthesis.
    Each step is time-bounded (see _run_with_timeout) so a stalled dispatch
    cannot wedge the single-instance worker.
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

    # Vision is optional — if it stalls/cold-loads too long, proceed without it.
    vision_desc = _run_with_timeout(
        lambda: _step_vision_analysis(ctx.get("canonical_image_path") or ""),
        90,
        "",
        "vision analysis",
    )
    # Agent self-consultation is optional context — empty on timeout.
    agent_perspective = _run_with_timeout(
        lambda: _step_consult_agent(
            agent_name=agent_name,
            model=ctx.get("model") or "qwen2.5:7b",
            system_prompt=ctx.get("system_prompt") or "",
            title=ctx.get("title") or "",
            department=ctx.get("department") or "",
            current_prompt=current_prompt,
            vision_desc=vision_desc,
            feedback=feedback,
        ),
        150,
        "",
        "agent consultation",
    )
    # M.U.S.E. synthesis is the required step — on timeout, fail cleanly so the
    # task is marked failed (and the worker freed) rather than hanging forever.
    synthesis = _run_with_timeout(
        lambda: _step_muse_synthesize(
            agent_name=agent_name,
            current_prompt=current_prompt,
            vision_desc=vision_desc,
            agent_perspective=agent_perspective,
            feedback=feedback,
            history=history or [],
        ),
        600,
        {"error": "M.U.S.E. synthesis timed out after 10 min — the hub model may be wedged; check History shortly"},
        "M.U.S.E. synthesis",
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


def set_approval_dismissed(agent_id: int, media_id: int, dismissed: bool = True) -> Dict:
    """Soft-dismiss (or restore) an unapproved portrait from dashboard review.

    Toggles media_library.metadata->>'approval_dismissed' for the agent's
    portrait candidate media row. This never deletes the image and never
    changes approval state — it only hides the row from the dashboard
    quick-review until re-listed. The owner can restore it with dismissed=False.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT owner_id FROM media_library WHERE id = %s AND owner_type = 'agent' AND is_deleted = false",
            (media_id,),
        )
        row = cur.fetchone()
        if not row or row["owner_id"] != agent_id:
            return {"error": "media not found or not owned by this agent"}
        cur.execute(
            """
            UPDATE media_library
            SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{approval_dismissed}',
                    %s::jsonb,
                    true
                )
            WHERE id = %s
            """,
            (("true" if dismissed else "false"), media_id),
        )
    return {"status": "dismissed" if dismissed else "restored", "agent_id": agent_id, "media_id": media_id}


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
            INSERT INTO agent_portraits
                (agent_id, canonical_image_path, ip_adapter_ref_path, face_seed, approved, updated_at)
            VALUES (%s, %s, %s, %s, true, NOW())
            ON CONFLICT (agent_id) DO UPDATE SET
                canonical_image_path = EXCLUDED.canonical_image_path,
                ip_adapter_ref_path = EXCLUDED.ip_adapter_ref_path,
                face_seed = COALESCE(EXCLUDED.face_seed, agent_portraits.face_seed),
                approved = true,
                updated_at = NOW()
            """,
            (agent_id, file_path, file_path, seed),
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

    # DHQ dispatch — vision capability routes to Creative & Design agent.
    # PORTRAIT_DESCRIBE_MODEL selects the Ollama model (default: moondream:latest,
    # 1.8B GPU, ~11s). The dispatcher's request_work() detects images=[b64] and
    # routes through analyze_image so model choice is preserved.
    vision_model = os.getenv("PORTRAIT_DESCRIBE_MODEL", "moondream:latest")

    try:
        from tools.department_hq.services.department_dispatcher import dispatch as _dhq_dispatch
    except ImportError as e:
        return {
            "success": False,
            "prompt": "",
            "model": "",
            "error": f"DHQ dispatcher import failed: {e}",
        }

    try:
        result = _dhq_dispatch(
            capability="vision",
            prompt=VISION_DESCRIBE_PROMPT,
            module_id="portrait_service",
            images=[b64],
            local_only=True,
        )
    except Exception as e:
        logger.exception("DHQ vision dispatch for describe_portrait failed")
        return {"success": False, "prompt": "", "model": vision_model, "error": str(e)}

    # Cold vision model → deferred to the fleet cold-load queue. Poll for the
    # worker's result (routes to whichever node has the VLM warm) instead of
    # dropping it as a failure — R.E.T.I.N.A.'s vision was silently returning
    # empty before this, so it never reached the M.U.S.E. synthesis.
    _polled = None
    if not result.success and getattr(result, "queued", False):
        import re as _re

        _m = _re.search(r"id=(\d+)", result.error or "")
        if _m:
            _polled = _poll_dispatch_queue(int(_m.group(1)), timeout_s=120)

    if not result.success and not _polled:
        return {
            "success": False,
            "prompt": "",
            "model": vision_model,
            "error": result.error or "DHQ vision dispatch returned failure",
        }

    desc = (_polled if _polled else (result.response or "")).strip()
    # Strip surrounding quotes if the model added them
    if len(desc) > 2 and desc[0] in ('"', "'") and desc[-1] == desc[0]:
        desc = desc[1:-1].strip()

    if not desc:
        return {
            "success": False,
            "prompt": "",
            "model": result.model_used or vision_model,
            "error": "vision model returned empty description",
        }

    return {
        "success": True,
        "prompt": desc,
        "model": result.model_used or vision_model,
        "provider": "ollama_vision",
    }


IDENTITY_FIELDS_PROMPT = (
    "Look at this portrait. Return ONLY strict JSON with exactly these keys: "
    "appearance_notes (a concise factual description of hair, eye color, face shape, "
    "skin tone, build, and any distinctive features; never invent identity markers), "
    "gender (gender presentation, e.g. woman or man; empty string if unsure), "
    "ethnicity (ethnic or heritage background, e.g. Black or South Asian; empty string "
    "if unsure), age_range (coarse range such as 20s or 40s; empty string if unsure). "
    "Prefer empty strings over guessing."
)


def _parse_identity_fields_draft(text: str) -> Dict:
    """Best-effort parse of the vision model's JSON draft into identity fields."""
    import json as _json
    import re as _re

    draft = {"appearance_notes": "", "gender": "", "ethnicity": "", "age_range": ""}
    text = (text or "").strip()
    if not text:
        return draft
    match = _re.search(r"\{.*\}", text, _re.S)
    payload = None
    if match:
        try:
            parsed = _json.loads(match.group(0))
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
    if payload is None:
        draft["appearance_notes"] = text[:500]
        return draft
    aliases = {
        "appearance_notes": ("appearance_notes", "appearance", "appearance description", "description"),
        "gender": ("gender", "gender_presentation", "gender presentation"),
        "ethnicity": ("ethnicity", "ethnic", "ethnicity background"),
        "age_range": ("age_range", "age", "age range"),
    }
    lookup = {
        str(key).lower().strip().replace(" ", "_"): str(value).strip()
        for key, value in payload.items()
        if isinstance(value, (str, int, float))
    }
    for target, keys in aliases.items():
        for key in keys:
            if lookup.get(key):
                draft[target] = lookup[key]
                break
    if not draft["appearance_notes"]:
        draft["appearance_notes"] = text[:500]
    return {key: value[:500] for key, value in draft.items()}


def _resolve_reference_fs_path(reference_path: str) -> Optional[str]:
    """Convert a /static/… portrait URL to a readable filesystem path when present."""
    reference_path = (reference_path or "").strip()
    if not reference_path:
        return None
    rel = reference_path.lstrip("/")
    if rel.startswith("static/"):
        return os.path.join(_PLATFORM_DIR, rel)
    return reference_path if os.path.isfile(reference_path) else None


def suggest_identity_fields(agent_id: int) -> Dict:
    """Draft appearance/demographics fields from the approved reference via vision.

    Read-only — returns a draft for human review; nothing is written to agents.
    Save accepted values through save_identity_fields (agent_service single-writer).
    """
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT a.name, ap.approved, ap.ip_adapter_ref_path, ap.canonical_image_path
            FROM agents a
            LEFT JOIN LATERAL (
                SELECT aproj.approved, aproj.ip_adapter_ref_path, aproj.canonical_image_path
                FROM agent_portraits aproj
                WHERE aproj.agent_id = a.id
                ORDER BY aproj.approved DESC NULLS LAST, aproj.is_primary DESC NULLS LAST,
                         aproj.updated_at DESC NULLS LAST, aproj.id DESC
                LIMIT 1
            ) ap ON TRUE
            WHERE a.id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"success": False, "fields": {}, "model": "", "error": "Agent not found"}
    reference = _resolve_reference_fs_path(row.get("ip_adapter_ref_path") or row.get("canonical_image_path") or "")
    if not row.get("approved") or not reference or not os.path.isfile(reference):
        return {
            "success": False,
            "fields": {},
            "model": "",
            "error": "An approved reference image is required before suggesting identity fields.",
        }
    with open(reference, "rb") as file_handle:
        b64 = base64.b64encode(file_handle.read()).decode("ascii")

    vision_model = os.getenv("PORTRAIT_DESCRIBE_MODEL", "moondream:latest")
    try:
        from tools.department_hq.services.department_dispatcher import dispatch as _dhq_dispatch
    except ImportError as exc:
        return {"success": False, "fields": {}, "model": vision_model, "error": f"DHQ dispatcher import failed: {exc}"}
    try:
        result = _dhq_dispatch(
            capability="vision",
            prompt=IDENTITY_FIELDS_PROMPT,
            module_id="portrait_service",
            images=[b64],
            local_only=True,
        )
    except Exception as exc:
        logger.exception("DHQ vision dispatch for suggest_identity_fields failed")
        return {"success": False, "fields": {}, "model": vision_model, "error": str(exc)}

    _polled = None
    if not result.success and getattr(result, "queued", False):
        import re as _re

        _match = _re.search(r"id=(\d+)", result.error or "")
        if _match:
            _polled = _poll_dispatch_queue(int(_match.group(1)), timeout_s=120)
    if not result.success and not _polled:
        return {
            "success": False,
            "fields": {},
            "model": vision_model,
            "error": result.error or "DHQ vision dispatch returned failure",
        }

    desc = (_polled if _polled else (result.response or "")).strip()
    if len(desc) > 2 and desc[0] in ('"', "'") and desc[-1] == desc[0]:
        desc = desc[1:-1].strip()
    if not desc:
        return {"success": False, "fields": {}, "model": vision_model, "error": "vision model returned empty draft"}
    return {
        "success": True,
        "fields": _parse_identity_fields_draft(desc),
        "model": getattr(result, "model_used", None) or vision_model,
        "provider": "ollama_vision",
    }


def save_identity_fields(
    agent_id: int,
    appearance_notes: str = "",
    gender: str = "",
    ethnicity: str = "",
    age_range: str = "",
) -> Dict:
    """Persist human-reviewed identity fields through the single-writer agent_service."""
    cleaned = {
        field: (value or "").strip()[:500]
        for field, value in (
            ("appearance_notes", appearance_notes),
            ("gender", gender),
            ("ethnicity", ethnicity),
            ("age_range", age_range),
        )
    }
    if not agent_service.update_identity(agent_id, **cleaned):
        return {"success": False, "error": "Agent not found"}
    return {"success": True, "agent_id": agent_id, "fields": cleaned}


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
                ip_adapter_ref_path  = %s,
                identity_prompt      = %s,
                approved             = true,
                provider             = 'upload',
                resolution_w         = %s,
                resolution_h         = %s,
                updated_at           = NOW()
            WHERE agent_id = %s
            """,
            (dest_rel, dest_rel, identity_prompt, final_w, final_h, agent_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO agent_portraits
                    (agent_id, canonical_image_path, ip_adapter_ref_path, identity_prompt, approved,
                     provider, resolution_w, resolution_h, updated_at)
                VALUES
                    (%s, %s, %s, %s, true, 'upload', %s, %s, NOW())
                """,
                (agent_id, dest_rel, dest_rel, identity_prompt, final_w, final_h),
            )

    agent_service.update_agent(
        agent_id,
        avatar_url=avatar_url_relative,
        avatar_generation_prompt=identity_prompt,
        portrait_prompt=identity_prompt,
    )

    return {
        "success": True,
        "agent_id": agent_id,
        "media_id": media_id,
        "avatar_url": avatar_url_relative,
        "width": final_w,
        "height": final_h,
    }


def update_identity_prompt(agent_id: int, prompt: str) -> Dict:
    """Update the identity prompt and keep roster prompt fields synchronized."""
    prompt = (prompt or "").strip()
    if not agent_service.update_agent(
        agent_id,
        avatar_generation_prompt=prompt,
        portrait_prompt=prompt,
    ):
        return {"success": False, "error": "Agent not found"}

    _ensure_portrait_record(agent_id, prompt)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE agent_portraits SET identity_prompt = %s, updated_at = NOW()
            WHERE agent_id = %s
            """,
            (prompt, agent_id),
        )
    return {"status": "updated", "success": True, "agent_id": agent_id, "identity_prompt": prompt}


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
