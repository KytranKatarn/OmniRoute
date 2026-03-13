# Media Studio Layer 4: Audio Generation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add audio generation (TTS speech, SFX, music) to Media Studio with local XTTS v2 for speech and external provider stubs for SFX/music.

**Architecture:** New `tts_service.py` wraps XTTS v2 for local speech. `generation_service.py` gains audio defaults, `generate_audio()`, and external audio stubs mirroring the video pattern. Migration 150 adds `voice_sample` column to agents and seeds audio providers. UI adds sub-mode buttons (Speech/SFX/Music) with mode-specific controls.

**Tech Stack:** Python (Flask), XTTS v2 (Coqui TTS), PostgreSQL, vanilla JS (DOM API, no innerHTML)

**Spec:** `docs/superpowers/specs/2026-03-13-media-studio-layer4-audio-design.md`

---

## Chunk 1: Backend — Migration + TTS Service + Generation Service

### Task 1: Database Migration 150

**Files:**
- Create: `database/migrations/150_audio_voice_samples.sql`

- [ ] **Step 1: Create migration file**

```sql
-- Migration 150: Audio voice samples + provider seeding
-- Adds voice_sample column to agents for XTTS v2 voice cloning
-- Seeds audio capabilities into contractor_providers

ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_sample VARCHAR(500);
COMMENT ON COLUMN agents.voice_sample IS 'Path to custom XTTS voice clone sample (6s WAV/MP3)';

-- Seed audio providers (stubbed — no real API keys yet)
INSERT INTO contractor_providers (provider_key, display_name, capabilities, is_active, cost_per_unit)
VALUES
    ('elevenlabs', 'ElevenLabs', '["audio_sfx"]'::jsonb, false, 0.30),
    ('stability_audio', 'Stability Audio', '["audio_music", "audio_sfx"]'::jsonb, false, 0.10),
    ('replicate_audio', 'Replicate Audio', '["audio_music", "audio_sfx"]'::jsonb, false, 0.05)
ON CONFLICT (provider_key) DO UPDATE
    SET capabilities = EXCLUDED.capabilities || contractor_providers.capabilities;
```

- [ ] **Step 2: Run migration**

Run: `docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/150_audio_voice_samples.sql`

If the migration path isn't mounted, copy it in first:
```bash
docker cp database/migrations/150_audio_voice_samples.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/150_audio_voice_samples.sql
```

- [ ] **Step 3: Verify**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='agents' AND column_name='voice_sample';"`
Expected: 1 row with `voice_sample`

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT provider_key FROM contractor_providers WHERE capabilities ? 'audio_sfx';"`
Expected: rows including `elevenlabs`, `stability_audio`, `replicate_audio`

- [ ] **Step 4: Commit**

```bash
git add database/migrations/150_audio_voice_samples.sql
git commit -m "feat(media-studio): add migration 150 — voice_sample column + audio provider seeds"
```

---

### Task 2: TTS Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/tts_service.py`

This is the core local TTS service wrapping XTTS v2. It provides `generate_speech()`, `list_voices()`, and `save_voice_sample()`. XTTS v2 may not be installed yet — the service gracefully degrades with clear error messages if the `TTS` package is missing.

- [ ] **Step 1: Create tts_service.py**

