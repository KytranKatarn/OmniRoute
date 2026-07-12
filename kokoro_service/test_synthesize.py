"""Tests for the Kokoro GPU TTS sidecar — the pipeline is stubbed, so these run
without a model download or a GPU (Flask contract + fail-soft only)."""

import base64

import app as kokoro_app


def _client():
    kokoro_app.app.config["TESTING"] = True
    return kokoro_app.app.test_client()


def test_health_reports_warm_flag():
    r = _client().get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["engine"] == "kokoro"
    assert "warm" in body  # False until the pipeline is preloaded


def test_synthesize_requires_text():
    assert _client().post("/synthesize", json={}).status_code == 400


def test_synthesize_returns_wav_audio(monkeypatch):
    monkeypatch.setattr(kokoro_app, "_synthesize", lambda text, blend=None, speed=1.0: b"RIFFfakewav")
    r = _client().post("/synthesize", json={"text": "hello", "emotion": "confident"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert base64.b64decode(body["audio_base64"]) == b"RIFFfakewav"
    assert body["format"] == "wav" and body["sample_rate"] == 24000


def test_synthesize_maps_emotion_to_speed(monkeypatch):
    seen = {}

    def fake(text, blend=None, speed=1.0):
        seen["speed"] = speed
        seen["blend"] = blend
        return b"RIFF"

    monkeypatch.setattr(kokoro_app, "_synthesize", fake)
    _client().post("/synthesize", json={"text": "hi", "emotion": "empathetic"})
    assert seen["speed"] == 0.90  # EMOTION_SPEED['empathetic']
    assert seen["blend"] == "af_heart,af_jessica"


def test_synthesize_is_fail_soft(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gpu oom")

    monkeypatch.setattr(kokoro_app, "_synthesize", boom)
    r = _client().post("/synthesize", json={"text": "hello"})
    assert r.status_code == 200  # fail-soft, never a 500
    assert r.get_json()["success"] is False
