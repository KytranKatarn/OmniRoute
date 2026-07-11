# COO Cockpit — Slice 3: Voice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A.R.C.H.I.E. speaks her replies (Kokoro TTS) and Kytran speaks to her (sovereign Whisper STT) from the cockpit — audio never leaves the cluster.

**Architecture:** Thin cockpit unchanged. **TTS** reuses the platform's existing `synthesize_for_agent` (Kokoro) behind a new `@_require_internal_key` endpoint. **STT** is a NEW lean **CPU** `archie_whisper` sidecar (faster-whisper `base`, int8) — isolated from the platform image, no GPU contention with the shared-GPU LLM/image workloads (owner-approved deployment shape). Comms proxies both; the frontend adds a voice toggle (play the reply) + a mic button (record → transcribe → fill input).

**Tech Stack:** Python 3.11 / Flask (platform + comms + whisper sidecar), faster-whisper (CPU int8), `requests`, base64, MediaRecorder + `Audio()` (frontend). Spec: `docs/superpowers/specs/2026-07-11-archie-coo-cockpit-design.md` §4.4.

## Global Constraints

- **Thin sovereign cockpit:** comms adds UI + fail-soft proxies only. TTS/STT run on the platform / the hub sidecar behind `@_require_internal_key`. No new secrets.
- **Voice is fail-SOFT:** TTS failure → silently fall back to text (no audio, no error spam). STT failure → the mic yields no transcript; the owner types. (Spec §8.)
- **Sovereign:** audio never leaves the cluster. Whisper runs on the hub (CPU); the platform reaches it at `http://archie_whisper:8090` (Docker-internal, never a public host).
- **Owner-only:** cockpit voice routes are session-auth (`flask_session['user_id']`).
- **TTS facts:** `get_voice_synthesizer().synthesize_for_agent(text, agent_id=2, emotion=, user_id=) -> {success, audio_base64, cached, ...}`; `get_archie_emotional_state(user_id) -> emotion`. Kytran = agent/user 2.
- **Her canonical voice (honor it — don't invent a new one):** `agent_voice_profiles`(agent 2) = Kokoro `af_heart` blended 90/10 `af_jessica`, warmth 0.80, speed 1.15, default emotion "excited", she/her — `synthesize_for_agent(agent_id=2)` loads this automatically. Her spoken character = `archie_personality.voice_system_prompt` ("Kytran's AI business partner, not an assistant; professional yet warm; direct but never cold; she/her; severity-adaptive tone; concise") — already used by the cockpit chat persona. Slice 3 wires the audio; it changes NEITHER the profile nor the persona.
- **Whisper shape (owner-approved):** dedicated `archie_whisper` container, faster-whisper `base`, `device=cpu`, `compute_type=int8`; `POST /transcribe {audio_b64, mime?}` → `{text}` + `GET /health`. NOT baked into the platform image.
- **Voice stays WARM/always-loaded (owner directive — "keep active and responsive"):** the whisper model is **preloaded at worker boot and kept resident** (never cold-loads per request) via a gunicorn `post_worker_init` warm hook; the container is `restart: unless-stopped` so it's always up. Kokoro TTS stays warm via the platform `get_voice_synthesizer()` singleton (already resident). Trades a little idle RAM (~1-2 GB, of 128 GB) for instant voice — same rationale as the LLM keep-alive set. `GET /health` reports `warm: true` once the model is resident.
- **Testing harness** (from Slices 1–2):
  - Platform: bundle sync + `docker exec -w /tmp/wt/platform_v2 archie_platform sh -c 'ARCHIE_APP_PY=/tmp/wt/platform_v2/app.py PYTHONPATH=/app:$PYTHONPATH python3 -m pytest tests/<f> -v'`.
  - Comms: host venv `/home/kytran/.claude/jobs/991c52c2/tmp/comms-venv/bin/python -m pytest`, cwd=`archie-comms`.
  - Whisper sidecar: its route/plumbing with the model stubbed; a REAL transcription (TTS clip → STT) in Task 6.
- **Never push to main; feature branch + PR; per-task commits.** docker-compose.yml gets ONE additive service block (Task 3) — no existing service edited.

---

## File Structure

| File | Responsibility |
|---|---|
| `platform_v2/services/voice_service.py` | **new** — pure `synthesize(text, user_id, emotion)` (wraps Kokoro) + `transcribe(audio_bytes, mime)` (proxy to the whisper sidecar); fail-soft |
| `platform_v2/app.py` | **modify** — `@_require_internal_key` `/api/internal/voice/synthesize` + `/api/internal/voice/transcribe` |
| `platform_v2/tests/test_voice_endpoints.py` | **new** |
| `whisper_service/app.py` | **new** — lean Flask faster-whisper `/transcribe` + `/health` |
| `whisper_service/Dockerfile` | **new** — python-slim + faster-whisper (CPU) |
| `whisper_service/requirements.txt` | **new** |
| `whisper_service/gunicorn.conf.py` | **new** — `post_worker_init` warm hook (preload the model at boot; owner directive) |
| `whisper_service/test_transcribe.py` | **new** — route + plumbing (model stubbed) |
| `docker-compose.yml` | **modify** — additive `archie_whisper` service |
| `archie-comms/services/voice_proxy.py` | **new** — fail-soft synthesize/transcribe proxy to the platform |
| `archie-comms/app_comms.py` | **modify** — `POST /api/voice/synthesize` + `POST /api/voice/transcribe` (owner-only) |
| `archie-comms/tests/test_voice_proxy.py` | **new** |
| `archie-comms/static/js/archie-chat.js` | **modify** — voice toggle (play reply on `done`) + mic (record→transcribe→fill input) + speaking/listening feedback |
| `archie-comms/templates/chat.html` | **modify** — voice toggle + mic button |
| `archie-comms/static/css/archie-chat.css` | **modify** — toggle/mic/pulse styles |

---

## Task 1: Platform — voice service + 2 internal endpoints

**Files:** Create `platform_v2/services/voice_service.py`, `platform_v2/tests/test_voice_endpoints.py`; Modify `platform_v2/app.py`.

**Interfaces:**
- Produces: `voice_service.synthesize(text, user_id=2, emotion=None) -> {success, audio_base64?, cached?, engine, error?}`.
- Produces: `voice_service.transcribe(audio_bytes, mime=None) -> {text} | {text:"", error}` (proxy to `WHISPER_URL`, fail-soft).
- Produces: `POST /api/internal/voice/synthesize {text, emotion?, user_id?}` and `POST /api/internal/voice/transcribe {audio_b64, mime?}`; 401 without key.

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_voice_endpoints.py
import base64
import importlib


def test_synthesize_wraps_synth(monkeypatch):
    vs = importlib.import_module("services.voice_service")
    class _Synth:
        def get_archie_emotional_state(self, uid): return "warm"
        def synthesize_for_agent(self, text, agent_id, emotion=None, user_id=None):
            assert agent_id == 2
            return {"success": True, "audio_base64": "QUJD", "cached": False}
    monkeypatch.setattr(vs, "get_voice_synthesizer", lambda: _Synth())
    out = vs.synthesize("hello", user_id=2)
    assert out["success"] is True and out["audio_base64"] == "QUJD" and out["engine"] == "kokoro"


def test_synthesize_failsoft(monkeypatch):
    vs = importlib.import_module("services.voice_service")
    def boom(): raise RuntimeError("kokoro down")
    monkeypatch.setattr(vs, "get_voice_synthesizer", boom)
    out = vs.synthesize("hi", user_id=2)
    assert out["success"] is False and "error" in out


def test_transcribe_proxies_to_whisper(monkeypatch):
    vs = importlib.import_module("services.voice_service")
    seen = {}
    class _R:
        status_code = 200
        content = b"x"
        def json(self): return {"text": "hello world"}
    monkeypatch.setattr(vs.requests, "post", lambda url, json=None, timeout=None: seen.update(url=url, body=json) or _R())
    out = vs.transcribe(b"\x00\x01", "audio/webm")
    assert out["text"] == "hello world"
    assert seen["url"].endswith("/transcribe")
    assert base64.b64decode(seen["body"]["audio_b64"]) == b"\x00\x01"


def test_transcribe_failsoft(monkeypatch):
    vs = importlib.import_module("services.voice_service")
    def boom(*a, **k): raise RuntimeError("whisper down")
    monkeypatch.setattr(vs.requests, "post", boom)
    out = vs.transcribe(b"x", None)
    assert out["text"] == "" and "error" in out


def test_internal_synthesize_requires_key(client):
    assert client.post("/api/internal/voice/synthesize", json={}).status_code == 401


def test_internal_transcribe_requires_key(client):
    assert client.post("/api/internal/voice/transcribe", json={}).status_code == 401


def test_internal_synthesize_routes(client, monkeypatch):
    import services.voice_service as vs
    monkeypatch.setattr(vs, "synthesize", lambda text, user_id=2, emotion=None: {"success": True, "audio_base64": "QUJD", "engine": "kokoro"})
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/voice/synthesize", json={"text": "hi"}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["audio_base64"] == "QUJD"


def test_internal_transcribe_routes(client, monkeypatch):
    import services.voice_service as vs
    monkeypatch.setattr(vs, "transcribe", lambda raw, mime=None: {"text": "hello"})
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/voice/transcribe",
                    json={"audio_b64": base64.b64encode(b"x").decode()}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["text"] == "hello"
```

- [ ] **Step 2: Run RED** (bundle + `ARCHIE_APP_PY`).

- [ ] **Step 3: Implement `services/voice_service.py`**

```python
"""Cockpit voice: TTS via Kokoro (synthesize_for_agent), STT via the sovereign
archie_whisper sidecar. Both fail-SOFT (voice is optional polish)."""
import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)

