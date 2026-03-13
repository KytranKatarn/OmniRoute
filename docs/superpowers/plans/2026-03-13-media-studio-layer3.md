# Media Studio Layer 3 — Video Generation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add video generation to Media Studio via AnimateDiff (local ComfyUI) and external providers (Runway/Kling/Pika), with GPU-tiered fleet routing and LCARS UI controls.

**Architecture:** Extend generation_service with video-specific params and AnimateDiff workflow builder in comfyui_manager. External video providers get submit/poll adapters in generation_service. The Generate tab gains a video mode with duration/FPS/motion controls and reference image upload. All video requests route through Bridge dispatcher with VRAM-gated tier checks.

**Tech Stack:** Flask, ComfyUI AnimateDiff Evolved, ComfyUI VideoHelperSuite, psycopg2, requests (external APIs), JavaScript DOM API

**Existing element IDs** (all use `ms` prefix): `msPrompt`, `msNegPrompt`, `msGenerateBtn`, `msModel`, `msSeed`, `msSteps`, `msCfg`, `msSampler`, `msSizePresets`. JS functions use `window.funcName = function() {}` pattern. Existing media type buttons use class `.ms-type-btn`. Existing `api()` helper wraps fetch calls.

---

## Chunk 1: Backend — AnimateDiff Workflow + Video Generation Flow

### Task 1: AnimateDiff Workflow Builder

**Files:**
- Modify: `platform_v2/tools/media_studio/services/comfyui_manager.py`

Adds `build_animatediff_workflow()` following the same pattern as `build_txt2img_workflow()` and `build_ipadapter_workflow()`. The workflow includes AnimateDiff motion model loading and video combine nodes.

- [ ] **Step 1: Read comfyui_manager.py to confirm current state**

Read `platform_v2/tools/media_studio/services/comfyui_manager.py` — confirm `build_ipadapter_workflow()` ends around line 354 and that `OPERATION_REQUIREMENTS` already has `animatediff_sd15` and `animatediff_sdxl` entries.

- [ ] **Step 2: Add build_animatediff_workflow()**

After `build_ipadapter_workflow()` (end of file), add:

```python
def build_animatediff_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    motion_model: str = "mm_sd_v15_v2.safetensors",
    width: int = 512,
    height: int = 512,
    frames: int = 16,
    fps: int = 8,
    seed: int = -1,
    steps: int = 20,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    motion_strength: float = 1.0,
    ref_image: Optional[str] = None,
) -> Dict:
    """Build ComfyUI AnimateDiff workflow for video generation.

    Requires ComfyUI-AnimateDiff-Evolved and ComfyUI-VideoHelperSuite.
    ref_image: optional basename for image-to-video mode (must be in ComfyUI input dir).
    Returns workflow dict for /prompt API.
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**63)

    # Sanitize ref_image to prevent path traversal
    if ref_image:
        ref_image = os.path.basename(ref_image)

    workflow = {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": frames,
                },
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt
                    or "blurry, low quality, distorted, deformed, static",
                    "clip": ["1", 1],
                },
            },
            "10": {
                "class_type": "ADE_AnimateDiffLoaderWithContext",
                "inputs": {
                    "model_name": motion_model,
                    "beta_schedule": "sqrt_linear (AnimateDiff)",
                    "motion_scale": motion_strength,
                    "model": ["1", 0],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["10", 0],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["2", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["6", 0],
                    "frame_rate": fps,
                    "loop_count": 0,
                    "filename_prefix": "animatediff",
                    "format": "video/h264-mp4",
                    "save_output": True,
                },
            },
        }
    }

    # Image-to-video: load reference image and use as init latent
    if ref_image:
        workflow["prompt"]["20"] = {
            "class_type": "LoadImage",
            "inputs": {"image": ref_image},
        }
        workflow["prompt"]["21"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["20", 0], "vae": ["1", 2]},
        }
        # Replace empty latent with encoded reference repeated across frames
        workflow["prompt"]["22"] = {
            "class_type": "RepeatLatentBatch",
            "inputs": {"samples": ["21", 0], "amount": frames},
        }
        # Point KSampler to repeated latent instead of empty
        workflow["prompt"]["5"]["inputs"]["latent_image"] = ["22", 0]
        workflow["prompt"]["5"]["inputs"]["denoise"] = 0.7

    return workflow
```

