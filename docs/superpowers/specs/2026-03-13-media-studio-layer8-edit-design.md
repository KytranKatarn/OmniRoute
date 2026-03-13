# Media Studio Layer 8: Image Editing & Post-Processing — Design Spec

## Overview

Add image editing and post-processing capabilities to Media Studio. Users can inpaint, outpaint, upscale, run img2img, and apply style transfer to any image in their gallery (including uploaded and agent-generated images). Edits create versioned entries in the media library, preserving the original.

**Goal:** Five editing operations accessible through a canvas-based mask editor, with ComfyUI workflows for AI-powered edits and Pillow fallback for quick upscaling, all producing versioned results linked to the source image.

## Scope

Five capabilities:
1. **Inpainting** — Paint a mask on an image, regenerate the masked region with a prompt
2. **Outpainting** — Extend an image in any direction with AI-generated content
3. **Upscaling** — Enlarge images via AI models (RealESRGAN) or Lanczos fallback
4. **Img2Img** — Transform an existing image guided by a new prompt
5. **Style Transfer** — Apply artistic styles via prompt description or reference image (IP-Adapter)

## Database Schema

### New table: `media_edits`

```sql
CREATE TABLE IF NOT EXISTS media_edits (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES media_library(id),
    edit_type VARCHAR(30) NOT NULL,        -- inpaint, outpaint, upscale, img2img, style_transfer
    params JSONB DEFAULT '{}',             -- edit-specific parameters
    mask_path VARCHAR(500),                -- stored mask image path (inpaint/outpaint)
    status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, completed, failed
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL
);
```

### Schema change: `media_library`

```sql
ALTER TABLE media_library
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES media_library(id);
```

- `version` — increments for each edit of the same source (v1, v2, v3)
- `parent_id` — links to the original image, forming a version chain
- Existing rows get `version=1, parent_id=NULL` (originals)
- Edit results insert a new `media_library` row with `parent_id` pointing to the source and `version = max(version) + 1` for that chain

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_media_edits_source ON media_edits(source_id);
CREATE INDEX IF NOT EXISTS idx_media_edits_status ON media_edits(status);
CREATE INDEX IF NOT EXISTS idx_media_library_parent ON media_library(parent_id);
```

## Edit Service

**New file:** `platform_v2/tools/media_studio/services/edit_service.py` (~250 lines)

### Entry point: `submit_edit(source_id, edit_type, params, mask_data, owner_type, owner_id)`

1. Validate `source_id` exists in `media_library` and caller owns it (or it's shared/agent)
2. Validate `edit_type` is one of: `inpaint`, `outpaint`, `upscale`, `img2img`, `style_transfer`
3. Validate type-specific params (see table below)
4. If `mask_data` provided (base64 canvas export or uploaded file), save to `media_studio/masks/` and store path
5. Insert row into `media_edits` with status `pending`
6. Build the appropriate ComfyUI workflow via type-specific builder
7. Submit to ComfyUI (or Lanczos fallback for upscale)
8. On completion: create new `media_library` row with `parent_id=source_id`, `version=next_version`
9. Update `media_edits` status to `completed`
10. Return `{edit_id, generation_id}`

### Per-type param validation

| Edit Type | Required Params | Optional Params |
|-----------|----------------|-----------------|
| `inpaint` | mask (canvas/upload) | prompt, strength (0.0-1.0), model |
| `outpaint` | direction (top/bottom/left/right/all), pixels (64-512) | prompt, model |
| `upscale` | scale_factor (2/4) | method (ai/lanczos), model |
| `img2img` | prompt | strength (0.0-1.0), model, negative_prompt |
| `style_transfer` | style_prompt OR reference_image_id | strength (0.0-1.0), model |

### Fallback logic (upscale only)

```python
def _upscale_with_fallback(source_path, scale_factor, method):
    if method == 'lanczos' or not _comfyui_available():
        return _lanczos_upscale(source_path, scale_factor)  # PIL/Pillow
    return _comfyui_upscale(source_path, scale_factor)
