"""Thin cockpit->platform voice proxy (COO Cockpit Slice 3).

synthesize (TTS) / transcribe (STT) forward to the platform's @_require_internal_key
voice endpoints with the Bearer key over the internal Docker network
(PLATFORM_URL=http://archie_platform:3000 — never a public hostname). Both are
fail-SOFT: any error -> a clean fallback ({success:False}/{text:""}) so the cockpit
degrades to text, never hangs or errors loudly.
"""

import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"}


def synthesize(text, user_id):
    try:
        r = requests.post(
            f"{_base()}/api/internal/voice/synthesize",
            json={"text": text, "user_id": user_id},
            headers=_headers(),
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200:
            return data
        return {"success": False, "error": data.get("error") or f"HTTP {r.status_code}"}
    except Exception as exc:  # fail-soft: no audio, cockpit falls back to text
        logger.warning("voice synthesize proxy failed: %s", exc)
        return {"success": False, "error": str(exc)}


def transcribe(audio_bytes, mime=None):
    try:
        r = requests.post(
            f"{_base()}/api/internal/voice/transcribe",
            json={"audio_b64": base64.b64encode(audio_bytes).decode(), "mime": mime},
            headers=_headers(),
            timeout=60,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200:
            return {"text": data.get("text", "")}
        return {"text": "", "error": data.get("error") or f"HTTP {r.status_code}"}
    except Exception as exc:  # fail-soft: mic yields no transcript, owner types
        logger.warning("voice transcribe proxy failed: %s", exc)
        return {"text": "", "error": str(exc)}