- [ ] **Step 3: Verify file parses**

Run: `docker exec archie_platform python3 -c "from tools.media_studio.services.comfyui_manager import build_animatediff_workflow; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/services/comfyui_manager.py
git commit -m "feat(media-studio): add AnimateDiff workflow builder for video generation"
```

---

### Task 2: Video Generation Flow in generation_service

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

Adds `DEFAULT_VIDEO_PARAMS` (single source of truth for video defaults), extends `submit_generation` to handle video-specific params (duration→frames conversion), and adds `generate_video_via_comfyui()` for direct local generation.

- [ ] **Step 1: Read generation_service.py to confirm current state**

Read `platform_v2/tools/media_studio/services/generation_service.py` — confirm `MEDIA_TYPE_CAPABILITIES` has `"video": "video_generation"` and `generate_via_comfyui()` is the last function.

- [ ] **Step 2: Add DEFAULT_VIDEO_PARAMS after DEFAULT_IMAGE_PARAMS**

After line ~41 (after `DEFAULT_IMAGE_PARAMS`), add:

```python
DEFAULT_VIDEO_PARAMS = {
    "model": "sd_xl_base_1.0.safetensors",
    "motion_model": "mm_sd_v15_v2.safetensors",
    "width": 512,
    "height": 512,
    "duration": 2,
    "fps": 8,
    "steps": 20,
    "cfg": 7.0,
    "sampler": "euler_ancestral",
    "seed": -1,
    "motion_strength": 1.0,
}

# Duration to frame count mapping
DURATION_FRAMES = {2: 16, 4: 32, 6: 48}
```

- [ ] **Step 3: Update submit_generation to merge video defaults**

In `submit_generation()`, change the param merge logic (around line 60) from:

```python
merged_params = {**DEFAULT_IMAGE_PARAMS, **(params or {})}
```

To:

```python
if media_type == "video":
    defaults = DEFAULT_VIDEO_PARAMS
else:
    defaults = DEFAULT_IMAGE_PARAMS
merged_params = {**defaults, **(params or {})}

# Convert duration to frames for video
if media_type == "video" and "duration" in merged_params:
    merged_params["frames"] = DURATION_FRAMES.get(
        merged_params["duration"], merged_params["duration"] * 8
    )
```

- [ ] **Step 4: Add generate_video_via_comfyui() after generate_via_comfyui()**

After `generate_via_comfyui()` (end of file), add:

```python
def generate_video_via_comfyui(queue_id: int) -> Optional[int]:
    """Direct ComfyUI AnimateDiff generation — called when Bridge assigns video to local Pixel.

    Builds AnimateDiff workflow, submits to ComfyUI API, polls for completion,
    retrieves output file, calls on_generation_complete.
    """
    from ai_bridge.comfyui_service import get_comfyui_service

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'generating', started_at = NOW() WHERE id = %s",
            (queue_id,),
        )

    try:
        from .comfyui_manager import build_animatediff_workflow

        start = time.time()
        svc = get_comfyui_service()

        workflow = build_animatediff_workflow(
            prompt=params.get("prompt", ""),
            negative_prompt=params.get("negative_prompt", ""),
            model=params.get("model", "sd_xl_base_1.0.safetensors"),
            motion_model=params.get("motion_model", "mm_sd_v15_v2.safetensors"),
            width=params.get("width", 512),
            height=params.get("height", 512),
            frames=params.get("frames", 16),
            fps=params.get("fps", 8),
            seed=params.get("seed", -1),
            steps=params.get("steps", 20),
            cfg=params.get("cfg", 7.0),
            sampler=params.get("sampler", "euler_ancestral"),
            motion_strength=params.get("motion_strength", 1.0),
            ref_image=params.get("ref_image"),
        )

        # Submit workflow directly to ComfyUI /prompt API
        import requests as http_requests

        comfyui_url = svc.base_url
        resp = http_requests.post(
            f"{comfyui_url}/prompt",
            json=workflow,
            timeout=10,
        )
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        # Poll for completion (video takes longer — up to 5 min)
        import time as time_mod

        max_wait = 300
        poll_interval = 3
        elapsed = 0
        output_file = None

        while elapsed < max_wait:
            time_mod.sleep(poll_interval)
            elapsed += poll_interval
            hist_resp = http_requests.get(
                f"{comfyui_url}/history/{prompt_id}", timeout=10
            )
            if hist_resp.status_code != 200:
                continue
            hist = hist_resp.json()
            if prompt_id not in hist:
                continue
            outputs = hist[prompt_id].get("outputs", {})
            # VHS_VideoCombine outputs gifs/videos in node "7"
            node_out = outputs.get("7", {})
            gifs = node_out.get("gifs", [])
            if gifs:
                output_file = gifs[0].get("filename")
                break

        duration_ms = int((time.time() - start) * 1000)

        if output_file:
            # Download from ComfyUI
            dl_resp = http_requests.get(
                f"{comfyui_url}/view",
                params={"filename": output_file, "type": "output"},
                timeout=30,
            )
            tmp_path = os.path.join(MEDIA_ROOT, f"tmp_video_{queue_id}.mp4")
            with open(tmp_path, "wb") as f:
                f.write(dl_resp.content)

            return on_generation_complete(
                queue_id=queue_id,
                file_path=tmp_path,
                seed=params.get("seed"),
                duration_ms=duration_ms,
                provider="comfyui",
            )
        else:
            on_generation_failed(queue_id, "AnimateDiff generation timed out or produced no output")
            return None

    except Exception as e:
        logger.error(f"AnimateDiff generation failed for queue {queue_id}: {e}")
        on_generation_failed(queue_id, str(e))
        return None
```

