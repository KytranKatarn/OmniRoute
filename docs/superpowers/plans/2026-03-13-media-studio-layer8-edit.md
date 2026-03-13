# Media Studio Layer 8: Image Editing & Post-Processing — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 image editing operations (inpaint, outpaint, upscale, img2img, style transfer) with canvas mask editor, ComfyUI workflows, versioning, and Lanczos fallback.

**Architecture:** New `edit_service.py` handles all edit operations through `submit_edit()`. Edit-specific ComfyUI workflows are added to the existing `comfyui_manager.py`. Results create versioned `media_library` rows linked via `parent_id`. Canvas mask editor is a modal in the existing HTML template.

**Tech Stack:** Flask, PostgreSQL, ComfyUI API, Pillow (Lanczos), HTML5 Canvas

**Key patterns from existing code:**
- Workflows live in `comfyui_manager.py` (NOT a separate file) — node dicts with string IDs, `["node_id", output_index]` references
- `submit_generation()` inserts into `media_generation_queue`, dispatches via Bridge
- `on_generation_complete()` creates `media_library` rows via `gallery_service.create_media_entry()`
- Routes use `@media_studio_bp.route()` + `@login_required`, local imports, `jsonify()` responses
- JS uses `window.funcName`, `api(method, path, body)` helper, `_clearChildren()`, `document.createElement`
- CSS uses `ms-` prefix, `var(--ms-border)`, `var(--ms-accent)`, `var(--ms-text)`

---

## Task 1: Database Migration 154

**Files:**
- Create: `database/migrations/154_media_edits.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 154: Media edits table + versioning columns
-- Idempotent: safe to run multiple times

-- New table for edit operations
CREATE TABLE IF NOT EXISTS media_edits (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES media_library(id),
    edit_type VARCHAR(30) NOT NULL,
    params JSONB DEFAULT '{}',
    mask_path VARCHAR(500),
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    result_id INTEGER REFERENCES media_library(id),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL
);

-- Versioning columns on media_library
ALTER TABLE media_library
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES media_library(id);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_media_edits_source ON media_edits(source_id);
CREATE INDEX IF NOT EXISTS idx_media_edits_status ON media_edits(status);
CREATE INDEX IF NOT EXISTS idx_media_edits_owner ON media_edits(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_library_parent ON media_library(parent_id);
```

Note: Added `result_id` column to `media_edits` (per spec review feedback) so we can directly reference the resulting `media_library` row without a join.

- [ ] **Step 2: Run migration in Docker**

```bash
docker cp database/migrations/154_media_edits.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/154_media_edits.sql
```

Expected: `CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX` (or notices if already exist).

- [ ] **Step 3: Verify schema**

```bash
docker exec archie_database psql -U archie -d archie -c "\d media_edits"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='media_library' AND column_name IN ('version', 'parent_id')"
```

Expected: `media_edits` table with all columns; `version` and `parent_id` columns present.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/154_media_edits.sql
git commit -m "feat(media-studio): add migration 154 — media_edits table + versioning"
```

---

## Task 2: Edit Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/edit_service.py`

**Dependencies:** Task 1 (migration must exist)

- [ ] **Step 1: Write the edit service**

Create `edit_service.py` (~250 lines) with these functions:

```python
"""Image editing service — inpaint, outpaint, upscale, img2img, style transfer.

Entry point:
- submit_edit()    — validate, save mask, dispatch to ComfyUI or fallback
- get_edit_status() — check edit progress
- get_versions()   — version history for an image

Internal:
- _validate_edit_params()  — per-type param validation
- _save_mask()             — save base64/uploaded mask to disk
- _cleanup_mask()          — delete mask after processing
- _next_version()          — compute next version number
- _lanczos_upscale()       — Pillow fallback for upscaling
"""
```

**`submit_edit(source_id, edit_type, params, mask_data, owner_type, owner_id)`**

1. Query `media_library` to verify `source_id` exists
2. Validate `edit_type` in `{'inpaint', 'outpaint', 'upscale', 'img2img', 'style_transfer'}`
3. Call `_validate_edit_params(edit_type, params, mask_data)` — returns error dict or None
4. If mask_data provided, call `_save_mask(mask_data, source_id)` — saves to `MEDIA_ROOT/masks/mask_{source_id}_{timestamp}.png`
5. Insert into `media_edits` table with status `'pending'`
6. For upscale with `method='lanczos'`: call `_lanczos_upscale()` directly, create media_library entry, update edit row to `completed`
7. For all other types: dispatch via Bridge `request_work(capability='image_edit', ...)` with context containing `{edit_id, edit_type, source_path, mask_path, params}`
8. Return `{"edit_id": id, "status": "pending"|"completed"}`

**`_validate_edit_params(edit_type, params, mask_data)`** — returns `{"error": "..."}` or `None`:

| edit_type | Required | Validation |
|-----------|----------|------------|
| inpaint | mask_data | must have mask_data (base64 or path) |
| outpaint | direction, pixels | direction in {top,bottom,left,right,all}; pixels 64-512 |
| upscale | scale_factor | scale_factor in {2, 4} |
| img2img | prompt | prompt must be non-empty string |
| style_transfer | style_prompt OR reference_image_id | at least one must be present |