ARCHIE_AGENT_ID = 2


def _whisper_url():
    return os.getenv("WHISPER_URL", "http://archie_whisper:8090").rstrip("/")


def synthesize(text, user_id=2, emotion=None):
    try:
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        synth = get_voice_synthesizer()
        emo = emotion or synth.get_archie_emotional_state(user_id)
        res = synth.synthesize_for_agent(text, ARCHIE_AGENT_ID, emotion=emo, user_id=user_id)
        return {
            "success": bool(res.get("success")),
            "audio_base64": res.get("audio_base64"),
            "cached": res.get("cached"),
            "engine": "kokoro",
            "error": res.get("error"),
        }
    except Exception as exc:
        logger.warning("voice synthesize failed: %s", exc)
        return {"success": False, "engine": "kokoro", "error": str(exc)}


def transcribe(audio_bytes, mime=None):
    try:
        r = requests.post(
            f"{_whisper_url()}/transcribe",
            json={"audio_b64": base64.b64encode(audio_bytes).decode(), "mime": mime},
            timeout=60,
        )
        if r.status_code == 200 and r.content:
            return {"text": (r.json() or {}).get("text", "")}
        return {"text": "", "error": f"HTTP {r.status_code}"}
    except Exception as exc:
        logger.warning("voice transcribe failed: %s", exc)
        return {"text": "", "error": str(exc)}
