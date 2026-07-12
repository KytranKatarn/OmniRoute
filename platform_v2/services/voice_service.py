"""Cockpit voice (COO Cockpit Slice 3).

TTS via Kokoro — synthesize_for_agent(agent_id=2) loads A.R.C.H.I.E.'s canonical
voice profile (af_heart blended with af_jessica, warmth 0.80) + her live emotional
state, so she sounds like herself, not a generic TTS. STT via the sovereign
archie_whisper sidecar (audio never leaves the cluster). Both fail-SOFT — voice is
optional polish, never a hard error.
"""

import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)

ARCHIE_AGENT_ID = 2

try:  # module-level so tests can monkeypatch it; guarded so import never breaks the module
    from ai_bridge.voice_synthesis import get_voice_synthesizer
except Exception:  # pragma: no cover
    get_voice_synthesizer = None


def _whisper_url():
    return os.getenv("WHISPER_URL", "http://archie_whisper:8090").rstrip("/")


def _kokoro_node_url():
    # Opt-in: when set (e.g. http://100.64.0.3:8092), a fleet GPU node synthesizes
    # her voice off the CPU-bound hub. Unset (default) => in-process hub Kokoro only,
    # so behaviour is unchanged until a live node is wired in.
    return os.getenv("KOKORO_NODE_URL", "").rstrip("/")


def _resolve_emotion(user_id, emotion):
    if emotion:
        return emotion
    if get_voice_synthesizer is not None:
        try:
            return get_voice_synthesizer().get_archie_emotional_state(user_id)
        except Exception:  # her mood is optional flavour, never a hard dependency
            pass
    return "neutral"


def _synthesize_via_node(text, emotion):
    """Try the GPU node TTS sidecar. Returns a result dict on success, else None
    (node resting/offline/slow) so the caller falls back to the in-process synth."""
    url = _kokoro_node_url()
    if not url:
        return None
    try:
        r = requests.post(
            f"{url}/synthesize",
            json={"text": text, "emotion": emotion, "voice_blend": "af_heart,af_jessica"},
            timeout=float(os.getenv("KOKORO_NODE_TIMEOUT", "12")),
        )
        if r.status_code == 200:
            body = r.json() or {}
            if body.get("success") and body.get("audio_base64"):
                return {
                    "success": True,
                    "audio_base64": body["audio_base64"],
                    "cached": False,
                    "engine": "kokoro",
                    "device": body.get("device"),
                    "via": "node",
                }
    except Exception as exc:  # node down/resting — fall back to the always-on hub
        logger.info("kokoro node unavailable, using hub: %s", exc)
    return None


def synthesize(text, user_id=2, emotion=None):
    """Text -> {success, audio_base64?, cached?, engine, via, error?} in her voice.

    Prefers the GPU node sidecar (fast, off the contended hub CPU) when
    KOKORO_NODE_URL is set + reachable; otherwise / on failure uses the in-process
    hub Kokoro (always-on). Fail-soft — the cockpit falls back to text on error.
    """
    emo = _resolve_emotion(user_id, emotion)

    via_node = _synthesize_via_node(text, emo)
    if via_node is not None:
        return via_node

    try:
        if get_voice_synthesizer is None:
            raise RuntimeError("voice synthesizer unavailable")
        synth = get_voice_synthesizer()
        res = synth.synthesize_for_agent(text, ARCHIE_AGENT_ID, emotion=emo, user_id=user_id)
        return {
            "success": bool(res.get("success")),
            "audio_base64": res.get("audio_base64"),
            "cached": res.get("cached"),
            "engine": "kokoro",
            "via": "hub",
            "error": res.get("error"),
        }
    except Exception as exc:  # fail-soft: no audio, the cockpit falls back to text
        logger.warning("voice synthesize failed: %s", exc)
        return {"success": False, "engine": "kokoro", "error": str(exc)}


def transcribe(audio_bytes, mime=None):
    """Audio bytes -> {text} via the sovereign whisper sidecar; fail-soft to text=''."""
    try:
        r = requests.post(
            f"{_whisper_url()}/transcribe",
            json={"audio_b64": base64.b64encode(audio_bytes).decode(), "mime": mime},
            timeout=60,
        )
        if r.status_code == 200 and r.content:
            return {"text": (r.json() or {}).get("text", "")}
        return {"text": "", "error": f"HTTP {r.status_code}"}
    except Exception as exc:  # fail-soft: mic yields no transcript, owner types
        logger.warning("voice transcribe failed: %s", exc)
        return {"text": "", "error": str(exc)}
