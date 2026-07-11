"""Cockpit voice endpoints (COO Cockpit Slice 3).

TTS wraps the platform's Kokoro synthesize_for_agent (agent 2 = her canonical
af_heart voice); STT proxies to the sovereign archie_whisper sidecar. Both are
fail-SOFT (voice is optional polish). These pin the pure service + the two
@_require_internal_key endpoints.
"""

import base64
import importlib


# ── pure service: synthesize (Kokoro) ─────────────────────────────────────────


def test_synthesize_wraps_synth(monkeypatch):
    vs = importlib.import_module("services.voice_service")

    class _Synth:
        def get_archie_emotional_state(self, uid):
            return "warm"

        def synthesize_for_agent(self, text, agent_id, emotion=None, user_id=None):
            assert agent_id == 2  # her canonical voice profile
            return {"success": True, "audio_base64": "QUJD", "cached": False}

    monkeypatch.setattr(vs, "get_voice_synthesizer", lambda: _Synth())
    out = vs.synthesize("hello", user_id=2)
    assert out["success"] is True
    assert out["audio_base64"] == "QUJD"
    assert out["engine"] == "kokoro"


def test_synthesize_failsoft(monkeypatch):
    vs = importlib.import_module("services.voice_service")

    def boom():
        raise RuntimeError("kokoro down")

    monkeypatch.setattr(vs, "get_voice_synthesizer", boom)
    out = vs.synthesize("hi", user_id=2)
    assert out["success"] is False and "error" in out


# ── pure service: transcribe (whisper sidecar) ────────────────────────────────


def test_transcribe_proxies_to_whisper(monkeypatch):
    vs = importlib.import_module("services.voice_service")
    seen = {}

    class _R:
        status_code = 200
        content = b"x"

        def json(self):
            return {"text": "hello world"}

    monkeypatch.setattr(
        vs.requests, "post", lambda url, json=None, timeout=None: seen.update(url=url, body=json) or _R()
    )
    out = vs.transcribe(b"\x00\x01", "audio/webm")
    assert out["text"] == "hello world"
    assert seen["url"].endswith("/transcribe")
    assert base64.b64decode(seen["body"]["audio_b64"]) == b"\x00\x01"


def test_transcribe_failsoft(monkeypatch):
    vs = importlib.import_module("services.voice_service")

    def boom(*a, **k):
        raise RuntimeError("whisper down")

    monkeypatch.setattr(vs.requests, "post", boom)
    out = vs.transcribe(b"x", None)
    assert out["text"] == "" and "error" in out


# ── internal endpoints ────────────────────────────────────────────────────────


def test_internal_synthesize_requires_key(client):
    assert client.post("/api/internal/voice/synthesize", json={}).status_code == 401


def test_internal_transcribe_requires_key(client):
    assert client.post("/api/internal/voice/transcribe", json={}).status_code == 401


def test_internal_synthesize_routes(client, monkeypatch):
    import services.voice_service as vs

    monkeypatch.setattr(
        vs,
        "synthesize",
        lambda text, user_id=2, emotion=None: {"success": True, "audio_base64": "QUJD", "engine": "kokoro"},
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/voice/synthesize", json={"text": "hi"}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["audio_base64"] == "QUJD"


def test_internal_synthesize_empty_text_400(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/voice/synthesize", json={"text": "  "}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 400


def test_internal_transcribe_routes(client, monkeypatch):
    import services.voice_service as vs

    monkeypatch.setattr(vs, "transcribe", lambda raw, mime=None: {"text": "hello"})
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/voice/transcribe",
        json={"audio_b64": base64.b64encode(b"x").decode()},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200 and r.get_json()["text"] == "hello"