```

### Version helper

```python
def _next_version(source_id):
    """Get the root parent and next version number."""
    # Walk up parent chain to find root
    # Count existing versions, return max + 1
```

## ComfyUI Workflow Builders

**New file:** `platform_v2/tools/media_studio/services/edit_workflows.py` (~200 lines)

Five workflow builder functions, each returning a ComfyUI API-format workflow dict. These follow the same pattern as the existing `comfyui_workflows.py` — node dicts with class_type, inputs, and connections.

### `build_inpaint_workflow(image_path, mask_path, prompt, strength, model)`
- Loads source image + mask via LoadImage nodes
- Uses `SetLatentNoiseMask` to apply mask to latent
- KSampler with `denoise=strength` (default 0.75)
- Model: SDXL inpainting checkpoint (falls back to standard SDXL with mask)

### `build_outpaint_workflow(image_path, direction, pixels, prompt, model)`
- Pads canvas in specified direction using `ImagePadForOutpaint` node
- Generates mask automatically for the padded region
- Same inpaint pipeline on the expanded canvas
- Returns larger image with seamless extension

### `build_upscale_workflow(image_path, scale_factor, model)`
- Uses `UpscaleModelLoader` → `ImageUpscaleWithModel` (RealESRGAN/4x-UltraSharp)
- If `scale_factor=2`, follows with `ImageScale` to halve the 4x result
- Simple 3-node workflow, no KSampler needed

### `build_img2img_workflow(image_path, prompt, strength, negative_prompt, model)`
- LoadImage → VAEEncode → KSampler with `denoise=strength`
- Standard txt2img workflow but starting from encoded source image latent
- Lower strength = closer to original, higher = more creative

### `build_style_transfer_workflow(image_path, style_prompt, reference_image_path, strength, model)`
- **Prompt-based** (no reference): img2img workflow with style-descriptive prompt at moderate strength (0.4-0.6)
- **Reference-based** (with reference_image_path): Uses `IPAdapterLoader` + `IPAdapterApply` nodes to inject style from reference image, combined with KSampler

### Shared patterns
- All builders use `_checkpoint_path(model)` helper to resolve model name → path
- All return `(workflow_dict, output_node_id)` tuple for ComfyUI submission
- Error if required checkpoint/model not found on disk

## API Routes

**Modified file:** `platform_v2/tools/media_studio/routes.py`

### New endpoints (4)

#### `POST /api/media-studio/edit`
Submit an edit operation. Authenticated.

```
Body: {
    source_id: int,
    edit_type: "inpaint"|"outpaint"|"upscale"|"img2img"|"style_transfer",
    params: { ...type-specific params... },
    mask_data: "base64..." (optional, for inpaint/outpaint canvas export)
}
Response: {edit_id, status: "pending"} or {error}
```

#### `GET /api/media-studio/edit/<int:edit_id>`
Get edit status and result. Authenticated.

```
Response: {id, source_id, edit_type, status, result_id, error_message, created_at, completed_at}
```
`result_id` is the new `media_library` row ID once completed.

#### `GET /api/media-studio/versions/<int:media_id>`
Get version history for an image. Authenticated.

```
Response: [{id, version, file_path, thumbnail_path, edit_type, created_at}, ...]
```
Walks the `parent_id` chain to find root, then returns all versions sorted by version number.

#### `POST /api/media-studio/edit/upload-mask`
Upload a mask image file (for users who prefer file upload over canvas drawing). Authenticated.

```
Body: multipart form with mask file
Response: {mask_path} — temporary path to use in subsequent edit request
```

### Existing endpoint modification

`GET /api/media-studio/gallery` — Add `parent_id` filter:
- Default behavior: exclude rows where `parent_id IS NOT NULL` (only show originals/latest versions)
- `?show_versions=true` includes all versions

## Frontend

**Modified file:** `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

### Mask Editor Component

A modal overlay with a canvas-based drawing tool for inpainting/outpainting masks. Opens when user clicks "Edit" on a gallery image and selects inpaint or outpaint.

