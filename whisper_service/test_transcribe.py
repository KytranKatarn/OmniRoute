"""archie_whisper sidecar — route + plumbing (COO Cockpit Slice 3).

The faster-whisper model is stubbed so these run without installing it (flask is
enough). The real transcription is smoke-tested live in Task 6 (TTS clip -> STT).
"""

import base64
import importlib


def test_transcribe_decodes_and_calls_model(monkeypatch):
    app_mod = importlib.import_module("app")
    monkeypatch.setattr(app_mod, "_transcribe_file", lambda path: "hello there")
    c = app_mod.app.test_client()
    r = c.post("/transcribe", json={"audio_b64": base64.b64encode(b"RIFF....").decode(), "mime": "audio/wav"})
    assert r.status_code == 200
    assert r.get_json()["text"] == "hello there"


def test_transcribe_empty_is_400():
    app_mod = importlib.import_module("app")
    c = app_mod.app.test_client()
    assert c.post("/transcribe", json={}).status_code == 400


def test_transcribe_failsoft_on_model_error(monkeypatch):
    app_mod = importlib.import_module("app")

    def boom(path):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(app_mod, "_transcribe_file", boom)
    c = app_mod.app.test_client()
    r = c.post("/transcribe", json={"audio_b64": base64.b64encode(b"x").decode()})
    # fail-soft to the caller: 200 with empty text + error note (never a 500)
    assert r.status_code == 200
    assert r.get_json()["text"] == ""


def test_health_reports_warm_flag():
    app_mod = importlib.import_module("app")
    c = app_mod.app.test_client()
    body = c.get("/health").get_json()
    assert body["ok"] is True
    assert "warm" in body  # False until the model is preloaded at boot
