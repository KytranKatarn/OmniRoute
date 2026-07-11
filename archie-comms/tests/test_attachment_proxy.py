"""COO Cockpit Slice 2 — comms->platform attachment extraction proxy.

Base64-forwards the in-memory bytes to the platform @_require_internal_key extract
endpoint with the Bearer key. Fail-SOFT: any transport/non-200 result returns
{"ok": False, "error": ...} so the chat message still sends without the text.
"""

import base64

import services.attachment_proxy as ap


class _Resp:
    def __init__(self, code, payload, content=b"x"):
        self.status_code = code
        self._p = payload
        self.content = content

    def json(self):
        return self._p


def test_extract_posts_b64_and_key(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, auth=(headers or {}).get("Authorization"))
        return _Resp(200, {"text": "hi", "chars": 2, "ocr_used": False, "truncated": False})

    monkeypatch.setattr(ap.requests, "post", fake_post)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ap.extract("a.txt", b"hi", "text/plain")
    assert out["ok"] is True and out["text"] == "hi"
    assert seen["url"].endswith("/api/internal/attachments/extract")
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["filename"] == "a.txt" and seen["body"]["mime"] == "text/plain"
    assert base64.b64decode(seen["body"]["content_b64"]) == b"hi"


def test_extract_failsoft_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("platform down")

    monkeypatch.setattr(ap.requests, "post", boom)
    out = ap.extract("a.txt", b"hi", "text/plain")
    assert out["ok"] is False and "error" in out


def test_extract_failsoft_on_non_200(monkeypatch):
    monkeypatch.setattr(ap.requests, "post", lambda *a, **k: _Resp(413, {"error": "file too large"}))
    out = ap.extract("big.bin", b"x", None)
    assert out["ok"] is False and "error" in out


# ── attachment block formatter (rides the DHQ prompt) ─────────────────────────


def test_format_attachment_block():
    b = ap.format_attachment_block("report.pdf", "some text", False, 9)
    assert b.startswith("\n\n[Attachment: report.pdf (9 chars, ocr=false)]\n")
    assert b.endswith("some text\n")


def test_format_attachment_block_ocr_true():
    b = ap.format_attachment_block("scan.png", "ocr text", True, 8)
    assert "ocr=true" in b
    assert "scan.png" in b