**HTML structure:**
- `#msEditModal` — full-screen modal containing the editor
- `#msEditCanvas` — HTML5 canvas layered over the source image
- Toolbar: brush size slider, eraser toggle, clear mask, undo stroke
- Edit type selector tabs: Inpaint | Outpaint | Upscale | Img2Img | Style Transfer
- Type-specific params panel (changes per selected tab)
- "Submit Edit" button + "Upload Mask" alternative link

**Canvas behavior (inpaint):**
- Source image rendered as background on canvas
- User paints white-on-black mask (white = edit region)
- Brush: circular, size 5-100px via slider
- Eraser mode: paints black (removes mask)
- Undo: stores stroke history, pops last stroke
- On submit: exports mask as base64 PNG via `canvas.toDataURL()`

**Canvas behavior (outpaint):**
- Shows source image centered with configurable padding zones
- User drags handles or enters pixel values for each direction (top/right/bottom/left)
- Visual preview of expanded canvas area
- No manual mask painting needed — mask auto-generated from padding

**Type-specific param panels:**
- **Inpaint/Img2img**: prompt textarea, strength slider (0.0-1.0)
- **Outpaint**: direction checkboxes, pixels input, prompt textarea
- **Upscale**: scale factor radio (2x/4x), method toggle (AI/Lanczos)
- **Style Transfer**: style prompt textarea, optional reference image picker (from gallery), strength slider

### JS functions (~200 lines)

- `openEditModal(mediaId)` — loads source image, initializes canvas
- `switchEditType(type)` — shows/hides type-specific params
- `initMaskCanvas()` — sets up drawing event listeners
- `submitEdit()` — collects params + mask data, calls `POST /api/media-studio/edit`
- `pollEditStatus(editId)` — polls until completed/failed, refreshes gallery
- `loadVersionHistory(mediaId)` — fetches and renders version sidebar
- `uploadMaskFile()` — file input handler for mask upload alternative

### Version display

Gallery cards for edited images show a version badge ("v2", "v3"). Clicking it opens a version history sidebar showing all versions as thumbnails with edit type labels. User can click any version to view full-size.

## CSS

**Modified file:** `platform_v2/tools/media_studio/static/css/media-studio.css`

New styles (~80 lines):
- `.ms-edit-modal` — full-screen modal overlay, dark backdrop
- `.ms-edit-canvas-wrap` — canvas container with source image background
- `.ms-edit-toolbar` — brush controls bar (size slider, eraser, clear, undo)
- `.ms-edit-tabs` — edit type tab selector (LCARS style buttons)
- `.ms-edit-params` — type-specific parameter panel
- `.ms-version-badge` — small version indicator on gallery cards ("v2")
- `.ms-version-sidebar` — version history panel with thumbnail list
- `.ms-mask-brush-preview` — circular cursor indicator following mouse on canvas
- `.ms-outpaint-handle` — draggable padding handles for outpaint direction

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/154_media_edits.sql` | `media_edits` table + `version`/`parent_id` on `media_library` + indexes |
| **Create** | `platform_v2/tools/media_studio/services/edit_service.py` | Core edit service (~250 lines): `submit_edit`, validation, version chain, fallback upscale |
| **Create** | `platform_v2/tools/media_studio/services/edit_workflows.py` | ComfyUI workflow builders (~200 lines): 5 edit type workflows |
| **Modify** | `platform_v2/tools/media_studio/routes.py` | 4 new endpoints + gallery version filter |
| **Modify** | `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Edit modal + canvas mask editor + JS handlers (~200 lines) |
| **Modify** | `platform_v2/tools/media_studio/static/css/media-studio.css` | Edit modal, canvas, version styles (~80 lines) |

**Total:** ~730 lines new code, ~30 lines modifications

## Dependencies

- Pillow (already available for Lanczos upscaling)
- IP-Adapter ComfyUI node (for reference-based style transfer)

## Scope constraints

- No batch editing (one image at a time)
- No real-time preview (submit and wait for result)
- No undo/redo of completed edits (version chain preserves all states)
- No collaborative editing
- No video editing (image only)
