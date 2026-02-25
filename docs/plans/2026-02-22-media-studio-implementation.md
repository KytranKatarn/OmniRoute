# Media Studio Module — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a full media suite module (image/video/audio generation) that routes through the AI Bridge with dynamic provider capability discovery, bridge-managed CREATIVE station assignment, and Telegram approval for paid generation.

**Architecture:** The Media Studio module calls the AI Bridge for all generation requests. The bridge discovers provider capabilities via a `capabilities` JSONB column on `contractor_providers`. Routing follows the existing tier pattern: free local first (TTS), then free cloud (Gemini Imagen 3), then paid cloud (OpenAI DALL-E) with Telegram approval. The existing `media_studio` Blueprint is gutted and rebuilt with new endpoints.

**Tech Stack:** Flask Blueprint, PostgreSQL (migrations), AI Bridge routing (`bridge_dispatcher.py`, `smart_router.py`, `external_providers.py`), Gemini/OpenAI/Kokoro provider adapters, LCARS gold-standard UI, existing Telegram approval system (`agent_loop.py`).

**Design doc:** `docs/plans/2026-02-22-media-studio-design.md`

**Security note:** All media generation requests require authentication. File uploads are not accepted — only text prompts routed to external APIs. Generated files are saved with UUID filenames to prevent path traversal. Provider API keys are never exposed to the frontend.

---

## Task 1: Database Migration — Capabilities Column + New Tables

**Files:**
- Create: `database/migrations/120_media_studio.sql`

**Step 1: Write the migration SQL**

Create `database/migrations/120_media_studio.sql` with:

```sql
-- Migration 120: Media Studio — capabilities column + media tables
-- Idempotent: safe to re-run

-- 1. Add capabilities JSONB column to contractor_providers
ALTER TABLE contractor_providers
ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '["text_chat"]';

-- 2. Seed capabilities for existing providers
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'minimax_cloud' AND capabilities = '["text_chat"]';
UPDATE contractor_providers SET capabilities = '["text_chat", "code"]' WHERE provider_key = 'qwen3_cloud';
UPDATE contractor_providers SET capabilities = '["text_chat", "code"]' WHERE provider_key = 'groq';
UPDATE contractor_providers SET capabilities = '["text_chat", "vision", "image_gen", "audio_tts"]' WHERE provider_key = 'gemini';
UPDATE contractor_providers SET capabilities = '["text_chat", "vision", "image_gen", "audio_tts", "code"]' WHERE provider_key = 'openai';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'cerebras';
UPDATE contractor_providers SET capabilities = '["text_chat", "code"]' WHERE provider_key = 'mistral';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'cohere';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'together';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'perplexity';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'xai';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'claude';

-- 3. Media assets table
CREATE TABLE IF NOT EXISTS media_assets (
    id SERIAL PRIMARY KEY,
    asset_type VARCHAR(20) NOT NULL,
    title VARCHAR(255),
    prompt TEXT NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT,
    mime_type VARCHAR(100),
    provider_key VARCHAR(50) NOT NULL,
    model_used VARCHAR(100),
    cost_usd DECIMAL(10,6) DEFAULT 0,
    generation_params JSONB DEFAULT '{}',
    is_profile_image BOOLEAN DEFAULT FALSE,
    agent_id INTEGER REFERENCES agents(id),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_assets_type ON media_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_media_assets_created_by ON media_assets(created_by);
CREATE INDEX IF NOT EXISTS idx_media_assets_agent ON media_assets(agent_id) WHERE agent_id IS NOT NULL;

-- 4. Media generation queue
CREATE TABLE IF NOT EXISTS media_generation_queue (
    id SERIAL PRIMARY KEY,
    request_type VARCHAR(20) NOT NULL,
    prompt TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'pending',
    provider_key VARCHAR(50),
    model_used VARCHAR(100),
    assigned_agent_id INTEGER REFERENCES agents(id),
    result_asset_id INTEGER REFERENCES media_assets(id),
    error_message TEXT,
    requested_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_queue_status ON media_generation_queue(status);
CREATE INDEX IF NOT EXISTS idx_media_queue_requested_by ON media_generation_queue(requested_by);
```

**Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/120_media_studio.sql
```

Expected: No errors. Tables created, column added.

**Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d contractor_providers" | grep capabilities
docker exec archie_database psql -U archie -d archie -c "\d media_assets"
docker exec archie_database psql -U archie -d archie -c "\d media_generation_queue"
docker exec archie_database psql -U archie -d archie -c "SELECT provider_key, capabilities FROM contractor_providers ORDER BY tier_position;"
```

Expected: `capabilities` column visible with JSONB type, both new tables exist, Gemini shows `["text_chat", "vision", "image_gen", "audio_tts"]`.

**Step 4: Commit**

```bash
git add database/migrations/120_media_studio.sql
git commit -m "feat(media): add capabilities column and media_assets/queue tables"
```

---

## Task 2: Provider Capability Discovery Function

**Files:**
- Modify: `ai_bridge/external_providers.py` (after line ~145, near `invalidate_provider_cache()`)

**Step 1: Add `get_providers_with_capability()` function**

