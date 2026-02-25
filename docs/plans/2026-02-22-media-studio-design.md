# Media Studio Module — Design Document

**Date**: 2026-02-22
**Status**: Approved
**Author**: Claude (brainstorming session with Kytran)

---

## Goal

Full media suite module (image, video, audio generation) that routes through the AI Bridge, with dynamic provider capability discovery, bridge-managed agent assignment on the CREATIVE station, and Telegram approval for paid generation.

## Architecture

The Media Studio module calls the AI Bridge for all generation requests. The bridge discovers which providers support which media capabilities via a new `capabilities` JSONB column on `contractor_providers`. Routing follows the existing tier pattern: free local first (TTS via Kokoro/XTTS), then free cloud (Gemini Imagen 3), then paid cloud (OpenAI DALL-E) with Telegram approval. The CREATIVE station agent is assigned by the bridge based on current scheduling.

## Tech Stack

- Flask Blueprint (existing `media_studio` module — gut and rebuild routes)
- PostgreSQL (3 schema changes: 1 column addition, 2 new tables)
- AI Bridge routing (`bridge_dispatcher.py`, `smart_router.py`, `external_providers.py`)
- Provider APIs: Gemini Imagen 3, OpenAI DALL-E 3, local Kokoro/XTTS
- LCARS gold-standard UI pattern
- Telegram bot (existing escalation flow)

---

## Section 1: Database & Provider Capabilities

### 1.1 New column on `contractor_providers`

```sql
ALTER TABLE contractor_providers
ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '["text_chat"]';
```

Capability tags: `text_chat`, `image_gen`, `video_gen`, `audio_tts`, `audio_music`, `vision`, `code`, `embedding`.

Seed existing providers:
- minimax_cloud: `["text_chat"]`
- qwen3_cloud: `["text_chat", "code"]`
- groq: `["text_chat", "code"]`
- gemini: `["text_chat", "vision", "image_gen", "audio_tts"]`
- openai (if added): `["text_chat", "vision", "image_gen", "audio_tts", "code"]`
- cerebras: `["text_chat"]`
- mistral: `["text_chat", "code"]`
- cohere: `["text_chat"]`

### 1.2 `media_assets` table

```sql
CREATE TABLE IF NOT EXISTS media_assets (
    id SERIAL PRIMARY KEY,
    asset_type VARCHAR(20) NOT NULL,          -- image, video, audio
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
    deleted_at TIMESTAMP                       -- soft delete
);
```

### 1.3 `media_generation_queue` table

```sql
CREATE TABLE IF NOT EXISTS media_generation_queue (
    id SERIAL PRIMARY KEY,
    request_type VARCHAR(20) NOT NULL,        -- image, video, audio_tts, audio_music
    prompt TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'pending',     -- pending, awaiting_approval, generating, completed, failed, rejected, cancelled
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
```

---

## Section 2: Bridge Routing & Capability Discovery

### 2.1 Capability discovery function (`external_providers.py`)

```python
def get_providers_with_capability(capability: str) -> list[dict]:
    """Return providers that support a given capability, ordered by cost."""
    # Reads from contractor_providers WHERE capabilities ? capability
    # Returns: [{provider_key, display_name, capabilities, is_free_tier, ...}]
```

### 2.2 CAPABILITY_STATION_MAP additions (`bridge_dispatcher.py`)

```python
"image_generation": "CREATIVE",
"video_generation": "CREATIVE",
"audio_generation": "CREATIVE",
"media_editing": "CREATIVE",
```

### 2.3 CAPABILITY_ROUTING additions (`smart_router.py`)

```python
"image_generation": "media_cloud",   # Skips local — Ollama can't generate images
"video_generation": "media_cloud",
"audio_generation": "local",          # Kokoro/XTTS first, then cloud fallback
"audio_music": "media_cloud",
```

### 2.4 Media routing tier (new)

```
media_cloud tier order:
1. Free cloud providers with matching capability (e.g., Gemini Imagen 3 free tier)
2. Paid cloud providers (OpenAI DALL-E, Replicate Flux) — requires Telegram approval
```

### 2.5 Bridge dispatch flow

```
User requests media generation
  -> Bridge identifies capability (image_generation, etc.)
  -> CAPABILITY_STATION_MAP -> CREATIVE station
  -> Bridge checks who's scheduled on CREATIVE
  -> get_providers_with_capability() -> [Gemini, OpenAI, ...]
  -> Smart router picks: free tier first
  -> If free fails/unavailable -> paid tier -> Telegram approval
  -> Provider API call via external_providers.py
  -> Result saved to media_assets
  -> Bridge logs dispatch as normal
```

No changes to `orchestration_engine.py` — media requests enter through module endpoints, not chat pipeline.

---

## Section 3: Media Studio Module — Endpoints & UI

### 3.1 API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/media/capabilities` | Available media capabilities from bridge |
| `POST` | `/api/media/generate` | Submit generation request |
| `GET` | `/api/media/queue` | List queued/in-progress/completed jobs |
| `GET` | `/api/media/queue/<id>` | Poll single job status |
| `DELETE` | `/api/media/queue/<id>` | Cancel pending job |
| `GET` | `/api/media/gallery` | Browse completed assets |
| `GET` | `/api/media/gallery/<id>` | Single asset details |
| `DELETE` | `/api/media/gallery/<id>` | Soft-delete asset |
| `POST` | `/api/media/gallery/<id>/set-profile` | Set image as agent profile pic |