```

- [ ] **Step 4: Add the endpoints in `app.py`** (after `api_internal_attachments_extract`)

```python
@app.route("/api/internal/voice/synthesize", methods=["POST"])
@_require_internal_key
def api_internal_voice_synthesize():
    from services.voice_service import synthesize

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "no text"}), 400
    return jsonify(synthesize(text, user_id=data.get("user_id") or 2, emotion=data.get("emotion")))


@app.route("/api/internal/voice/transcribe", methods=["POST"])
@_require_internal_key
def api_internal_voice_transcribe():
    import base64

    from services.voice_service import transcribe

    data = request.get_json(silent=True) or {}
    try:
        raw = base64.b64decode(data.get("audio_b64") or "", validate=True)
    except Exception:
        return jsonify({"text": "", "error": "invalid audio_b64"}), 400
    return jsonify(transcribe(raw, data.get("mime")))
```

- [ ] **Step 5: Run GREEN.**  **Step 6: Commit** — `feat(voice): platform TTS + STT internal endpoints (Kokoro + whisper proxy)`

---

## Task 2: Whisper sidecar service (CPU faster-whisper)

**Files:** Create `whisper_service/{app.py,Dockerfile,requirements.txt,test_transcribe.py}`.

**Interfaces:** `GET /health` → `{ok, model}`; `POST /transcribe {audio_b64, mime?}` → `{text}`. Model lazy-loaded (`base`, cpu, int8).

- [ ] **Step 1: Write the failing test** (model stubbed — no faster-whisper install needed to test plumbing)

```python
# whisper_service/test_transcribe.py
import base64
import importlib