Insert after the `invalidate_provider_cache()` function (line ~151):

```python
def get_providers_with_capability(capability: str) -> list:
    """Return active providers that support a given capability, ordered by tier_position.

    Args:
        capability: e.g. 'image_gen', 'audio_tts', 'video_gen', 'text_chat'

    Returns:
        List of dicts: [{provider_key, display_name, capabilities, is_free_tier, tier_position, models}]
    """
    _load_all_providers()
    results = []
    for key, provider in _provider_cache.items():
        caps = provider.get("capabilities", ["text_chat"])
        if capability in caps and provider.get("is_active", False):
            results.append({
                "provider_key": key,
                "display_name": provider.get("display_name", key),
                "capabilities": caps,
                "is_free_tier": not provider.get("is_cloud_proxy", False) and provider.get("tier_position", 99) >= 8,
                "tier_position": provider.get("tier_position", 99),
                "models": provider.get("models", []),
                "base_url": provider.get("base_url", ""),
            })
    results.sort(key=lambda p: p["tier_position"])
    return results
```

**Step 2: Add `get_all_capabilities()` summary function**

Insert right after:

```python
def get_all_capabilities() -> dict:
    """Return a summary of which capabilities are available and how many providers support each.

    Returns:
        Dict: {capability: [{provider_key, display_name, is_free_tier}]}
    """
    _load_all_providers()
    caps_map = {}
    for key, provider in _provider_cache.items():
        if not provider.get("is_active", False):
            continue
        for cap in provider.get("capabilities", ["text_chat"]):
            if cap not in caps_map:
                caps_map[cap] = []
            caps_map[cap].append({
                "provider_key": key,
                "display_name": provider.get("display_name", key),
                "is_free_tier": not provider.get("is_cloud_proxy", False) and provider.get("tier_position", 99) >= 8,
            })
    return caps_map
```

**Step 3: Update `_load_all_providers()` to include capabilities in cache**

In `_load_all_providers()` (line ~47), find the SQL SELECT query and ensure `capabilities` is included. The current query selects `*` from `contractor_providers`, so it already includes the column — but verify the row-to-dict mapping includes it. If the function uses `dict(row)` or `row._asdict()`, it's automatic. If it cherry-picks columns, add `capabilities`.

**Step 4: Verify capability discovery**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.external_providers import get_providers_with_capability, get_all_capabilities
print('Image providers:', get_providers_with_capability('image_gen'))
print('TTS providers:', get_providers_with_capability('audio_tts'))
print('All capabilities:', list(get_all_capabilities().keys()))
"
```

Expected: Gemini appears in image_gen list. Gemini appears in audio_tts list. All capabilities include at least `text_chat`, `image_gen`, `audio_tts`, `code`, `vision`.

**Step 5: Commit**

```bash
git add ai_bridge/external_providers.py
git commit -m "feat(media): add provider capability discovery functions"
```

---

## Task 3: Bridge Routing — Station Map + Media Capability Routing

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (lines ~33-98, CAPABILITY_STATION_MAP)
- Modify: `ai_bridge/smart_router.py` (lines ~160-173, CAPABILITY_ROUTING)

**Step 1: Add media capabilities to CAPABILITY_STATION_MAP**

In `bridge_dispatcher.py`, find the `CAPABILITY_STATION_MAP` dict (line ~33). Add these entries alongside the existing ones:

```python
"image_generation": "CREATIVE",
"video_generation": "CREATIVE",
"audio_generation": "CREATIVE",
"audio_tts": "CREATIVE",
"audio_music": "CREATIVE",
"media_editing": "CREATIVE",
```

**Step 2: Add media routing to CAPABILITY_ROUTING**

In `smart_router.py`, find the `CAPABILITY_ROUTING` dict (line ~160). Add:

```python
"image_generation": "gemini",      # Free cloud — Ollama can't generate images
"video_generation": "gemini",      # Cloud only
"audio_tts": "local",             # Kokoro/XTTS local first
"audio_music": "gemini",          # Cloud only
```

Note: These map to tier names. `"gemini"` routes to the gemini tier in `DEFAULT_MODEL_CONFIGS`. `"local"` routes to the dolphin3-8k local tier. For audio_tts, we'll handle the Kokoro/XTTS routing in the adapter (Task 6), not in the smart router — the smart router is for LLM model selection.

**Step 3: Verify routing resolves**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.smart_router import CAPABILITY_ROUTING
print('image_generation routes to:', CAPABILITY_ROUTING.get('image_generation'))
print('audio_tts routes to:', CAPABILITY_ROUTING.get('audio_tts'))
"
```

Expected: `image_generation routes to: gemini`, `audio_tts routes to: local`.