```python
"""TTS Service — XTTS v2 wrapper for local speech generation.

Provides generate_speech(), list_voices(), save_voice_sample().
Gracefully degrades if Coqui TTS package is not installed.
"""

import logging
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Voice samples and presets directory
_PLATFORM_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")
VOICES_DIR = os.path.join(MEDIA_ROOT, "voices")
PRESET_DIR = os.path.join(_PLATFORM_DIR, "static", "voices")

# Ensure voices directory exists
os.makedirs(VOICES_DIR, exist_ok=True)

# XTTS v2 model instance (loaded on demand)
_tts_model = None

# Built-in preset voices (XTTS v2 speaker embeddings)
PRESET_VOICES = [
    {"id": "preset_female_1", "name": "Female 1 (Default)", "type": "preset"},
    {"id": "preset_female_2", "name": "Female 2", "type": "preset"},
    {"id": "preset_male_1", "name": "Male 1", "type": "preset"},
    {"id": "preset_male_2", "name": "Male 2", "type": "preset"},
]


def _load_model():
    """Load XTTS v2 model on demand. Returns model or None if unavailable."""
    global _tts_model
    if _tts_model is not None:
        return _tts_model

    try:
        from TTS.api import TTS

        logger.info("Loading XTTS v2 model (first use — may download ~1.5GB)...")
        _tts_model = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")
        if hasattr(_tts_model, "to"):
            _tts_model.to("cuda")
        logger.info("XTTS v2 model loaded successfully")
        return _tts_model
    except ImportError:
        logger.warning("Coqui TTS package not installed — pip install TTS")
        return None
    except Exception as e:
        logger.error(f"Failed to load XTTS v2: {e}")
        return None


def _unload_model():
    """Unload XTTS v2 from GPU to free VRAM."""
    global _tts_model
    if _tts_model is not None:
        del _tts_model
        _tts_model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("XTTS v2 unloaded, GPU cache cleared")
        except ImportError:
            pass


def _free_gpu_for_tts():
    """Ask Ollama to unload GPU models before TTS generation."""
    try:
        import requests as http_requests

        # Send keep_alive=0 to unload any loaded model
        resp = http_requests.post(
            "http://host.docker.internal:11434/api/generate",
            json={"model": "dummy", "keep_alive": 0},
            timeout=5,
        )
        # Ignore errors — model may not exist, that's fine
    except Exception:
        pass


def generate_speech(
    text: str,
    voice_id: str = "preset_female_1",
    speed: float = 1.0,
    language: str = "en",
    output_path: Optional[str] = None,
) -> Dict:
    """Generate speech audio from text using XTTS v2.

    Args:
        text: Text to speak
        voice_id: Preset voice ID or path to custom voice sample
        speed: Speech speed multiplier (0.5 - 2.0)
        language: Language code (en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh, ja, hu, ko)
        output_path: Override output file path (default: auto-generated in MEDIA_ROOT/tmp/)

    Returns:
        dict with 'file_path' on success or 'error' on failure
    """
    model = _load_model()
    if model is None:
        return {"error": "XTTS v2 model not available. Install: pip install TTS"}

    # Clamp speed
    speed = max(0.5, min(2.0, speed))

    # Determine output path
    if not output_path:
        os.makedirs(os.path.join(MEDIA_ROOT, "tmp"), exist_ok=True)
        output_path = os.path.join(
            MEDIA_ROOT, "tmp", f"tts_{int(time.time())}_{os.getpid()}.wav"
        )

    # Resolve voice: preset or custom sample file
    speaker_wav = None
    if voice_id.startswith("preset_"):
        # Use built-in speaker — XTTS v2 has built-in multi-speaker support
        preset_file = os.path.join(PRESET_DIR, f"{voice_id}.wav")
        if os.path.exists(preset_file):
            speaker_wav = preset_file
    elif voice_id.startswith("agent_"):
        # Custom agent voice sample
        agent_file = os.path.join(VOICES_DIR, f"{voice_id}.wav")
        if os.path.exists(agent_file):
            speaker_wav = agent_file
    else:
        # Direct path (sanitized)
        safe_name = os.path.basename(voice_id)
        candidate = os.path.join(VOICES_DIR, safe_name)
        if os.path.exists(candidate):
            speaker_wav = candidate

    try:
        # Free GPU for TTS
        _free_gpu_for_tts()

        if speaker_wav:
            model.tts_to_file(
                text=text,
                file_path=output_path,
                speaker_wav=speaker_wav,
                language=language,
                speed=speed,
            )
        else:
            # No speaker wav — use default speaker
            model.tts_to_file(
                text=text,
                file_path=output_path,
                language=language,
                speed=speed,
            )

        # Unload model to free VRAM
        _unload_model()

        return {"file_path": output_path}
    except Exception as e:
        _unload_model()
        logger.error(f"TTS generation failed: {e}")
        return {"error": f"TTS generation failed: {str(e)}"}


def list_voices() -> List[Dict]:
    """Return all available voices (presets + custom agent voices).

    Returns:
        List of dicts with id, name, type keys
    """
    voices = list(PRESET_VOICES)

    # Scan for custom agent voice samples
    if os.path.isdir(VOICES_DIR):
        for fname in sorted(os.listdir(VOICES_DIR)):
            if fname.endswith((".wav", ".mp3")):
                voice_id = os.path.splitext(fname)[0]
                voices.append(
                    {
                        "id": voice_id,
                        "name": voice_id.replace("_", " ").title(),
                        "type": "custom",
                    }
                )

    # Add agent voices from DB
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT name, display_name, voice_sample
                   FROM agents
                   WHERE status = 'active' AND voice_sample IS NOT NULL"""
            )
            for row in cur.fetchall():
                voices.append(
                    {
                        "id": f"agent_{row['name']}",
                        "name": f"{row['display_name'] or row['name']} (Agent)",
                        "type": "agent",
                        "sample_path": row["voice_sample"],
                    }
                )
    except Exception as e:
        logger.warning(f"Failed to query agent voices: {e}")

    return voices


def save_voice_sample(agent_name: str, audio_data: bytes, extension: str = ".wav") -> Dict:
    """Save a voice sample for an agent.

    Args:
        agent_name: Agent code name (used as filename)
        audio_data: Raw audio bytes
        extension: File extension (.wav or .mp3)

    Returns:
        dict with 'path' on success or 'error' on failure
    """
    safe_name = os.path.basename(agent_name)
    if not safe_name:
        return {"error": "Invalid agent name"}

    ext = extension if extension in (".wav", ".mp3") else ".wav"
    dest = os.path.join(VOICES_DIR, f"agent_{safe_name}{ext}")

    try:
        with open(dest, "wb") as f:
            f.write(audio_data)

        # Update agents table
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE agents SET voice_sample = %s WHERE name = %s",
                    (dest, safe_name),
                )
        except Exception as e:
            logger.warning(f"Failed to update agent voice_sample: {e}")

        return {"path": dest}
    except Exception as e:
        logger.error(f"Failed to save voice sample: {e}")
        return {"error": f"Failed to save voice sample: {str(e)}"}
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('platform_v2/tools/media_studio/services/tts_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/tts_service.py
git commit -m "feat(media-studio): add TTS service with XTTS v2 wrapper"
```

