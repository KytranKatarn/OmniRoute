"""Sovereign GPU TTS sidecar for the COO Cockpit (P2 — voice on a fleet GPU node).

Runs A.R.C.H.I.E.'s Kokoro voice (the af_heart+af_jessica blend) on a node GPU
(e.g. Starship-246, RTX 3070) so cockpit synthesis is instant and never competes
with the hub's CPU-bound LLM inference. The platform (services/voice_service.py)
calls this FIRST and falls back to its in-process hub Kokoro when the node is
resting/offline. The pipeline is preloaded + warmed on the GPU at worker boot
(owner directive: always-loaded voice). fail-soft — never a 500.
"""

import base64
import io
import logging
import os

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kokoro")
app = Flask(__name__)

# A.R.C.H.I.E.'s canonical voice. Kokoro blends the listed voices equally; any
# ":weight" annotations are accepted but ignored (matches the hub KokoroEngine).
DEFAULT_BLEND = os.getenv("ARCHIE_VOICE_BLEND", "af_heart,af_jessica")
LANG = os.getenv("KOKORO_LANG", "a")  # 'a' = American English

# Mirror of voice_synthesis.EMOTION_VOICE_MAP — Kokoro honours speed only.
EMOTION_SPEED = {
    "excited": 1.10, "curious": 1.00, "empathetic": 0.90, "focused": 0.95,
    "playful": 1.05, "concerned": 0.88, "thoughtful": 0.92, "confident": 1.02,
    "gentle": 0.88, "neutral": 1.00,
}

_pipeline = None
_device = "cpu"


def _get_pipeline():
    global _pipeline, _device
    if _pipeline is None:
        import torch
        from kokoro import KPipeline

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("loading Kokoro KPipeline lang=%s device=%s", LANG, _device)
        try:
            _pipeline = KPipeline(lang_code=LANG, device=_device)
        except TypeError:
            # older kokoro without a device kwarg — load, then move the model
            _pipeline = KPipeline(lang_code=LANG)
            try:
                _pipeline.model.to(_device)
            except Exception:  # pragma: no cover
                pass
    return _pipeline


def _synthesize(text, blend=None, speed=1.0):
    """text -> WAV bytes (24 kHz), on the GPU when available. Her exact voice blend."""
    import numpy as np
    import soundfile as sf

    blend = blend or DEFAULT_BLEND
    # strip ":weight" annotations ("af_heart:90" -> "af_heart"); Kokoro blends equally
    voice = ",".join(v.split(":")[0].strip() for v in blend.split(",") if v.strip()) or "af_heart"
    pipeline = _get_pipeline()
    chunks = [audio for _gs, _ps, audio in pipeline(text, voice=voice, speed=speed)]
    if not chunks:
        raise RuntimeError("Kokoro produced no audio")
    full = np.concatenate(chunks)
    buf = io.BytesIO()
    sf.write(buf, full, 24000, format="WAV")
    return buf.getvalue()


@app.route("/health", methods=["GET"])
def health():
    # warm=True once the pipeline is resident (preloaded at boot by gunicorn.conf.py)
    return jsonify({"ok": True, "engine": "kokoro", "device": _device, "warm": _pipeline is not None})


@app.route("/synthesize", methods=["POST"])
def synthesize():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "no text"}), 400
    blend = data.get("voice_blend") or DEFAULT_BLEND
    speed = data.get("speed")
    if speed is None:
        speed = EMOTION_SPEED.get((data.get("emotion") or "neutral").lower(), 1.0)
    try:
        wav = _synthesize(text, blend=blend, speed=float(speed))
        return jsonify({
            "success": True,
            "audio_base64": base64.b64encode(wav).decode(),
            "sample_rate": 24000,
            "format": "wav",
            "engine": "kokoro",
            "device": _device,
        })
    except Exception as exc:  # fail-soft — the platform falls back to its in-process synth
        logger.warning("synthesize failed: %s", exc)
        return jsonify({"success": False, "engine": "kokoro", "error": str(exc)}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8092")))