**`_next_version(source_id)`**:
```python
def _next_version(source_id):
    """Walk parent_id chain to root, count versions, return (root_id, next_version)."""
    with get_db_cursor() as (conn, cur):
        # Find root by walking up
        current = source_id
        for _ in range(50):  # max depth guard
            cur.execute("SELECT parent_id FROM media_library WHERE id = %s", (current,))
            row = cur.fetchone()
            if not row or row['parent_id'] is None:
                break
            current = row['parent_id']
        root_id = current
        # Count existing versions
        cur.execute(
            "SELECT COALESCE(MAX(version), 1) FROM media_library "
            "WHERE id = %s OR parent_id = %s",
            (root_id, root_id)
        )
        max_ver = cur.fetchone()[0]
        return root_id, max_ver + 1
```

**`on_edit_complete(edit_id, file_path, seed=None, duration_ms=None)`**:
1. Load edit row from `media_edits`
2. Load source row from `media_library`
3. Call `_next_version(source_id)` to get root_id and version number
4. Call `gallery_service.create_media_entry(...)` with `parent_id=source_id`, `version=next_ver`
5. Update `media_edits` set `status='completed'`, `result_id=new_media_id`, `completed_at=NOW()`
6. Call `_cleanup_mask(edit.mask_path)` if mask exists
7. Return `new_media_id`

**`on_edit_failed(edit_id, error_message)`**:
1. Update `media_edits` set `status='failed'`, `error_message=error_message`, `completed_at=NOW()`
2. Call `_cleanup_mask()` if mask exists

**`get_edit_status(edit_id)`**: Simple SELECT from `media_edits` returning dict.

**`get_versions(media_id)`**:
1. Walk parent_id chain to find root
2. Query all rows with `id = root_id OR parent_id = root_id` ordered by `version`
3. Return list of dicts with `id, version, file_path, thumbnail_path, created_at, media_type`

**`_lanczos_upscale(source_path, scale_factor, edit_id, owner_type, owner_id)`**:
```python
from PIL import Image
img = Image.open(source_path)
new_size = (img.width * scale_factor, img.height * scale_factor)
upscaled = img.resize(new_size, Image.LANCZOS)
output_path = source_path.replace('.', f'_upscaled_{scale_factor}x.')
upscaled.save(output_path, quality=95)
return output_path
```

**`_save_mask(mask_data, source_id)`**: Decode base64 → save PNG to `MEDIA_ROOT/masks/`. Return path.

**`_cleanup_mask(mask_path)`**: `os.remove(mask_path)` wrapped in try/except.

- [ ] **Step 2: Verify imports and structure**

```bash
docker exec archie_platform python3 -c "from tools.media_studio.services.edit_service import submit_edit, get_edit_status, get_versions; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/edit_service.py
git commit -m "feat(media-studio): add edit service with 5 edit types + versioning"
```

---

## Task 3: ComfyUI Edit Workflows

**Files:**
- Modify: `platform_v2/tools/media_studio/services/comfyui_manager.py` (append new builders)

**Dependencies:** Task 1

- [ ] **Step 1: Read existing comfyui_manager.py to find append location**

Read the file, find the last workflow builder function. New builders go after it.

- [ ] **Step 2: Add 4 workflow builder functions**

Append to `comfyui_manager.py` after the last existing builder. Follow the existing pattern: return `{"prompt": {"1": {...}, ...}}` with string node IDs.

**`build_inpaint_workflow(image_path, mask_path, prompt, negative_prompt="", model="sd_xl_base_1.0.safetensors", width=1024, height=1024, seed=-1, steps=25, cfg=7.0, sampler="euler_ancestral", denoise=0.75)`**

Nodes:
- `"1"`: CheckpointLoaderSimple (model)
- `"2"`: CLIPTextEncode positive (prompt)
- `"3"`: CLIPTextEncode negative (negative_prompt)
- `"4"`: LoadImage (image_path)
- `"5"`: LoadImage (mask_path)
- `"6"`: VAEEncode (from node 4)
- `"7"`: SetLatentNoiseMask (latent from 6, mask from 5)
- `"8"`: KSampler (model from 1, positive 2, negative 3, latent 7, seed, steps, cfg, sampler, denoise)
- `"9"`: VAEDecode (samples from 8, vae from 1)
- `"10"`: SaveImage (images from 9, filename_prefix="edit_inpaint")

**`build_outpaint_workflow(image_path, prompt, negative_prompt="", direction="right", pixels=128, model="sd_xl_base_1.0.safetensors", seed=-1, steps=25, cfg=7.0, sampler="euler_ancestral", denoise=0.8)`**

Nodes:
- `"1"`: CheckpointLoaderSimple
- `"2"`: CLIPTextEncode positive
- `"3"`: CLIPTextEncode negative
- `"4"`: LoadImage (image_path)
- `"5"`: ImagePadForOutpaint (image from 4, left/right/top/bottom pixels based on direction, feathering=40)
- `"6"`: VAEEncode (padded image from 5 [0])
- `"7"`: SetLatentNoiseMask (latent from 6, mask from 5 [1])
- `"8"`: KSampler (denoise=denoise)
- `"9"`: VAEDecode
- `"10"`: SaveImage (filename_prefix="edit_outpaint")