---

### Task 3: Generation Service — Audio Support

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

Adds `DEFAULT_AUDIO_PARAMS`, `generate_audio()`, external audio stubs, and `get_audio_providers()`. Follows the exact same patterns as the video functions already in this file.

- [ ] **Step 1: Add DEFAULT_AUDIO_PARAMS after DEFAULT_VIDEO_PARAMS (after line ~57)**

After the `DURATION_FRAMES` dict (line ~60), add:

```python
DEFAULT_AUDIO_PARAMS = {
    "audio_mode": "speech",
    "voice_id": "preset_female_1",
    "speed": 1.0,
    "language": "en",
    "duration": 5,
    "seed": -1,
}

# Audio duration presets per mode
AUDIO_DURATIONS = {
    "speech": [5, 10, 30, 60],
    "sfx": [1, 3, 5, 10],
    "music": [10, 30, 60],
}
```

- [ ] **Step 2: Update submit_generation() param merge (line ~79)**

Find the line:
```python
        defaults = DEFAULT_VIDEO_PARAMS if media_type == "video" else DEFAULT_IMAGE_PARAMS
```

Replace with:
```python
        if media_type == "video":
            defaults = DEFAULT_VIDEO_PARAMS
        elif media_type == "audio":
            defaults = DEFAULT_AUDIO_PARAMS
        else:
            defaults = DEFAULT_IMAGE_PARAMS
```

- [ ] **Step 3: Add generate_audio() after get_video_providers() (after line ~698)**

Append to end of file:

```python
# ─── Audio ────────────────────────────────────────────────────────────


def generate_audio(queue_id: int) -> Optional[str]:
    """Generate audio via local XTTS v2 (speech) or external provider (sfx/music).

    Called by the queue worker when processing an audio generation request.
    Returns the output file path on success, None on failure.
    """
    from database import get_db_cursor

    # Read queue entry
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT prompt, params FROM media_generation_queue WHERE id = %s", (queue_id,)
        )
        row = cur.fetchone()
        if not row:
            logger.error(f"Audio gen: queue entry {queue_id} not found")
            return None

    prompt = row["prompt"]
    params = row["params"] or {}
    audio_mode = params.get("audio_mode", "speech")

    if audio_mode == "speech":
        return _generate_speech_local(queue_id, prompt, params)
    else:
        # SFX and Music — external providers
        provider = params.get("provider", "auto")
        if provider == "local":
            logger.warning(f"No local provider for audio mode '{audio_mode}'")
            _update_queue_status(queue_id, "failed", error=f"No local provider for {audio_mode}")
            return None
        return _submit_and_poll_external_audio(queue_id, prompt, params, audio_mode)


def _generate_speech_local(queue_id: int, prompt: str, params: dict) -> Optional[str]:
    """Generate speech using local XTTS v2."""
    from .tts_service import generate_speech

    _update_queue_status(queue_id, "processing")

    result = generate_speech(
        text=prompt,
        voice_id=params.get("voice_id", "preset_female_1"),
        speed=params.get("speed", 1.0),
        language=params.get("language", "en"),
    )

    if "error" in result:
        _update_queue_status(queue_id, "failed", error=result["error"])
        return None

    file_path = result["file_path"]
    _update_queue_status(queue_id, "completed", output_path=file_path)
    return file_path


def _submit_and_poll_external_audio(
    queue_id: int, prompt: str, params: dict, audio_mode: str
) -> Optional[str]:
    """Submit to external audio provider and poll for completion."""
    provider = params.get("provider", "auto")

    if provider == "auto":
        # Pick first available provider for this audio mode
        cap_key = f"audio_{audio_mode}"
        providers = get_audio_providers(audio_mode)
        if not providers:
            _update_queue_status(
                queue_id, "failed", error=f"No external providers available for {audio_mode}"
            )
            return None
        provider = providers[0]["provider_key"]

    _update_queue_status(queue_id, "dispatched")

    # Store provider info in params for polling
    from database import get_db_cursor
    import json

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_generation_queue
               SET params = params || %s
               WHERE id = %s""",
            (json.dumps({"external_provider": provider}), queue_id),
        )

    # Submit to external provider (stubbed)
    try:
        job_id = _call_external_audio(provider, "submit", {
            "prompt": prompt,
            "audio_mode": audio_mode,
            "duration": params.get("duration", 5),
        })

        if not job_id:
            _update_queue_status(queue_id, "failed", error=f"External submit to {provider} failed")
            return None

        # Store job ID
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE media_generation_queue
                   SET params = params || %s
                   WHERE id = %s""",
                (json.dumps({"external_job_id": job_id}), queue_id),
            )

        # Poll for completion (up to 5 min)
        import time as time_mod

        for _ in range(60):
            time_mod.sleep(5)
            status = _call_external_audio(provider, "poll", {"job_id": job_id})
            if status and status.get("status") == "completed":
                url = status.get("output_url")
                if url:
                    file_path = download_external_result(provider, url, queue_id)
                    if file_path:
                        _update_queue_status(queue_id, "completed", output_path=file_path)
                        return file_path
            elif status and status.get("status") == "failed":
                _update_queue_status(queue_id, "failed", error=status.get("error", "External failed"))
                return None

        _update_queue_status(queue_id, "failed", error=f"External {provider} timed out")
        return None
    except Exception as e:
        logger.error(f"External audio generation failed: {e}")
        _update_queue_status(queue_id, "failed", error=str(e))
        return None


def _call_external_audio(provider: str, action: str, params: dict):
    """Stub for external audio provider API calls.

    Returns job_id string for 'submit', status dict for 'poll'.
    Real implementations will be added when API keys are configured.
    """
    logger.info(f"External audio stub: {provider}/{action} — params={params}")
    # Stub: return None to indicate no real provider configured
    return None


def _update_queue_status(queue_id: int, status: str, output_path: str = None, error: str = None):
    """Update queue entry status."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            if output_path:
                cur.execute(
                    """UPDATE media_generation_queue
                       SET status = %s, output_path = %s, completed_at = NOW()
                       WHERE id = %s""",
                    (status, output_path, queue_id),
                )
            elif error:
                cur.execute(
                    """UPDATE media_generation_queue
                       SET status = %s, error_message = %s, completed_at = NOW()
                       WHERE id = %s""",
                    (status, error, queue_id),
                )
            else:
                cur.execute(
                    "UPDATE media_generation_queue SET status = %s WHERE id = %s",
                    (status, queue_id),
                )
    except Exception as e:
        logger.error(f"Failed to update queue status: {e}")


def get_audio_providers(audio_mode: str = "sfx") -> list:
    """Return available external audio providers for a given mode.

    Args:
        audio_mode: 'sfx' or 'music'

    Returns:
        List of provider dicts with provider_key, display_name, capabilities, cost_per_unit
    """
    cap_key = f"audio_{audio_mode}"
    providers = []
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT provider_key, display_name, capabilities, cost_per_unit
                   FROM contractor_providers
                   WHERE is_active = true
                     AND capabilities ? %s
                   ORDER BY cost_per_unit ASC NULLS LAST""",
                (cap_key,),
            )
            for row in cur.fetchall():
                providers.append(dict(row))
    except Exception as e:
        logger.warning(f"Failed to query audio providers: {e}")
    return providers
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('platform_v2/tools/media_studio/services/generation_service.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): add audio generation flow with TTS + external stubs"
```