- [ ] **Step 5: Verify file parses**

Run: `docker exec archie_platform python3 -c "from tools.media_studio.services.generation_service import generate_video_via_comfyui; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): add video generation flow with AnimateDiff support"
```

---

### Task 3: External Video Provider Stubs + Polling

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

Adds `submit_external_video()`, `poll_external_video()`, `download_external_result()`, and `get_video_providers()`. These are called when Bridge escalates beyond local ComfyUI. The actual provider adapters live in `ai_bridge/external_providers.py` and will be extended when providers are configured.

- [ ] **Step 1: Add external video helpers after generate_video_via_comfyui()**

```python
def submit_external_video(queue_id: int, provider: str) -> Optional[str]:
    """Submit video generation to an external provider (Runway, Kling, Pika).

    Returns external job_id for polling, or None on failure.
    Called by Bridge dispatcher when no local ComfyUI node can handle the request.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_generation_queue
               SET status = 'dispatched', started_at = NOW(),
                   params = params || %s
               WHERE id = %s""",
            (psycopg2.extras.Json({"external_provider": provider}), queue_id),
        )

    try:
        from ai_bridge.external_providers import call_external

        result = call_external(
            provider_key=provider,
            prompt=params.get("prompt", ""),
            model=params.get("external_model"),
        )
        # Store external job reference for polling
        if result and not result.startswith("Error"):
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE media_generation_queue
                       SET params = params || %s
                       WHERE id = %s""",
                    (psycopg2.extras.Json({"external_job_id": result}), queue_id),
                )
            return result
        else:
            on_generation_failed(queue_id, f"External provider {provider} failed: {result}")
            return None
    except Exception as e:
        logger.error(f"External video submission failed: {e}")
        on_generation_failed(queue_id, str(e))
        return None


def poll_external_video(queue_id: int) -> Optional[int]:
    """Poll an external video provider for job completion.

    Checks the external_job_id stored in queue params, queries the provider,
    and if complete, downloads the result and calls on_generation_complete.
    Returns media_library ID on success, None if still pending or failed.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}
    provider = params.get("external_provider")
    job_id = params.get("external_job_id")

    if not provider or not job_id:
        logger.warning(f"Queue {queue_id} missing external provider/job_id for polling")
        return None

    try:
        from ai_bridge.external_providers import call_external

        # Poll provider — result is either a URL (complete), "pending", or error
        result = call_external(
            provider_key=provider,
            prompt=f"poll:{job_id}",
            model=None,
        )

        if result and result.startswith("http"):
            # Job complete — download result
            file_path = download_external_result(provider, result, queue_id)
            if file_path:
                return on_generation_complete(
                    queue_id=queue_id,
                    file_path=file_path,
                    provider=provider,
                )
            else:
                on_generation_failed(queue_id, f"Failed to download from {provider}")
                return None
        elif result == "pending":
            return None  # Still processing
        else:
            on_generation_failed(queue_id, f"External poll failed: {result}")
            return None
    except Exception as e:
        logger.error(f"External video poll failed for queue {queue_id}: {e}")
        return None


def download_external_result(provider: str, url: str, queue_id: int) -> Optional[str]:
    """Fetch completed video from external API, save locally.

    Downloads the file from the provider URL and saves to MEDIA_ROOT.
    Returns local file path on success, None on failure.
    """
    import requests as http_requests

    try:
        resp = http_requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        # Determine extension from content-type
        ct = resp.headers.get("content-type", "")
        ext = ".mp4"
        if "gif" in ct:
            ext = ".gif"
        elif "webm" in ct:
            ext = ".webm"

        filename = f"external_{provider}_{queue_id}_{int(time.time())}{ext}"
        dest_path = os.path.join(MEDIA_ROOT, "tmp", filename)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return dest_path
    except Exception as e:
        logger.error(f"Failed to download external result from {provider}: {e}")
        return None


def get_video_providers() -> list:
    """Return available external video providers with capabilities.

    Reads from contractor_providers table where provider supports video.
    """
    providers = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT provider_key, display_name, capabilities, cost_per_unit
                   FROM contractor_providers
                   WHERE is_active = true
                     AND capabilities ? 'video_generation'
                   ORDER BY cost_per_unit ASC NULLS LAST"""
            )
            for row in cur.fetchall():
                providers.append(dict(row))
    except Exception as e:
        logger.warning(f"Failed to query video providers: {e}")
    return providers
```

