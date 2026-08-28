"""Lifestyle content generation — themed prompt building, M.U.S.E. refinement, caption + queue submit."""

import logging
from typing import Dict

from database import get_db_cursor

logger = logging.getLogger(__name__)

_TYPE_SUFFIXES = {
    "lifestyle": ", environmental portrait, natural scene, photorealistic, cinematic depth of field",
    "selfie": ", close-crop selfie photo, face-forward, natural expression, soft bokeh background, authentic, photorealistic",
    "announcement": ", professional headshot, confident pose, clean background, sharp focus, photorealistic",
}


def build_lifestyle_prompt(agent_id: int, scene_id: int, generation_type: str = "lifestyle") -> Dict:
    """Build a generation prompt from an agent's identity + a scene template.

    Returns dict: prompt, negative_prompt, scene, agent — or {error: ...} on failure.
    """
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent:
        return {"error": f"Agent {agent_id} not found"}

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT s.*, t.name AS theme_name, t.tone AS theme_tone, t.accent_color
            FROM social_content_scenes s
            JOIN social_content_themes t ON t.id = s.theme_id
            WHERE s.id = %s
            """,
            (scene_id,),
        )
        scene_row = cur.fetchone()
        if not scene_row:
            return {"error": f"Scene {scene_id} not found"}
        scene = dict(scene_row)

        cur.execute(
            "SELECT identity_prompt, canonical_image_path FROM agent_portraits WHERE agent_id = %s",
            (agent_id,),
        )
        portrait_row = cur.fetchone()

    identity = (portrait_row["identity_prompt"] if portrait_row else "") or ""
    canonical_path = (portrait_row["canonical_image_path"] if portrait_row else "") or ""

    agent_description = identity or f"{agent.get('display_name', '')} — {agent.get('department', '')} professional"
    template = scene.get("visual_prompt_template", "{agent_description}")
    base_prompt = template.replace("{agent_description}", agent_description)

    suffix = _TYPE_SUFFIXES.get(generation_type, _TYPE_SUFFIXES["lifestyle"])
    prompt = base_prompt + suffix
    if scene.get("style_directive"):
        prompt += f", {scene['style_directive']}"

    return {
        "prompt": prompt,
        "negative_prompt": (
            "cartoon, anime, illustration, low quality, blurry, watermark, "
            "text overlay, duplicate faces, disfigured, extra limbs"
        ),
        "agent": {
            "id": agent_id,
            "name": agent.get("display_name") or agent.get("name"),
            "department": agent.get("department"),
            "canonical_path": canonical_path,
        },
        "scene": scene,
        "generation_type": generation_type,
    }


def refine_prompt_with_muse(prompt: str, scene_description: str = "") -> str:
    """Refine image prompt via M.U.S.E. (capability=visual_design). Falls back to original on failure."""
    from tools.department_hq.services.department_dispatcher import dispatch

    instruction = (
        f"Refine this image generation prompt to be more vivid and visually specific "
        f"while preserving the same subject and composition. "
        f"Return ONLY the refined prompt, no explanation. "
        f"Original: {prompt}"
    )
    if scene_description:
        instruction += f" Scene context: {scene_description}"

    try:
        result = dispatch("visual_design", instruction, module_id="lifestyle_service")
        if result and result.success and result.response:
            refined = result.response.strip()
            if len(refined) > 30:
                return refined
    except Exception as exc:
        logger.warning("[lifestyle] M.U.S.E. refinement failed (using original): %s", exc)
    return prompt


def generate_lifestyle_content(
    user_id: int,
    agent_id: int,
    scene_id: int,
    generation_type: str = "lifestyle",
    refine: bool = True,
) -> Dict:
    """Full pipeline: build prompt → M.U.S.E. refine → submit to queue → S.I.G.N.A.L. caption.

    Returns: {queue_id, status, prompt, refined_prompt, caption, agent, scene, generation_type}
    """
    from .calendar_service import generate_themed_caption
    from .generation_service import submit_generation

    built = build_lifestyle_prompt(agent_id, scene_id, generation_type)
    if "error" in built:
        return built

    prompt = built["prompt"]
    scene = built["scene"]
    agent = built["agent"]

    refined_prompt = refine_prompt_with_muse(prompt, scene.get("description", "")) if refine else prompt

    result = submit_generation(
        user_id=user_id,
        media_type="image",
        prompt=refined_prompt,
        negative_prompt=built["negative_prompt"],
        params={
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "seed": -1,
            "asset_type": generation_type,
            "theme_id": scene.get("theme_id"),
            "scene_id": scene_id,
        },
        owner_type="agent",
        owner_id=agent_id,
    )

    if "error" in result:
        return result

    caption = ""
    try:
        caption = generate_themed_caption(agent_id, scene["theme_id"], scene.get("description", ""))
    except Exception as exc:
        logger.warning("[lifestyle] Caption generation failed (non-blocking): %s", exc)

    return {
        "queue_id": result.get("queue_id"),
        "status": result.get("status", "pending"),
        "prompt": prompt,
        "refined_prompt": refined_prompt,
        "caption": caption,
        "agent": agent,
        "scene": scene,
        "generation_type": generation_type,
    }