---

### Task 4: Audio API Routes

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

Adds 4 audio endpoints. Insert them after the video routes section (after line ~360) and before the Environments section (line ~362).

- [ ] **Step 1: Add audio routes before the Environments section**

Before the `# ─── Environments` comment block, add:

```python
# ─── Audio ────────────────────────────────────────────────────────────


@media_studio_bp.route("/api/audio/generate", methods=["POST"])
@login_required
def api_generate_audio():
    """Submit an audio generation request (speech/sfx/music)."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    audio_mode = data.get("audio_mode", "speech")
    if audio_mode not in ("speech", "sfx", "music"):
        return jsonify({"error": "audio_mode must be speech, sfx, or music"}), 400

    # Validate mode-specific required fields
    if audio_mode == "speech" and not data.get("voice_id"):
        return jsonify({"error": "voice_id is required for speech mode"}), 400

    params = {}
    for k in ("audio_mode", "voice_id", "speed", "language", "duration",
              "provider", "seed"):
        if k in data:
            params[k] = data[k]

    result = submit_generation(
        user_id=current_user.id,
        media_type="audio",
        prompt=prompt,
        negative_prompt="",
        params=params,
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500
    return jsonify(result), 201


@media_studio_bp.route("/api/audio/voices")
@login_required
def api_audio_voices():
    """Get available TTS voices (presets + custom agent voices)."""
    from .services.tts_service import list_voices

    return jsonify({"voices": list_voices()})


@media_studio_bp.route("/api/audio/voices/upload", methods=["POST"])
@login_required
def api_upload_voice_sample():
    """Upload a custom voice sample for an agent."""
    from .services.tts_service import save_voice_sample

    agent_name = request.form.get("agent_name", "").strip()
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400

    if "audio" not in request.files:
        return jsonify({"error": "audio file is required"}), 400

    audio_file = request.files["audio"]
    if not audio_file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(audio_file.filename)[1].lower()
    if ext not in (".wav", ".mp3"):
        return jsonify({"error": "Only .wav and .mp3 files accepted"}), 400

    result = save_voice_sample(agent_name, audio_file.read(), ext)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result), 201


@media_studio_bp.route("/api/audio/providers")
@login_required
def api_audio_providers():
    """Get available external audio providers for a mode."""
    from .services.generation_service import get_audio_providers

    mode = request.args.get("mode", "sfx")
    return jsonify({"providers": get_audio_providers(mode)})
```

- [ ] **Step 2: Add os import if missing**

