# Media Studio SaaS Module — Design Spec

**Date**: 2026-03-13
**Status**: Draft
**Module**: `platform_v2/tools/media_studio/`
**Category**: `MEDIA_HOME`

---

## 1. Overview

Rebuild the existing Media Studio module as ARCHIE's central AI media generation hub. The module provides a full LCARS UI for generating images, video, and audio — all routed through Bridge dispatcher with fleet-aware GPU scheduling. Supports per-user and per-agent media galleries, consistent agent face generation via IP-Adapter, environment art for nodes/hub, and multi-provider escalation.

### Goals

- Unified media generation interface (image, video, audio/TTS)
- All generation routed through Bridge dispatcher — fleet-aware (Starbase + node ComfyUI instances)
- Per-user and per-agent media libraries with ownership tracking
- Consistent agent identity system (faces + voices)
- Environment art generation (starbase backgrounds, starship scenes for nodes)
- Multi-provider escalation: local ComfyUI → node ComfyUI → free cloud → paid cloud (contractors)

### Delivery Layers

| Layer | Scope | Dependencies |
|-------|-------|-------------|
| 1 | Core UI + ComfyUI image gen + Bridge dispatch + gallery | None |
| 2 | Agent portraits + environment art + identity system | Layer 1 + IP-Adapter plugin |
| 3 | Video generation (AnimateDiff + external providers) | Layer 1 + AnimateDiff plugin |
| 4 | Audio/TTS + agent voices | Layer 1 |

---

## 2. Architecture

### 2.1 Module Structure

```
media_studio/
  __init__.py                          # Blueprint registration
  routes.py                            # API endpoints (rebuild)
  services/
    generation_service.py              # Orchestrates generation → Bridge dispatch
    gallery_service.py                 # Media library CRUD, per-user/per-agent ownership
    portrait_service.py                # Agent face consistency, canonical images, IP-Adapter
    audio_service.py                   # TTS, music generation, agent voice profiles
    comfyui_manager.py                 # Plugin sync, workflow mgmt, fleet coordination
  templates/tools/media_studio/
    media_studio.html                  # LCARS UI (dashboard + tabs)
```

### 2.2 Data Flow

```
User/Agent → Media Studio UI → generation_service → Bridge Dispatcher
  → Pixel agent (or fleet agent with ComfyUI capability)
    → Local ComfyUI / Node ComfyUI / Cloud Provider
      → Result saved to media_library table + filesystem
        → Gallery updated, notification sent
```

### 2.3 UI Layout

**Pattern**: Dashboard + workspace with tabbed navigation (LCARS aesthetic)

| Tab | Purpose |
|-----|---------|
| Dashboard | Recent generations grid, fleet GPU status cards, generation stats |
| Generate | Wizard-style: pick type → configure → preview prompt → submit |
| Gallery | Masonry grid, filters by type/owner/agent/date, full metadata view |
| Portraits | Agent portrait management — canonical images, approve/reject, regenerate |
| Queue | Active/pending/completed jobs, real-time status, cancel pending |

### 2.4 Bridge Integration

**New capabilities** added to capability→station map:
- `image_generation` → CREATIVE station
- `video_generation` → CREATIVE station
- `audio_generation` → CREATIVE station

**Primary agent**: Pixel (ComfyUI specialist, `gpu_tools: ["comfyui"]`)

**Escalation chain**:
1. Local ComfyUI (Starbase — Pixel agent)
2. Node ComfyUI (fleet nodes with GPU + ComfyUI container)
3. Free cloud providers (if configured in external_providers)
4. Paid cloud providers / contractors (Telegram approval for cost)

**VRAM management**: Existing ComfyUI VRAM swap behavior — auto-unloads Ollama GPU models before generation. Bridge tracks ComfyUI VRAM state via `/system_stats`.

### 2.5 Filesystem Layout

```
platform_v2/static/media/
  users/{user_id}/{YYYY-MM-DD}/       # User-generated media
  agents/{agent_name}/{YYYY-MM-DD}/   # Agent-generated media
  portraits/{agent_name}/
    canonical.png                      # Source-of-truth face
    ip_adapter_ref.png                 # Preprocessed IP-Adapter reference
    variants/                          # Alternative poses/styles
  environments/
    hub/                               # Starbase backgrounds
    nodes/{node_id}/                   # Per-node starship backgrounds
```

