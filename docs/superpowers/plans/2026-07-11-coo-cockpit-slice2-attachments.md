# COO Cockpit — Slice 2: Attachments — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Kytran drops a file (PDF / docx / text / image) in the cockpit chat; A.R.C.H.I.E. reads its text and can discuss/act on it — extraction stays sovereign on the platform.

**Architecture:** Thin cockpit (unchanged principle). New platform `@_require_internal_key POST /api/internal/attachments/extract` wraps the existing `extract_text_from_file` (PDF/docx/text/image-OCR). Comms holds the bytes **in memory only**, forwards base64 to the platform, formats an `[Attachment: …]` block, and the frontend prepends that block to the outgoing message (rides the DHQ prompt — no change to `stream_send_message`).

**Tech Stack:** Python 3.11 / Flask (platform + comms), `requests`, base64, vanilla JS (comms LCARS frontend). Spec: `docs/superpowers/specs/2026-07-11-archie-coo-cockpit-design.md` §4.3.

## Global Constraints

- **Thin sovereign cockpit:** comms adds UI + a thin fail-soft proxy only. All extraction runs on the platform behind `@_require_internal_key`. No new secrets; bytes never persisted in comms (read-only rootfs + tmpfs anyway).
- **Owner-only:** cockpit routes are session-auth (`flask_session['user_id']`), like the Slice-1 routes.
- **Fail-SOFT (not fail-closed):** attachments are additive context. Oversize/unsupported → rejected with a message; extraction failure → the message still sends **without** the attachment text (+ a note). Contrast Slice-1 approvals (fail-CLOSED).
- **Caps (explicit, logged):** `ATTACHMENT_MAX_BYTES = 10*1024*1024` (10 MB upload), `ATTACHMENT_TEXT_CAP = 20000` chars; truncation sets `truncated=true` and is surfaced.
- **Text-only in this slice:** images extract via OCR (`ocr_used=true`); no vision/base64-image lane (deferred).
- **`extract_text_from_file(path, mime_type=None) -> (text, ocr_used)`** lives in `platform_v2/services/chronicle_attachment_service.py`; it **raises on a genuinely unreadable file** and returns `("", False)` for unknown/binary — the endpoint must try/except.
- **`_kind()` keys on mime first, then extension** — pass the mime AND give the temp file the original extension.
- **Testing harness** (from Slice 1):
  - Platform unit tests against a synced bundle: `tar -C <worktree> -cf - platform_v2 | docker exec -i archie_platform sh -c 'rm -rf /tmp/wt && mkdir -p /tmp/wt && tar -xf - -C /tmp/wt'` then `docker exec -w /tmp/wt/platform_v2 archie_platform sh -c 'PYTHONPATH=/app:$PYTHONPATH python3 -m pytest tests/<f> -v'`. App-loading tests set `ARCHIE_APP_PY=/tmp/wt/platform_v2/app.py` too.
  - Comms tests: host venv `/home/kytran/.claude/jobs/991c52c2/tmp/comms-venv/bin/python -m pytest`, cwd=`archie-comms`.
- **Never push to main; feature branch + PR; per-task commits.**

---

## File Structure

| File | Responsibility |
|---|---|
| `platform_v2/services/attachment_extract_service.py` | **new** — pure `extract_payload(filename, raw_bytes, mime) -> dict` (temp file + extract + cap + cleanup), no Flask |
| `platform_v2/app.py` | **modify** — `@_require_internal_key POST /api/internal/attachments/extract` |
| `platform_v2/tests/test_attachment_extract.py` | **new** — service + endpoint tests |
| `archie-comms/services/attachment_proxy.py` | **new** — fail-soft base64 forward to the platform extract endpoint |
| `archie-comms/app_comms.py` | **modify** — `POST /api/chat/attach` (multipart) + `_format_attachment_block` |
| `archie-comms/tests/test_attachment_proxy.py` | **new** — proxy + block-format tests |
| `archie-comms/static/js/archie-chat.js` | **modify** — 📎 button, attach flow, chip, prepend-on-send |
| `archie-comms/templates/chat.html` | **modify** — 📎 button + hidden file input + chip container in the input bar |
| `archie-comms/static/css/archie-chat.css` | **modify** — 📎 button + chip styles |

---