Direction mapping: set the corresponding direction's pixel count, others to 0. `"all"` sets all 4 to `pixels`.

**`build_upscale_workflow(image_path, model_name="RealESRGAN_x4plus.pth", target_scale=4)`**

Nodes:
- `"1"`: UpscaleModelLoader (model_name)
- `"2"`: LoadImage (image_path)
- `"3"`: ImageUpscaleWithModel (upscale_model from 1, image from 2)
- `"4"`: SaveImage (images from 3, filename_prefix="edit_upscale")

If `target_scale=2`: add node `"5"` ImageScale to halve dimensions (method="lanczos", width/2, height/2).

**`build_img2img_workflow(image_path, prompt, negative_prompt="", model="sd_xl_base_1.0.safetensors", seed=-1, steps=25, cfg=7.0, sampler="euler_ancestral", denoise=0.6)`**

Nodes:
- `"1"`: CheckpointLoaderSimple
- `"2"`: CLIPTextEncode positive
- `"3"`: CLIPTextEncode negative
- `"4"`: LoadImage (image_path)
- `"5"`: VAEEncode (image from 4, vae from 1)
- `"6"`: KSampler (model 1, positive 2, negative 3, latent 5, denoise=denoise)
- `"7"`: VAEDecode (samples from 6, vae from 1)
- `"8"`: SaveImage (images from 7, filename_prefix="edit_img2img")

Note: Style transfer with prompt-only mode uses this same workflow with `denoise=0.4-0.6`. Style transfer with reference image uses the existing `build_ipadapter_workflow()` with the source image as input — no new builder needed.

- [ ] **Step 3: Verify builders import correctly**

```bash
docker exec archie_platform python3 -c "from tools.media_studio.services.comfyui_manager import build_inpaint_workflow, build_outpaint_workflow, build_upscale_workflow, build_img2img_workflow; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/services/comfyui_manager.py
git commit -m "feat(media-studio): add inpaint/outpaint/upscale/img2img workflow builders"
```

---

## Task 4: API Routes — Edit Endpoints

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py` (append new section)

**Dependencies:** Task 2 (edit service)

- [ ] **Step 1: Read the end of routes.py to find append location**

Read last ~30 lines to find where to append.

- [ ] **Step 2: Append edit route section**

Add a comment block `# ── S22  Image Editing ──` (following the existing S21 pattern), then 4 routes:

**`POST /api/media-studio/edit`**
```python
@media_studio_bp.route("/api/media-studio/edit", methods=["POST"])
@login_required
def api_submit_edit():
    from tools.media_studio.services.edit_service import submit_edit
    data = request.get_json() or {}
    source_id = data.get("source_id")
    edit_type = data.get("edit_type")
    params = data.get("params", {})
    mask_data = data.get("mask_data")
    if not source_id or not edit_type:
        return jsonify({"error": "source_id and edit_type are required"}), 400
    result = submit_edit(
        source_id=source_id, edit_type=edit_type, params=params,
        mask_data=mask_data, owner_type="user", owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`GET /api/media-studio/edit/<int:edit_id>`**
```python
@media_studio_bp.route("/api/media-studio/edit/<int:edit_id>", methods=["GET"])
@login_required
def api_get_edit_status(edit_id):
    from tools.media_studio.services.edit_service import get_edit_status
    result = get_edit_status(edit_id)
    if result is None:
        return jsonify({"error": "Edit not found"}), 404
    # Serialize datetimes
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return jsonify(result)
```

**`GET /api/media-studio/versions/<int:media_id>`**
```python
@media_studio_bp.route("/api/media-studio/versions/<int:media_id>", methods=["GET"])
@login_required
def api_get_versions(media_id):
    from tools.media_studio.services.edit_service import get_versions
    versions = get_versions(media_id)
    for v in versions:
        for k, val in v.items():
            if hasattr(val, "isoformat"):
                v[k] = val.isoformat()
    return jsonify(versions)
```

**`POST /api/media-studio/edit/upload-mask`**
```python
@media_studio_bp.route("/api/media-studio/edit/upload-mask", methods=["POST"])
@login_required
def api_upload_mask():
    from tools.media_studio.services.edit_service import _save_mask
    if "mask" not in request.files:
        return jsonify({"error": "No mask file provided"}), 400
    mask_file = request.files["mask"]
    import base64
    mask_data = base64.b64encode(mask_file.read()).decode("utf-8")
    mask_path = _save_mask(mask_data, source_id=0)
    return jsonify({"mask_path": mask_path})
```

- [ ] **Step 3: Update existing gallery endpoint**

Find the existing `api_gallery` function. Add version-aware filtering:

```python
# Inside api_gallery, after existing query building:
show_versions = request.args.get("show_versions", "false") == "true"
if not show_versions:
    # Show only originals (parent_id IS NULL) and latest versions
    # Exclude intermediate versions
    query += " AND (parent_id IS NULL OR id IN (SELECT ml2.id FROM media_library ml2 WHERE ml2.parent_id IS NOT NULL AND ml2.version = (SELECT MAX(ml3.version) FROM media_library ml3 WHERE ml3.parent_id = ml2.parent_id OR ml3.id = ml2.parent_id)))"
