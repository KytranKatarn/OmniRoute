"""Sovereign STT sidecar (COO Cockpit Slice 3). faster-whisper 'base', CPU int8.

Audio never leaves the cluster. The model is preloaded at worker boot by
gunicorn.conf.py (owner directive: always-loaded/warm voice) and kept resident,
so the first transcription is instant. _get_model() also lazy-loads as a fallback.
"""

import base64
import logging
import os
import tempfile

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whisper")
app = Flask(__name__)

MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        logger.info("loading faster-whisper %s (cpu/int8)", MODEL_NAME)
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def _transcribe_file(path):
    segments, _info = _get_model().transcribe(path, language="en", vad_filter=True)
    return "".join(seg.text for seg in segments).strip()


@app.route("/health", methods=["GET"])
def health():
    # warm=True once the model is resident (preloaded at boot by gunicorn.conf.py)
    return jsonify({"ok": True, "model": MODEL_NAME, "warm": _model is not None})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json(silent=True) or {}
    b64 = data.get("audio_b64")
    if not b64:
        return jsonify({"error": "no audio_b64"}), 400
    suffix = ".webm" if "webm" in (data.get("mime") or "") else ".wav"
    path = None
    try:
        raw = base64.b64decode(b64)
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        return jsonify({"text": _transcribe_file(path)})
    except Exception as exc:  # fail-soft to the caller — never a 500
        logger.warning("transcribe failed: %s", exc)
        return jsonify({"text": "", "error": str(exc)}), 200
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8090")))