## Task 1: Platform — extraction service + internal endpoint

**Files:** Create `platform_v2/services/attachment_extract_service.py`; Modify `platform_v2/app.py`; Test `platform_v2/tests/test_attachment_extract.py`.

**Interfaces:**
- Produces: `attachment_extract_service.extract_payload(filename, raw_bytes, mime=None) -> {"text","chars","ocr_used","truncated"}` (fail-soft: extraction error → text="" + `error`).
- Produces: `POST /api/internal/attachments/extract {filename, content_b64, mime?}` → same dict; 413 if decoded bytes > cap; 401 without key.

- [ ] **Step 1: Write the failing service test**

```python
# platform_v2/tests/test_attachment_extract.py
import importlib


def test_extract_payload_routes_to_extract_text(monkeypatch):
    svc = importlib.import_module("services.attachment_extract_service")
    seen = {}
    monkeypatch.setattr(
        svc, "extract_text_from_file",
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


def test_extract_payload_failsoft_on_raise(monkeypatch):
    svc = importlib.import_module("services.attachment_extract_service")
    def boom(p, mime_type=None):
        raise RuntimeError("corrupt pdf")
    monkeypatch.setattr(svc, "extract_text_from_file", boom)
    out = svc.extract_payload("x.pdf", b"x", "application/pdf")
    assert out["text"] == ""
    assert out["chars"] == 0
    assert "error" in out
```

- [ ] **Step 2: Run RED** (sync bundle) — `docker exec -w /tmp/wt/platform_v2 archie_platform sh -c 'PYTHONPATH=/app:$PYTHONPATH python3 -m pytest tests/test_attachment_extract.py -v'` → FAIL (module missing).

- [ ] **Step 3: Implement the service**

```python
# platform_v2/services/attachment_extract_service.py
"""Sovereign attachment text extraction (COO Cockpit Slice 2).

Decode uploaded bytes to a temp file, run the existing extract_text_from_file
(PDF/docx/text/image-OCR), cap the text, always clean up. Fail-SOFT: a genuinely
unreadable file yields text="" + an error note so the chat message still sends."""
import logging
import os
import tempfile

from services.chronicle_attachment_service import extract_text_from_file

logger = logging.getLogger(__name__)

ATTACHMENT_TEXT_CAP = 20000  # chars returned to the model


def extract_payload(filename, raw_bytes, mime=None):
    suffix = os.path.splitext(filename or "")[1][:10]  # preserve ext for _kind()
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw_bytes)
        text, ocr_used = extract_text_from_file(tmp_path, mime)
        text = text or ""
        truncated = len(text) > ATTACHMENT_TEXT_CAP
        if truncated:
            logger.info("attachment %s truncated %d -> %d chars", filename, len(text), ATTACHMENT_TEXT_CAP)
            text = text[:ATTACHMENT_TEXT_CAP]
        return {"text": text, "chars": len(text), "ocr_used": bool(ocr_used), "truncated": truncated}
    except Exception as exc:  # fail-soft — the message still sends without the text
        logger.warning("attachment extract failed for %s: %s", filename, exc)
        return {"text": "", "chars": 0, "ocr_used": False, "truncated": False, "error": str(exc)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
```

- [ ] **Step 4: Run the service tests GREEN.**

- [ ] **Step 5: Write the failing endpoint test** (append; uses the `client` fixture + `ARCHIE_APP_PY`)

```python
def test_internal_extract_requires_key(client):
    r = client.post("/api/internal/attachments/extract", json={})
    assert r.status_code == 401


def test_internal_extract_routes_to_service(client, monkeypatch):
    import base64
    import services.attachment_extract_service as svc
    monkeypatch.setattr(svc, "extract_payload",
                        lambda fn, raw, mime=None: {"text": "hi", "chars": 2, "ocr_used": False, "truncated": False})
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/attachments/extract",
                    json={"filename": "a.txt", "content_b64": base64.b64encode(b"hi").decode(), "mime": "text/plain"},
                    headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    assert r.get_json()["text"] == "hi"


def test_internal_extract_rejects_oversize(client, monkeypatch):
    import base64
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import app as _app  # loaded via ARCHIE_APP_PY
    big = base64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
    r = client.post("/api/internal/attachments/extract",
                    json={"filename": "big.bin", "content_b64": big},
                    headers={"Authorization": "Bearer k"})
    assert r.status_code == 413
```

