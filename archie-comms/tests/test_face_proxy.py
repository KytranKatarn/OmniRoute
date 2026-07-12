"""Avatar proxy (COO Cockpit Slice 4) — fetch her portrait from the platform, fail-soft."""

import base64

import services.face_proxy as fp


def test_portrait_returns_bytes_and_mime(monkeypatch):
    class _R:
        status_code = 200
        content = b"x"

        def json(self):
            return {"ok": True, "image_b64": base64.b64encode(b"\x89PNGdata").decode(), "mime": "image/png"}

    seen = {}
    monkeypatch.setattr(fp.requests, "get", lambda url, headers=None, timeout=None: seen.update(url=url) or _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    got = fp.portrait()
    assert got is not None
    raw, mime = got
    assert raw == b"\x89PNGdata" and mime == "image/png"
    assert seen["url"].endswith("/api/internal/archie/portrait")


def test_portrait_none_on_not_ok(monkeypatch):
    class _R:
        status_code = 200
        content = b"x"

        def json(self):
            return {"ok": False, "error": "no portrait"}

    monkeypatch.setattr(fp.requests, "get", lambda *a, **k: _R())
    assert fp.portrait() is None


def test_portrait_none_on_transport_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("platform down")

    monkeypatch.setattr(fp.requests, "get", boom)
    assert fp.portrait() is None
