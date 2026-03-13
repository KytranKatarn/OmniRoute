# Media Studio Layer 2 — Agent Portraits + Environment Art

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable agent portrait generation with face consistency (IP-Adapter) and environment art for hub/node backgrounds, all routed through Bridge dispatcher with GPU-tiered fleet scheduling.

**Architecture:** Portrait service manages the full lifecycle: generate canonical portrait from diversity map, approve, extract IP-Adapter reference, generate consistent variants. Environment art generates starbase/starship backgrounds assigned to hub/node via `media_assignments`. All generation flows through existing `generation_service.submit_generation()` and ComfyUI fleet. Portrait routes added to existing `routes.py`. Portraits tab unlocked in template with agent grid + management panel.

**Tech Stack:** Flask, ComfyUI (IP-Adapter Plus, Impact Pack), PostgreSQL, LCARS CSS, vanilla JS

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Create:** `platform_v2/tools/media_studio/services/portrait_service.py` | Portrait lifecycle: canonical gen, variant gen, approve, IP-Adapter ref extraction, environment art |
| **Modify:** `platform_v2/tools/media_studio/routes.py` | Add 8 portrait + environment API endpoints |
| **Modify:** `platform_v2/tools/media_studio/services/comfyui_manager.py` | Add `build_ipadapter_workflow()` for face-consistent generation |
| **Modify:** `platform_v2/tools/media_studio/services/generation_service.py` | Update `submit_generation` to accept `owner_type`/`owner_id` params |
| **Modify:** `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Enable Portraits tab, add agent grid + management panel + environment section |
| **Modify:** `platform_v2/tools/media_studio/static/css/media-studio.css` | Portrait grid, agent cards, approval UI, environment preview CSS |

---

## Chunk 1: Backend — Portrait Service + ComfyUI IP-Adapter Workflow

### Task 1: Portrait Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/portrait_service.py`
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

**Context:** The existing `ai_bridge/portrait_generator.py` has `AGENT_DIVERSITY` dict mapping agent names to (description, age) tuples. The `agent_portraits` table (migration 149) stores `identity_prompt`, `face_seed`, `canonical_image_path`, `ip_adapter_ref_path`, `approved`. The `gallery_service.create_media_entry()` handles saving to `media_library`. The `generation_service.submit_generation()` handles Bridge dispatch. For canonical portraits (no IP-Adapter ref yet), we generate directly via `comfyui_manager.build_txt2img_workflow()`. For variants, we use the new `build_ipadapter_workflow()`.

- [ ] **Step 1: Write portrait_service.py**

```python
"""Portrait service — agent face generation with IP-Adapter consistency.

Manages canonical portraits, face-consistent variants, approval workflow,
and environment art for hub/node backgrounds.
"""

import logging
import os
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

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
            SELECT a.id, a.name, a.display_name, a.avatar_url, a.station_code,
                   p.id AS portrait_id, p.canonical_image_path, p.identity_prompt,
                   p.face_seed, p.ip_adapter_ref_path, p.approved,
                   p.style_tags, p.updated_at
            FROM agents a
            LEFT JOIN agent_portraits p ON p.agent_id = a.id
            WHERE a.is_active = true
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
            result["default_identity_prompt"] = _build_identity_prompt(
                result["display_name"], desc, age
            )

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
            identity_prompt = _build_identity_prompt(
                display_name, "person with distinctive features", "adult"
            )

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


def generate_variant(
    agent_id: int, style: Optional[str] = None, pose: Optional[str] = None
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
    and updates agent avatar_url. IP-Adapter ref extraction is separate step.
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
        cur.execute(
            "UPDATE agents SET avatar_url = %s WHERE id = %s",
            (thumb, agent_id),
        )

    return {"status": "approved", "agent_id": agent_id, "media_id": media_id}


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


def generate_environment(
    target_type: str, target_id: Optional[int], prompt: str
) -> Dict:
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
```

