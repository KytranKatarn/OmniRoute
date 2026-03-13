# Media Studio Layer 4: Audio Generation — Design Spec

**Date**: 2026-03-13
**Project**: Media Studio (#129)
**Layers**: 1 (Image) ✅ → 2 (Portraits) ✅ → 3 (Video) ✅ → **4 (Audio)**

---

## Overview

Add full audio generation to Media Studio with three sub-modes: Speech (TTS), Sound Effects, and Music. Local XTTS v2 for speech generation, external provider stubs for SFX and music (same pattern as Layer 3 video providers).

## Audio Sub-Modes

| Mode | Backend | Model/Provider | VRAM | Controls |
|------|---------|---------------|------|----------|
| Speech | Local XTTS v2 | coqui/xtts-v2 (~2GB) | ~2GB | Text, voice picker, speed slider |
| Sound FX | External (stubbed) | contractor_providers | 0 | Description prompt, duration (1/3/5/10s), provider |
| Music | External (stubbed) | contractor_providers | 0 | Description prompt, duration (10/30/60s), provider |

## Backend Architecture

### TTS Service (`services/tts_service.py`)

New service wrapping XTTS v2 inference:

- `generate_speech(text, voice_id, speed, output_path)` — core TTS function
- `list_voices()` — returns preset voices + custom agent voice samples
- `save_voice_sample(agent_id, audio_file)` — stores uploaded voice clip to `MEDIA_ROOT/voices/`
- XTTS v2 loaded on-demand, auto-unloaded after generation (same VRAM swap pattern as ComfyUI SDXL)
- Voice samples: 6-second WAV/MP3 clips stored in `MEDIA_ROOT/voices/` (MEDIA_ROOT = `/mnt/archie_brain/platform_v2/media`, Docker-mounted)
- `os.makedirs(MEDIA_ROOT + "/voices", exist_ok=True)` in service init (same pattern as `MEDIA_ROOT/tmp/` in generation_service)
- Preset voices: 3-4 built-in XTTS speaker embeddings shipped as static files in `static/voices/`
- Output format: WAV (lossless), optionally converted to MP3

### Generation Service Updates (`services/generation_service.py`)

- Add `DEFAULT_AUDIO_PARAMS` dict (audio_mode, voice_id, speed, duration)
- Add `generate_audio(queue_id)` — routes by `audio_mode`:
  - `speech` → `tts_service.generate_speech()`
  - `sfx` / `music` → `call_external()` stubs
- Add `submit_external_audio(queue_id, provider)` — mirrors `submit_external_video()`
- Add `poll_external_audio(queue_id)` — mirrors `poll_external_video()`
- Add `get_audio_providers(audio_mode)` — queries `contractor_providers` WHERE `capabilities ? 'audio_sfx'` or `capabilities ? 'audio_music'` (JSONB `?` operator works on arrays, same pattern as video `capabilities ? 'video_generation'`)
- Update `submit_generation()` to handle `media_type="audio"` with merged defaults

### External Provider Stubs

Same `contractor_providers` table pattern as Layer 3 video:

- Capability keys: `audio_sfx`, `audio_music`
- `call_external(provider, action, params)` extended with audio actions
- Stubbed for: ElevenLabs, Stability Audio, Replicate (configured later via DB)

### Voice Management

- `agents` table gets `voice_sample` column (nullable varchar) — path to custom voice clip
- Default: agents use preset voice (mapped by agent station or role)
- Custom: upload 6-second clip via API, stored at `MEDIA_ROOT/voices/{agent_name}.wav`
- Voice picker UI shows presets first, then custom agent voices

## API Routes

Added to `routes.py`:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/audio/generate` | Submit audio generation (speech/sfx/music via `audio_mode` param) |
| GET | `/api/audio/voices` | List available voices (presets + custom agent voices) |
| POST | `/api/audio/voices/upload` | Upload custom voice sample for an agent |
| GET | `/api/audio/providers` | List external SFX/music providers |

### POST `/api/audio/generate` payload

```json
{
    "prompt": "Hello, this is a test of the ARCHIE speech system.",
    "audio_mode": "speech",
    "voice_id": "preset_female_1",
    "speed": 1.0,
    "duration": null,
    "provider": "auto",
    "seed": -1
}
```

### Validation Rules

- `audio_mode` required, must be one of: `speech`, `sfx`, `music`
- **Speech mode**: `prompt` required (text to speak), `voice_id` required (preset or agent voice)
- **SFX mode**: `prompt` required (description), `duration` required (1/3/5/10)
- **Music mode**: `prompt` required (description), `duration` required (10/30/60)
- `provider` defaults to `"auto"` (local for speech, first available external for sfx/music)

## Database Migration

`150_audio_voice_samples.sql`:

```sql
-- Add voice_sample column to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_sample VARCHAR(500);
COMMENT ON COLUMN agents.voice_sample IS 'Path to custom XTTS voice clone sample (6s WAV/MP3)';

-- Seed audio capabilities into contractor_providers (stubbed — no real API keys yet)
-- The capabilities column is JSONB array from migration 117
INSERT INTO contractor_providers (provider_key, display_name, capabilities, is_active, cost_per_unit)
VALUES
    ('elevenlabs', 'ElevenLabs', '["text_chat", "audio_sfx"]'::jsonb, false, 0.30),
    ('stability_audio', 'Stability Audio', '["audio_music", "audio_sfx"]'::jsonb, false, 0.10),
    ('replicate_audio', 'Replicate Audio', '["audio_music", "audio_sfx"]'::jsonb, false, 0.05)
ON CONFLICT (provider_key) DO UPDATE
    SET capabilities = EXCLUDED.capabilities || contractor_providers.capabilities;
```

**Note on capabilities column**: Migration 117 created `capabilities JSONB` as an array (e.g., `'["text_chat"]'`). The `?` operator works on JSONB arrays to check containment — same pattern as Layer 3 video (`capabilities ? 'video_generation'`). Existing providers like Gemini already have `audio_tts` capability.

## UI Changes

### Generate Tab — Audio Mode

When user clicks Audio type button:

1. Sub-mode row appears: **Speech** | **Sound FX** | **Music** (toggle buttons, same pattern as duration/FPS buttons)
2. `msAudioControls` div shown (hidden for image/video modes)
3. Controls change based on selected sub-mode:

**Speech mode:**
- Prompt textarea repurposed as "Text to speak"
- Voice picker dropdown (presets + custom agent voices)
- Speed slider (0.5x — 2.0x, default 1.0)

**SFX mode:**
- Prompt textarea for description (e.g., "spaceship engine hum")
- Duration buttons: 1s / 3s / 5s / 10s
- Provider dropdown (from `/api/audio/providers?mode=sfx`)

**Music mode:**
- Prompt textarea for description (e.g., "epic sci-fi orchestral theme")
- Duration buttons: 10s / 30s / 60s
- Provider dropdown (from `/api/audio/providers?mode=music`)

4. Generate button text → "Generate Audio"
5. `selectMediaType('audio')` removes the Layer 4 guard in JS

### JS Functions

- `window.selectAudioMode(mode)` — toggles sub-mode buttons, shows/hides mode-specific controls
- `window.setAudioDuration(dur)` — updates duration selection
- `window.loadAudioVoices()` — populates voice picker from API
- `window.loadAudioProviders()` — populates provider dropdowns
- `submitGeneration()` updated: audio mode sends to `/api/audio/generate` with `audio_mode`, `voice_id`, `speed`, `duration`, `provider`

### CSS — S18 Audio Controls

- `.ms-audio-controls` — container (matches `.ms-video-controls` pattern)
- `.ms-audio-mode-btns` — sub-mode button row
- `.ms-audio-mode-btn` — individual sub-mode button (active state: purple accent)
- `.ms-voice-picker` — voice dropdown styling
- `.ms-speed-slider` — speed control (reuses `.ms-slider` pattern)
- Mode-specific control divs: `.ms-audio-speech-controls`, `.ms-audio-sfx-controls`, `.ms-audio-music-controls`

## File Changes Summary

| File | Change |
|------|--------|
| `services/tts_service.py` | **NEW** — XTTS v2 wrapper (generate_speech, list_voices, save_voice_sample) |
| `services/generation_service.py` | Add DEFAULT_AUDIO_PARAMS, generate_audio(), external audio stubs, get_audio_providers() |
| `routes.py` | Add 4 audio endpoints |
| `media_studio.html` | Enable Audio button, add msAudioControls with sub-modes, JS functions |
| `media-studio.css` | Add S18 Audio Controls section |
| `database/migrations/150_audio_voice_samples.sql` | Add voice_sample column to agents |

## VRAM Impact

- XTTS v2: ~2GB VRAM, loaded on-demand for speech generation
- **VRAM swap lifecycle**: Before TTS generation, `tts_service` calls Ollama `/api/generate` with `keep_alive=0` on any GPU-loaded model to free VRAM (same pattern as ComfyUI SDXL swap in `generation_service.py`). After TTS completes, the model is unloaded from GPU via Python garbage collection + `torch.cuda.empty_cache()`. Ollama's warmup will reload agent models on next dispatch.
- No orchestration_engine integration needed — TTS is a synchronous call within the generation queue worker, not a routed agent task
- External SFX/music: zero VRAM impact (API calls only)
- Within 8GB M4000 budget alongside Ollama agent models

## Dependencies

- `TTS` pip package (Coqui TTS) — needs to be added to Docker requirements
- XTTS v2 model downloaded on first use (~1.5GB disk)
- No new containers needed — runs inside existing `archie_platform`