---

## 3. Database Schema

### 3.1 `media_library` — Every Generated Asset

```sql
CREATE TABLE IF NOT EXISTS media_library (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL,         -- 'user' or 'agent'
    owner_id INTEGER NOT NULL,
    media_type VARCHAR(20) NOT NULL,         -- 'image', 'video', 'audio'
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    prompt TEXT,
    negative_prompt TEXT,
    model VARCHAR(100),
    provider VARCHAR(50),                    -- 'comfyui', 'claude', 'runway', 'elevenlabs', etc.
    node_id INTEGER REFERENCES remote_nodes(id),
    seed BIGINT,
    width INTEGER,
    height INTEGER,
    duration_seconds DECIMAL(8,2),           -- video/audio duration
    duration_ms INTEGER,                     -- generation time
    cost DECIMAL(10,4) DEFAULT 0,
    is_favorite BOOLEAN DEFAULT false,
    is_deleted BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_media_library_owner ON media_library(owner_type, owner_id);
CREATE INDEX idx_media_library_type ON media_library(media_type);
CREATE INDEX idx_media_library_created ON media_library(created_at DESC);
```

### 3.2 `media_generation_queue` — Job Tracking

```sql
CREATE TABLE IF NOT EXISTS media_generation_queue (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL,
    owner_id INTEGER NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',    -- pending/dispatched/generating/completed/failed/cancelled
    bridge_job_id INTEGER,
    params JSONB NOT NULL,
    result_media_id INTEGER REFERENCES media_library(id),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_media_queue_status ON media_generation_queue(status);
CREATE INDEX idx_media_queue_owner ON media_generation_queue(owner_type, owner_id);
```

### 3.3 `agent_portraits` — Face Identity System