- [ ] **Step 2: Fix submit_generation to accept owner_type/owner_id**

The current `submit_generation()` in `generation_service.py` takes `user_id` and hardcodes `owner_type='user'`. We need to allow `owner_type='agent'` and `owner_type='system'` for portrait and environment generation.

**Modify:** `platform_v2/tools/media_studio/services/generation_service.py`

Find the `submit_generation` function signature and update:

```python
def submit_generation(
    user_id: int,
    media_type: str,
    prompt: str,
    negative_prompt: str = "",
    params: Optional[Dict] = None,
    owner_type: str = "user",
    owner_id: Optional[int] = None,
) -> Dict:
```

Update the owner logic inside the function:

```python
    # Use provided owner_type/owner_id, fallback to user
    actual_owner_type = owner_type
    actual_owner_id = owner_id if owner_id is not None else user_id
```

Replace `'user'` and `user_id` in the INSERT with `actual_owner_type` and `actual_owner_id`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/portrait_service.py platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): portrait service — canonical gen, variants, approval, environments"
```

---

### Task 2: IP-Adapter Workflow Builder in ComfyUI Manager

**Files:**
- Modify: `platform_v2/tools/media_studio/services/comfyui_manager.py`

**Context:** The existing `build_txt2img_workflow()` builds a 7-node standard ComfyUI workflow. We need a new function that adds IP-Adapter nodes for face consistency. IP-Adapter Plus (`ComfyUI_IPAdapter_plus`) adds nodes: `IPAdapterModelLoader`, `IPAdapterApply`. The workflow chains: load checkpoint -> load IP-Adapter model -> load reference image -> apply IP-Adapter -> KSampler -> decode -> save. This function is called by `generate_variant()` when `ip_adapter_ref` is in params.

- [ ] **Step 1: Add build_ipadapter_workflow to comfyui_manager.py**

Add after `build_txt2img_workflow`:

```python
def build_ipadapter_workflow(
    prompt: str,
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 30,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    negative_prompt: str = "",
    ip_adapter_ref: str = "",
    ip_adapter_weight: float = 0.85,
) -> Dict:
    """Build ComfyUI workflow with IP-Adapter for face-consistent generation.

    Requires ComfyUI_IPAdapter_plus custom node.
    ip_adapter_ref: path to the reference face image.
    """
    if seed == -1:
        import random
        seed = random.randint(0, 2**32 - 1)

    return {
        "3": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": model},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["3", 1]},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["3", 1]},
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "10": {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": "ip-adapter-faceid-plusv2_sdxl.bin"},
        },
        "11": {
            "class_type": "LoadImage",
            "inputs": {"image": ip_adapter_ref},
        },
        "12": {
            "class_type": "IPAdapterApply",
            "inputs": {
                "ipadapter": ["10", 0],
                "clip_vision": ["10", 1],
                "image": ["11", 0],
                "model": ["3", 0],
                "weight": ip_adapter_weight,
                "noise": 0.0,
                "weight_type": "original",
                "start_at": 0.0,
                "end_at": 1.0,
            },
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["12", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "portrait_variant"},
        },
    }
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/comfyui_manager.py
git commit -m "feat(media-studio): IP-Adapter workflow builder for face consistency"
```

---

### Task 3: Portrait + Environment API Routes

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

**Context:** Add 8 endpoints per spec section 5.6. These are thin handlers calling `portrait_service` functions. Follows existing pattern: lazy imports, `@login_required`, `current_user.id`. The assignments endpoints already exist from Layer 1.

- [ ] **Step 1: Add portrait routes to routes.py**

Add after the `# --- Assignments` section:

```python
# --- Portraits ---------------------------------------------------------------


@media_studio_bp.route("/api/portraits")
@login_required
def api_portraits():
    """All agents with portrait status for grid view."""
    from .services.portrait_service import get_all_agent_portraits

    return jsonify({"agents": get_all_agent_portraits()})


@media_studio_bp.route("/api/portraits/<int:agent_id>")
@login_required
def api_portrait_detail(agent_id):
    """Agent portrait detail with variant gallery."""
    from .services.portrait_service import get_agent_portrait

    result = get_agent_portrait(agent_id)
    if not result:
        return jsonify({"error": "Agent not found"}), 404
    return jsonify(result)


@media_studio_bp.route("/api/portraits/<int:agent_id>/generate-canonical", methods=["POST"])
@login_required
def api_generate_canonical(agent_id):
    """Generate initial canonical portrait."""
    from .services.portrait_service import generate_canonical

    data = request.get_json() or {}
    result = generate_canonical(agent_id, prompt_override=data.get("prompt"))
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/portraits/<int:agent_id>/generate-variant", methods=["POST"])
@login_required
def api_generate_variant(agent_id):
    """Generate face-consistent variant using IP-Adapter."""
    from .services.portrait_service import generate_variant

    data = request.get_json() or {}
    result = generate_variant(
        agent_id, style=data.get("style"), pose=data.get("pose")
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/portraits/<int:agent_id>/approve", methods=["POST"])
@login_required
def api_approve_canonical(agent_id):
    """Approve an image as the canonical portrait."""
    from .services.portrait_service import approve_canonical

    data = request.get_json()
    if not data or "media_id" not in data:
        return jsonify({"error": "media_id is required"}), 400
    result = approve_canonical(agent_id, data["media_id"])
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/portraits/<int:agent_id>/identity-prompt", methods=["PUT"])
@login_required
def api_update_identity_prompt(agent_id):
    """Update the identity prompt for an agent."""
    from .services.portrait_service import update_identity_prompt

    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "prompt is required"}), 400
    result = update_identity_prompt(agent_id, data["prompt"])
    return jsonify(result)


# --- Environments ------------------------------------------------------------


@media_studio_bp.route("/api/environments/generate", methods=["POST"])
@login_required
def api_generate_environment():
    """Generate hub or node background art."""
    from .services.portrait_service import generate_environment

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    target_type = data.get("target_type")
    if target_type not in ("hub", "node"):
        return jsonify({"error": "target_type must be 'hub' or 'node'"}), 400

    result = generate_environment(
        target_type=target_type,
        target_id=data.get("target_id"),
        prompt=data.get("prompt", ""),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/environments/prompts")
@login_required
def api_environment_prompts():
    """Get default environment prompt templates."""
    from .services.portrait_service import get_environment_prompts

    return jsonify({"prompts": get_environment_prompts()})
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): portrait + environment API routes — 8 new endpoints"
```

---

## Chunk 2: Frontend — Portraits Tab + Environment Section

### Task 4: Enable Portraits Tab in HTML Template

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Context:** The Portraits tab button has class `disabled` and the tab pane shows a "Layer 2" placeholder message. We need to: (1) remove `disabled` from the nav button, (2) replace the placeholder with a full agent grid + management panel + environment section. The template uses GlassNav for tab switching, `data-i18n` for i18n, `data-utc` for timestamps, and DOM API (createElement/textContent) for rendering. All dynamic content must use DOM methods (createElement, textContent, appendChild) — never set content via string concatenation into the DOM. JS functions follow the existing pattern: `loadDashboard()`, `loadGallery()`, etc.

- [ ] **Step 1: Enable the Portraits tab button**

In the template, find the disabled Portraits button (around line 50):
```html
<button class="glass-nav-item disabled" data-tab="portraits">
```
Replace with:
```html
<button class="glass-nav-item" data-tab="portraits">
```

- [ ] **Step 2: Replace the Portraits tab pane placeholder**

Find the placeholder (around line 274):
```html
<div id="ms-tab-portraits" class="ms-tab-pane">
    <div class="ms-coming-soon">
        <span data-i18n="media_studio.portraits_locked">Portraits module is planned for Layer 2 development.</span>
    </div>
</div>
```