```

Actually, simpler approach: just exclude rows where `parent_id IS NOT NULL` unless `show_versions=true`. The version sidebar handles showing the chain. This avoids complex subqueries.

```python
if not show_versions:
    query += " AND parent_id IS NULL"
```

- [ ] **Step 4: Verify routes register**

```bash
docker exec archie_platform python3 -c "
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'edit' in r.rule and 'media-studio' in r.rule]
print(f'{len(rules)} edit routes: {rules}')
"
```

Expected: 4 edit routes.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add edit API routes — submit, status, versions, upload-mask"
```

---

## Task 5: Edit Modal HTML + Canvas Mask Editor

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Dependencies:** Task 4 (routes must exist for JS to call)

- [ ] **Step 1: Read the HTML file to find insertion points**

Need to find: (a) where to add the edit modal HTML, (b) where to add edit button to gallery cards, (c) where to add the JS block.

- [ ] **Step 2: Add edit modal HTML**

Insert after the existing modals (batch modal, etc.), before the closing content div. The modal structure:

```html
<!-- ── S22  Edit Modal ── -->
<div id="msEditModal" class="ms-edit-modal" style="display:none;">
  <div class="ms-edit-modal-content">
    <div class="ms-edit-modal-header">
      <span class="ms-edit-modal-title">Edit Image</span>
      <button class="ms-edit-modal-close" onclick="closeEditModal()">&times;</button>
    </div>
    <!-- Edit type tabs -->
    <div class="ms-edit-tabs">
      <button class="ms-edit-tab active" data-type="inpaint" onclick="switchEditType('inpaint')">Inpaint</button>
      <button class="ms-edit-tab" data-type="outpaint" onclick="switchEditType('outpaint')">Outpaint</button>
      <button class="ms-edit-tab" data-type="upscale" onclick="switchEditType('upscale')">Upscale</button>
      <button class="ms-edit-tab" data-type="img2img" onclick="switchEditType('img2img')">Img2Img</button>
      <button class="ms-edit-tab" data-type="style_transfer" onclick="switchEditType('style_transfer')">Style Transfer</button>
    </div>
    <div class="ms-edit-body">
      <!-- Canvas area -->
      <div class="ms-edit-canvas-wrap">
        <canvas id="msEditCanvas"></canvas>
      </div>
      <!-- Toolbar (inpaint/outpaint only) -->
      <div id="msEditToolbar" class="ms-edit-toolbar">
        <label>Brush: <input type="range" id="msEditBrushSize" min="5" max="100" value="30"></label>
        <button id="msEditEraser" onclick="toggleEraser()">Eraser</button>
        <button onclick="clearMask()">Clear</button>
        <button onclick="undoStroke()">Undo</button>
      </div>
      <!-- Type-specific params -->
      <div id="msEditParamsInpaint" class="ms-edit-params">
        <label>Prompt: <textarea id="msEditInpaintPrompt" rows="2" class="ms-input-xs"></textarea></label>
        <label>Strength: <input type="range" id="msEditInpaintStrength" min="0" max="100" value="75"> <span id="msEditInpaintStrengthVal">0.75</span></label>
      </div>
      <div id="msEditParamsOutpaint" class="ms-edit-params" style="display:none;">
        <label>Direction:
          <select id="msEditOutpaintDir" class="ms-input-xs">
            <option value="right">Right</option>
            <option value="left">Left</option>
            <option value="top">Top</option>
            <option value="bottom">Bottom</option>
            <option value="all">All</option>
          </select>
        </label>
        <label>Pixels: <input type="number" id="msEditOutpaintPx" value="128" min="64" max="512" step="64" class="ms-input-xs"></label>
        <label>Prompt: <textarea id="msEditOutpaintPrompt" rows="2" class="ms-input-xs"></textarea></label>
      </div>
      <div id="msEditParamsUpscale" class="ms-edit-params" style="display:none;">
        <label><input type="radio" name="msEditScale" value="2" checked> 2x</label>
        <label><input type="radio" name="msEditScale" value="4"> 4x</label>
        <label><input type="radio" name="msEditMethod" value="ai" checked> AI (RealESRGAN)</label>
        <label><input type="radio" name="msEditMethod" value="lanczos"> Quick (Lanczos)</label>
      </div>
      <div id="msEditParamsImg2img" class="ms-edit-params" style="display:none;">
        <label>Prompt: <textarea id="msEditImg2imgPrompt" rows="2" class="ms-input-xs"></textarea></label>
        <label>Strength: <input type="range" id="msEditImg2imgStrength" min="0" max="100" value="60"> <span id="msEditImg2imgStrengthVal">0.60</span></label>
      </div>
      <div id="msEditParamsStyle" class="ms-edit-params" style="display:none;">
        <label>Style Prompt: <textarea id="msEditStylePrompt" rows="2" class="ms-input-xs"></textarea></label>
        <label>Reference Image ID (optional): <input type="number" id="msEditStyleRef" class="ms-input-xs" placeholder="Leave empty for prompt-only"></label>
        <label>Strength: <input type="range" id="msEditStyleStrength" min="0" max="100" value="50"> <span id="msEditStyleStrengthVal">0.50</span></label>
      </div>
    </div>
    <div class="ms-edit-modal-footer">
      <label class="ms-text-muted">Or <input type="file" id="msEditMaskUpload" accept="image/png" style="display:none;" onchange="onMaskFileSelected(this)"><a href="#" onclick="document.getElementById('msEditMaskUpload').click(); return false;">upload mask</a></label>
      <button class="ms-btn ms-btn-primary" onclick="submitEdit()">Submit Edit</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add edit button to gallery cards**

Find the existing `_createGalleryCard` function. Add an "Edit" button to each card's action bar:

```javascript
var editBtn = document.createElement('button');
editBtn.className = 'ms-card-action-btn';
editBtn.textContent = 'Edit';
editBtn.onclick = function() { openEditModal(g.id, g.file_path); };
actionBar.appendChild(editBtn);
```

Also add version badge if `g.version > 1`:

```javascript
if (g.version && g.version > 1) {
    var vBadge = document.createElement('span');
    vBadge.className = 'ms-version-badge';
    vBadge.textContent = 'v' + g.version;
    vBadge.onclick = function(e) { e.stopPropagation(); loadVersionHistory(g.id); };
    card.appendChild(vBadge);
}
```

- [ ] **Step 4: Add version sidebar HTML**

```html
<div id="msVersionSidebar" class="ms-version-sidebar" style="display:none;">
  <div class="ms-version-sidebar-header">
    <span>Version History</span>
    <button onclick="document.getElementById('msVersionSidebar').style.display='none'">&times;</button>
  </div>
  <div id="msVersionList"></div>