- [ ] **Step 6: Add the endpoint in `app.py`** (beside the Slice-1 internal endpoints, after `api_internal_approvals_deny`)

```python
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024


@app.route("/api/internal/attachments/extract", methods=["POST"])
@_require_internal_key
def api_internal_attachments_extract():
    """Sovereign attachment extraction for the cockpit. Bearer INTERNAL_API_KEY.
    Decodes content_b64 -> temp file -> extract_text_from_file -> capped text."""
    import base64

    from services.attachment_extract_service import extract_payload

    data = request.get_json(silent=True) or {}
    filename = data.get("filename") or "attachment"
    try:
        raw = base64.b64decode(data.get("content_b64") or "", validate=False)
    except Exception:
        return jsonify({"error": "invalid content_b64"}), 400
    if len(raw) > ATTACHMENT_MAX_BYTES:
        return jsonify({"error": "file too large", "max_bytes": ATTACHMENT_MAX_BYTES}), 413
    return jsonify(extract_payload(filename, raw, data.get("mime")))
```

- [ ] **Step 7: Run all Task-1 tests GREEN** (`ARCHIE_APP_PY=/tmp/wt/platform_v2/app.py PYTHONPATH=/app:$PYTHONPATH`).

- [ ] **Step 8: Commit** — `feat(attachments): platform sovereign extract service + internal endpoint`

---

## Task 2: Comms — attachment proxy service

**Files:** Create `archie-comms/services/attachment_proxy.py`; Test `archie-comms/tests/test_attachment_proxy.py`.