Replace with the full portraits UI. See the HTML block below. All dynamic rendering in JS uses DOM API (createElement/textContent/appendChild), no string-to-DOM injection.

```html
<div id="ms-tab-portraits" class="ms-tab-pane">
    <!-- Agent Grid -->
    <div class="ms-section-header">
        <div class="ms-section-line"></div>
        <h3 data-i18n="media_studio.agent_portraits">Agent Portraits</h3>
        <div class="ms-section-line"></div>
    </div>

    <div class="ms-portrait-actions">
        <button class="ms-btn ms-btn-accent" onclick="generateAllMissing()" data-i18n="media_studio.generate_all_missing">Generate All Missing</button>
    </div>

    <div id="ms-portrait-grid" class="ms-portrait-grid">
        <!-- Populated by loadPortraits() -->
    </div>

    <!-- Agent Detail Panel (hidden until agent clicked) -->
    <div id="ms-portrait-detail" class="ms-portrait-detail" style="display:none;">
        <div class="ms-detail-header">
            <button class="ms-btn ms-btn-ghost" onclick="closePortraitDetail()" data-i18n="media_studio.back_to_grid">Back</button>
            <h3 id="ms-portrait-agent-name"></h3>
            <span id="ms-portrait-status" class="ms-status-badge"></span>
        </div>

        <div class="ms-detail-layout">
            <div class="ms-canonical-panel">
                <div id="ms-canonical-image" class="ms-canonical-image">
                    <div class="ms-placeholder" data-i18n="media_studio.no_canonical">No canonical portrait</div>
                </div>
                <div class="ms-canonical-actions">
                    <button class="ms-btn ms-btn-accent" onclick="generateCanonical()" data-i18n="media_studio.generate_canonical">Generate Canonical</button>
                    <button class="ms-btn ms-btn-success" id="ms-approve-btn" onclick="approveCanonical()" style="display:none;" data-i18n="media_studio.approve">Approve</button>
                </div>
            </div>

            <div class="ms-identity-panel">
                <label data-i18n="media_studio.identity_prompt">Identity Prompt</label>
                <textarea id="ms-identity-prompt" class="ms-prompt-area" rows="4"></textarea>
                <button class="ms-btn ms-btn-ghost" onclick="saveIdentityPrompt()" data-i18n="media_studio.save_prompt">Save Prompt</button>
            </div>
        </div>

        <!-- Variants Section -->
        <div class="ms-section-header" style="margin-top:24px;">
            <div class="ms-section-line"></div>
            <h3 data-i18n="media_studio.variants">Variants</h3>
            <div class="ms-section-line"></div>
        </div>

        <div class="ms-variant-actions">
            <button class="ms-btn ms-btn-accent" id="ms-variant-btn" onclick="generateVariant()" style="display:none;" data-i18n="media_studio.generate_variant">Generate Variant</button>
            <select id="ms-variant-style" class="ms-model-select">
                <option value="">Default style</option>
                <option value="professional headshot">Professional</option>
                <option value="casual portrait">Casual</option>
                <option value="action pose">Action</option>
                <option value="LCARS holographic">Holographic</option>
            </select>
        </div>

        <div id="ms-variant-grid" class="ms-recent-grid">
            <!-- Populated by loadPortraitDetail() -->
        </div>
    </div>

    <!-- Environment Art Section -->
    <div class="ms-section-header" style="margin-top:40px;">
        <div class="ms-section-line"></div>
        <h3 data-i18n="media_studio.environment_art">Environment Art</h3>
        <div class="ms-section-line"></div>
    </div>

    <div class="ms-env-grid">
        <div class="ms-env-card">
            <h4 data-i18n="media_studio.hub_background">Hub Background (Starbase)</h4>
            <div id="ms-env-hub-preview" class="ms-env-preview">
                <div class="ms-placeholder" data-i18n="media_studio.no_env">No background set</div>
            </div>
            <textarea id="ms-env-hub-prompt" class="ms-prompt-area" rows="3"></textarea>
            <button class="ms-btn ms-btn-accent" onclick="generateEnvironment('hub')" data-i18n="media_studio.generate_background">Generate</button>
        </div>
        <div class="ms-env-card">
            <h4 data-i18n="media_studio.node_background">Node Background (Starship)</h4>
            <div id="ms-env-node-select" class="ms-node-select">
                <select id="ms-env-node-id" class="ms-model-select">
                    <!-- Populated from fleet data -->
                </select>
            </div>
            <div id="ms-env-node-preview" class="ms-env-preview">
                <div class="ms-placeholder" data-i18n="media_studio.no_env">No background set</div>
            </div>
            <textarea id="ms-env-node-prompt" class="ms-prompt-area" rows="3"></textarea>
            <button class="ms-btn ms-btn-accent" onclick="generateEnvironment('node')" data-i18n="media_studio.generate_background">Generate</button>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Add JavaScript functions for Portraits tab**

Add to the script section, after the existing queue functions. **All DOM rendering uses createElement/textContent/appendChild — no string-to-DOM injection for user content.**

```javascript
// --- Portraits ---------------------------------------------------------------
var _currentAgentId = null;

