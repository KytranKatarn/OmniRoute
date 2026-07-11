"""COO Cockpit Slice 3 — comms->platform voice proxy.

synthesize/transcribe forward to the platform's @_require_internal_key voice
endpoints with the Bearer key; both fail-SOFT (voice is optional polish).
"""

import base64

import services.voice_proxy as vp


class _Resp:
    def __init__(self, code, payload, content=b"x"):
        self.status_code = code
        self._p = payload
        self.content = content

    def json(self):
        return self._p


def test_synthesize_posts_text_and_key(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, auth=(headers or {}).get("Authorization"))
        return _Resp(200, {"success": True, "audio_base64": "QUJD", "engine": "kokoro"})

    monkeypatch.setattr(vp.requests, "post", fake_post)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = vp.synthesize("hi", 2)
    assert out["success"] is True and out["audio_base64"] == "QUJD"
    assert seen["url"].endswith("/api/internal/voice/synthesize")
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["text"] == "hi" and seen["body"]["user_id"] == 2


def test_synthesize_failsoft(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("platform down")

    monkeypatch.setattr(vp.requests, "post", boom)
    out = vp.synthesize("hi", 2)
    assert out["success"] is False and "error" in out


def test_transcribe_posts_b64(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json)
        return _Resp(200, {"text": "hello"})

    monkeypatch.setattr(vp.requests, "post", fake_post)
    out = vp.transcribe(b"\x00\x01", "audio/webm")
    assert out["text"] == "hello"
    assert seen["url"].endswith("/api/internal/voice/transcribe")
    assert base64.b64decode(seen["body"]["audio_b64"]) == b"\x00\x01"


def test_transcribe_failsoft(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("whisper down")

    monkeypatch.setattr(vp.requests, "post", boom)
    out = vp.transcribe(b"x", None)
    assert out["text"] == "" and "error" in out


def test_synthesize_uses_long_timeout(monkeypatch):
    # A first synth that races the platform Kokoro warmup can cold-load (~40s);
    # the proxy timeout must be long enough not to abort it.
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["timeout"] = timeout
        return _Resp(200, {"success": True, "audio_base64": "QUJD"})

    monkeypatch.setattr(vp.requests, "post", fake_post)
    vp.synthesize("hi", 2)
    assert seen["timeout"] >= 90