Check if `import os` is at top of routes.py. If not, add it.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('platform_v2/tools/media_studio/routes.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add audio generation and voices API routes"
```

---

## Chunk 2: Frontend — UI + CSS

### Task 5: Audio Mode UI — HTML + JS

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

Enables the Audio button, adds `msAudioControls` div with sub-mode buttons and mode-specific controls, adds JS functions, and updates `submitGeneration()` and `selectMediaType()`.

- [ ] **Step 1: Enable the Audio button (line ~134)**

Find:
```html
                    <button class="ms-type-btn disabled" data-type="audio">
                        <i data-lucide="music" style="width:16px;height:16px;"></i>
                        <span data-i18n="media_studio.audio">Audio</span>
                        <span class="ms-coming-soon" data-i18n="media_studio.coming_soon">Coming Soon</span>
                    </button>
```

Replace with:
```html
                    <button class="ms-type-btn" data-type="audio" onclick="selectMediaType('audio')">
                        <i data-lucide="music" style="width:16px;height:16px;"></i>
                        <span data-i18n="media_studio.audio">Audio</span>
                    </button>
```

- [ ] **Step 2: Add audio controls div after msVideoControls (after line ~278)**

After the closing `</div>` of `msVideoControls`, add:

```html
            <!-- Audio Controls (hidden when media_type != audio) -->
            <div id="msAudioControls" class="ms-audio-controls" style="display:none;">
                <div class="ms-section-header">Audio Settings</div>
                <div class="ms-form-group">
                    <label class="ms-form-label">Mode</label>
                    <div class="ms-audio-mode-btns">
                        <button class="ms-audio-mode-btn active" data-mode="speech" onclick="selectAudioMode('speech')">Speech</button>
                        <button class="ms-audio-mode-btn" data-mode="sfx" onclick="selectAudioMode('sfx')">Sound FX</button>
                        <button class="ms-audio-mode-btn" data-mode="music" onclick="selectAudioMode('music')">Music</button>
                    </div>
                </div>

                <!-- Speech-specific controls -->
                <div id="msAudioSpeechControls" class="ms-audio-mode-controls">
                    <div class="ms-form-group">
                        <label class="ms-form-label">Voice</label>
                        <select id="msVoicePicker" class="ms-select">
                            <option value="preset_female_1">Female 1 (Default)</option>
                        </select>
                    </div>
                    <div class="ms-form-group">
                        <label class="ms-form-label">Speed</label>
                        <input type="range" id="msAudioSpeed" class="ms-slider" min="0.5" max="2.0" step="0.1" value="1.0">
                        <span id="msAudioSpeedVal" class="ms-slider-val">1.0x</span>
                    </div>
                </div>

                <!-- SFX-specific controls -->
                <div id="msAudioSfxControls" class="ms-audio-mode-controls" style="display:none;">
                    <div class="ms-form-group">
                        <label class="ms-form-label">Duration</label>
                        <div class="ms-duration-btns">
                            <button class="ms-duration-btn active" data-dur="1" onclick="setAudioDuration(1)">1s</button>
                            <button class="ms-duration-btn" data-dur="3" onclick="setAudioDuration(3)">3s</button>
                            <button class="ms-duration-btn" data-dur="5" onclick="setAudioDuration(5)">5s</button>
                            <button class="ms-duration-btn" data-dur="10" onclick="setAudioDuration(10)">10s</button>
                        </div>
                    </div>
                    <div class="ms-form-group">
                        <label class="ms-form-label">Provider</label>
                        <select id="msAudioSfxProvider" class="ms-select">
                            <option value="auto">Auto</option>
                        </select>
                    </div>
                </div>

                <!-- Music-specific controls -->
                <div id="msAudioMusicControls" class="ms-audio-mode-controls" style="display:none;">
                    <div class="ms-form-group">
                        <label class="ms-form-label">Duration</label>
                        <div class="ms-duration-btns">
                            <button class="ms-duration-btn active" data-dur="10" onclick="setAudioDuration(10)">10s</button>
                            <button class="ms-duration-btn" data-dur="30" onclick="setAudioDuration(30)">30s</button>
                            <button class="ms-duration-btn" data-dur="60" onclick="setAudioDuration(60)">60s</button>
                        </div>
                    </div>
                    <div class="ms-form-group">
                        <label class="ms-form-label">Provider</label>
                        <select id="msAudioMusicProvider" class="ms-select">
                            <option value="auto">Auto</option>
                        </select>
                    </div>
                </div>
            </div>
```

- [ ] **Step 3: Update selectMediaType() to handle audio (line ~738)**

Find the existing `window.selectMediaType` function and replace it entirely:

```javascript
    window.selectMediaType = function(type) {
        _currentMediaType = type;
        var btns = document.querySelectorAll(".ms-type-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", btns[i].dataset.type === type);
        }
        var vc = document.getElementById("msVideoControls");
        if (vc) vc.style.display = type === "video" ? "" : "none";
        var ac = document.getElementById("msAudioControls");
        if (ac) ac.style.display = type === "audio" ? "" : "none";
        // Reset audio sub-mode to speech when switching to audio
        if (type === "audio") selectAudioMode("speech");
        // Update generate button text
        var genBtn = document.getElementById("msGenerateBtn");
        if (genBtn) {
            _clearChildren(genBtn);
            var spinner = document.createElement("div");
            spinner.className = "ms-spinner";
            genBtn.appendChild(spinner);
            var icon = document.createElement("i");
            var iconName = type === "video" ? "film" : type === "audio" ? "music" : "zap";
            icon.setAttribute("data-lucide", iconName);
            icon.style.cssText = "width:18px;height:18px;";
            genBtn.appendChild(icon);
            var label = type === "video" ? " Generate Video" : type === "audio" ? " Generate Audio" : " Generate";
            genBtn.appendChild(document.createTextNode(label));
            if (window.lucide) lucide.createIcons();
        }
    };