function _clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
}

function loadPortraits() {
    fetch(API_BASE + '/api/portraits')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var grid = document.getElementById('ms-portrait-grid');
            _clearChildren(grid);
            (data.agents || []).forEach(function(agent) {
                var card = document.createElement('div');
                card.className = 'ms-portrait-card' + (agent.has_portrait ? ' has-portrait' : '');
                card.onclick = function() { openPortraitDetail(agent.id); };

                var thumb = document.createElement('div');
                thumb.className = 'ms-portrait-thumb';
                if (agent.avatar_url || agent.canonical_image_path) {
                    var imgEl = document.createElement('img');
                    imgEl.src = '/static/' + (agent.canonical_image_path || agent.avatar_url);
                    imgEl.alt = agent.display_name;
                    thumb.appendChild(imgEl);
                } else {
                    var placeholder = document.createElement('div');
                    placeholder.className = 'ms-portrait-placeholder';
                    placeholder.textContent = (agent.display_name || '?').charAt(0);
                    thumb.appendChild(placeholder);
                }
                card.appendChild(thumb);

                var info = document.createElement('div');
                info.className = 'ms-portrait-info';
                var name = document.createElement('span');
                name.className = 'ms-portrait-name';
                name.textContent = agent.display_name;
                info.appendChild(name);

                var status = document.createElement('span');
                status.className = 'ms-status-badge ' + (agent.approved ? 'completed' : agent.has_portrait ? 'pending' : 'idle');
                status.textContent = agent.approved ? 'Approved' : agent.has_portrait ? 'Pending' : 'No Portrait';
                info.appendChild(status);

                card.appendChild(info);
                grid.appendChild(card);
            });
            loadEnvironmentPrompts();
        });
}

function openPortraitDetail(agentId) {
    _currentAgentId = agentId;
    document.getElementById('ms-portrait-grid').style.display = 'none';
    document.querySelector('.ms-portrait-actions').style.display = 'none';
    document.getElementById('ms-portrait-detail').style.display = 'block';
    loadPortraitDetail(agentId);
}

function closePortraitDetail() {
    _currentAgentId = null;
    document.getElementById('ms-portrait-detail').style.display = 'none';
    document.getElementById('ms-portrait-grid').style.display = '';
    document.querySelector('.ms-portrait-actions').style.display = '';
}