- [ ] **Step 2: Verify file parses**

Run: `docker exec archie_platform python3 -c "from tools.media_studio.services.generation_service import poll_external_video, download_external_result, get_video_providers; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): add external video provider stubs with poll + download"
```

---

## Chunk 2: API Routes + Frontend

### Task 4: Video API Routes

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

Adds video-specific endpoints alongside existing generation routes.

- [ ] **Step 1: Read routes.py to confirm current state**

Read `platform_v2/tools/media_studio/routes.py` — confirm the Environments section ends around line 335.

- [ ] **Step 2: Add video routes before the Environments section**

Before the `# ─── Environments` comment block, add:

```python
# ─── Video ───────────────────────────────────────────────────────────


@media_studio_bp.route("/api/video/generate", methods=["POST"])
@login_required
def api_generate_video():
    """Submit a video generation request (AnimateDiff or external)."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    params = {}
    for k in ("model", "motion_model", "width", "height", "duration", "fps",
              "steps", "cfg", "sampler", "seed", "motion_strength", "ref_image",
              "provider"):
        if k in data:
            params[k] = data[k]

    result = submit_generation(
        user_id=current_user.id,
        media_type="video",
        prompt=prompt,
        negative_prompt=data.get("negative_prompt", ""),
        params=params,
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500
    return jsonify(result), 201


@media_studio_bp.route("/api/video/providers")
@login_required
def api_video_providers():
    """Get available external video providers."""
    from .services.generation_service import get_video_providers

    return jsonify({"providers": get_video_providers()})
```

- [ ] **Step 3: Verify routes load**

Run: `docker exec archie_platform python3 -c "from tools.media_studio.routes import media_studio_bp; print(f'Rules: {len(media_studio_bp.deferred_functions)}')"`
Expected: prints a number (no import errors)

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add video generation and providers API routes"
```

---

### Task 5: Generate Tab — Video Mode UI

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

Enables the Video button in the existing `.ms-type-btn` selector and adds video-specific controls below the generate form. Uses the existing `window.funcName = function(){}` pattern and `ms` element ID prefix. No innerHTML — DOM API only.

- [ ] **Step 1: Read current Generate tab HTML section**

Read `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` lines 120-240 — find the media type selector and generate form.

- [ ] **Step 2: Enable the Video button**

Change the video button from disabled to clickable. Find:
```html
<button class="ms-type-btn disabled" data-type="video">
    <i data-lucide="film" style="width:16px;height:16px;"></i>
    <span data-i18n="media_studio.video">Video</span>
    <span class="ms-coming-soon" data-i18n="media_studio.coming_soon">Coming Soon</span>
