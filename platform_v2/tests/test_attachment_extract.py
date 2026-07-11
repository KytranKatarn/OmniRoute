"""Sovereign attachment extraction (COO Cockpit Slice 2).

The cockpit forwards uploaded bytes (base64) to a @_require_internal_key platform
endpoint that wraps the existing extract_text_from_file. These pin the pure
service (routing / cap / fail-soft) and the endpoint (auth / routing / oversize).
"""

import base64
import importlib


# ── pure service ──────────────────────────────────────────────────────────────


def test_extract_payload_routes_to_extract_text(monkeypatch):
    svc = importlib.import_module("services.attachment_extract_service")
    seen = {}
    monkeypatch.setattr(
        svc,
        "extract_text_from_file",
        lambda path, mime_type=None: seen.update(path=path, mime=mime_type) or ("hello world", False),
    )
    out = svc.extract_payload("notes.txt", b"hello world", "text/plain")
    assert out["text"] == "hello world"
    assert out["chars"] == 11
    assert out["ocr_used"] is False
    assert out["truncated"] is False
    assert seen["mime"] == "text/plain"


def test_extract_payload_caps_text(monkeypatch):
    svc = importlib.import_module("services.attachment_extract_service")
    monkeypatch.setattr(svc, "ATTACHMENT_TEXT_CAP", 5)
    monkeypatch.setattr(svc, "extract_text_from_file", lambda p, mime_type=None: ("abcdefghij", False))
    out = svc.extract_payload("big.txt", b"x", "text/plain")
    assert out["text"] == "abcde"
    assert out["truncated"] is True
    assert out["chars"] == 5


def test_extract_payload_ocr_flag(monkeypatch):
    svc = importlib.import_module("services.attachment_extract_service")
    monkeypatch.setattr(svc, "extract_text_from_file", lambda p, mime_type=None: ("scanned", True))
    out = svc.extract_payload("scan.png", b"x", "image/png")
    assert out["ocr_used"] is True


def test_extract_payload_failsoft_on_raise(monkeypatch):
    svc = importlib.import_module("services.attachment_extract_service")

    def boom(p, mime_type=None):
        raise RuntimeError("corrupt pdf")

    monkeypatch.setattr(svc, "extract_text_from_file", boom)
    out = svc.extract_payload("x.pdf", b"x", "application/pdf")
    assert out["text"] == ""
    assert out["chars"] == 0
    assert "error" in out


# ── internal endpoint ─────────────────────────────────────────────────────────


def test_internal_extract_requires_key(client):
    r = client.post("/api/internal/attachments/extract", json={})
    assert r.status_code == 401


def test_internal_extract_routes_to_service(client, monkeypatch):
    import services.attachment_extract_service as svc

    monkeypatch.setattr(
        svc,
        "extract_payload",
        lambda fn, raw, mime=None: {"text": "hi", "chars": 2, "ocr_used": False, "truncated": False},
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/attachments/extract",
        json={"filename": "a.txt", "content_b64": base64.b64encode(b"hi").decode(), "mime": "text/plain"},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    assert r.get_json()["text"] == "hi"


def test_internal_extract_rejects_oversize(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    big = base64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
    r = client.post(
        "/api/internal/attachments/extract",
        json={"filename": "big.bin", "content_b64": big},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 413


def test_internal_extract_bad_b64(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/attachments/extract",
        json={"filename": "a.txt", "content_b64": "!!!not-base64!!!="},
        headers={"Authorization": "Bearer k"},
    )
    # invalid base64 must not 500 — either 400 (reject) or a clean fail-soft 200
    assert r.status_code in (200, 400)