function loadPortraitDetail(agentId) {
    fetch(API_BASE + '/api/portraits/' + agentId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('ms-portrait-agent-name').textContent = data.display_name;

            var statusBadge = document.getElementById('ms-portrait-status');
            statusBadge.className = 'ms-status-badge ' + (data.approved ? 'completed' : data.has_portrait ? 'pending' : 'idle');
            statusBadge.textContent = data.approved ? 'Approved' : 'Pending Approval';

            // Canonical image
            var canonPanel = document.getElementById('ms-canonical-image');
            _clearChildren(canonPanel);
            if (data.canonical_image_path) {
                var img = document.createElement('img');
                img.src = '/static/' + data.canonical_image_path;
                img.alt = 'Canonical portrait';
                canonPanel.appendChild(img);
            } else {
                var ph = document.createElement('div');
                ph.className = 'ms-placeholder';
                ph.textContent = 'No canonical portrait';
                canonPanel.appendChild(ph);
            }

            // Show/hide buttons
            document.getElementById('ms-approve-btn').style.display = (data.canonical_image_path && !data.approved) ? '' : 'none';
            document.getElementById('ms-variant-btn').style.display = data.approved ? '' : 'none';

            // Identity prompt
            document.getElementById('ms-identity-prompt').value = data.identity_prompt || data.default_identity_prompt || '';

            // Variants grid
            var vGrid = document.getElementById('ms-variant-grid');
            _clearChildren(vGrid);
            (data.variants || []).forEach(function(v) {
                var item = document.createElement('div');
                item.className = 'ms-gallery-item';
                item.onclick = function() { showMediaDetail(v.id); };

                var vImg = document.createElement('img');
                vImg.src = '/static/' + (v.thumbnail_path || v.file_path);
                vImg.alt = 'Variant';
                vImg.loading = 'lazy';
                item.appendChild(vImg);

                vGrid.appendChild(item);
            });
        });
}

function generateCanonical() {
    if (!_currentAgentId) return;
    var prompt = document.getElementById('ms-identity-prompt').value.trim();
    fetch(API_BASE + '/api/portraits/' + _currentAgentId + '/generate-canonical', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt: prompt || undefined})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { alert(data.error); return; }
        alert('Generation submitted. Check Queue tab for progress.');
    });
}

function generateVariant() {
    if (!_currentAgentId) return;
    var style = document.getElementById('ms-variant-style').value;
    fetch(API_BASE + '/api/portraits/' + _currentAgentId + '/generate-variant', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({style: style || undefined})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { alert(data.error); return; }
        alert('Variant generation submitted. Check Queue tab for progress.');
    });
}

function approveCanonical() {
    if (!_currentAgentId) return;
    fetch(API_BASE + '/api/portraits/' + _currentAgentId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.variants || !data.variants.length) {
                alert('No images to approve. Generate a canonical first.');
                return;
            }
            var mediaId = data.variants[0].id;
            fetch(API_BASE + '/api/portraits/' + _currentAgentId + '/approve', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({media_id: mediaId})
            })
            .then(function(r) { return r.json(); })
            .then(function(result) {
                if (result.error) { alert(result.error); return; }
                loadPortraitDetail(_currentAgentId);
            });
        });
}

function saveIdentityPrompt() {
    if (!_currentAgentId) return;
    var prompt = document.getElementById('ms-identity-prompt').value.trim();
    if (!prompt) return;
    fetch(API_BASE + '/api/portraits/' + _currentAgentId + '/identity-prompt', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt: prompt})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { alert(data.error); return; }
    });
}

function generateAllMissing() {
    fetch(API_BASE + '/api/portraits')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var missing = (data.agents || []).filter(function(a) { return !a.has_portrait; });
            if (!missing.length) { alert('All agents have portraits.'); return; }
            if (!confirm('Generate portraits for ' + missing.length + ' agents?')) return;
            missing.forEach(function(agent) {
                fetch(API_BASE + '/api/portraits/' + agent.id + '/generate-canonical', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
            });
            alert(missing.length + ' portrait generations submitted. Check Queue tab.');
        });
}