def test_transcribe_decodes_and_calls_model(monkeypatch):
    app_mod = importlib.import_module("app")
    monkeypatch.setattr(app_mod, "_transcribe_file", lambda path: "hello there")
    c = app_mod.app.test_client()
    r = c.post("/transcribe", json={"audio_b64": base64.b64encode(b"RIFF....").decode(), "mime": "audio/wav"})
    assert r.status_code == 200 and r.get_json()["text"] == "hello there"


def test_transcribe_empty_is_400(monkeypatch):
    app_mod = importlib.import_module("app")
    c = app_mod.app.test_client()
    assert c.post("/transcribe", json={}).status_code == 400


def test_health(monkeypatch):
    app_mod = importlib.import_module("app")
    c = app_mod.app.test_client()
    assert c.get("/health").get_json()["ok"] is True
```

- [ ] **Step 2: Run RED** — `cd whisper_service && <a python with flask> -m pytest test_transcribe.py -v` (flask is enough; faster-whisper is stubbed).

- [ ] **Step 3: Implement `whisper_service/app.py`**

```python
"""Sovereign STT sidecar (COO Cockpit Slice 3). faster-whisper 'base', CPU int8.
Audio never leaves the cluster. Lazy-loads the model on first transcribe."""
import base64
import logging
import os
import tempfile

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whisper")
app = Flask(__name__)

MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        logger.info("loading faster-whisper %s (cpu/int8)", MODEL_NAME)
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def _transcribe_file(path):
    segments, _info = _get_model().transcribe(path, language="en", vad_filter=True)
    return "".join(seg.text for seg in segments).strip()


@app.route("/health", methods=["GET"])
def health():
    # warm=True once the model is resident (preloaded at boot by gunicorn.conf.py)
    return jsonify({"ok": True, "model": MODEL_NAME, "warm": _model is not None})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json(silent=True) or {}
    b64 = data.get("audio_b64")
    if not b64:
        return jsonify({"error": "no audio_b64"}), 400
    suffix = ".webm" if "webm" in (data.get("mime") or "") else ".wav"
    path = None
    try:
        raw = base64.b64decode(b64)
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        return jsonify({"text": _transcribe_file(path)})
    except Exception as exc:
        logger.warning("transcribe failed: %s", exc)
        return jsonify({"text": "", "error": str(exc)}), 200  # fail-soft to the caller
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8090")))
```

- [ ] **Step 4: `whisper_service/requirements.txt`**
```
faster-whisper==1.0.3
flask==3.0.3
gunicorn==22.0.0
```

- [ ] **Step 5: `whisper_service/gunicorn.conf.py`** — WARM the model at worker boot (owner directive: always-loaded voice). Runs only under gunicorn (production), never in pytest.
```python
bind = "0.0.0.0:8090"
workers = 1
timeout = 120


def post_worker_init(worker):
    """Preload faster-whisper so the FIRST transcription is instant + the model
    stays resident (active + responsive). Non-fatal if it can't load yet."""
    try:
        import app
        app._get_model()
        worker.log.info("faster-whisper preloaded (warm)")
    except Exception as exc:  # pragma: no cover
        worker.log.warning("whisper preload failed (will lazy-load): %s", exc)
```

- [ ] **Step 6: `whisper_service/Dockerfile`** (ffmpeg is needed to decode webm/ogg)
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py gunicorn.conf.py ./
ENV WHISPER_MODEL=base PORT=8090
EXPOSE 8090
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
```

- [ ] **Step 7: Run GREEN** (plumbing).  **Step 8: Commit** — `feat(voice): archie_whisper CPU sidecar (faster-whisper base, warm-preloaded, sovereign STT)`

---

## Task 3: docker-compose — additive `archie_whisper` service

**Files:** Modify `docker-compose.yml` (ADD one block; edit nothing existing).

- [ ] **Step 1: Read an existing lean sidecar block** for the exact network name + restart/logging conventions: `sed -n '/archie_comfyui:/,/^  [a-z]/p' docker-compose.yml` (note the `networks:` name — reuse it).

- [ ] **Step 2: Add the service** (match the network name found in Step 1; example uses `archie_net`)

```yaml
  archie_whisper:
    build: ./whisper_service
    container_name: archie_whisper
    restart: unless-stopped
    environment:
      - WHISPER_MODEL=base
      - PORT=8090
    networks:
      - archie_net
    read_only: true
    tmpfs:
      - /tmp
    mem_limit: 3g
    cpus: 2.0
```

- [ ] **Step 3: Validate** — `docker compose -f /mnt/archie_brain/docker-compose.yml config >/dev/null && echo OK` (config parses; does NOT start anything).