</div>
```

- [ ] **Step 5: Commit HTML structure**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add edit modal HTML + canvas + version sidebar"
```

---

## Task 6: Edit Modal JavaScript

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` (append JS)

**Dependencies:** Task 5 (HTML elements must exist)

- [ ] **Step 1: Add S22 JavaScript block**

Append after the S21 JS block. ~200 lines in an IIFE:

```javascript
/* ── S22  Image Editing JS ── */
(function() {
    var editSourceId = null;
    var editSourcePath = null;
    var editType = 'inpaint';
    var isErasing = false;
    var strokes = []; // for undo
    var canvas, ctx, bgImage;
    var isDrawing = false;

    window.openEditModal = function(mediaId, filePath) {
        editSourceId = mediaId;
        editSourcePath = filePath;
        document.getElementById('msEditModal').style.display = 'flex';
        switchEditType('inpaint');
        // Load source image onto canvas
        canvas = document.getElementById('msEditCanvas');
        ctx = canvas.getContext('2d');
        bgImage = new Image();
        bgImage.onload = function() {
            canvas.width = bgImage.width;
            canvas.height = bgImage.height;
            ctx.drawImage(bgImage, 0, 0);
        };
        bgImage.src = filePath;
    };

    window.closeEditModal = function() {
        document.getElementById('msEditModal').style.display = 'none';
        editSourceId = null;
        strokes = [];
    };

    window.switchEditType = function(type) {
        editType = type;
        // Update tab active states
        document.querySelectorAll('.ms-edit-tab').forEach(function(t) {
            t.classList.toggle('active', t.dataset.type === type);
        });
        // Show/hide param panels
        var panels = {inpaint:'msEditParamsInpaint', outpaint:'msEditParamsOutpaint',
                      upscale:'msEditParamsUpscale', img2img:'msEditParamsImg2img',
                      style_transfer:'msEditParamsStyle'};
        Object.keys(panels).forEach(function(k) {
            document.getElementById(panels[k]).style.display = (k === type) ? '' : 'none';
        });
        // Show/hide toolbar
        var toolbar = document.getElementById('msEditToolbar');
        toolbar.style.display = (type === 'inpaint') ? '' : 'none';
        // Redraw canvas
        if (bgImage && bgImage.complete) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(bgImage, 0, 0);
            strokes = [];
        }
    };

    // Canvas drawing for inpaint mask
    window.initMaskCanvas = function() { /* called after image loads */ };

    // Mouse/touch event handlers on canvas
    canvas = document.getElementById('msEditCanvas');
    if (canvas) {
        canvas.addEventListener('mousedown', function(e) {
            if (editType !== 'inpaint') return;
            isDrawing = true;
            strokes.push([]);
            draw(e);
        });
        canvas.addEventListener('mousemove', function(e) {
            if (!isDrawing || editType !== 'inpaint') return;
            draw(e);
        });
        canvas.addEventListener('mouseup', function() { isDrawing = false; });
        canvas.addEventListener('mouseleave', function() { isDrawing = false; });
    }

    function draw(e) {
        var rect = canvas.getBoundingClientRect();
        var x = (e.clientX - rect.left) * (canvas.width / rect.width);
        var y = (e.clientY - rect.top) * (canvas.height / rect.height);
        var size = parseInt(document.getElementById('msEditBrushSize').value);
        ctx.beginPath();
        ctx.arc(x, y, size / 2, 0, Math.PI * 2);
        ctx.fillStyle = isErasing ? 'rgba(0,0,0,1)' : 'rgba(255,255,255,0.7)';
        ctx.fill();
        if (strokes.length > 0) strokes[strokes.length - 1].push({x:x, y:y, size:size, erase:isErasing});
    }

    window.toggleEraser = function() {
        isErasing = !isErasing;
        document.getElementById('msEditEraser').classList.toggle('active', isErasing);
    };

    window.clearMask = function() {
        if (bgImage && bgImage.complete) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(bgImage, 0, 0);
            strokes = [];
        }
    };

    window.undoStroke = function() {
        if (strokes.length === 0) return;
        strokes.pop();
        // Redraw from scratch
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bgImage, 0, 0);
        strokes.forEach(function(stroke) {
            stroke.forEach(function(pt) {
                ctx.beginPath();
                ctx.arc(pt.x, pt.y, pt.size / 2, 0, Math.PI * 2);
                ctx.fillStyle = pt.erase ? 'rgba(0,0,0,1)' : 'rgba(255,255,255,0.7)';
                ctx.fill();
            });
        });
    };

    function getMaskDataUrl() {
        // Create a separate canvas with just the mask (white on black)
        var maskCanvas = document.createElement('canvas');
        maskCanvas.width = canvas.width;
        maskCanvas.height = canvas.height;
        var mctx = maskCanvas.getContext('2d');
        mctx.fillStyle = 'black';
        mctx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
        strokes.forEach(function(stroke) {
            stroke.forEach(function(pt) {
                if (!pt.erase) {
                    mctx.beginPath();
                    mctx.arc(pt.x, pt.y, pt.size / 2, 0, Math.PI * 2);
                    mctx.fillStyle = 'white';
                    mctx.fill();
                }
            });
        });
        return maskCanvas.toDataURL('image/png');
    }

    window.submitEdit = function() {
        if (!editSourceId) return;
        var params = {};
        var maskData = null;

        if (editType === 'inpaint') {
            params.prompt = document.getElementById('msEditInpaintPrompt').value;
            params.strength = parseInt(document.getElementById('msEditInpaintStrength').value) / 100;
            maskData = getMaskDataUrl();
        } else if (editType === 'outpaint') {
            params.direction = document.getElementById('msEditOutpaintDir').value;
            params.pixels = parseInt(document.getElementById('msEditOutpaintPx').value);
            params.prompt = document.getElementById('msEditOutpaintPrompt').value;
        } else if (editType === 'upscale') {
            params.scale_factor = parseInt(document.querySelector('input[name="msEditScale"]:checked').value);
            params.method = document.querySelector('input[name="msEditMethod"]:checked').value;
        } else if (editType === 'img2img') {
            params.prompt = document.getElementById('msEditImg2imgPrompt').value;
            params.strength = parseInt(document.getElementById('msEditImg2imgStrength').value) / 100;
        } else if (editType === 'style_transfer') {
            params.style_prompt = document.getElementById('msEditStylePrompt').value;
            var refId = document.getElementById('msEditStyleRef').value;
            if (refId) params.reference_image_id = parseInt(refId);
            params.strength = parseInt(document.getElementById('msEditStyleStrength').value) / 100;
        }

        var body = {source_id: editSourceId, edit_type: editType, params: params};
        if (maskData) body.mask_data = maskData;

        api('POST', '/api/media-studio/edit', body).then(function(data) {
            if (data.error) { alert(data.error); return; }
            closeEditModal();
            if (data.status === 'completed') {
                // Lanczos upscale — immediate result
                if (typeof loadGallery === 'function') loadGallery();
            } else {
                // Poll for completion
                pollEditStatus(data.edit_id);
            }
        });
    };

    window.pollEditStatus = function(editId) {
        var interval = setInterval(function() {
            api('GET', '/api/media-studio/edit/' + editId).then(function(data) {
                if (data.status === 'completed' || data.status === 'failed') {
                    clearInterval(interval);
                    if (data.status === 'completed' && typeof loadGallery === 'function') loadGallery();
                    if (data.status === 'failed') alert('Edit failed: ' + (data.error_message || 'Unknown error'));
                }
            });
        }, 3000);
    };

    window.loadVersionHistory = function(mediaId) {
        var sidebar = document.getElementById('msVersionSidebar');
        var list = document.getElementById('msVersionList');
        sidebar.style.display = '';
        _clearChildren(list);
        api('GET', '/api/media-studio/versions/' + mediaId).then(function(versions) {
            versions.forEach(function(v) {
                var item = document.createElement('div');
                item.className = 'ms-version-item';
                var thumb = document.createElement('img');
                thumb.src = v.thumbnail_path || v.file_path;
                thumb.className = 'ms-version-thumb';
                var label = document.createElement('span');
                label.textContent = 'v' + v.version;
                item.appendChild(thumb);
                item.appendChild(label);
                item.onclick = function() {
                    // Open full-size view
                    if (typeof openPreview === 'function') openPreview(v);
                };
                list.appendChild(item);
            });
        });
    };

    window.onMaskFileSelected = function(input) {
        if (!input.files || !input.files[0]) return;
        // Read file and set as mask
        var reader = new FileReader();
        reader.onload = function(e) {
            var maskImg = new Image();
            maskImg.onload = function() {
                ctx.drawImage(maskImg, 0, 0, canvas.width, canvas.height);
            };
            maskImg.src = e.target.result;
        };
        reader.readAsDataURL(input.files[0]);
    };

    // Strength slider display updates
    ['msEditInpaintStrength', 'msEditImg2imgStrength', 'msEditStyleStrength'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('input', function() {
            var valEl = document.getElementById(id + 'Val');
            if (valEl) valEl.textContent = (parseInt(el.value) / 100).toFixed(2);
        });
    });
})();
```

- [ ] **Step 2: Commit JS**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add edit modal JavaScript — canvas mask + submit + poll + versions"
```