// --- Environments ------------------------------------------------------------
function loadEnvironmentPrompts() {
    fetch(API_BASE + '/api/environments/prompts')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var prompts = data.prompts || {};
            document.getElementById('ms-env-hub-prompt').value = prompts.hub || '';
            document.getElementById('ms-env-node-prompt').value = prompts.node || '';
        });

    // Load hub environment assignment
    fetch(API_BASE + '/api/assignments/hub/0?type=hub_background')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.assignment && data.assignment.file_path) {
                var preview = document.getElementById('ms-env-hub-preview');
                _clearChildren(preview);
                var img = document.createElement('img');
                img.src = '/static/' + data.assignment.file_path;
                img.alt = 'Hub background';
                preview.appendChild(img);
            }
        });
}

function generateEnvironment(targetType) {
    var promptEl = document.getElementById('ms-env-' + targetType + '-prompt');
    var prompt = promptEl.value.trim();
    if (!prompt) { alert('Enter a prompt first.'); return; }

    var body = {target_type: targetType, prompt: prompt};
    if (targetType === 'node') {
        var nodeId = document.getElementById('ms-env-node-id').value;
        if (!nodeId) { alert('Select a node first.'); return; }
        body.target_id = parseInt(nodeId);
    }

    fetch(API_BASE + '/api/environments/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { alert(data.error); return; }
        alert('Environment generation submitted. Check Queue tab.');
    });
}
```

- [ ] **Step 4: Update tab switching to load portraits**

Find the GlassNav `onSwitch` callback or `switchMsTab` function. Add a case for `portraits`:

```javascript
// In the tab switch handler, add:
if (tabId === 'portraits') loadPortraits();
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): portraits tab — agent grid, canonical gen, approval, environment art"
```

---

### Task 5: Portrait + Environment CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css`

**Context:** Add CSS for portrait grid, agent cards, detail panel, canonical image display, environment cards. Follow existing `ms-` prefix convention. Use CSS Grid for portrait grid (auto-fill, minmax(160px)). Purple accent for CREATIVE station.

- [ ] **Step 1: Append portrait and environment CSS**

Append to end of `media-studio.css`:

```css
/* ============================================================================
   S14. PORTRAITS — Agent Grid
   ============================================================================ */
.ms-portrait-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 16px;
    margin-top: 16px;
}

.ms-portrait-card {
    background: var(--ms-bg-card);
    border: 1px solid var(--ms-border);
    border-radius: var(--ms-radius);
    padding: 12px;
    cursor: pointer;
    transition: border-color 0.2s, transform 0.15s;
    text-align: center;
}

.ms-portrait-card:hover {
    border-color: var(--ms-accent);
    transform: translateY(-2px);
}

.ms-portrait-card.has-portrait {
    border-color: rgba(139, 92, 246, 0.25);
}

.ms-portrait-thumb {
    width: 120px;
    height: 120px;
    margin: 0 auto 10px;
    border-radius: 50%;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.03);
}

.ms-portrait-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.ms-portrait-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Orbitron', monospace;
    font-size: 2.4rem;
    color: var(--ms-text-tertiary);
}

.ms-portrait-info {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.ms-portrait-name {
    font-family: 'Antonio', sans-serif;
    font-size: 0.95rem;
    color: var(--ms-text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ms-portrait-actions {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 12px;
}

/* ============================================================================
   S15. PORTRAITS — Detail Panel
   ============================================================================ */
.ms-portrait-detail {
    animation: msFadeIn 0.3s ease-out;
}

.ms-detail-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 20px;
}

.ms-detail-header h3 {
    font-family: 'Orbitron', monospace;
    font-size: 1.3rem;
    color: var(--ms-accent);
    flex: 1;
}

.ms-detail-layout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
}

@media (max-width: 767px) {
    .ms-detail-layout {
        grid-template-columns: 1fr;
    }
}

.ms-canonical-panel {
    text-align: center;
}

.ms-canonical-image {
    width: 100%;
    max-width: 400px;
    aspect-ratio: 1;
    margin: 0 auto 16px;
    border-radius: var(--ms-radius);
    overflow: hidden;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--ms-border);
}

.ms-canonical-image img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.ms-canonical-actions {
    display: flex;
    gap: 10px;
    justify-content: center;
    flex-wrap: wrap;
}

.ms-identity-panel label {
    display: block;
    font-family: 'Antonio', sans-serif;
    color: var(--ms-text-secondary);
    margin-bottom: 8px;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.ms-variant-actions {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-bottom: 16px;
}

/* ============================================================================
   S16. ENVIRONMENT ART
   ============================================================================ */
.ms-env-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
    gap: 24px;
    margin-top: 16px;
}

@media (max-width: 767px) {
    .ms-env-grid {
        grid-template-columns: 1fr;
    }
}

.ms-env-card {
    background: var(--ms-bg-card);
    border: 1px solid var(--ms-border);
    border-radius: var(--ms-radius);
    padding: 20px;
}

.ms-env-card h4 {
    font-family: 'Orbitron', monospace;
    font-size: 1rem;
    color: var(--ms-accent);
    margin-bottom: 12px;
}

.ms-env-preview {
    width: 100%;
    aspect-ratio: 16/9;
    border-radius: var(--ms-radius-sm);
    overflow: hidden;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--ms-border);
    margin-bottom: 12px;
}

.ms-env-preview img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.ms-node-select {
    margin-bottom: 12px;
}

.ms-env-card .ms-prompt-area {
    margin-bottom: 12px;
}

.ms-env-card .ms-btn {
    width: 100%;
}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): portrait grid + environment art CSS"
```

