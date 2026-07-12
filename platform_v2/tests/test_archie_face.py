"""A.R.C.H.I.E.'s face — portrait service + internal endpoint (COO Cockpit Slice 4).

Agent 2's canonical portrait is read from disk and served base64 to the cockpit
avatar behind @_require_internal_key. Fail-soft (missing file -> ok:false ->
frontend falls back to a monogram)."""

import base64
import importlib


def test_get_portrait_reads_file(monkeypatch, tmp_path):
    svc = importlib.import_module("services.archie_face_service")
    p = tmp_path / "arch.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nDATA")
    monkeypatch.setattr(svc, "_portrait_path", lambda: str(p))
    out = svc.get_portrait()
    assert out["ok"] is True
    assert base64.b64decode(out["image_b64"]) == b"\x89PNG\r\n\x1a\nDATA"
    assert out["mime"] == "image/png"


def test_get_portrait_failsoft_when_missing(monkeypatch):
    svc = importlib.import_module("services.archie_face_service")
    monkeypatch.setattr(svc, "_portrait_path", lambda: "/nope/missing.png")
    out = svc.get_portrait()
    assert out["ok"] is False


def test_internal_portrait_requires_key(client):
    # GET-only + key-gated. Wrong method must not serve the portrait (this app's
    # global handler maps a 405 -> 500, so assert "rejected", not an exact code).
    assert client.post("/api/internal/archie/portrait").status_code != 200
    assert client.get("/api/internal/archie/portrait").status_code == 401


def test_internal_portrait_routes(client, monkeypatch):
    import services.archie_face_service as svc

    monkeypatch.setattr(svc, "get_portrait", lambda: {"ok": True, "image_b64": "QUJD", "mime": "image/png"})
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.get("/api/internal/archie/portrait", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["image_b64"] == "QUJD"