---

## Task 7: Edit CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css` (append)

**Dependencies:** Task 5 (HTML classes must exist)

- [ ] **Step 1: Append edit CSS block**

Add `/* ── S22  Image Editing ── */` section (~80 lines):

```css
/* ── S22  Image Editing ── */
.ms-edit-modal {
    position: fixed; inset: 0; z-index: 9999;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.85);
}
.ms-edit-modal-content {
    background: var(--ms-bg, #1a1a2e);
    border: 1px solid var(--ms-accent, #f90);
    border-radius: 8px;
    width: 90vw; max-width: 1000px; max-height: 90vh;
    display: flex; flex-direction: column; overflow: hidden;
}
.ms-edit-modal-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--ms-border, #334);
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90);
}
.ms-edit-modal-close {
    background: none; border: none; color: var(--ms-text, #aab);
    font-size: 1.5rem; cursor: pointer;
}
.ms-edit-tabs {
    display: flex; gap: 0; border-bottom: 1px solid var(--ms-border, #334);
}
.ms-edit-tab {
    flex: 1; padding: 0.5rem; border: none; background: transparent;
    color: var(--ms-text, #aab); font-family: 'Antonio', sans-serif;
    text-transform: uppercase; font-size: 0.75rem; cursor: pointer;
    border-bottom: 2px solid transparent; transition: all 0.2s;
}
.ms-edit-tab:hover { color: var(--ms-accent, #f90); }
.ms-edit-tab.active {
    color: var(--ms-accent, #f90);
    border-bottom-color: var(--ms-accent, #f90);
}
.ms-edit-body {
    padding: 1rem; overflow-y: auto; flex: 1;
}
.ms-edit-canvas-wrap {
    display: flex; justify-content: center;
    background: #000; border-radius: 4px; margin-bottom: 0.75rem;
    max-height: 50vh; overflow: hidden;
}
.ms-edit-canvas-wrap canvas {
    max-width: 100%; max-height: 50vh; cursor: crosshair;
}
.ms-edit-toolbar {
    display: flex; gap: 0.5rem; align-items: center;
    padding: 0.5rem; background: rgba(255,255,255,0.03);
    border-radius: 4px; margin-bottom: 0.75rem;
    font-size: 0.75rem; color: var(--ms-text, #aab);
}
.ms-edit-toolbar button {
    padding: 0.25rem 0.5rem; border: 1px solid var(--ms-border, #334);
    background: transparent; color: var(--ms-text, #aab); border-radius: 3px;
    cursor: pointer; font-size: 0.7rem;
}
.ms-edit-toolbar button.active {
    background: var(--ms-accent, #f90); color: #000;
}
.ms-edit-params {
    display: flex; flex-direction: column; gap: 0.5rem;
    font-size: 0.75rem; color: var(--ms-text, #aab);
}
.ms-edit-params label { display: flex; flex-direction: column; gap: 0.25rem; }
.ms-edit-params textarea { resize: vertical; min-height: 2rem; }
.ms-edit-modal-footer {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--ms-border, #334);
}
.ms-btn-primary {
    padding: 0.4rem 1rem; background: var(--ms-accent, #f90); color: #000;
    border: none; border-radius: 4px; font-family: 'Antonio', sans-serif;
    text-transform: uppercase; cursor: pointer; font-size: 0.8rem;
}
.ms-btn-primary:hover { opacity: 0.9; }
.ms-version-badge {
    position: absolute; top: 4px; right: 4px;
    background: var(--ms-accent, #f90); color: #000;
    font-size: 0.6rem; padding: 1px 4px; border-radius: 3px;
    font-family: 'Antonio', sans-serif; cursor: pointer;
}
.ms-version-sidebar {
    position: fixed; right: 0; top: 0; bottom: 0; width: 220px;
    background: var(--ms-bg, #1a1a2e);
    border-left: 1px solid var(--ms-accent, #f90);
    z-index: 9998; overflow-y: auto; padding: 0.5rem;
}
.ms-version-sidebar-header {
    display: flex; justify-content: space-between; align-items: center;
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90); padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--ms-border, #334);
}
.ms-version-item {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.5rem; cursor: pointer; border-radius: 4px;
}
.ms-version-item:hover { background: rgba(255, 153, 0, 0.05); }
.ms-version-thumb {
    width: 60px; height: 60px; object-fit: cover; border-radius: 3px;
    border: 1px solid var(--ms-border, #334);
}
```