</button>
```

Replace with:
```html
<button class="ms-type-btn" data-type="video" onclick="selectMediaType('video')">
    <i data-lucide="film" style="width:16px;height:16px;"></i>
    <span data-i18n="media_studio.video">Video</span>
</button>
```

- [ ] **Step 3: Add video controls section**

After the generate button (`id="msGenerateBtn"`) and its parent container, but still within the generate tab pane, add:

```html
<!-- Video Controls (hidden when media_type != video) -->
<div id="msVideoControls" class="ms-video-controls" style="display:none;">
    <div class="ms-section-header">Video Settings</div>
    <div class="ms-form-group">
        <label class="ms-form-label">Duration</label>
        <div class="ms-duration-btns">
            <button class="ms-duration-btn active" data-dur="2" onclick="setVideoDuration(2)">2s</button>
            <button class="ms-duration-btn" data-dur="4" onclick="setVideoDuration(4)">4s</button>
            <button class="ms-duration-btn" data-dur="6" onclick="setVideoDuration(6)">6s</button>
        </div>
    </div>
    <div class="ms-form-group">
        <label class="ms-form-label">FPS</label>
        <div class="ms-fps-btns">
            <button class="ms-fps-btn active" data-fps="8" onclick="setVideoFPS(8)">8</button>
            <button class="ms-fps-btn" data-fps="12" onclick="setVideoFPS(12)">12</button>
            <button class="ms-fps-btn" data-fps="24" onclick="setVideoFPS(24)">24</button>
        </div>
    </div>
    <div class="ms-form-group">
        <label class="ms-form-label">Motion Strength</label>
        <input type="range" id="msMotionStrength" class="ms-slider" min="0" max="2" step="0.1" value="1.0">
        <span id="msMotionStrengthVal" class="ms-slider-val">1.0</span>
    </div>
    <div class="ms-form-group">
        <label class="ms-form-label">Reference Image (optional — for image-to-video)</label>
        <div class="ms-ref-upload">
            <input type="file" id="msRefImageFile" accept="image/*" style="display:none;">
            <button class="ms-btn ms-btn-secondary" onclick="document.getElementById('msRefImageFile').click()">Choose Image</button>
            <span id="msRefImageName" class="ms-ref-name">No file selected</span>
        </div>
    </div>
    <div class="ms-form-group">
        <label class="ms-form-label">Provider</label>
        <select id="msVideoProvider" class="ms-select">
            <option value="auto">Auto (Local First)</option>
            <option value="local">Local ComfyUI Only</option>
        </select>
    </div>
</div>
```

- [ ] **Step 4: Add video JS functions in the script section**

In the `<script>` block, after the existing `window.selectMediaType` function, add:

```javascript
    /* ── Video Controls ──────────────────────────── */

    var _currentMediaType = "image";
    var _videoDuration = 2;
    var _videoFPS = 8;

    // Override selectMediaType to also toggle video controls
    window.selectMediaType = function(type) {
        if (type === "audio") return; // Layer 4
        _currentMediaType = type;
        var btns = document.querySelectorAll(".ms-type-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", btns[i].dataset.type === type);
        }
        var vc = document.getElementById("msVideoControls");
        if (vc) vc.style.display = type === "video" ? "" : "none";
        // Update generate button text
        var genBtn = document.getElementById("msGenerateBtn");
        if (genBtn) {
            _clearChildren(genBtn);
            var icon = document.createElement("i");
            icon.setAttribute("data-lucide", type === "video" ? "film" : "sparkles");
            icon.style.cssText = "width:18px;height:18px;";
            genBtn.appendChild(icon);
            genBtn.appendChild(document.createTextNode(type === "video" ? " Generate Video" : " Generate Image"));
            if (window.lucide) lucide.createIcons();
        }
    };

    window.setVideoDuration = function(dur) {
        _videoDuration = dur;
        var btns = document.querySelectorAll(".ms-duration-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", parseInt(btns[i].dataset.dur) === dur);
        }
    };

    window.setVideoFPS = function(fps) {
        _videoFPS = fps;
        var btns = document.querySelectorAll(".ms-fps-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", parseInt(btns[i].dataset.fps) === fps);
        }
    };

    // Motion strength slider live update
    (function() {
        var slider = document.getElementById("msMotionStrength");
        var valSpan = document.getElementById("msMotionStrengthVal");
        if (slider && valSpan) {
            slider.addEventListener("input", function() {
                valSpan.textContent = this.value;
            });
        }
    })();

    // Reference image file name display
    (function() {
        var fileInput = document.getElementById("msRefImageFile");
        var nameSpan = document.getElementById("msRefImageName");
        if (fileInput && nameSpan) {
            fileInput.addEventListener("change", function() {
                nameSpan.textContent = this.files.length ? this.files[0].name : "No file selected";
            });
        }
    })();

    // Load external video providers into dropdown
    window.loadVideoProviders = function() {
        api("GET", "/api/video/providers").then(function(data) {
            var sel = document.getElementById("msVideoProvider");
            if (!sel) return;
            (data.providers || []).forEach(function(p) {
                var opt = document.createElement("option");
                opt.value = p.provider_key;
                opt.textContent = p.display_name || p.provider_key;
                if (p.cost_per_unit) {
                    opt.textContent += " ($" + p.cost_per_unit + "/gen)";
                }
                sel.appendChild(opt);
            });
        }).catch(function(e) {
            console.warn("Failed to load video providers:", e);
        });
    };