**Interfaces:**
- Produces: `attachment_proxy.extract(filename, raw_bytes, mime=None) -> {"ok", "text","chars","ocr_used","truncated"}` or `{"ok": False, "error"}` (fail-soft).

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_attachment_proxy.py
import services.attachment_proxy as ap


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
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
    import base64
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
```

- [ ] **Step 2: Run RED** — `cd archie-comms && <venv> -m pytest tests/test_attachment_proxy.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# archie-comms/services/attachment_proxy.py
"""Thin cockpit->platform attachment extraction proxy (COO Cockpit Slice 2).
Base64-forwards the in-memory bytes to the platform @_require_internal_key extract
endpoint. Fail-SOFT: any error -> {"ok": False, "error"} so the message still sends."""
import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def extract(filename, raw_bytes, mime=None):
    try:
        body = {"filename": filename, "content_b64": base64.b64encode(raw_bytes).decode(), "mime": mime}
        r = requests.post(
            f"{_base()}/api/internal/attachments/extract",
            json=body,
            headers={"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200:
            return {"ok": True, **data}
        return {"ok": False, "error": data.get("error") or f"HTTP {r.status_code}"}
    except Exception as exc:
        logger.warning("attachment extract proxy failed: %s", exc)
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Run GREEN.**  **Step 5: Commit** — `feat(comms): attachment extraction proxy (fail-soft)`

---

## Task 3: Comms — `/api/chat/attach` route + block formatter

**Files:** Modify `archie-comms/app_comms.py`; Test `archie-comms/tests/test_attachment_proxy.py` (extend).

**Interfaces:**
- Produces: `_format_attachment_block(filename, text, ocr_used, chars) -> str` = `"\n\n[Attachment: <name> (<chars> chars, ocr=<bool>)]\n<text>\n"`.
- Produces: `POST /api/chat/attach` (multipart `file`) → `{ok, filename, chars, ocr_used, truncated, block}` (owner-only). Oversize → 413; empty text → `ok:true` with `block` carrying a "no readable text" note.

- [ ] **Step 1: Write the failing block-format test**

```python
# append to archie-comms/tests/test_attachment_proxy.py
import app_comms


def test_format_attachment_block():
    b = app_comms._format_attachment_block("report.pdf", "some text", False, 9)
    assert b.startswith("\n\n[Attachment: report.pdf (9 chars, ocr=false)]\n")
    assert b.endswith("some text\n")


def test_format_attachment_block_ocr_true():
    b = app_comms._format_attachment_block("scan.png", "ocr text", True, 8)
    assert "ocr=true" in b
```

- [ ] **Step 2: Run RED** (`_format_attachment_block` missing).

- [ ] **Step 3: Implement in `app_comms.py`** (beside the Slice-1 `/api/approvals` routes)

```python
_ATTACH_MAX_BYTES = 10 * 1024 * 1024


def _format_attachment_block(filename, text, ocr_used, chars):
    return f"\n\n[Attachment: {filename} ({chars} chars, ocr={str(bool(ocr_used)).lower()})]\n{text}\n"


@app.route("/api/chat/attach", methods=["POST"])
def api_chat_attach():
    """Owner-only: extract an uploaded file's text (sovereign, on the platform).
    Bytes are held in memory only. Fail-soft: extraction failure still returns a
    block with a note so the chat message can send."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    raw = f.read()
    if len(raw) > _ATTACH_MAX_BYTES:
        return jsonify({"error": "file too large (max 10 MB)"}), 413
    from services.attachment_proxy import extract

    res = extract(f.filename or "attachment", raw, f.mimetype)
    if not res.get("ok"):
        # fail-soft: let the message send, note the failure in the block
        block = _format_attachment_block(f.filename or "attachment", "(could not read this file)", False, 0)
        return jsonify({"ok": True, "filename": f.filename, "chars": 0, "ocr_used": False,
                        "truncated": False, "block": block, "note": res.get("error")})
    text = res.get("text") or ""
    if not text:
        text = "(no readable text found)"
    block = _format_attachment_block(f.filename or "attachment", text, res.get("ocr_used"), res.get("chars", len(text)))
    return jsonify({"ok": True, "filename": f.filename, "chars": res.get("chars", 0),
                    "ocr_used": bool(res.get("ocr_used")), "truncated": bool(res.get("truncated")), "block": block})
```

- [ ] **Step 4: Run GREEN** (block-format tests; the route is exercised in Task 5/6). **Step 5: Commit** — `feat(comms): /api/chat/attach route + attachment block formatter`

---

## Task 4: Frontend — 📎 button, file chip, prepend-on-send

**Files:** Modify `archie-comms/templates/chat.html`, `archie-comms/static/js/archie-chat.js`, `archie-comms/static/css/archie-chat.css`. Verify: browser (Task 5).

**Interfaces:** Consumes `POST /api/chat/attach`. The pending attachment's `block` is prepended to the outgoing `message`; the user bubble renders the typed text + a chip (block not shown in the bubble).

- [ ] **Step 1: Read the input bar + `send()` payload build**

Run: `grep -n 'ac-input-bar\|ac-quick-actions\|ac-send-btn\|id=\"ac-input\"' archie-comms/templates/chat.html` and read `MessageStream.send()` in `archie-chat.js` (the `fetch('/api/chat/send_message'…)` at ~L141 + the user-bubble render just before it). Confirm where `message` is built and where the optimistic user bubble is appended.

- [ ] **Step 2: Add the 📎 control to `chat.html`** — beside `#ac-send-btn` in the input bar:

```html
<input type="file" id="ac-attach-input" style="display:none"
       accept=".pdf,.docx,.doc,.txt,.md,.csv,.json,.png,.jpg,.jpeg,.webp,.gif">
<button class="ac-attach-btn" id="ac-attach-btn" type="button" title="Attach a file">&#128206;</button>
```
And a chip container above the input: `<div id="ac-attach-chip" class="ac-attach-chip" style="display:none"></div>`.

- [ ] **Step 3: Wire the attach flow in `archie-chat.js`** (module-level state + handlers, called from the DOMContentLoaded init found in Step 1):

```javascript
let _pendingAttachment = null;   // { block, filename, chars, truncated }

function _showAttachChip(a) {
  const chip = document.getElementById('ac-attach-chip');
  if (!chip) return;
  chip.textContent = '';
  const label = _mk('span', 'ac-attach-chip-label');
  label.textContent = '📎 ' + a.filename + (a.chars ? ' (' + a.chars + ' chars' + (a.truncated ? ', truncated' : '') + ')' : '');
  const x = _mk('button', 'ac-attach-chip-x'); x.type = 'button'; x.textContent = '×';
  x.addEventListener('click', () => { _pendingAttachment = null; chip.style.display = 'none'; chip.textContent = ''; });
  chip.appendChild(label); chip.appendChild(x);
  chip.style.display = 'flex';
}

async function _onAttachSelected(ev) {
  const file = ev.target.files && ev.target.files[0];
  ev.target.value = '';               // allow re-selecting the same file
  if (!file) return;
  const chip = document.getElementById('ac-attach-chip');
  if (chip) { chip.style.display = 'flex'; chip.textContent = 'Reading ' + file.name + '…'; }
  try {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/chat/attach', { method: 'POST', body: fd });
    const out = await r.json().catch(() => ({}));
    if (r.ok && out.ok) { _pendingAttachment = out; _showAttachChip(out); }
    else { _pendingAttachment = null; if (chip) chip.textContent = out.error || 'Could not attach file'; }
  } catch (_) {
    _pendingAttachment = null; if (chip) chip.textContent = 'Could not attach file';
  }
}

// consume the pending attachment: returns the block to prepend, then clears the chip
function _consumePendingAttachmentBlock() {
  const a = _pendingAttachment; _pendingAttachment = null;
  const chip = document.getElementById('ac-attach-chip');
  if (chip) { chip.style.display = 'none'; chip.textContent = ''; }
  return a ? a.block : '';
}
```

Wire the button + input in init: `document.getElementById('ac-attach-btn').addEventListener('click', () => document.getElementById('ac-attach-input').click()); document.getElementById('ac-attach-input').addEventListener('change', _onAttachSelected);`

- [ ] **Step 4: Prepend the block on send** — in `MessageStream.send()` (found in Step 1), compute `const block = _consumePendingAttachmentBlock();` and send `message: block ? (block + userText) : userText` in the fetch body, while the optimistic user bubble renders **only** `userText` (append a small "📎 filename" note to the bubble if `block` is non-empty). Do NOT display the block text in the bubble.

- [ ] **Step 5: CSS** — `.ac-attach-btn` (icon button matching `.ac-send-btn`), `.ac-attach-chip` (flex row, cyan border, small), `.ac-attach-chip-x` (dim × button). Match the LCARS cyan theme + existing `--ac-*` vars.

- [ ] **Step 6: `node --check archie-chat.js`; Commit** — `feat(comms): 📎 attachment button + chip + prepend-on-send`

---

## Task 5: End-to-end deploy + live verification (post-merge)

- [ ] **Step 1: Deploy** — after merge: `git -C /mnt/archie_brain pull`; `docker compose restart archie_platform`; `docker compose up -d --build archie_comms`.
- [ ] **Step 2: Backend live smoke** — from the comms container, base64 a small text file and call `attachment_proxy.extract` → confirm `{ok:true, text:…, chars:…}` (proves comms→platform extract path). Repeat with a small PDF if available.
- [ ] **Step 3: Browser (P.R.O.B.E./Playwright)** — at archie.kytranempowerment.com: click 📎 → pick a .txt/.pdf → chip shows filename + char count → type "summarize this" → send → A.R.C.H.I.E.'s reply reflects the file content. Confirm the bubble shows the typed text + chip note (not the raw block).
- [ ] **Step 4: Fail-soft check** — attach an unsupported/garbage binary → chip notes it couldn't be read → the message still sends without attachment text.
- [ ] **Step 5: Open PR / hand to /merge-pr.**

---

## Self-Review

- **Spec coverage (§4.3):** platform `/api/internal/attachments/extract` (Task 1) · comms in-memory base64 forward (Task 2) · `[Attachment: …]` block prepended to the DHQ prompt (Task 3 formatter + Task 4 prepend) · 📎 button + chip (Task 4) · caps + truncation surfaced (Tasks 1/3) · fail-soft (Tasks 1/2/3) · owner-only (Task 3). Open questions resolved: 20k cap, 10 MB upload, text-only (OCR for images).
- **Type consistency:** `extract_payload -> {text,chars,ocr_used,truncated[,error]}` consumed identically by the endpoint (Task 1) and the proxy (Task 2); `extract() -> {ok,…}` consumed by `/api/chat/attach` (Task 3); `{ok,filename,chars,ocr_used,truncated,block}` consumed by the frontend (Task 4). `_format_attachment_block` output pinned by tests + used verbatim in the prompt.
- **No stream_send_message surgery:** the block rides `message` client-side — smallest change that satisfies "the attachment summary rides that message."