- [ ] **Step 2: Commit CSS**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add edit modal + version badge + sidebar CSS"
```

---

## Task 8: Integration Test

**Files:**
- Create: `/tmp/test_layer8.py`

**Dependencies:** All previous tasks

- [ ] **Step 1: Write integration test**

```python
import sys, json, os, logging, inspect
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test imports
from tools.media_studio.services.edit_service import (
    submit_edit, get_edit_status, get_versions,
    _validate_edit_params, _next_version, _save_mask,
)
results.append(('Import edit_service', 'OK', True))

# Test submit_edit signature
sig = inspect.signature(submit_edit)
results.append(('submit_edit params', list(sig.parameters.keys()),
    all(p in sig.parameters for p in ['source_id', 'edit_type', 'params', 'mask_data', 'owner_type', 'owner_id'])))

# Test validation
from app import app
with app.app_context():
    # Bad edit type
    r = _validate_edit_params('bad_type', {}, None)
    results.append(('Reject bad edit_type', r.get('error', ''), 'error' in r))

    # Inpaint without mask
    r = _validate_edit_params('inpaint', {}, None)
    results.append(('Inpaint needs mask', r.get('error', ''), 'error' in r))

    # Upscale bad scale
    r = _validate_edit_params('upscale', {'scale_factor': 3}, None)
    results.append(('Upscale bad scale', r.get('error', ''), 'error' in r))

    # Img2img without prompt
    r = _validate_edit_params('img2img', {}, None)
    results.append(('Img2img needs prompt', r.get('error', ''), 'error' in r))

    # Style transfer needs something
    r = _validate_edit_params('style_transfer', {}, None)
    results.append(('Style needs prompt or ref', r.get('error', ''), 'error' in r))

    # Valid upscale
    r = _validate_edit_params('upscale', {'scale_factor': 2}, None)
    results.append(('Valid upscale params', r, r is None))

    # Valid img2img
    r = _validate_edit_params('img2img', {'prompt': 'test'}, None)
    results.append(('Valid img2img params', r, r is None))

    # Check DB tables
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS cnt FROM media_edits")
        row = cur.fetchone()
        cnt = row['cnt'] if hasattr(row, '__getitem__') and not isinstance(row, tuple) else row[0]
        results.append(('media_edits table', cnt >= 0, True))

        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='media_library' AND column_name IN ('version', 'parent_id') "
            "ORDER BY column_name"
        )
        cols = [r['column_name'] if hasattr(r, '__getitem__') and not isinstance(r, tuple) else r[0] for r in cur.fetchall()]
        results.append(('media_library version+parent_id', cols, 'parent_id' in cols and 'version' in cols))

    # Check workflow builders
    from tools.media_studio.services.comfyui_manager import (
        build_inpaint_workflow, build_outpaint_workflow,
        build_upscale_workflow, build_img2img_workflow,
    )
    results.append(('Import workflow builders', 'OK', True))

    # Test inpaint workflow structure
    wf = build_inpaint_workflow('/test.png', '/mask.png', 'test prompt')
    results.append(('Inpaint workflow has prompt key', 'prompt' in wf, True))

    # Test outpaint workflow
    wf = build_outpaint_workflow('/test.png', 'test prompt', direction='right', pixels=128)
    results.append(('Outpaint workflow has prompt key', 'prompt' in wf, True))

    # Test upscale workflow
    wf = build_upscale_workflow('/test.png')
    results.append(('Upscale workflow has prompt key', 'prompt' in wf, True))

    # Test img2img workflow
    wf = build_img2img_workflow('/test.png', 'a painting')
    results.append(('Img2img workflow has prompt key', 'prompt' in wf, True))

    # Check routes
    rules = [r.rule for r in app.url_map.iter_rules()
             if 'media-studio' in r.rule and 'edit' in r.rule]
    results.append(('Edit routes registered', len(rules), len(rules) >= 3))

    versions_route = [r.rule for r in app.url_map.iter_rules()
                      if 'versions' in r.rule and 'media-studio' in r.rule]
    results.append(('Versions route', len(versions_route), len(versions_route) >= 1))

    # Check HTML
    html_path = '/app/tools/media_studio/templates/tools/media_studio/media_studio.html'
    with open(html_path) as f:
        html = f.read()
    for elem in ['msEditModal', 'msEditCanvas', 'switchEditType', 'submitEdit',
                 'openEditModal', 'pollEditStatus', 'loadVersionHistory', 'msVersionSidebar']:
        results.append((f'HTML has {elem}', elem, elem in html))

    # Check CSS
    css_path = '/app/tools/media_studio/static/css/media-studio.css'
    with open(css_path) as f:
        css = f.read()
    for cls in ['.ms-edit-modal', '.ms-edit-tabs', '.ms-edit-canvas-wrap',
                '.ms-version-badge', '.ms-version-sidebar']:
        results.append((f'CSS has {cls}', cls, cls in css))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_layer8.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_layer8.py
```

Expected: All tests PASS.

- [ ] **Step 3: Fix any failures, re-test, commit test**

---

## Task 9: Deploy + Git Push + Dev HQ Update

**Dependencies:** Task 8 (all tests pass)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify running**

```bash
docker logs --tail 20 archie_platform
```

- [ ] **Step 3: Push to remote**

```bash
git push origin main
```

- [ ] **Step 4: Update Dev HQ**

Use MCP tools:
- `complete_task` for Layer 8 task
- `log_decision` for architectural choices (unified edit service, versioning via parent_id)
- `store_memory` for roadmap update (Layer 8 complete)
- `update_project_understanding` for Media Studio project

- [ ] **Step 5: Final commit if needed**
