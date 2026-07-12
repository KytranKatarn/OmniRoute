# COO Cockpit — Slice 4: Face / Presence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the cockpit A.R.C.H.I.E.'s face — her avatar + a persona header ("A.R.C.H.I.E. · COO · <presence>"), live presence states (idle · thinking · speaking · listening), and a per-message agent·model attribution badge.

**Architecture:** Thin cockpit. One new `@_require_internal_key` platform endpoint serves her portrait (base64); comms proxies it as an image. Presence is pure frontend, driven by the chat/voice states already hooked in Slices 1–3 (streaming → thinking; TTS playing → speaking; mic recording → listening). Attribution reuses the DHQ reply's `agent_name`/`model_used` (already returned by `/api/internal/dhq/chat`) — threaded through comms into the SSE `done` event.

**Tech Stack:** Python 3.11 / Flask (platform + comms), `requests`, base64, vanilla JS (comms LCARS). Spec: `docs/superpowers/specs/2026-07-11-archie-coo-cockpit-design.md` §4.5.

## Global Constraints

- **Thin cockpit / fail-soft:** portrait failure → the frontend `<img>` `onerror` falls back to a CSS monogram; missing attribution → the badge is omitted. Never a hard error.
- **Grounded facts:** agent 2 = A.R.C.H.I.E.; her portrait = `agent_portraits.canonical_image_path` (currently `/static/media/images/2026-05-16/media_studio_00003_.png`, served from the platform's static dir). `/api/internal/dhq/chat` returns `{success, response, agent_name, model_used}`. Her persona/title = COO (static); presence is dynamic.
- **Owner-only** cockpit routes (session-auth). The portrait is her public face — the comms avatar route may be session-auth like the rest.
- **Presence states:** `idle` (default) · `thinking` (reply streaming) · `speaking` (TTS audio playing) · `listening` (mic recording). Slice 3 already added `_setPresence(state)` + speaking/listening hooks — Slice 4 makes it a real header visual + adds `thinking`.
- **Testing:** platform bundle harness (`ARCHIE_APP_PY` + `PYTHONPATH=/app`); comms host venv; JS `node --check`. Frontend visuals verified in the browser (Task 5).
- **Never push to main; feature branch + PR; per-task commits.**

---

## File Structure

| File | Responsibility |
|---|---|
| `platform_v2/services/archie_face_service.py` | **new** — `get_portrait() -> {ok, image_b64, mime}` (read agent-2's portrait file, fail-soft) |
| `platform_v2/app.py` | **modify** — `@_require_internal_key GET /api/internal/archie/portrait` |
| `platform_v2/tests/test_archie_face.py` | **new** |
| `archie-comms/services/face_proxy.py` | **new** — `portrait() -> (bytes, mime) | None` (fetch from platform, fail-soft) |
| `archie-comms/app_comms.py` | **modify** — `GET /api/archie/avatar` (image or 404) |
| `archie-comms/services/conversation_service.py` | **modify** — `_dhq_chat_reply` returns reply + `agent_name`/`model_used`; `stream_send_message` puts them in the `done` event |
| `archie-comms/tests/test_face_proxy.py` | **new** |
| `archie-comms/tests/test_attribution.py` | **new** — `done` event carries agent/model |
| `archie-comms/templates/chat.html` | **modify** — persona header (avatar + name/title + presence) |
| `archie-comms/static/js/archie-chat.js` | **modify** — avatar load + monogram fallback; presence header; `thinking` on send/`idle` on done; attribution badge on assistant turns |
| `archie-comms/static/css/archie-chat.css` | **modify** — header, avatar ring per presence, badge |

---

## Task 1: Platform — portrait service + internal endpoint

**Files:** Create `platform_v2/services/archie_face_service.py`, `platform_v2/tests/test_archie_face.py`; Modify `platform_v2/app.py`.

**Interfaces:** `get_portrait() -> {ok, image_b64?, mime?, error?}`; `GET /api/internal/archie/portrait` → same; 401 without key.

- [ ] **Step 1: Read how a portrait path resolves to a file** — `docker exec archie_platform sh -c "docker=..."`; confirm `canonical_image_path` like `/static/media/images/.../x.png` maps to `/app/static/media/images/.../x.png` on disk. (The path is app-relative under `/app`.)

- [ ] **Step 2: Write the failing tests**

```python
# platform_v2/tests/test_archie_face.py
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
    assert client.post("/api/internal/archie/portrait").status_code in (401, 405)
    assert client.get("/api/internal/archie/portrait").status_code == 401


def test_internal_portrait_routes(client, monkeypatch):
    import services.archie_face_service as svc
    monkeypatch.setattr(svc, "get_portrait", lambda: {"ok": True, "image_b64": "QUJD", "mime": "image/png"})
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.get("/api/internal/archie/portrait", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["image_b64"] == "QUJD"
```

- [ ] **Step 3: Implement `services/archie_face_service.py`**

```python
"""A.R.C.H.I.E.'s face — serve agent-2's portrait for the cockpit. Fail-soft."""
import base64
import logging
import os

logger = logging.getLogger(__name__)

ARCHIE_AGENT_ID = 2
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /app


def _portrait_path():
    """Absolute path to agent 2's canonical portrait, or '' if none."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT canonical_image_path FROM agent_portraits WHERE agent_id=%s", (ARCHIE_AGENT_ID,)
            )
            row = cur.fetchone()
        rel = (row["canonical_image_path"] if row else "") or ""
        if not rel:
            return ""
        return os.path.join(_APP_DIR, rel.lstrip("/"))  # /static/... -> /app/static/...
    except Exception as exc:
        logger.warning("portrait path lookup failed: %s", exc)
        return ""


def get_portrait():
    path = _portrait_path()
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "no portrait"}
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        ext = os.path.splitext(path)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
            ext.lstrip("."), "image/png"
        )
        return {"ok": True, "image_b64": base64.b64encode(raw).decode(), "mime": mime}
    except Exception as exc:
        logger.warning("portrait read failed: %s", exc)
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Endpoint in `app.py`** (beside the other internal endpoints)

```python
@app.route("/api/internal/archie/portrait", methods=["GET"])
@_require_internal_key
def api_internal_archie_portrait():
    """A.R.C.H.I.E.'s portrait for the cockpit avatar. Bearer INTERNAL_API_KEY."""
    from services.archie_face_service import get_portrait

    return jsonify(get_portrait())
```

- [ ] **Step 5: RED → GREEN (bundle).**  **Step 6: Commit** — `feat(face): platform archie portrait service + internal endpoint`

---

## Task 2: Comms — avatar proxy route

**Files:** Create `archie-comms/services/face_proxy.py`, `archie-comms/tests/test_face_proxy.py`; Modify `archie-comms/app_comms.py`.

**Interfaces:** `face_proxy.portrait() -> (raw_bytes, mime) | None` (fail-soft). `GET /api/archie/avatar` → image bytes or 404.

- [ ] **Step 1: Write the failing test** — `portrait()` GETs `/api/internal/archie/portrait` with Bearer; returns (bytes, mime) on `{ok:true}`; `None` on error/`{ok:false}` (mirror `attachment_proxy`).

- [ ] **Step 2: RED.**

- [ ] **Step 3: Implement `face_proxy.py`** — `_base()`=PLATFORM_URL, Bearer; GET; on 200+`ok` → `(base64.b64decode(image_b64), mime)`; else/except → `None`.

- [ ] **Step 4: Route in `app_comms.py`**

```python
@app.route("/api/archie/avatar", methods=["GET"])
def api_archie_avatar():
    """A.R.C.H.I.E.'s avatar image (proxied from the platform). 404 -> frontend
    falls back to a monogram. Cached a day (her face rarely changes)."""
    from flask import Response, session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.face_proxy import portrait

    got = portrait()
    if not got:
        return ("", 404)
    raw, mime = got
    return Response(raw, mimetype=mime, headers={"Cache-Control": "public, max-age=86400"})
```

- [ ] **Step 5: RED→GREEN.**  **Step 6: Commit** — `feat(comms): archie avatar proxy route`

---

## Task 3: Comms — thread agent·model attribution into the SSE done event

**Files:** Modify `archie-comms/services/conversation_service.py`; Test `archie-comms/tests/test_attribution.py`.

**Interfaces:** `_dhq_chat_reply` now returns `{"response","agent_name","model_used"} | None`; `stream_send_message` yields the `done` event as `{type:"done", conversation_id, agent_name, model_used}`.

- [ ] **Step 1: Read `_dhq_chat_reply` callers + the `done` yield** — `grep -n "_dhq_chat_reply\|type.*done\|yield {\"type\": \"done\"" archie-comms/services/conversation_service.py`. Confirm the ONLY consumer is `stream_send_message` (else adapt both).

- [ ] **Step 2: Write the failing test**

```python
# archie-comms/tests/test_attribution.py
import services.conversation_service as cs


def test_dhq_reply_returns_agent_and_model(monkeypatch):
    class _R:
        status_code = 200
        content = b"x"
        def json(self):
            return {"success": True, "response": "hi", "agent_name": "A.R.C.H.I.E.", "model_used": "qwen2.5:7b"}
    import requests as _rq
    monkeypatch.setattr(_rq, "post", lambda *a, **k: _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = cs._dhq_chat_reply("sys", "hi", 2)
    assert out["response"] == "hi"
    assert out["agent_name"] == "A.R.C.H.I.E." and out["model_used"] == "qwen2.5:7b"


def test_dhq_reply_none_on_failure(monkeypatch):
    import requests as _rq
    monkeypatch.setattr(_rq, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cs._dhq_chat_reply("sys", "hi", 2) is None
```

- [ ] **Step 3: RED.**

- [ ] **Step 4: Change `_dhq_chat_reply`** to return `{"response": data["response"], "agent_name": data.get("agent_name"), "model_used": data.get("model_used")}` (instead of the bare string) on success; `None` unchanged on failure.

- [ ] **Step 5: Update `stream_send_message`** — `dhq_reply` is now a dict: `full_parts = [dhq_reply["response"]]`; capture `dhq_agent = dhq_reply.get("agent_name")`, `dhq_model = dhq_reply.get("model_used")` (None on the Ollama fallback path). Change the done yield to `{"type": "done", "conversation_id": conv_id, "agent_name": dhq_agent, "model_used": dhq_model}`.

- [ ] **Step 6: RED→GREEN + run `test_v1_cli_api.py` (no regression).**  **Step 7: Commit** — `feat(comms): thread agent+model attribution into the SSE done event`

---

## Task 4: Frontend — persona header + presence + attribution badge

**Files:** Modify `archie-comms/templates/chat.html`, `archie-comms/static/js/archie-chat.js`, `archie-comms/static/css/archie-chat.css`. Verify: browser (Task 5).

- [ ] **Step 1: Read the chat header region** in `chat.html` (where the conversation title/toggles live) + the `_appendBubble`/`_finaliseStream`/`done` handler in `archie-chat.js`.

- [ ] **Step 2: Persona header in `chat.html`** — near the top of the center column:
```html
<div class="ac-persona" id="ac-persona">
  <div class="ac-avatar" id="ac-avatar" data-presence="idle">
    <img id="ac-avatar-img" alt="A.R.C.H.I.E." />
    <span class="ac-avatar-mono">A</span>
  </div>
  <div class="ac-persona-meta">
    <div class="ac-persona-name">A.R.C.H.I.E. <span class="ac-persona-title">· COO</span></div>
    <div class="ac-persona-presence" id="ac-presence-label">online</div>
  </div>
</div>
```

- [ ] **Step 3: Avatar load + fallback (`archie-chat.js`, init)**
```javascript
(function _loadAvatar() {
  const img = document.getElementById('ac-avatar-img');
  const av = document.getElementById('ac-avatar');
  if (!img) return;
  img.onerror = () => { av && av.classList.add('ac-avatar-mono-on'); img.style.display = 'none'; };
  img.onload = () => { av && av.classList.remove('ac-avatar-mono-on'); };
  img.src = '/api/archie/avatar?ts=' + Date.now();
})();
```

- [ ] **Step 4: Presence → header** — extend `_setPresence(state)` (from Slice 3) to also set the avatar ring + label:
```javascript
function _setPresence(state) {
  document.body.dataset.presence = state;
  const av = document.getElementById('ac-avatar');
  if (av) av.dataset.presence = state;
  const label = document.getElementById('ac-presence-label');
  if (label) label.textContent = { idle: 'online', thinking: 'thinking…', speaking: 'speaking…', listening: 'listening…' }[state] || 'online';
  const vt = document.getElementById('ac-voice-toggle');
  if (vt) vt.classList.toggle('ac-speaking', state === 'speaking');
}
```
Drive `thinking`: call `_setPresence('thinking')` right after the stream starts (in `send()`, after appending the streaming bubble) and `_setPresence('idle')` in the `done` branch (unless voice will speak — then `_speak` sets `speaking`, and its `onended` returns to `idle`). Guard against clobbering speaking/listening.

- [ ] **Step 5: Attribution badge** — in the `done` SSE branch, capture `evt.agent_name`/`evt.model_used`; after `_finaliseStream`, set the just-finished assistant bubble's meta to include a badge, e.g. append a `<span class="ac-attrib">⟨A.R.C.H.I.E. · qwen2.5:7b⟩</span>` (via `textContent`, XSS-safe) when both are present. (Keep a handle to the finished bubble before `_streamingBubble` is nulled.)

- [ ] **Step 6: CSS** — `.ac-persona`/`.ac-avatar` (round, cyan ring), `.ac-avatar[data-presence=…]` ring color+pulse (idle dim / thinking cyan / speaking green / listening red), `.ac-avatar-mono-on .ac-avatar-mono` show + hide img, `.ac-attrib` (small dim monospace). LCARS `--ac-*` vars.

- [ ] **Step 7: `node --check`; Commit** — `feat(comms): persona header + avatar presence + attribution badge`

---

## Task 5: End-to-end deploy + live verification

- [ ] **Step 1:** after merge — `git -C /mnt/archie_brain pull`; `docker compose restart archie_platform`; `docker compose up -d --build archie_comms`.
- [ ] **Step 2: Avatar smoke** — `docker exec archie_comms python3 -c "import services.face_proxy as f; g=f.portrait(); print('bytes', len(g[0]) if g else None, 'mime', g[1] if g else None)"` → real bytes + mime.
- [ ] **Step 3: Attribution smoke** — send a message; confirm the SSE `done` event carries `agent_name`+`model_used` (or check a reply's saved metadata).
- [ ] **Step 4: Browser (P.R.O.B.E./Playwright)** — her avatar shows in the header; presence ring goes thinking→(speaking if 🔊)→idle on a message; listening while 🎤 records; each reply shows the ⟨agent · model⟩ badge.
- [ ] **Step 5: Open PR / hand to /merge-pr.**

---

## Self-Review

- **Spec coverage (§4.5):** avatar (Tasks 1–2 + Task 4 header) · presence states idle/thinking/speaking/listening (Task 4, reusing Slice-3 hooks) · per-message attribution (Task 3 backend + Task 4 badge) · persona header "A.R.C.H.I.E. · COO · <presence>" (Task 4). Fail-soft: portrait 404 → monogram; missing attribution → no badge.
- **Type consistency:** `get_portrait -> {ok, image_b64, mime}` used by the endpoint (T1) + `face_proxy.portrait -> (bytes,mime)|None` (T2) + `<img>` (T4). `_dhq_chat_reply -> {response,agent_name,model_used}|None` consumed by `stream_send_message` (T3); `done` event `{agent_name,model_used}` consumed by the badge (T4). Presence strings idle/thinking/speaking/listening consistent across `_setPresence`, `_speak`, `_toggleMic`, `send`, `done`.