```

- [ ] **Step 4: Add audio JS functions after loadVideoProviders (after line ~815)**

After the `loadVideoProviders` function and before `submitGeneration`, add:

```javascript
    /* ── Audio Controls ──────────────────────────── */

    var _audioMode = "speech";
    var _audioDuration = 5;

    window.selectAudioMode = function(mode) {
        _audioMode = mode;
        var btns = document.querySelectorAll(".ms-audio-mode-btn");
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle("active", btns[i].dataset.mode === mode);
        }
        // Show/hide mode-specific controls
        var speech = document.getElementById("msAudioSpeechControls");
        var sfx = document.getElementById("msAudioSfxControls");
        var music = document.getElementById("msAudioMusicControls");
        if (speech) speech.style.display = mode === "speech" ? "" : "none";
        if (sfx) sfx.style.display = mode === "sfx" ? "" : "none";
        if (music) music.style.display = mode === "music" ? "" : "none";
        // Set default duration per mode
        if (mode === "sfx") _audioDuration = 1;
        else if (mode === "music") _audioDuration = 10;
        else _audioDuration = 5;
    };

    window.setAudioDuration = function(dur) {
        _audioDuration = dur;
        // Update active state within the current mode's duration buttons
        var container = _audioMode === "music" ? document.getElementById("msAudioMusicControls")
                                                : document.getElementById("msAudioSfxControls");
        if (container) {
            var btns = container.querySelectorAll(".ms-duration-btn");
            for (var i = 0; i < btns.length; i++) {
                btns[i].classList.toggle("active", parseInt(btns[i].dataset.dur) === dur);
            }
        }
    };

    // Speed slider live update
    (function() {
        var slider = document.getElementById("msAudioSpeed");
        var valSpan = document.getElementById("msAudioSpeedVal");
        if (slider && valSpan) {
            slider.addEventListener("input", function() {
                valSpan.textContent = this.value + "x";
            });
        }
    })();

    // Load voices into picker
    window.loadAudioVoices = function() {
        api("GET", "/api/audio/voices").then(function(data) {
            var sel = document.getElementById("msVoicePicker");
            if (!sel) return;
            // Clear existing options except first
            while (sel.options.length > 1) sel.remove(1);
            (data.voices || []).forEach(function(v) {
                // Skip the first preset (already in HTML)
                if (v.id === "preset_female_1") return;
                var opt = document.createElement("option");
                opt.value = v.id;
                opt.textContent = v.name;
                if (v.type === "agent") opt.textContent += " 🎤";
                sel.appendChild(opt);
            });
        }).catch(function(e) {
            console.warn("Failed to load voices:", e);
        });
    };

    // Load audio providers into dropdowns
    window.loadAudioProviders = function() {
        ["sfx", "music"].forEach(function(mode) {
            api("GET", "/api/audio/providers?mode=" + mode).then(function(data) {
                var selId = mode === "sfx" ? "msAudioSfxProvider" : "msAudioMusicProvider";
                var sel = document.getElementById(selId);
                if (!sel) return;
                // Clear existing options except "Auto"
                while (sel.options.length > 1) sel.remove(1);
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
                console.warn("Failed to load audio providers for " + mode + ":", e);
            });
        });
    };
```

- [ ] **Step 5: Update submitGeneration() to handle audio mode (line ~820)**

Replace the entire `window.submitGeneration` function with:

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
        } else if (_currentMediaType === "audio") {
            url = "/api/audio/generate";
            payload = {
                prompt: prompt,
                audio_mode: _audioMode,
                seed: parseInt(document.getElementById("msSeed").value, 10),
            };
            if (_audioMode === "speech") {
                payload.voice_id = document.getElementById("msVoicePicker").value || "preset_female_1";
                payload.speed = parseFloat(document.getElementById("msAudioSpeed").value || "1.0");
            } else if (_audioMode === "sfx") {
                payload.duration = _audioDuration;
                payload.provider = document.getElementById("msAudioSfxProvider").value || "auto";
            } else if (_audioMode === "music") {
                payload.duration = _audioDuration;
                payload.provider = document.getElementById("msAudioMusicProvider").value || "auto";
            }
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

- [ ] **Step 6: Update switchMsTab to load audio data (line ~521)**

Find:
```javascript
        else if (tabId === "generate") { loadModels(); loadVideoProviders(); }
```

Replace with:
```javascript
        else if (tabId === "generate") { loadModels(); loadVideoProviders(); loadAudioVoices(); loadAudioProviders(); }