---

## Chunk 3: Integration + Deploy

### Task 6: Integration Test + Deploy

**Files:** None (testing only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify module loads**

Check logs for `Loaded module: Media Studio`

- [ ] **Step 3: Test portrait endpoints**

```bash
docker exec archie_platform python3 -c "
import requests, json
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'admin','password':'Kyt\$13ran2025'})
r = s.get('http://localhost:3000/tools/media-studio/api/portraits')
data = r.json()
print(f'Agents: {len(data.get(\"agents\", []))}')
for a in data.get('agents', [])[:5]:
    print(f'  {a[\"display_name\"]}: portrait={a[\"has_portrait\"]}, approved={a.get(\"approved\", False)}')
"
```

- [ ] **Step 4: Test environment prompts endpoint**

```bash
docker exec archie_platform python3 -c "
import requests, json
s = requests.Session()
s.post('http://localhost:3000/login', data={'username':'admin','password':'Kyt\$13ran2025'})
r = s.get('http://localhost:3000/tools/media-studio/api/environments/prompts')
print(json.dumps(r.json(), indent=2))
"
```

- [ ] **Step 5: Navigate to Portraits tab in browser**

Go to http://192.168.1.200:3000/tools/media-studio and click Portraits tab.
Verify: agent grid loads with all active agents, each showing placeholder or existing avatar.

- [ ] **Step 6: Push to remote**

```bash
git push origin main
```

- [ ] **Step 7: Update Dev HQ**

```
mcp update_project_understanding — media studio layer 2 complete
mcp complete_task — with notes on portraits + environment art
mcp log_decision — "Added portrait service with IP-Adapter workflow for face consistency"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Portrait Service + generation_service update | `services/portrait_service.py`, `services/generation_service.py` |
| 2 | IP-Adapter Workflow Builder | `services/comfyui_manager.py` |
| 3 | Portrait + Environment Routes | `routes.py` (8 new endpoints) |
| 4 | Portraits Tab HTML + JS | `media_studio.html` |
| 5 | Portrait + Environment CSS | `media-studio.css` |
| 6 | Integration Test + Deploy | Test + push + Dev HQ |

**Dependency chain:** Task 1 + Task 2 (parallel, different files) -> Task 3 (routes call service) -> Task 4 + Task 5 (parallel, HTML vs CSS) -> Task 6 (integration test)