```

- [ ] **Step 5: Update submitGeneration() to handle video mode**

Replace the existing `window.submitGeneration` function (lines ~691-729) with:

```javascript
    window.submitGeneration = function() {
        var prompt = document.getElementById("msPrompt").value.trim();
        if (!prompt) {
            alert("Please enter a prompt.");
            return;
        }

        var btn = document.getElementById("msGenerateBtn");
        btn.disabled = true;
        btn.classList.add("loading");

        var url, payload;

        if (_currentMediaType === "video") {
            url = "/api/video/generate";
            payload = {
                prompt: prompt,
                negative_prompt: document.getElementById("msNegPrompt").value.trim() || "",
                model: document.getElementById("msModel").value,
                duration: _videoDuration,
                fps: _videoFPS,
                motion_strength: parseFloat(document.getElementById("msMotionStrength").value || "1.0"),
                provider: document.getElementById("msVideoProvider").value || "auto",
                seed: parseInt(document.getElementById("msSeed").value, 10),
            };
        } else {
            url = "/api/generate";
            var sizeBtn = document.querySelector(".ms-size-btn.active");
            var sizeParts = (sizeBtn ? sizeBtn.dataset.size : "1024x1024").split("x");
            payload = {
                prompt: prompt,
                negative_prompt: document.getElementById("msNegPrompt").value.trim() || "",
                model: document.getElementById("msModel").value,
                width: parseInt(sizeParts[0], 10),
                height: parseInt(sizeParts[1], 10),
                steps: parseInt(document.getElementById("msSteps").value, 10),
                cfg_scale: parseFloat(document.getElementById("msCfg").value),
                sampler: document.getElementById("msSampler").value,
                seed: parseInt(document.getElementById("msSeed").value, 10),
                media_type: "image",
            };
        }

        api("POST", url, payload).then(function(data) {
            btn.disabled = false;
            btn.classList.remove("loading");
            if (window._msGlassNav) window._msGlassNav.setActive("queue");
            switchMsTab("queue");
        }).catch(function(err) {
            btn.disabled = false;
            btn.classList.remove("loading");
            console.error("Generation failed:", err);
            alert("Generation request failed. Check console for details.");
        });
    };
```

- [ ] **Step 6: Load providers when Generate tab opens**

In the `switchMsTab` function, add a case for loading video providers. Find the existing tab switch handler and add after any existing tab-specific loads:

```javascript
if (tabId === "generate") loadVideoProviders();
```

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): enable video mode UI with duration/FPS/motion controls"
```

---

### Task 6: Video CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css`

Adds S17 (Video Controls) section for video parameter buttons, motion slider, and ref upload. Reuses existing `.ms-type-btn` styles (already defined) — no new media type switcher CSS needed.

- [ ] **Step 1: Read end of CSS file to find insertion point**

Read the last ~30 lines of `platform_v2/tools/media_studio/static/css/media-studio.css` to find the last section number.

- [ ] **Step 2: Append S17 Video Controls**

Add at end of file:

```css
/* ═══════════════════════════════════════════════════════════════
   S17 · VIDEO CONTROLS
   ═══════════════════════════════════════════════════════════════ */

.ms-video-controls {
    margin-top: 1rem;
    padding: 1rem;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid rgba(138, 92, 246, 0.15);
    border-radius: 8px;
}

.ms-duration-btns,
.ms-fps-btns {
    display: flex;
    gap: 0.5rem;
}

.ms-duration-btn,
.ms-fps-btn {
    padding: 0.4rem 1rem;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(138, 92, 246, 0.3);
    color: rgba(255, 255, 255, 0.6);
    border-radius: 4px;
    cursor: pointer;
    font-family: var(--ms-font-mono);
    font-size: 0.85rem;
    transition: all 0.2s ease;
}

.ms-duration-btn:hover,
.ms-fps-btn:hover {
    border-color: rgba(138, 92, 246, 0.6);
    color: white;
}

.ms-duration-btn.active,
.ms-fps-btn.active {
    background: rgba(138, 92, 246, 0.3);
    border-color: #8b5cf6;
    color: #c4b5fd;
}

.ms-slider-val {
    color: #c4b5fd;
    font-family: var(--ms-font-mono);
    font-size: 0.85rem;
    margin-left: 0.5rem;
}

.ms-ref-upload {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.ms-ref-name {
    color: rgba(255, 255, 255, 0.4);
    font-size: 0.8rem;
    font-style: italic;
}
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add video controls CSS (S17)"
```

---

### Task 7: Integration Test + Deploy

**Files:**
- No new files — testing existing endpoints

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

Wait 3 seconds for startup.

- [ ] **Step 2: Test video generation endpoint**

Login and test:

```python
import requests
s = requests.Session()
s.post("http://192.168.1.200:3000/login",
       data={"username": "admin", "password": "Kyt$13ran2025"},
       allow_redirects=False)

# Test video generate endpoint (will fail at Bridge dispatch, but route should return 201 or 500)
r = s.post("http://192.168.1.200:3000/tools/media-studio/api/video/generate",
           json={"prompt": "test video", "duration": 2, "fps": 8},
           allow_redirects=False)
print(f"Video generate: {r.status_code}")

# Test video providers endpoint
r2 = s.get("http://192.168.1.200:3000/tools/media-studio/api/video/providers",
           allow_redirects=False)
print(f"Video providers: {r2.status_code}, {r2.json()}")

# Verify existing endpoints still work
r3 = s.get("http://192.168.1.200:3000/tools/media-studio/api/dashboard",
           allow_redirects=False)
print(f"Dashboard: {r3.status_code}")

r4 = s.get("http://192.168.1.200:3000/tools/media-studio/api/portraits",
           allow_redirects=False)
print(f"Portraits: {r4.status_code}")
```

Expected: Video generate returns 201 or 500 (Bridge dispatch may fail, that's OK — the route works). Video providers returns 200 with `{"providers": []}`. Dashboard and portraits still 200.

- [ ] **Step 3: Verify Media Studio page loads in browser**

Open http://192.168.1.200:3000/tools/media-studio in a browser. Check:
- Generate tab shows Image/Video/Audio type buttons
- Video button is now clickable (not greyed out)
- Clicking "Video" shows duration, FPS, motion strength, ref image, provider controls
- Audio button remains greyed out with "Coming Soon" badge
- Switching back to "Image" hides video controls
- Generate button text changes between "Generate Image" / "Generate Video"

- [ ] **Step 4: Push to remote**

```bash
git push origin main
```

- [ ] **Step 5: Update Dev HQ**

```python
mcp__archie__update_project_understanding(
    project_id=129,
    understanding_level=90,
    emotional_association="confident",
    key_insights=[
        "Layer 3 complete: AnimateDiff workflow builder, video gen flow, external provider stubs with poll+download",
        "Video controls: duration (2/4/6s), FPS (8/12/24), motion strength slider, ref image upload, provider picker",
        "AnimateDiff SD1.5 needs Base tier (6GB+), SDXL needs Mid (10GB+) — enforced by comfyui_manager",
        "External video providers read from contractor_providers table with video_generation capability",
        "ref_image sanitized with os.path.basename() to prevent path traversal",
    ],
    notes="Layers 1-3 complete. Layer 4 (audio/TTS) remaining.",
)
```

- [ ] **Step 6: Commit any test fixes**

If integration tests revealed bugs (like Layer 2's station_code/is_active issues), fix and commit them.