```sql
CREATE TABLE IF NOT EXISTS agent_portraits (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) UNIQUE,
    canonical_image_path TEXT,
    identity_prompt TEXT,                    -- locked appearance description
    face_seed BIGINT,                       -- seed that produced canonical
    ip_adapter_ref_path TEXT,               -- preprocessed reference for IP-Adapter
    style_tags JSONB DEFAULT '[]',
    approved BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.4 `media_assignments` — Maps Media to UI Locations

```sql
CREATE TABLE IF NOT EXISTS media_assignments (
    id SERIAL PRIMARY KEY,
    media_id INTEGER REFERENCES media_library(id),
    assignment_type VARCHAR(50) NOT NULL,    -- 'node_background', 'hub_background',
                                             -- 'agent_portrait', 'agent_avatar',
                                             -- 'station_banner', 'module_header'
    target_type VARCHAR(30) NOT NULL,        -- 'node', 'hub', 'agent', 'station', 'module'
    target_id INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_media_assignments_target ON media_assignments(target_type, target_id, is_active);
```

### 3.5 `agent_voices` — Voice Identity System

```sql
CREATE TABLE IF NOT EXISTS agent_voices (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) UNIQUE,
    provider VARCHAR(50) NOT NULL,           -- 'piper', 'coqui', 'elevenlabs', 'openai_tts'
    voice_id VARCHAR(100),                   -- provider-specific voice identifier
    voice_params JSONB DEFAULT '{}',         -- pitch, speed, style per provider
    sample_path TEXT,                        -- reference audio clip
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 4. Layer 1 — Core UI + ComfyUI Image Generation + Bridge Dispatch + Gallery

### 4.1 Frontend (LCARS UI)

**`media_studio.html`** — single-page app with 5 tabs.

**Dashboard Tab:**
- Recent generations grid (last 20 items, thumbnail + prompt snippet)
- Fleet GPU status cards: Starbase + each node, showing ComfyUI health, VRAM usage, loaded models
- Generation stats: total count, by type, by provider, estimated cost this month

**Generate Tab (Wizard Flow):**
1. **Media type selector**: Image (active), Video (Layer 3), Audio (Layer 4) — greyed-out types show "Coming Soon"
2. **Model picker**: dropdown populated from `comfyui_manager.get_available_models()` (SDXL, SD1.5, etc.)
3. **Prompt textarea** + negative prompt (collapsible)
4. **Size presets**: 512×512, 768×768, 1024×1024, custom
5. **Advanced controls** (collapsible): sampler, steps (20-50), CFG scale (1-20), seed (random or fixed)
6. **Provider preference**: Auto (Bridge picks) / specific node
7. **Submit button** → creates queue entry, dispatches to Bridge

**Gallery Tab:**
- Masonry grid layout, lazy-loaded thumbnails
- Filters: media type, date range, model, provider, favorites only
- Click image → full-size modal with metadata (prompt, model, seed, provider, node, generation time, cost)
- Actions: download, favorite, delete, assign to location, regenerate with same params

**Queue Tab:**
- Live job list with status badges: pending (yellow), dispatched (blue), generating (purple pulse), completed (green), failed (red)
- Each row: thumbnail preview (if available), prompt snippet, provider, duration, timestamp
- Cancel button for pending/dispatched jobs
- Auto-refresh every 5 seconds

### 4.2 Backend Services

**`generation_service.py`:**
```python
def submit_generation(user_id, media_type, params):
    """Validate params, create queue entry, dispatch to Bridge."""
    # 1. Validate params (model exists, size within limits)
    # 2. Insert media_generation_queue row (status='pending')
    # 3. Build Bridge dispatch payload
    # 4. Call Bridge dispatcher with capability='image_generation'
    # 5. Update queue row with bridge_job_id, status='dispatched'
    # Return queue_id for frontend polling

def on_generation_complete(queue_id, result):
    """Callback when Bridge job finishes."""
    # 1. Save file to filesystem (users/{user_id}/{date}/)
    # 2. Generate thumbnail (256px wide)
    # 3. Insert media_library row
    # 4. Update queue row (status='completed', result_media_id)

def on_generation_failed(queue_id, error):
    """Callback when Bridge job fails."""
    # Update queue row (status='failed', error_message)

def get_queue_status(owner_type, owner_id, limit=20):
    """Get recent queue entries for polling."""
```

**`gallery_service.py`:**
```python
def get_gallery(owner_type, owner_id, filters, page, per_page):
    """Paginated media library query with filters."""

def get_media_detail(media_id, owner_type, owner_id):
    """Full metadata with ownership check."""

def delete_media(media_id, owner_type, owner_id):
    """Soft delete with ownership verification."""

def toggle_favorite(media_id, owner_type, owner_id):
    """Toggle is_favorite flag."""

def assign_media(media_id, assignment_type, target_type, target_id):
    """Link media to a UI location (node background, agent portrait, etc.)."""
```

**`comfyui_manager.py`:**
```python
def get_fleet_comfyui_status():
    """Health check all ComfyUI instances (Starbase + nodes)."""
    # Query Starbase ComfyUI /system_stats
    # Query each online node's ComfyUI via heartbeat data
    # Return aggregated status

def get_available_models():
    """Aggregate checkpoints across fleet."""
    # Merge Starbase + node model lists, deduplicate

def sync_plugins_to_nodes(plugin_list):
    """Push required plugin list via Starship sync."""
    # Build plugin manifest, push via node sync mechanism

def build_workflow(prompt, negative_prompt, model, width, height, seed, steps, cfg, sampler):
    """Build ComfyUI API workflow JSON for image generation."""
    # Return workflow dict ready for ComfyUI /prompt endpoint
```

### 4.3 API Endpoints

```
GET  /api/dashboard          — stats, recent, fleet GPU status
POST /api/generate           — submit generation request
GET  /api/queue              — poll queue status
POST /api/queue/{id}/cancel  — cancel pending job
GET  /api/gallery            — paginated gallery with filters
GET  /api/gallery/{id}       — single media detail
POST /api/gallery/{id}/favorite  — toggle favorite
DELETE /api/gallery/{id}     — soft delete
GET  /api/models             — available ComfyUI models across fleet
GET  /api/comfyui/status     — fleet ComfyUI health
```

### 4.4 Bridge Dispatcher Changes

In `ai_bridge/bridge_dispatcher.py`:
- Add `image_generation` to CREATIVE station capability map
- Pixel agent as primary handler (check `gpu_tools` contains `"comfyui"`)
- Fleet dispatch: if Starbase ComfyUI busy, check node ComfyUI instances
- On completion: call `generation_service.on_generation_complete()` with result

### 4.5 ComfyUI Plugin Requirements

**Layer 1**: No new plugins needed — stock SDXL + SD1.5 workflows work with base ComfyUI nodes.

---

## 5. Layer 2 — Agent Portraits + Environment Art + Identity System

### 5.1 Agent Portrait Workflow

1. **Generate initial portrait** — use detailed identity prompt from existing `portrait_generator.py` diversity map (ethnicity, features, age, hair color, etc.)
2. **Review in Portraits tab** — user sees all agents, clicks to view generated options
3. **Approve canonical** — selected image becomes source-of-truth, IP-Adapter reference extracted
4. **Future generations** — all subsequent images of that agent use IP-Adapter + canonical reference for face consistency
5. **Agent self-service** (future) — agents can request regeneration (different pose, outfit) but face stays consistent via IP-Adapter lock

### 5.2 Environment Art

**Hub Background (Archie Starbase):**
- Prompt template: "massive orbital space station, Federation starbase style, multiple docking rings, nebula backdrop, dramatic lighting, LCARS aesthetic, 8k, cinematic"
- Assigned via `media_assignments` (target_type='hub', assignment_type='hub_background')
- Displayed behind stats in Starship Command hub card

**Node Backgrounds (per starship):**
- Prompt template: "starship [class] bridge interior, warp-capable vessel, holographic displays, deep space visible through viewports, LCARS panels, 8k, cinematic"
- Each node gets unique ship class/style stored in `remote_nodes.metadata` JSONB
- Assigned via `media_assignments` (target_type='node', target_id=remote_nodes.id)
- Displayed behind stats in Starship Command node cards

### 5.3 Portraits Tab UI

- Agent grid: all agents with current portrait (or placeholder)
- Click agent → portrait management panel:
  - Current canonical image (large)
  - Identity prompt (editable by admin)
  - "Generate New" button → produces variant using IP-Adapter + canonical ref
  - "Generate Canonical" button → fresh generation without IP-Adapter (for initial or reset)
  - Approval toggle
  - Gallery of all variants for this agent
- Bulk actions: "Generate All Missing" — batch canonical generation for agents without portraits

### 5.4 Portrait Service

**`portrait_service.py`:**
```python
def generate_canonical(agent_id, prompt_override=None):
    """Generate initial portrait without IP-Adapter reference."""
    # Use identity_prompt from agent_portraits or diversity map fallback
    # Submit to Bridge as image_generation with agent ownership
    # On complete: save to portraits/{agent_name}/canonical.png

def generate_variant(agent_id, style=None, pose=None):
    """Generate consistent variant using IP-Adapter + canonical reference."""
    # Load canonical + IP-Adapter ref from agent_portraits
    # Build IP-Adapter workflow with face reference
    # Submit to Bridge

def approve_canonical(agent_id, media_id):
    """Lock image as canonical, extract IP-Adapter reference."""
    # Copy to portraits/{agent_name}/canonical.png
    # Run IP-Adapter preprocessing to create ref embedding
    # Update agent_portraits row (approved=true, paths set)

def extract_ip_adapter_ref(image_path):
    """Preprocess face for IP-Adapter input."""
    # Face detection (Impact Pack) → crop → save as ip_adapter_ref.png

def generate_environment(target_type, target_id, prompt):
    """Generate hub/node background art."""
    # Submit image_generation with owner_type='system'
    # On complete: create media_assignment linking to target

def assign_media(media_id, assignment_type, target_type, target_id):
    """Link generated media to a UI location."""
    # Deactivate previous assignment for same target+type
    # Create new media_assignments row
```

### 5.5 ComfyUI Plugins Required

| Plugin | Repository | Purpose |
|--------|-----------|---------|
| IP-Adapter Plus | `ComfyUI_IPAdapter_plus` | Face consistency from reference image |
| InstantID | `ComfyUI-InstantID` | Backup face matching (stronger identity lock) |
| Impact Pack | `ComfyUI-Impact-Pack` | Face detection, crop, segmentation |

**Models to download:**
- IP-Adapter FaceID SDXL model
- InsightFace analysis model (for IP-Adapter)
- ControlNet models for InstantID

### 5.6 Additional API Endpoints

```
GET  /api/portraits                    — all agents with portrait status
GET  /api/portraits/{agent_id}         — agent portrait detail + variants
POST /api/portraits/{agent_id}/generate-canonical  — new canonical
POST /api/portraits/{agent_id}/generate-variant    — IP-Adapter variant
POST /api/portraits/{agent_id}/approve             — approve canonical
POST /api/environments/generate        — generate hub/node background
GET  /api/assignments/{target_type}/{target_id}    — active assignments
POST /api/assignments                  — create/update assignment
```

---

## 6. Layer 3 — Video Generation

### 6.1 Video Types

- **Image-to-video** — animate a still image (agent portrait comes alive, starbase scene with moving ships)
- **Text-to-video** — generate from prompt only (via external providers)
- **Img2img animation** — AnimateDiff style transfer on existing images

### 6.2 Provider Routing

```
Video request → Bridge Dispatcher (capability: video_generation)
  → Tier 1: Local ComfyUI AnimateDiff (free, slower, 2-4s clips)
  → Tier 2: Node ComfyUI AnimateDiff (free, fleet GPU)
  → Tier 3: Free cloud providers (if configured)
  → Tier 4: Paid providers — Runway/Kling/Pika (Telegram approval for cost)
```

### 6.3 Generate Tab Updates

- Video option unlocked in media type selector
- Additional controls: duration (2s/4s/6s), FPS (8/12/24), motion strength slider
- Reference image upload (for image-to-video)
- Provider preference: Auto / Local ComfyUI / specific external provider
- Estimated cost preview for paid providers before submit

### 6.4 ComfyUI Plugins Required

| Plugin | Repository | Purpose |
|--------|-----------|---------|
| AnimateDiff Evolved | `ComfyUI-AnimateDiff-Evolved` | Core video generation |
| VideoHelperSuite | `ComfyUI-VideoHelperSuite` | Video encoding, frame export, GIF |

**Models to download:**
- `mm_sd_v15_v2.safetensors` (AnimateDiff motion model for SD1.5)
- `mm_sdxl_v10_beta.safetensors` (AnimateDiff motion model for SDXL)

### 6.5 External Provider Integration

Extend `ai_bridge/external_providers.py`:
```python
# Each video provider adapter implements:
def submit_video(prompt, params) -> job_id
def poll_video(job_id) -> {status, url, error}
def get_capabilities() -> {max_duration, supported_modes, cost_per_second}
```

**Supported providers** (configured via external_providers settings):
- Runway ML (Gen-3)
- Kling AI
- Pika Labs
- Additional providers added via adapter pattern

### 6.6 Video Service

**In `generation_service.py` (extended):**
```python
def build_animatediff_workflow(prompt, ref_image, duration, fps, motion_strength):
    """Build AnimateDiff ComfyUI workflow."""

def download_external_result(provider, url):
    """Fetch completed video from external API, save locally."""
```

**Output formats:** MP4 (primary), GIF (thumbnail/preview)

---

## 7. Layer 4 — Audio/TTS + Agent Voices

### 7.1 Audio Types

- **TTS** — text-to-speech with selectable voices (agent voices, generic voices)
- **Music** — background music generation (ambient, cinematic, station themes)
- **Sound effects** — UI sounds, notification tones, alert sounds

### 7.2 Agent Voice System

Each agent gets a distinct voice profile stored in `agent_voices`:
- Different pitch, tone, accent per agent
- Consistent across all uses (notifications, briefings, station announcements)
- Voice sample stored for preview

### 7.3 Provider Routing

```
TTS request → Bridge Dispatcher (capability: audio_generation)
  → Tier 1: Local Piper TTS (free, CPU, fast, good quality)
  → Tier 2: Local Coqui TTS (free, GPU optional, more natural)
  → Tier 3: OpenAI TTS API
  → Tier 4: ElevenLabs (highest quality, paid, Telegram approval)

Music request → Bridge Dispatcher
  → Tier 1: Local engine (if available)
  → Tier 2: Free cloud providers
  → Tier 3: Paid providers (Telegram approval)
```

### 7.4 Local TTS Options

**Piper TTS** (recommended primary):
- Lightweight, runs on CPU
- Multiple voice models available
- Can run as Docker sidecar or inside existing container
- Fast inference, good for real-time use

**Coqui TTS** (quality upgrade):
- More natural sounding
- GPU optional (benefits from it)
- Heavier resource usage
- Good for pre-generated content

### 7.5 Generate Tab Updates

- Audio option unlocked in media type selector
- **TTS mode**: text input area, voice picker (agent voices + generic), speed/pitch controls, preview button
- **Music mode**: genre/mood selector, duration slider, text prompt for style description
- Playback preview before saving to gallery

### 7.6 Audio Service

**`audio_service.py`:**
```python
def submit_tts(owner_type, owner_id, text, voice_id, params):
    """Submit TTS request through Bridge dispatch."""

def submit_music(owner_type, owner_id, params):
    """Submit music generation request."""

def get_agent_voice(agent_id):
    """Return active voice profile for agent."""

def preview_voice(voice_id, sample_text):
    """Quick sample generation without saving to gallery."""

def get_available_voices():
    """List all available voices across providers."""
```

### 7.7 Integration Points

- **Agent profile modals**: play voice sample alongside portrait
- **Bridge notifications**: agents can "speak" their alerts via TTS
- **Station announcements**: TTS from station commander's voice
- **Future**: agents compose their own voice messages autonomously

### 7.8 Additional API Endpoints

```
GET  /api/voices                       — available voices (all providers)
GET  /api/voices/agents                — agent voice assignments
POST /api/voices/agents/{agent_id}     — assign/update agent voice
POST /api/voices/preview               — generate quick voice sample
```

---

## 8. ComfyUI Plugin Sync Strategy

### 8.1 Required Plugins (All Layers)

| Plugin | Layer | Purpose |
|--------|-------|---------|
| ComfyUI-Manager | (exists) | Plugin installer/manager |
| ComfyUI_IPAdapter_plus | 2 | Face consistency |
| ComfyUI-InstantID | 2 | Identity lock |
| ComfyUI-Impact-Pack | 2 | Face detection/segmentation |
| ComfyUI-AnimateDiff-Evolved | 3 | Video generation |
| ComfyUI-VideoHelperSuite | 3 | Video encoding/export |

### 8.2 Fleet Sync

- `comfyui_manager.py` maintains a plugin manifest (list of required repos + versions)
- Starship Command sync pushes manifest to nodes
- Nodes install plugins via ComfyUI-Manager API or git clone
- Health check verifies plugin presence across fleet
- Model files synced separately (large files, manual or rsync)

---

## 9. Existing Code Reuse

| Existing Component | How It's Used |
|-------------------|---------------|
| `ai_bridge/comfyui_service.py` | Wrapped by `comfyui_manager.py` — health, models, queue, poll |
| `ai_bridge/portrait_generator.py` | Identity prompts and diversity map consumed by `portrait_service.py` |
| `ai_bridge/external_providers.py` | Extended with video provider adapters, used for cloud escalation |
| `ai_bridge/bridge_dispatcher.py` | All generation routed through dispatcher, new CREATIVE capabilities |
| `media_studio/routes.py` | Rebuilt — existing API patterns preserved where applicable |
| Bridge VRAM monitoring | Existing GPU tracking informs ComfyUI dispatch decisions |
| Starship node sync | Plugin manifest pushed to nodes via existing sync pipeline |

---

## 10. Non-Goals (Explicitly Out of Scope)

- Multi-tenant billing / usage quotas (single-user SaaS for now)
- Real-time streaming of generation progress (poll-based is sufficient)
- Training custom LoRA models (may add later as premium feature)
- Social media posting from Media Studio (exists in social_media module)
- Media Hub integration (Plex/Jellyfin — separate module, no overlap)
