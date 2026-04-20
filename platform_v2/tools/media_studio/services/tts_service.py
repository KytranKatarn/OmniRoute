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
_PLATFORM_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    """Placeholder — the original implementation passed ``model`` +
    ``keep_alive`` kwargs to ``dispatch()``, but the canonical
    signature never accepted them, so this call was a silent no-op
    in production. Proper VRAM management belongs inside the
    dispatcher's ``_vram_swap_for_comfyui`` / ``_vram_swap_for_vision``
    paths. Kept as a named hook in case we wire a real unload later.
    See follow-up task #2129.
    """
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
        output_path = os.path.join(MEDIA_ROOT, "tmp", f"tts_{int(time.time())}_{os.getpid()}.wav")

    # Resolve voice: preset or custom sample file
    speaker_wav = None
    if voice_id.startswith("preset_"):
        preset_file = os.path.join(PRESET_DIR, f"{voice_id}.wav")
        if os.path.exists(preset_file):
            speaker_wav = preset_file
    elif voice_id.startswith("agent_"):
        agent_file = os.path.join(VOICES_DIR, f"{voice_id}.wav")
        if os.path.exists(agent_file):
            speaker_wav = agent_file
    else:
        safe_name = os.path.basename(voice_id)
        candidate = os.path.join(VOICES_DIR, safe_name)
        if os.path.exists(candidate):
            speaker_wav = candidate

    try:
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
            model.tts_to_file(
                text=text,
                file_path=output_path,
                language=language,
                speed=speed,
            )

        _unload_model()
        return {"file_path": output_path}
    except Exception as e:
        _unload_model()
        logger.error(f"TTS generation failed: {e}")
        return {"error": f"TTS generation failed: {str(e)}"}


def list_voices() -> List[Dict]:
    """Return all available voices (presets + custom agent voices)."""
    voices = list(PRESET_VOICES)

    # Scan for custom voice samples on disk
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

        # Update agents table — single-writer path via agent_service
        # so the agents table only has one canonical mutation surface
        # (Project #241 Track C.1).
        try:
            from services import agent_service

            agent = agent_service.get_agent_by_name(safe_name)
            if agent:
                agent_service.update_agent(agent["id"], voice_sample=dest)
            else:
                logger.warning(f"Voice sample saved but no agent named {safe_name!r} to link it to")
        except Exception as e:
            logger.warning(f"Failed to update agent voice_sample: {e}")

        return {"path": dest}
    except Exception as e:
        logger.error(f"Failed to save voice sample: {e}")
        return {"error": f"Failed to save voice sample: {str(e)}"}