- [ ] **Step 4: Commit** — `chore(voice): add archie_whisper sidecar to docker-compose (CPU, isolated)`. (Build+start happens in Task 6.)

---

## Task 4: Comms — voice proxy + cockpit routes

**Files:** Create `archie-comms/services/voice_proxy.py`, `archie-comms/tests/test_voice_proxy.py`; Modify `archie-comms/app_comms.py`.

**Interfaces:** `voice_proxy.synthesize(text, user_id) -> dict` + `voice_proxy.transcribe(audio_bytes, mime) -> dict` (fail-soft). Cockpit `POST /api/voice/synthesize {text}` + `POST /api/voice/transcribe` (multipart `audio` OR json `audio_b64`), owner-only.

- [ ] **Step 1: Write the failing test** (mirror `attachment_proxy` tests: posts to the platform internal endpoints w/ Bearer; fail-soft). Include: synthesize posts `{text,user_id}` to `/api/internal/voice/synthesize`; transcribe base64s bytes to `/api/internal/voice/transcribe`; both fail-soft on error.

- [ ] **Step 2: Run RED.**

- [ ] **Step 3: Implement `voice_proxy.py`** — same shape as `attachment_proxy.py` (`_base()` = `PLATFORM_URL`, Bearer `INTERNAL_API_KEY`, try/except fail-soft). `synthesize` returns the platform dict or `{success:False,error}`; `transcribe` returns `{text}` or `{text:"",error}`.

- [ ] **Step 4: Add cockpit routes in `app_comms.py`** (owner-only, beside `/api/chat/attach`)

```python
@app.route("/api/voice/synthesize", methods=["POST"])
def api_voice_synthesize():
    from flask import session as flask_session
    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.voice_proxy import synthesize
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "no text"}), 400
    return jsonify(synthesize(text, flask_session.get("user_id")))


@app.route("/api/voice/transcribe", methods=["POST"])
def api_voice_transcribe():
    from flask import session as flask_session
    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.voice_proxy import transcribe
    f = request.files.get("audio")
    if f:
        raw = f.read(); mime = f.mimetype
    else:
        import base64
        data = request.get_json(silent=True) or {}
        try:
            raw = base64.b64decode(data.get("audio_b64") or "")
        except Exception:
            return jsonify({"text": "", "error": "bad audio"}), 400
        mime = data.get("mime")
    if len(raw) > 25 * 1024 * 1024:
        return jsonify({"text": "", "error": "audio too large"}), 413
    return jsonify(transcribe(raw, mime))
```

- [ ] **Step 5: Run GREEN.**  **Step 6: Commit** — `feat(comms): voice proxy + /api/voice/{synthesize,transcribe} cockpit routes`

---

## Task 5: Frontend — voice toggle (TTS) + mic (STT) + speaking/listening feedback

**Files:** Modify `archie-comms/templates/chat.html`, `archie-comms/static/js/archie-chat.js`, `archie-comms/static/css/archie-chat.css`. Verify: browser (Task 6).

- [ ] **Step 1: Read `_finaliseStream()` / the `done` SSE branch** to find where the completed reply text is available, and read the input-bar (now has 📎). Confirm how to grab the final reply text (streaming bubble `.ac-message-bubble` textContent).

- [ ] **Step 2: Add controls to `chat.html`** in the input bar (beside 📎): a mic button `#ac-mic-btn` (🎤) and a voice toggle `#ac-voice-toggle` (🔊, `aria-pressed`).

- [ ] **Step 3: TTS in `archie-chat.js`** — a module-level `let _voiceOn = false;` toggled by `#ac-voice-toggle` (persist in `localStorage`). In the `done` SSE branch (after `_finaliseStream`), if `_voiceOn` and the reply text is non-empty, call `_speak(text)`:
```javascript
async function _speak(text) {
  try {
    const r = await fetch('/api/voice/synthesize', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ text }) });
    const out = await r.json();
    if (!out.success || !out.audio_base64) return;      // fail-soft: no audio, no error
    _setPresence('speaking');
    const audio = new Audio('data:audio/wav;base64,' + out.audio_base64);
    audio.onended = () => _setPresence('idle');
    audio.play().catch(() => _setPresence('idle'));
  } catch (_) { _setPresence('idle'); }
}
```