```

- [ ] **Step 7: Remove the audio guard in selectMediaType**

The old `selectMediaType` had `if (type === "audio") return; // Layer 4`. The replacement in Step 3 already removes this guard. Verify no other reference remains.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): enable audio mode UI with speech/SFX/music sub-modes"
```

---

### Task 6: Audio CSS — S18

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css`

Adds S18 Audio Controls section after S17. Reuses duration button and slider patterns from S17.

- [ ] **Step 1: Append S18 at end of CSS file (after line ~1652)**

```css
/* ═══════════════════════════════════════════════════════════════
   S18 · AUDIO CONTROLS
   ═══════════════════════════════════════════════════════════════ */

.ms-audio-controls {
    margin-top: 1rem;
    padding: 1rem;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid rgba(138, 92, 246, 0.15);
    border-radius: 8px;
}

.ms-audio-mode-btns {
    display: flex;
    gap: 0.5rem;
}

.ms-audio-mode-btn {
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

.ms-audio-mode-btn:hover {
    border-color: rgba(138, 92, 246, 0.6);
    color: white;
}

.ms-audio-mode-btn.active {
    background: rgba(138, 92, 246, 0.3);
    border-color: #8b5cf6;
    color: #c4b5fd;
}

.ms-audio-mode-controls {
    margin-top: 0.75rem;
}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add audio controls CSS (S18)"
```

---

### Task 7: Integration Test + Deploy

**Files:**
- No new files — testing existing endpoints

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

Wait 4 seconds for startup.

- [ ] **Step 2: Test audio endpoints**

```python
import requests
s = requests.Session()
s.post("http://192.168.1.200:3000/login",
       data={"username": "admin", "password": "Kyt$13ran2025"},
       allow_redirects=False)

# Test audio voices endpoint
r1 = s.get("http://192.168.1.200:3000/tools/media-studio/api/audio/voices",
           allow_redirects=False)
print(f"Audio voices: {r1.status_code}, {r1.text[:200]}")

# Test audio providers endpoint
r2 = s.get("http://192.168.1.200:3000/tools/media-studio/api/audio/providers?mode=sfx",
           allow_redirects=False)
print(f"Audio providers: {r2.status_code}, {r2.text[:200]}")

# Verify existing endpoints still work
r3 = s.get("http://192.168.1.200:3000/tools/media-studio/api/dashboard",
           allow_redirects=False)
print(f"Dashboard: {r3.status_code}")

r4 = s.get("http://192.168.1.200:3000/tools/media-studio/api/video/providers",
           allow_redirects=False)
print(f"Video providers: {r4.status_code}")

# Verify page loads with audio controls
r5 = s.get("http://192.168.1.200:3000/tools/media-studio/",
           allow_redirects=False)
print(f"Page load: {r5.status_code}")
print(f"Has audio controls: {'msAudioControls' in r5.text}")
print(f"Has audio JS: {'_audioMode' in r5.text}")
```

Expected: Audio voices returns 200 with `{"voices": [...]}` (at least 4 presets). Audio providers returns 200 with `{"providers": []}` (stubbed providers are is_active=false). Dashboard 200. Video providers 200. Page loads 200 with audio controls present.

- [ ] **Step 3: Verify UI in browser**

Open http://192.168.1.200:3000/tools/media-studio in a browser. Check:
- Generate tab shows Image/Video/Audio type buttons
- Audio button is clickable (not greyed out)
- Clicking "Audio" shows sub-mode buttons: Speech / Sound FX / Music
- Speech mode shows voice picker + speed slider
- Clicking "Sound FX" shows duration (1/3/5/10s) + provider dropdown
- Clicking "Music" shows duration (10/30/60s) + provider dropdown
- Generate button says "Generate Audio"
- Switching back to Image/Video hides audio controls
- Video controls still work correctly

- [ ] **Step 4: Push to remote**

```bash
git push origin main
```

- [ ] **Step 5: Update Dev HQ**

```python
mcp__archie__update_project_understanding(
    project_id=129,
    understanding_level=95,
    emotional_association="confident",
    key_insights=[
        "Layer 4 complete: TTS service (XTTS v2), audio gen flow, external audio provider stubs",
        "Three audio sub-modes: Speech (local XTTS), SFX (external), Music (external)",
        "Voice management: preset voices + custom agent voice cloning via 6s WAV upload",
        "VRAM swap: Ollama unload before TTS, torch.cuda.empty_cache after",
        "All 4 media layers complete: Image, Portraits, Video, Audio",
    ],
    notes="All Media Studio layers complete. Module is feature-complete for v1.",
)
```