### 3.2 Generation flow

```
POST /api/media/generate {type: "image", prompt: "...", params: {size: "1024x1024"}}
  -> Insert into media_generation_queue (status: "pending")
  -> Bridge dispatches to CREATIVE station agent
  -> Provider selected via capability discovery + smart router
  -> If paid -> Telegram approval -> status: "awaiting_approval"
  -> Provider API call -> download result
  -> Save to /static/media/{type}/{date}/{uuid}.{ext}
  -> Insert into media_assets, queue status -> "completed"
```

### 3.3 Processing model

- **Synchronous** (< 30s): Image gen via Gemini/DALL-E — hold request, return result
- **Async queue** (> 30s): Video gen, music gen — return job ID, client polls

### 3.4 UI — LCARS gold-standard, 3 tabs

1. **Create** — Type selector (Image/Video/Audio), prompt textarea, parameter controls, capability indicator
2. **Queue** — Active/recent jobs with status badges, progress indicators, cancel button
3. **Gallery** — Thumbnail grid, filterable by type/date, expand for details, "Set as Profile" button

### 3.5 File storage

```
platform_v2/static/media/
  images/2026-02-22/uuid.png
  video/2026-02-22/uuid.mp4
  audio/2026-02-22/uuid.wav
```

### 3.6 Profile picture integration

"Set as Profile" updates `agents.avatar_url` to the media asset path. Bridge, dashboard, and mockup all read `avatar_url` for instant propagation.

---

## Section 4: Provider Integration

### 4.1 Unified request format

```python
{
    "type": "image",
    "prompt": "a starship bridge at sunset",
    "params": {
        "size": "1024x1024",
        "duration": 5,
        "voice": "alloy",
        "style": "vivid"
    }
}
```

### 4.2 Phase 1 providers (this build)

| Provider | Capability | Free Tier | Notes |
|----------|-----------|-----------|-------|
| Gemini | `image_gen` | Yes (15 imgs/min) | Already a contractor — needs capability flag + adapter |
| OpenAI | `image_gen` | No ($0.04/img) | Needs Telegram approval |
| Kokoro/XTTS | `audio_tts` | Free (local) | Already built — wire bridge routing |
| Gemini | `audio_tts` | Yes | Cloud TTS fallback |

### 4.3 Phase 2 providers (future)

Replicate (image + video), Together AI (image), ElevenLabs (TTS), Suno/Udio (music).

### 4.4 Adapter pattern

```python
def generate_media(provider_key: str, request: dict) -> dict:
    adapters = {
        "gemini": _gemini_media_adapter,
        "openai": _openai_image_adapter,
        "local_tts": _local_tts_adapter,
    }
    adapter = adapters.get(provider_key)
    return adapter(request)
```

Each adapter: translate params -> API call -> download result -> save file -> return `{success, file_path, metadata}`.

### 4.5 Cost tracking

Media costs logged in `bridge_usage_log` via existing `log_bridge_call()`. Also stored in `media_assets.cost_usd` for gallery-level visibility.

---

## Section 5: Telegram Approval Flow

### 5.1 When approval is needed

- Paid providers (OpenAI DALL-E, future Replicate, etc.)
- Free-tier quota exhausted

### 5.2 No approval needed

- Local TTS (Kokoro/XTTS)
- Free-tier cloud (Gemini Imagen 3 within quota)
- Providers where `is_free_tier = true`

### 5.3 Telegram message format

```
Media Generation Request
Type: Image (1024x1024)
Provider: OpenAI DALL-E 3
Est. Cost: $0.04
Prompt: "Generate image of starship bridge"
Requested by: admin

/approve_media_123  |  /reject_media_123
```

### 5.4 Integration

- `telegram_bot.py`: Add `/approve_media_<id>` and `/reject_media_<id>` handlers (same pattern as model escalation)
- Frontend polls queue endpoint every 3s during `awaiting_approval` / `generating` states
- `system_config` key `media_auto_approve_under_usd` (default: 0.00) for auto-approval threshold

---

## Decision Log

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Architecture | Capability Discovery on contractor_providers | Extensible, no hardcoded provider lists, bridge scans dynamically |
| Scope | All 3 media types at once | Shared infrastructure (queue, gallery, routing) — minimal marginal cost per type |
| Existing module | Gut and rebuild routes.py | Old Fooocus/DALL-E code is untested and incompatible with bridge-only pattern |
| Image gen backend | Gemini Imagen 3 (free) + OpenAI DALL-E 3 (paid) | Gemini already a contractor; OpenAI is highest quality |
| Audio TTS | Local Kokoro/XTTS first, cloud fallback | Already built, free, fast |
| Approval flow | Reuse existing Telegram escalation | No new bot code, consistent UX for admin |
| Processing | Sync for fast (<30s), async queue for slow | Best UX — instant results for images, non-blocking for video |