- [ ] **Step 4: STT (mic) in `archie-chat.js`** — `#ac-mic-btn` toggles recording via MediaRecorder:
```javascript
let _mediaRecorder = null, _audioChunks = [];
async function _toggleMic(btn) {
  if (_mediaRecorder && _mediaRecorder.state === 'recording') { _mediaRecorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _mediaRecorder = new MediaRecorder(stream); _audioChunks = [];
    _mediaRecorder.ondataavailable = e => _audioChunks.push(e.data);
    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      btn.classList.remove('ac-recording'); _setPresence('idle');
      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      const fd = new FormData(); fd.append('audio', blob, 'clip.webm');
      try {
        const r = await fetch('/api/voice/transcribe', { method: 'POST', body: fd });
        const out = await r.json();
        if (out.text) {                     // fill the input; owner edits + sends (spec default)
          const inp = document.getElementById('ac-input');
          inp.value = (inp.value ? inp.value + ' ' : '') + out.text; inp.focus();
        }
      } catch (_) {}
    };
    _mediaRecorder.start(); btn.classList.add('ac-recording'); _setPresence('listening');
  } catch (_) { /* mic denied → owner types */ }
}
```

- [ ] **Step 5: `_setPresence(state)`** — minimal in this slice: toggle a class on the mic/voice buttons (`ac-recording` / a speaking pulse). Full avatar/presence header is Slice 4. Wire the buttons in init.

- [ ] **Step 6: CSS** — `.ac-mic-btn`/`.ac-voice-toggle` (match `.ac-attach-btn`), `.ac-recording` (red pulse), `.ac-voice-toggle[aria-pressed="true"]` (cyan active), a speaking pulse. LCARS `--ac-*` vars.

- [ ] **Step 7: `node --check`; Commit** — `feat(comms): voice toggle (TTS) + mic (STT) + speaking/listening feedback`

---

## Task 6: End-to-end deploy + live verification

- [ ] **Step 1: Build + start the sidecar** (isolated — touches nothing else): `docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_whisper`; then `docker exec archie_whisper python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8090/health').read())"` → `{ok:true}` (first build pulls faster-whisper + the base model — allow a few min).
- [ ] **Step 2: Deploy the rest** (after merge): `git -C /mnt/archie_brain pull`; `docker compose restart archie_platform`; `docker compose up -d --build archie_comms`.
- [ ] **Step 3: TTS live smoke** — `docker exec archie_comms python3 -c "import services.voice_proxy as v; o=v.synthesize('Hello Kytran, this is A.R.C.H.I.E.', 2); print('ok', o.get('success'), 'bytes', len(o.get('audio_base64') or ''))"` → success + audio.
- [ ] **Step 4: STT live smoke (round-trip)** — synthesize a clip on the platform (Kokoro WAV) → feed its bytes to `voice_service.transcribe` (or the whisper `/transcribe`) → assert non-empty transcript. This proves TTS→audio→STT sovereign-loop.
- [ ] **Step 5: Browser (P.R.O.B.E./Playwright)** at archie.kytranempowerment.com: toggle 🔊 on → send a message → hear the reply; click 🎤 → speak → the transcript fills the input → send. Presence pulses while speaking/listening.
- [ ] **Step 6: Open PR / hand to /merge-pr.**

---

## Self-Review

- **Spec coverage (§4.4):** platform `/api/internal/voice/{synthesize,transcribe}` (Task 1) · sovereign CPU Whisper sidecar (Tasks 2–3, owner-approved shape) · comms proxy + routes (Task 4) · voice toggle plays the reply + mic records→transcribes→fills input (Task 5) · speaking/listening feedback (Task 5; full avatar = Slice 4). Fail-soft everywhere (Global Constraints). Audio never leaves the cluster (CPU sidecar on the hub, Docker-internal URL).
- **Open questions resolved:** Whisper shape = CPU sidecar (owner-approved); STT default = fill input, owner sends (spec default).
- **Type consistency:** `synthesize -> {success, audio_base64, engine, ...}` used by the platform endpoint (Task 1), the comms proxy (Task 4), and `_speak` (Task 5). `transcribe -> {text}` used by the platform endpoint, the sidecar (Task 2), the comms proxy, and the mic handler.
- **Blast radius:** docker-compose gets ONE additive block; the sidecar is built+started alone (Task 6 Step 1); the shared-GPU LLM/image workloads untouched.