**Step 4: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py ai_bridge/smart_router.py
git commit -m "feat(media): add media capabilities to bridge station map and routing"
```

---

## Task 4: Media Generation Adapters — Gemini Image + OpenAI Image

**Files:**
- Modify: `ai_bridge/external_providers.py` (add new section after `call_external()`, line ~396)

**Step 1: Add the unified `generate_media()` dispatcher**

Insert after `call_external()`:

```python
def generate_media(provider_key: str, request: dict) -> dict:
    """Generate media (image/video/audio) via a provider adapter.

    Args:
        provider_key: e.g. 'gemini', 'openai', 'local_tts'
        request: {type, prompt, params: {size, style, duration, voice, ...}}

    Returns:
        {success: bool, file_path: str, metadata: dict, error: str}
    """
    adapters = {
        "gemini": _gemini_media_adapter,
        "openai": _openai_image_adapter,
        "local_tts": _local_tts_adapter,
    }
    adapter = adapters.get(provider_key)
    if not adapter:
        return {"success": False, "error": f"No media adapter for provider: {provider_key}"}

    try:
        return adapter(request)
    except Exception as e:
        logger.error(f"Media generation failed ({provider_key}): {e}")
        return {"success": False, "error": str(e)}
```

**Step 2: Add Gemini Imagen 3 adapter**

```python
def _gemini_media_adapter(request: dict) -> dict:
    """Generate images via Gemini Imagen 3 API."""
    import requests as http_requests
    import uuid
    import os
    from datetime import datetime

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY not configured"}

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    req_type = request.get("type", "image")

    if req_type != "image":
        return {"success": False, "error": f"Gemini adapter only supports image generation, got: {req_type}"}

    # Gemini Imagen 3 via generateContent with image output
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={api_key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": params.get("aspect_ratio", "1:1"),
            "safetyFilterLevel": "block_few",
        }
    }

    resp = http_requests.post(url, json=payload, timeout=60)
    if resp.status_code != 200:
        return {"success": False, "error": f"Gemini API error {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    predictions = data.get("predictions", [])
    if not predictions:
        return {"success": False, "error": "Gemini returned no predictions"}

    # Decode base64 image
    import base64
    img_b64 = predictions[0].get("bytesBase64Encoded", "")
    if not img_b64:
        return {"success": False, "error": "Gemini returned empty image data"}

    img_bytes = base64.b64decode(img_b64)

    # Save to disk
    date_str = datetime.now().strftime("%Y-%m-%d")
    file_uuid = str(uuid.uuid4())[:12]
    rel_dir = f"static/media/images/{date_str}"
    abs_dir = os.path.join("/mnt/archie_brain/platform_v2", rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    file_name = f"{file_uuid}.png"
    file_path = os.path.join(abs_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(img_bytes)

    return {
        "success": True,
        "file_path": f"/{rel_dir}/{file_name}",
        "metadata": {
            "provider": "gemini",
            "model": "imagen-3.0-generate-002",
            "cost_usd": 0.0,
            "mime_type": "image/png",
            "file_size_bytes": len(img_bytes),
            "aspect_ratio": params.get("aspect_ratio", "1:1"),
        }
    }
```

**Step 3: Add OpenAI DALL-E 3 adapter**

```python
def _openai_image_adapter(request: dict) -> dict:
    """Generate images via OpenAI DALL-E 3 API."""
    import requests as http_requests
    import uuid
    import os
    from datetime import datetime

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "OPENAI_API_KEY not configured"}

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    size = params.get("size", "1024x1024")
    quality = params.get("quality", "standard")
    style = params.get("style", "vivid")

    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "style": style,
        "response_format": "b64_json",
    }

    resp = http_requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        return {"success": False, "error": f"OpenAI API error {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    images = data.get("data", [])
    if not images:
        return {"success": False, "error": "OpenAI returned no images"}

    import base64
    img_b64 = images[0].get("b64_json", "")
    revised_prompt = images[0].get("revised_prompt", prompt)
    img_bytes = base64.b64decode(img_b64)

    # Cost calculation
    cost_map = {
        "1024x1024": {"standard": 0.04, "hd": 0.08},
        "1024x1792": {"standard": 0.08, "hd": 0.12},
        "1792x1024": {"standard": 0.08, "hd": 0.12},
    }
    cost_usd = cost_map.get(size, {}).get(quality, 0.04)

    # Save to disk
    date_str = datetime.now().strftime("%Y-%m-%d")
    file_uuid = str(uuid.uuid4())[:12]
    rel_dir = f"static/media/images/{date_str}"
    abs_dir = os.path.join("/mnt/archie_brain/platform_v2", rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    file_name = f"{file_uuid}.png"
    file_path = os.path.join(abs_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(img_bytes)

    return {
        "success": True,
        "file_path": f"/{rel_dir}/{file_name}",
        "metadata": {
            "provider": "openai",
            "model": "dall-e-3",
            "cost_usd": cost_usd,
            "mime_type": "image/png",
            "file_size_bytes": len(img_bytes),
            "size": size,
            "quality": quality,
            "style": style,
            "revised_prompt": revised_prompt,
        }
    }
```

**Step 4: Add local TTS adapter stub**

```python
def _local_tts_adapter(request: dict) -> dict:
    """Generate audio via local Kokoro/XTTS engines."""
    import requests as http_requests
    import uuid
    import os
    from datetime import datetime

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    voice = params.get("voice", "default")
    language = params.get("language", "en")

    # Call existing Voice DNA endpoint
    tts_url = "http://localhost:3000/api/voice/generate"
    payload = {
        "text": prompt,
        "speaker": voice,
        "language": language,
        "emotion": params.get("emotion", "neutral"),
    }

    try:
        resp = http_requests.post(tts_url, json=payload, timeout=30)
        if resp.status_code != 200:
            return {"success": False, "error": f"Local TTS error {resp.status_code}: {resp.text[:200]}"}

        audio_bytes = resp.content

        date_str = datetime.now().strftime("%Y-%m-%d")
        file_uuid = str(uuid.uuid4())[:12]
        rel_dir = f"static/media/audio/{date_str}"
        abs_dir = os.path.join("/mnt/archie_brain/platform_v2", rel_dir)
        os.makedirs(abs_dir, exist_ok=True)

        file_name = f"{file_uuid}.wav"
        file_path = os.path.join(abs_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(audio_bytes)

        return {
            "success": True,
            "file_path": f"/{rel_dir}/{file_name}",
            "metadata": {
                "provider": "local_tts",
                "model": "kokoro" if language == "en" else "xtts_v2",
                "cost_usd": 0.0,
                "mime_type": "audio/wav",
                "file_size_bytes": len(audio_bytes),
                "language": language,
                "voice": voice,
            }
        }
    except http_requests.ConnectionError:
        return {"success": False, "error": "Local TTS service unavailable"}
```

**Step 5: Verify adapters import correctly**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.external_providers import generate_media, get_providers_with_capability
print('generate_media function:', generate_media)
print('Image providers:', [p['provider_key'] for p in get_providers_with_capability('image_gen')])
"
```

Expected: Function imported, Gemini listed as image provider.

**Step 6: Commit**

```bash
git add ai_bridge/external_providers.py
git commit -m "feat(media): add Gemini, OpenAI, and local TTS media generation adapters"
```

---

## Task 5: Create Media File Storage Directory Structure

**Files:**
- Create: `platform_v2/static/media/.gitkeep`

**Step 1: Create the directory structure**

```bash
mkdir -p /mnt/archie_brain/platform_v2/static/media/images
mkdir -p /mnt/archie_brain/platform_v2/static/media/video
mkdir -p /mnt/archie_brain/platform_v2/static/media/audio
touch /mnt/archie_brain/platform_v2/static/media/.gitkeep
```

**Step 2: Add .gitignore for generated files**

Create `platform_v2/static/media/.gitignore`:

```
# Keep directory structure but ignore generated media files
*
!.gitkeep
!.gitignore
!images/
!video/
!audio/
images/*
video/*
audio/*
```

**Step 3: Commit**

```bash
git add platform_v2/static/media/.gitkeep platform_v2/static/media/.gitignore
git commit -m "feat(media): create media file storage directory structure"
```

---

## Task 6: Rewrite Media Studio Routes — Core Endpoints

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py` (gut and rewrite entirely)

**Step 1: Rewrite routes.py with new endpoints**

Replace the entire contents of `platform_v2/tools/media_studio/routes.py` with:

```python
"""Media Studio Module — Image, Video, and Audio generation via AI Bridge.

Routes through the bridge for provider capability discovery, CREATIVE station
assignment, and smart router escalation (free → paid with Telegram approval).
"""

import os
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session, g
from functools import wraps

logger = logging.getLogger(__name__)

media_studio_bp = Blueprint(
    "media_studio", __name__,
    url_prefix="/tools/media-studio",
    template_folder="templates"
)


def login_required_api(f):
    """Decorator for API endpoints requiring authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def get_db():
    """Get database connection from app context."""
    from database import get_db_connection
    return get_db_connection()


# ─── Page Route ────────────────────────────────────────────────────

@media_studio_bp.route("/")
def media_studio_page():
    """Render the Media Studio module page."""
    if "user_id" not in session:
        return render_template("login.html")
    return render_template("tools/media_studio.html")


# ─── Capabilities ──────────────────────────────────────────────────

@media_studio_bp.route("/api/capabilities", methods=["GET"])
@login_required_api
def get_capabilities():
    """Return available media generation capabilities from configured providers."""
    try:
        from ai_bridge.external_providers import get_all_capabilities, get_providers_with_capability

        media_caps = {}
        for cap in ["image_gen", "video_gen", "audio_tts", "audio_music", "vision"]:
            providers = get_providers_with_capability(cap)
            if providers:
                media_caps[cap] = [{
                    "provider_key": p["provider_key"],
                    "display_name": p["display_name"],
                    "is_free_tier": p["is_free_tier"],
                } for p in providers]

        return jsonify({
            "capabilities": media_caps,
            "supported_types": [k for k in media_caps if media_caps[k]],
        })
    except Exception as e:
        logger.error(f"Failed to load capabilities: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Generation ────────────────────────────────────────────────────

@media_studio_bp.route("/api/generate", methods=["POST"])
@login_required_api
def generate_media():
    """Submit a media generation request.

    Body: {type: "image"|"video"|"audio_tts"|"audio_music", prompt: str, params: {}}

    For fast providers (image): returns result synchronously.
    For slow providers (video/music): returns queue job ID for polling.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        req_type = data.get("type", "image")
        prompt = data.get("prompt", "").strip()
        params = data.get("params", {})

        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400

        if req_type not in ("image", "video", "audio_tts", "audio_music"):
            return jsonify({"error": f"Unsupported type: {req_type}"}), 400

        # Map request type to capability name
        cap_map = {
            "image": "image_gen",
            "video": "video_gen",
            "audio_tts": "audio_tts",
            "audio_music": "audio_music",
        }
        capability = cap_map[req_type]

        # Find provider
        from ai_bridge.external_providers import get_providers_with_capability, generate_media as bridge_generate

        providers = get_providers_with_capability(capability)
        if not providers:
            return jsonify({"error": f"No providers available for {req_type} generation"}), 503

        # Pick first available (sorted by tier_position — free first)
        provider = providers[0]
        provider_key = provider["provider_key"]
        is_free = provider["is_free_tier"]

        user_id = session.get("user_id")

        # Insert queue entry
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO media_generation_queue
                (request_type, prompt, params, status, provider_key, requested_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (req_type, prompt, jsonify(params).get_data(as_text=True) if params else '{}',
              "generating", provider_key, user_id))
        queue_id = cur.fetchone()[0]
        conn.commit()

        # For paid providers, check approval
        if not is_free:
            # Check auto-approve threshold
            cur.execute("SELECT value FROM system_config WHERE key = 'media_auto_approve_under_usd'")
            row = cur.fetchone()
            auto_threshold = float(row[0]) if row else 0.0
            estimated_cost = 0.04  # Default estimate for DALL-E

            if estimated_cost > auto_threshold:
                cur.execute("""
                    UPDATE media_generation_queue SET status = 'awaiting_approval'
                    WHERE id = %s
                """, (queue_id,))
                conn.commit()

                # Request approval via existing system
                try:
                    from ai_bridge.agent_loop import request_approval
                    request_approval(
                        action_type="media_generation",
                        action_data={
                            "queue_id": queue_id,
                            "type": req_type,
                            "prompt": prompt[:200],
                            "provider": provider_key,
                            "estimated_cost": estimated_cost,
                        },
                        reason=f"Media generation ({req_type}) via {provider_key} — est. ${estimated_cost:.4f}",
                        requested_by=f"user:{user_id}",
                        priority="normal",
                        tier=2
                    )
                except Exception as e:
                    logger.error(f"Failed to request approval: {e}")

                return jsonify({
                    "queue_id": queue_id,
                    "status": "awaiting_approval",
                    "message": f"Paid provider ({provider_key}) requires admin approval via Telegram",
                })

        # Synchronous generation for fast providers (images)
        import json
        media_request = {
            "type": req_type,
            "prompt": prompt,
            "params": params,
        }

        # Special case: local TTS
        if req_type == "audio_tts":
            provider_key = "local_tts"

        result = bridge_generate(provider_key, media_request)

        if not result.get("success"):
            cur.execute("""
                UPDATE media_generation_queue
                SET status = 'failed', error_message = %s, completed_at = NOW()
                WHERE id = %s
            """, (result.get("error", "Unknown error"), queue_id))
            conn.commit()
            return jsonify({
                "queue_id": queue_id,
                "status": "failed",
                "error": result.get("error"),
            }), 500

        # Save asset
        meta = result.get("metadata", {})
        cur.execute("""
            INSERT INTO media_assets
                (asset_type, prompt, file_path, file_size_bytes, mime_type,
                 provider_key, model_used, cost_usd, generation_params, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            req_type, prompt, result["file_path"],
            meta.get("file_size_bytes", 0), meta.get("mime_type", ""),
            meta.get("provider", provider_key), meta.get("model", ""),
            meta.get("cost_usd", 0), json.dumps(params), user_id
        ))
        asset_id = cur.fetchone()[0]

        # Update queue
        cur.execute("""
            UPDATE media_generation_queue
            SET status = 'completed', result_asset_id = %s, model_used = %s, completed_at = NOW()
            WHERE id = %s
        """, (asset_id, meta.get("model", ""), queue_id))
        conn.commit()

        return jsonify({
            "queue_id": queue_id,
            "status": "completed",
            "asset_id": asset_id,
            "file_path": result["file_path"],
            "metadata": meta,
        })

    except Exception as e:
        logger.error(f"Media generation error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ─── Queue ─────────────────────────────────────────────────────────

@media_studio_bp.route("/api/queue", methods=["GET"])
@login_required_api
def list_queue():
    """List media generation queue for current user."""
    try:
        user_id = session.get("user_id")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT q.id, q.request_type, q.prompt, q.status, q.provider_key,
                   q.model_used, q.error_message, q.created_at, q.completed_at,
                   q.result_asset_id,
                   a.file_path AS result_file_path
            FROM media_generation_queue q
            LEFT JOIN media_assets a ON q.result_asset_id = a.id
            WHERE q.requested_by = %s
            ORDER BY q.created_at DESC
            LIMIT 50
        """, (user_id,))

        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        # Serialize datetimes
        for row in rows:
            for key in ("created_at", "completed_at"):
                if row.get(key):
                    row[key] = row[key].isoformat()

        return jsonify({"queue": rows})
    except Exception as e:
        logger.error(f"Queue list error: {e}")
        return jsonify({"error": str(e)}), 500


@media_studio_bp.route("/api/queue/<int:queue_id>", methods=["GET"])
@login_required_api
def get_queue_item(queue_id):
    """Get single queue item status (for polling)."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT q.*, a.file_path AS result_file_path
            FROM media_generation_queue q
            LEFT JOIN media_assets a ON q.result_asset_id = a.id
            WHERE q.id = %s AND q.requested_by = %s
        """, (queue_id, session.get("user_id")))

        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404

        columns = [desc[0] for desc in cur.description]
        item = dict(zip(columns, row))
        for key in ("created_at", "completed_at", "started_at"):
            if item.get(key):
                item[key] = item[key].isoformat()

        return jsonify(item)
    except Exception as e:
        logger.error(f"Queue item error: {e}")
        return jsonify({"error": str(e)}), 500


@media_studio_bp.route("/api/queue/<int:queue_id>", methods=["DELETE"])
@login_required_api
def cancel_queue_item(queue_id):
    """Cancel a pending queue item."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE media_generation_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE id = %s AND requested_by = %s AND status IN ('pending', 'awaiting_approval')
            RETURNING id
        """, (queue_id, session.get("user_id")))

        row = cur.fetchone()
        conn.commit()

        if not row:
            return jsonify({"error": "Not found or not cancellable"}), 404

        return jsonify({"status": "cancelled", "queue_id": queue_id})
    except Exception as e:
        logger.error(f"Queue cancel error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Gallery ───────────────────────────────────────────────────────

@media_studio_bp.route("/api/gallery", methods=["GET"])
@login_required_api
def list_gallery():
    """Browse completed media assets."""
    try:
        asset_type = request.args.get("type")
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))

        conn = get_db()
        cur = conn.cursor()

        query = """
            SELECT id, asset_type, title, prompt, file_path, file_size_bytes,
                   mime_type, provider_key, model_used, cost_usd, generation_params,
                   is_profile_image, agent_id, created_at
            FROM media_assets
            WHERE created_by = %s AND deleted_at IS NULL
        """
        params_list = [session.get("user_id")]

        if asset_type:
            query += " AND asset_type = %s"
            params_list.append(asset_type)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params_list.extend([limit, offset])

        cur.execute(query, params_list)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            if row.get("cost_usd"):
                row["cost_usd"] = float(row["cost_usd"])

        return jsonify({"assets": rows, "count": len(rows)})
    except Exception as e:
        logger.error(f"Gallery list error: {e}")
        return jsonify({"error": str(e)}), 500


@media_studio_bp.route("/api/gallery/<int:asset_id>", methods=["GET"])
@login_required_api
def get_asset(asset_id):
    """Get single asset details."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM media_assets
            WHERE id = %s AND created_by = %s AND deleted_at IS NULL
        """, (asset_id, session.get("user_id")))

        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404

        columns = [desc[0] for desc in cur.description]
        asset = dict(zip(columns, row))
        for key in ("created_at", "deleted_at"):
            if asset.get(key):
                asset[key] = asset[key].isoformat()
        if asset.get("cost_usd"):
            asset["cost_usd"] = float(asset["cost_usd"])

        return jsonify(asset)
    except Exception as e:
        logger.error(f"Asset get error: {e}")
        return jsonify({"error": str(e)}), 500


@media_studio_bp.route("/api/gallery/<int:asset_id>", methods=["DELETE"])
@login_required_api
def delete_asset(asset_id):
    """Soft-delete a media asset."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE media_assets SET deleted_at = NOW()
            WHERE id = %s AND created_by = %s AND deleted_at IS NULL
            RETURNING id
        """, (asset_id, session.get("user_id")))

        row = cur.fetchone()
        conn.commit()

        if not row:
            return jsonify({"error": "Not found"}), 404

        return jsonify({"status": "deleted", "asset_id": asset_id})
    except Exception as e:
        logger.error(f"Asset delete error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Profile Picture ───────────────────────────────────────────────

@media_studio_bp.route("/api/gallery/<int:asset_id>/set-profile", methods=["POST"])
@login_required_api
def set_profile_image(asset_id):
    """Set a generated image as an agent's profile picture."""
    try:
        data = request.get_json() or {}
        agent_id = data.get("agent_id")

        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400

        conn = get_db()
        cur = conn.cursor()

        # Get the asset
        cur.execute("""
            SELECT file_path, asset_type FROM media_assets
            WHERE id = %s AND created_by = %s AND deleted_at IS NULL
        """, (asset_id, session.get("user_id")))

        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Asset not found"}), 404

        file_path, asset_type = row
        if asset_type != "image":
            return jsonify({"error": "Only images can be set as profile pictures"}), 400

        # Clear previous profile image flag
        cur.execute("""
            UPDATE media_assets SET is_profile_image = FALSE
            WHERE agent_id = %s AND is_profile_image = TRUE
        """, (agent_id,))

        # Set new profile image
        cur.execute("""
            UPDATE media_assets SET is_profile_image = TRUE, agent_id = %s
            WHERE id = %s
        """, (agent_id, asset_id))

        # Update agent avatar_url
        cur.execute("""
            UPDATE agents SET avatar_url = %s WHERE id = %s
        """, (file_path, agent_id))

        conn.commit()

        return jsonify({
            "status": "set",
            "agent_id": agent_id,
            "asset_id": asset_id,
            "avatar_url": file_path,
        })
    except Exception as e:
        logger.error(f"Set profile error: {e}")
        return jsonify({"error": str(e)}), 500


# ─── Status/Health ─────────────────────────────────────────────────

@media_studio_bp.route("/api/status", methods=["GET"])
@login_required_api
def media_status():
    """Health check for Media Studio."""
    try:
        from ai_bridge.external_providers import get_providers_with_capability

        image_providers = get_providers_with_capability("image_gen")
        tts_providers = get_providers_with_capability("audio_tts")

        return jsonify({
            "status": "operational" if image_providers else "degraded",
            "image_providers": len(image_providers),
            "tts_providers": len(tts_providers),
            "providers": {
                "image_gen": [p["provider_key"] for p in image_providers],
                "audio_tts": [p["provider_key"] for p in tts_providers],
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
```

**Step 2: Verify endpoints load without errors**

```bash
docker compose restart archie_platform
sleep 3
docker exec archie_platform python3 -c "from tools.media_studio.routes import media_studio_bp; print('Blueprint loaded:', media_studio_bp.name)"
```

Expected: `Blueprint loaded: media_studio`

**Step 3: Test capabilities endpoint**

```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/media-studio/api/capabilities | python3 -m json.tool
```

Expected: JSON with `capabilities` containing `image_gen` with Gemini listed.

**Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media): rewrite Media Studio routes with capability discovery and generation endpoints"
```

---

## Task 7: Update Module Registry — Move from Placeholder to Active

**Files:**
- Modify: `platform_v2/module_registry.py` (media_studio entry)

**Step 1: Update the module definition**

Find the `media_studio` entry in `module_registry.py` and change:
- `category` from `ModuleCategory.PLACEHOLDERS_FUTURE` to `ModuleCategory.CREATIVE` (or the appropriate active category)
- `description` to `"Generate images, video, and audio with AI — routes through the bridge for dynamic provider selection"`
- `tags` to `["ai", "images", "video", "audio", "creative", "generation", "media"]`
- Remove `"placeholder"` from tags

**Step 2: Verify module appears in active modules**

```bash
docker compose restart archie_platform
sleep 3
curl -s http://192.168.1.200:3000/api/modules | python3 -c "import sys,json; mods=json.load(sys.stdin); print([m['id'] for m in mods if 'media' in m['id']])"
```

Expected: `['media_studio']` appears in the list.

**Step 3: Commit**

```bash
git add platform_v2/module_registry.py
git commit -m "feat(media): activate Media Studio module — move from placeholder to active"
```

---

## Task 8: Create Media Studio Template — LCARS UI with 3 Tabs

**Files:**
- Create: `platform_v2/templates/tools/media_studio.html`

**Step 1: Create the template**

Create `platform_v2/templates/tools/media_studio.html` following the LCARS gold-standard module pattern (refer to `bridge.html` or `dashboard_dynamic.html` for the framed header, icon nav, tab pills pattern). The template should include:

**Header section:**
- LCARS framed header with "Media Studio" title, Lucide `palette` icon
- Status indicator showing connected provider count

**3 tab pills:**
1. **Create** (default active tab)
2. **Queue**
3. **Gallery**

**Create tab content:**
- Type selector: 3 buttons (Image, Video, Audio) — greyed out if no providers available for that type
- Provider capability indicator (shows which providers available for selected type, free vs paid badge)
- Prompt textarea (4 rows)
- Parameter controls section:
  - Image: size dropdown (1024x1024, 1024x1792, 1792x1024), style (vivid/natural), quality (standard/hd)
  - Audio TTS: voice selector, language dropdown
  - Video: placeholder "Coming soon" for now
- "Generate" button (disabled until prompt entered + type selected)
- Result preview area (shows generated image/audio player inline)

**Queue tab content:**
- Table/list of recent queue items with: type icon, prompt preview (50 chars), status badge (pending=yellow, generating=blue pulse, awaiting_approval=orange, completed=green, failed=red), provider, timestamp
- Cancel button for pending/awaiting_approval items
- Auto-polls every 3 seconds when any items are generating/awaiting_approval

**Gallery tab content:**
- Thumbnail grid (3 columns desktop, 2 tablet, 1 mobile)
- Each card: thumbnail, type badge, prompt preview, provider, cost, date
- Click to expand: full-size view, all metadata, "Set as Profile" button (opens agent selector dropdown), "Delete" button
- Filter bar: type dropdown (All, Image, Video, Audio)

**JavaScript:**
- `loadCapabilities()` — fetches `/api/capabilities`, updates type selector availability
- `submitGeneration()` — POSTs to `/api/generate`, shows result or starts polling
- `loadQueue()` — fetches `/api/queue`, renders list, starts poll interval if needed
- `loadGallery(type, offset)` — fetches `/api/gallery`, renders grid
- `cancelJob(id)` — DELETEs `/api/queue/<id>`
- `deleteAsset(id)` — DELETEs `/api/gallery/<id>`
- `setAsProfile(assetId, agentId)` — POSTs to `/api/gallery/<id>/set-profile`
- `pollQueue()` — 3s interval when active jobs exist, calls `loadQueue()`

**CSS:**
- Follow LCARS design tokens (use existing CSS variables from base layout)
- Image thumbnails: 200px grid cells, `object-fit: cover`, rounded corners
- Audio: native `<audio>` element with controls
- Status badges: match bridge.html dispatch status badge pattern

**Step 2: Verify template renders**

Navigate to `http://192.168.1.200:3000/tools/media-studio` — should see the LCARS header and 3 tabs with the Create tab active.

**Step 3: Test image generation end-to-end**

1. Select "Image" type
2. Enter prompt: "A futuristic starship bridge"
3. Click "Generate"
4. Should see result image inline (if Gemini API key is configured)

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/media_studio.html
git commit -m "feat(media): LCARS Media Studio template with Create, Queue, and Gallery tabs"
```

---

## Task 9: Telegram Approval for Paid Media Generation

**Files:**
- Modify: `ai_bridge/agent_loop.py` (add media approval handler in `_process_approval_queue()`)

**Step 1: Add media generation approval processing**

Find the `_process_approval_queue()` method in `agent_loop.py` (line ~181). After the existing approval types are processed, add handling for `action_type = 'media_generation'`:

When a media_generation approval is approved:
1. Read `action_data.queue_id`
2. Update `media_generation_queue` status from `awaiting_approval` to `generating`
3. Call `generate_media()` with the saved provider and request
4. Update queue with result (completed/failed)

When rejected:
1. Update `media_generation_queue` status to `rejected`

**Step 2: Add Telegram message formatting for media requests**

In the Telegram notification function (wherever escalation messages are formatted), add a media-specific format:

```
🎨 Media Generation Request
Type: {type} ({params})
Provider: {provider_key}
Est. Cost: ${cost:.4f}
Prompt: {prompt[:200]}
Requested by: user #{user_id}
```

**Step 3: Verify by checking approval queue**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT * FROM autonomy_approval_queue WHERE action_type = 'media_generation' LIMIT 5;"
```

Expected: No rows yet (this confirms the table/column accepts the new action_type).

**Step 4: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(media): Telegram approval flow for paid media generation requests"
```

---

## Task 10: Integration Testing and Final Verification

**Files:**
- No new files — testing existing work

**Step 1: Restart platform and verify all modules load**

```bash
docker compose restart archie_platform
sleep 5
docker logs archie_platform 2>&1 | tail -20
```

Expected: No errors related to media_studio or external_providers.

**Step 2: Test capabilities endpoint**

```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/media-studio/api/capabilities
```

Expected: JSON listing `image_gen` with Gemini provider.

**Step 3: Test image generation (if Gemini API key configured)**

```bash
curl -s -b cookies.txt -X POST http://192.168.1.200:3000/tools/media-studio/api/generate \
  -H "Content-Type: application/json" \
  -d '{"type": "image", "prompt": "A golden starship bridge with holographic displays", "params": {"aspect_ratio": "1:1"}}' | python3 -m json.tool
```

Expected: JSON with `status: "completed"`, `file_path` pointing to a PNG, `asset_id`.

**Step 4: Test gallery**

```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/media-studio/api/gallery | python3 -m json.tool
```

Expected: JSON with `assets` array containing the generated image.

**Step 5: Test queue**

```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/media-studio/api/queue | python3 -m json.tool
```

Expected: JSON with `queue` array showing the completed job.

**Step 6: Visual check**

Navigate to `http://192.168.1.200:3000/tools/media-studio` in browser. Verify:
- Create tab: type buttons reflect available capabilities
- Queue tab: shows recent job
- Gallery tab: shows generated image thumbnail

**Step 7: Run visual baseline**

```bash
node platform_v2/tests/visual_baseline.mjs --username admin --password 'Kyt$13ran2025'
```

**Step 8: Final commit**

```bash
git add -A
git commit -m "feat(media): Media Studio module — complete implementation with bridge routing"
```

---

## Summary

| Task | Description | Files Modified |
|------|-------------|----------------|
| 1 | Database migration | `database/migrations/120_media_studio.sql` |
| 2 | Provider capability discovery | `ai_bridge/external_providers.py` |
| 3 | Bridge routing (station map + capability) | `bridge_dispatcher.py`, `smart_router.py` |
| 4 | Media generation adapters (Gemini, OpenAI, TTS) | `ai_bridge/external_providers.py` |
| 5 | File storage directory structure | `platform_v2/static/media/` |
| 6 | Media Studio routes rewrite | `tools/media_studio/routes.py` |
| 7 | Module registry activation | `module_registry.py` |
| 8 | LCARS template with 3 tabs | `templates/tools/media_studio.html` |
| 9 | Telegram approval for paid generation | `ai_bridge/agent_loop.py` |
| 10 | Integration testing | (no new files) |
