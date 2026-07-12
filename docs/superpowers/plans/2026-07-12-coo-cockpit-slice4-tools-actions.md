# COO Cockpit Slice 4 — Tools & Actions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From her cockpit chat, A.R.C.H.I.E. runs a curated set of SAFE diagnostic actions (health, QA, dep-drift, misroute audit, briefing health) and relays the result as a follow-up — the last slice of the COO command surface.

**Architecture:** Thin cockpit + platform internal endpoints (Slice-1/2/3 pattern). A curated catalog maps action keys → SAFE known-tool capabilities; `run_action` executes them SYNCHRONOUSLY via `delegation_service._execute_known_tool` (no worker/poll). A `{{ACTION:<key>}}` marker rail (clone of `{{CONSULT}}`) runs the action in a background thread and saves the result as a follow-up; a quick-action bar triggers the same via the normal send flow. Only catalog keys run — nothing state-changing. Slice 4 of `docs/superpowers/specs/2026-07-12-archie-coo-command-surface-design.md`.

**Tech Stack:** Flask (both apps), the DHQ known-tool shortcuts, the LCARS tab/quick-action system, vanilla JS (`_mk`/textContent).

## Global Constraints

- Thin cockpit → platform internal endpoints behind `@_require_internal_key`; key NEVER reaches the browser.
- **Curated SAFE actions ONLY.** `run_action` runs a key ONLY if it's in the fixed `_CATALOG` (health_check, check_platform_health, check_dep_drift, run_misroute_audit, run_briefing_health, run_qa_suite). Any other key → rejected. State-changing/gated capabilities (deploy_*, restore_*, run_misroute_to_proposal_adapter, external_fetch) are NOT in the catalog — they can't run via this lane. Sensitive work still goes through the existing `{{DELEGATE}}` rail → DHQ → approval.
- Result relayed in her voice as a follow-up (`save_message` + the 5s poll), like `{{CONSULT}}`. Unified voice.
- XSS: `_mk`+textContent only. Fail-soft. `PLATFORM_URL` base. Don't duplicate `{{DELEGATE}}`.

## File Structure

**Platform (`platform_v2/`)**
- `services/coo_actions_service.py` — CREATE. `_CATALOG` + `list_actions()` + `run_action(key)`.
- `app.py` — MODIFY. `GET /api/internal/actions/catalog` + `POST /api/internal/actions/run` (insert at line ~4680, after the mail endpoints).
- `tests/test_coo_actions.py` — CREATE.

**Cockpit (`archie-comms/`)**
- `services/coo_actions.py` — CREATE. `catalog()` + `run(key)` proxies.
- `app_comms.py` — MODIFY. `GET /api/actions/catalog` + `POST /api/actions/run` (after `api_mail_queue_reply`, ~line 452).
- `services/conversation_service.py` — MODIFY. `_ACTION_RE` + `_ACTION_SYSTEM_PROMPT` + `_run_action` + `_spawn_action`; wire into `stream_send_message`.
- `templates/chat.html` — MODIFY. Action chips in a new `#ac-actions-bar`.
- `static/js/archie-chat.js` — MODIFY. Populate + wire the action chips.
- `static/css/archie-chat.css` — MODIFY. Action-bar styles.
- `tests/test_coo_actions.py` + `tests/test_action_rail.py` — CREATE.

---

### Task 1: Platform — actions catalog + synchronous run

**Files:**
- Create: `platform_v2/services/coo_actions_service.py`
- Modify: `platform_v2/app.py` (add `GET /api/internal/actions/catalog` + `POST /api/internal/actions/run`)
- Test: `platform_v2/tests/test_coo_actions.py`

**Interfaces:**
- Consumes: `delegation_service._execute_known_tool(capability, payload, reason) -> {success, summary, result, error?}`.
- Produces: `list_actions() -> list[dict]` (`{key, label, description}`); `run_action(key) -> {ok, label, summary, result} | {ok: False, error}`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_coo_actions.py
def test_list_actions_is_curated_safe(monkeypatch):
    import services.coo_actions_service as svc
    out = svc.list_actions()
    keys = {a["key"] for a in out}
    assert "health" in keys and "qa" in keys
    # No state-changing capability leaks into the catalog:
    caps = {svc._CATALOG[a["key"]]["capability"] for a in out}
    assert not (caps & {"deploy_static", "deploy_vps", "restore_production", "run_misroute_to_proposal_adapter"})


def test_run_action_rejects_unknown_key():
    import services.coo_actions_service as svc
    assert svc.run_action("nope")["ok"] is False


def test_run_action_executes_known_tool(client, monkeypatch):
    # `client` boots the app so delegation_service imports with the ai_bridge path (KB #272154).
    import services.coo_actions_service as svc
    import services.delegation_service as dsvc
    seen = {}
    monkeypatch.setattr(
        dsvc, "_execute_known_tool",
        lambda cap, payload, reason: seen.update(cap=cap) or {"success": True, "summary": "All green", "result": {"ok": 1}},
    )
    out = svc.run_action("health")
    assert out["ok"] and out["summary"] == "All green" and seen["cap"] == "check_platform_health"


def test_actions_catalog_endpoint(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.get("/api/internal/actions/catalog", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and any(a["key"] == "health" for a in r.get_json()["actions"])


def test_actions_run_endpoint_requires_key(client):
    assert client.post("/api/internal/actions/run", json={"key": "health"}).status_code == 401
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the service**

```python
# platform_v2/services/coo_actions_service.py
"""COO command surface — Tools & Actions (Slice 4). A CURATED, SAFE catalog of known-tool
diagnostics she runs from the cockpit chat. run_action executes them synchronously via the
delegation service's known-tool path. Only catalog keys run — nothing state-changing."""
from __future__ import annotations

# key -> {label, capability, description}. SAFE read-only diagnostics ONLY. Do NOT add
# state-changing capabilities (deploy_*, restore_*, *_proposal_adapter, external_fetch, ...).
_CATALOG = {
    "health": {"label": "Platform health", "capability": "check_platform_health",
               "description": "Live platform + service health."},
    "qa": {"label": "QA suite", "capability": "run_qa_suite",
           "description": "Run the platform QA test suite."},
    "dep_drift": {"label": "Dependency drift", "capability": "check_dep_drift",
                  "description": "Check for dependency drift."},
    "misroute_audit": {"label": "Misroute audit", "capability": "run_misroute_audit",
                       "description": "Audit agent dispatch misroutes."},
    "briefing_health": {"label": "Briefing health", "capability": "run_briefing_health",
                        "description": "Check the session-briefing pipeline."},
}


def list_actions():
    return [{"key": k, "label": v["label"], "description": v["description"]} for k, v in _CATALOG.items()]


def run_action(key):
    entry = _CATALOG.get((key or "").strip())
    if not entry:
        return {"ok": False, "error": "unknown_action"}
    try:
        from services.delegation_service import _execute_known_tool

        res = _execute_known_tool(entry["capability"], {}, f"Cockpit action: {entry['label']}")
        if res and res.get("success"):
            return {"ok": True, "label": entry["label"], "summary": res.get("summary") or "",
                    "result": res.get("result")}
        return {"ok": False, "label": entry["label"], "error": (res or {}).get("error") or "failed"}
    except Exception:
        return {"ok": False, "label": entry["label"], "error": "exception"}
```

- [ ] **Step 4: Add the 2 endpoints in `app.py`** (after `api_internal_mail_queue_reply`, ~line 4680)

```python
@app.route("/api/internal/actions/catalog", methods=["GET"])
@_require_internal_key
def api_internal_actions_catalog():
    """Curated safe actions the cockpit can run (Slice 4). Fail-soft."""
    try:
        from services.coo_actions_service import list_actions

        return jsonify({"success": True, "actions": list_actions()})
    except Exception as e:
        logger.warning(f"actions/catalog failed: {e}")
        return jsonify({"success": False, "actions": []}), 200


@app.route("/api/internal/actions/run", methods=["POST"])
@_require_internal_key
def api_internal_actions_run():
    """Run a curated safe action synchronously (Slice 4). Only catalog keys run. Fail-soft."""
    try:
        from services.coo_actions_service import run_action

        data = request.get_json(silent=True) or {}
        return jsonify(run_action(data.get("key") or ""))
    except Exception as e:
        logger.warning(f"actions/run failed: {e}")
        return jsonify({"ok": False, "error": "exception"}), 200
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add platform_v2/services/coo_actions_service.py platform_v2/app.py platform_v2/tests/test_coo_actions.py
git commit -m "feat(coo): platform Tools & Actions — curated safe action catalog + sync run (Slice 4)"
```

---

### Task 2: Cockpit — actions proxy + session routes

**Files:**
- Create: `archie-comms/services/coo_actions.py`
- Modify: `archie-comms/app_comms.py`
- Test: `archie-comms/tests/test_coo_actions.py`

**Interfaces:**
- Produces: `catalog() -> {actions:[...]}`; `run(key) -> dict` (platform result or fail-soft).

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_coo_actions.py
import services.coo_actions as ca


def test_run_posts_key(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"ok": True, "label": "Platform health", "summary": "green"}

    import requests as rq
    monkeypatch.setattr(rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(url=url, json=json) or _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ca.run("health")
    assert out["ok"] and seen["json"]["key"] == "health" and seen["url"].endswith("/api/internal/actions/run")


def test_catalog_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert ca.catalog() == {"actions": []}
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the proxy** (mirror `coms_hub.py`)

```python
# archie-comms/services/coo_actions.py
"""Cockpit-side proxy to the platform Tools & Actions endpoints. Server-side only —
INTERNAL_API_KEY never reaches the browser. Curated safe actions. Slice 4 of the COO command surface."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def catalog():
    try:
        r = requests.get(f"{_base()}/api/internal/actions/catalog", headers=_headers(), timeout=15)
        if r.status_code == 200:
            return {"actions": r.json().get("actions", [])}
    except Exception as e:
        logger.warning("actions catalog proxy failed: %s", e)
    return {"actions": []}


def run(key):
    try:
        r = requests.post(
            f"{_base()}/api/internal/actions/run",
            json={"key": key},
            headers=_headers(),
            timeout=float(os.getenv("ACTION_TIMEOUT", "120")),
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("actions run proxy failed: %s", e)
    return {"ok": False, "error": "unreachable"}
```

- [ ] **Step 4: Add the 2 session routes in `app_comms.py`** (after `api_mail_queue_reply`, ~line 452)

```python
@app.route("/api/actions/catalog", methods=["GET"])
def api_actions_catalog():
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.coo_actions import catalog

    return jsonify(catalog())


@app.route("/api/actions/run", methods=["POST"])
def api_actions_run():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.coo_actions import run

    return jsonify(run((fr.get_json(silent=True) or {}).get("key") or ""))
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add archie-comms/services/coo_actions.py archie-comms/app_comms.py archie-comms/tests/test_coo_actions.py
git commit -m "feat(coo): cockpit Tools & Actions proxy + session routes (Slice 4)"
```

---

### Task 3: Cockpit — the `{{ACTION}}` marker rail (natural-language)

**Files:**
- Modify: `archie-comms/services/conversation_service.py`
- Test: `archie-comms/tests/test_action_rail.py`

**Interfaces:**
- Consumes: `coo_actions.run(key)` (Task 2); `save_message`; the `{{CONSULT}}` shape (`_run_consult`/`_spawn_consult`).
- Produces: `_ACTION_RE` (`\{\{ACTION:([^}]+)\}\}`), `_ACTION_SYSTEM_PROMPT`, `_run_action`, `_spawn_action`; `stream_send_message` acks + runs the action; the result arrives as a follow-up.

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_action_rail.py
import services.conversation_service as cs


def test_action_marker_regex():
    assert cs._ACTION_RE.search("On it.\n{{ACTION:health}}").group(1) == "health"
    assert cs._ACTION_RE.sub("", "Running.\n{{ACTION:qa}}").strip() == "Running."


def test_action_system_prompt_lists_keys():
    assert "{{ACTION:" in cs._ACTION_SYSTEM_PROMPT and "health" in cs._ACTION_SYSTEM_PROMPT


def test_run_action_saves_followup(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_coo_action",
                        lambda key: {"ok": True, "label": "Platform health", "summary": "All systems green."})
    monkeypatch.setattr(cs, "save_message",
                        lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content, meta=meta or {}))
    cs._run_action(42, "web", "health", 4)
    assert "Platform health" in saved["content"] and "All systems green." in saved["content"]
    assert saved["meta"].get("action") is True


def test_run_action_failsoft(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_coo_action", lambda key: {"ok": False, "error": "x", "label": "QA suite"})
    monkeypatch.setattr(cs, "save_message",
                        lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content))
    cs._run_action(42, "web", "qa", 4)
    assert "couldn" in saved["content"].lower() or "could not" in saved["content"].lower()
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the rail** (near the `{{CONSULT}}` defs; import the proxy as `_coo_action`)

```python
from services.coo_actions import run as _coo_action  # noqa: E402  (module-level test seam)

_ACTION_RE = _re.compile(r"\{\{ACTION:([^}]+)\}\}")

_ACTION_SYSTEM_PROMPT = (
    "[RUN ACTION] You can run these safe diagnostics on request: health (platform health), "
    "qa (test suite), dep_drift (dependency drift), misroute_audit (agent misroutes), "
    "briefing_health (session-briefing pipeline). When Kytran asks you to RUN or CHECK one of these, "
    "briefly say you're running it, then on its own line emit exactly {{ACTION:<key>}} (e.g. "
    "{{ACTION:health}}). Emit AT MOST ONE. For anything else, do NOT emit it."
)


def _run_action(conv_id, channel, key, user_id):
    """Run a curated safe action and save the result as a follow-up (her voice; the poll delivers it)."""
    ctx = None
    try:
        from app_comms import app

        ctx = app.app_context()
        ctx.push()
    except Exception:  # pragma: no cover
        ctx = None
    try:
        try:
            res = _coo_action(key)
        except Exception:  # pragma: no cover
            res = None
        if res and res.get("ok"):
            label = res.get("label") or key
            summary = (res.get("summary") or "").strip() or "Done — no issues reported."
            content = f"**{label}** — {summary}"
            meta = {"role": "assistant", "conversation_id": conv_id, "action": True, "key": key}
        else:
            label = (res or {}).get("label") or key
            content = f"I couldn't run **{label}** just now — I'll try again."
            meta = {"role": "assistant", "conversation_id": conv_id, "action": True, "key": key, "action_failed": True}
        save_message(conv_id, channel, "outbound", "archie", content, meta)
    except Exception as exc:  # pragma: no cover
        logger.warning("action worker error: %s", exc)
    finally:
        if ctx is not None:
            ctx.pop()


def _spawn_action(conv_id, channel, key, user_id):
    import threading

    threading.Thread(target=_run_action, args=(conv_id, channel, key, user_id), daemon=True).start()
```

- [ ] **Step 4: Wire into `stream_send_message`** — mirror the `{{CONSULT}}` wiring.

Append to the system prompt (after `_CONSULT_SYSTEM_PROMPT`):
```python
        system_prompt = f"{system_prompt}\n\n{_ACTION_SYSTEM_PROMPT}"
```
In the marker block (beside `consult_target`):
```python
        _action_match = _ACTION_RE.search(clean_text)
        action_key = _action_match.group(1).strip() if _action_match else None
        clean_text = _ACTION_RE.sub("", clean_text).strip()
```
Add `_ACTION_RE.sub("", clean_token)` to the per-token strip chain (beside `_CONSULT_RE`).
After the `_spawn_consult` call:
```python
        if action_key and conv_id:
            _spawn_action(conv_id, channel, action_key, user_id)
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add archie-comms/services/conversation_service.py archie-comms/tests/test_action_rail.py
git commit -m "feat(coo): {{ACTION}} rail — she runs curated safe diagnostics, relays the result (Slice 4)"
```

---

### Task 4: Cockpit — the quick-action bar (frontend)

**Files:**
- Modify: `archie-comms/templates/chat.html` (add `#ac-actions-bar` above the input)
- Modify: `archie-comms/static/js/archie-chat.js` (`_loadActions()` + wire)
- Modify: `archie-comms/static/css/archie-chat.css`

**Interfaces:**
- Consumes: `GET /api/actions/catalog` (Task 2); the send flow (`#ac-input` + `#ac-send-btn`); `_mk`/textContent.
- Produces: action chips that send a run-request through the normal chat flow (so the `{{ACTION}}` rail fires) — deterministic via the real send button.

- [ ] **Step 1: Add the bar to `chat.html`** (just above `.ac-input-bar`, ~line 70)

```html
<div class="ac-actions-bar" id="ac-actions-bar"></div>
```

- [ ] **Step 2: Populate + wire in `archie-chat.js`** (call on init, beside `_loadCrew()`)

```javascript
async function _loadActions() {
  const bar = document.getElementById('ac-actions-bar');
  if (!bar) return;
  try {
    const r = await fetch('/api/actions/catalog', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    if (!Array.isArray(d.actions)) return;
    d.actions.forEach((a) => {
      if (!a || !a.key) return;
      const chip = _mk('button', 'ac-action-chip');
      chip.type = 'button';
      chip.textContent = '⚡ ' + (a.label || a.key);
      chip.title = a.description || '';
      chip.addEventListener('click', () => {
        const input = document.getElementById('ac-input');
        const send = document.getElementById('ac-send-btn');
        if (input && send) { input.value = 'Run the ' + (a.label || a.key) + ' action'; send.click(); }
      });
      bar.appendChild(chip);
    });
  } catch (e) { /* fail-soft: no action chips */ }
}
```
Call `_loadActions();` in the DOMContentLoaded init (beside `_loadCrew();`).

- [ ] **Step 3: Style in `archie-chat.css`** (append)

```css
/* Tools & Actions bar (Slice 4) */
.ac-actions-bar { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 12px 0; }
.ac-action-chip { background: var(--ac-panel, #10151c); color: var(--ac-text-dim, #9fb4c8);
  border: 1px solid var(--ac-line, #24405c); border-radius: 14px; padding: 3px 10px; font-size: 11px; cursor: pointer; }
.ac-action-chip:hover { color: var(--ac-accent, #00e5ff); border-color: var(--ac-accent, #00e5ff); }
```

- [ ] **Step 4: Verify** `node --check archie-comms/static/js/archie-chat.js` — clean.

- [ ] **Step 5: Commit.**

```bash
git add archie-comms/templates/chat.html archie-comms/static/js/archie-chat.js archie-comms/static/css/archie-chat.css
git commit -m "feat(coo): quick-action bar in the cockpit — one-tap safe diagnostics (Slice 4)"
```

---

## Deploy & verify (after all tasks green)

- Platform: `docker restart archie_platform`. Cockpit: `docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_comms`.
- Live: `GET /api/internal/actions/catalog` lists the safe actions; `POST /api/internal/actions/run {"key":"health"}` returns `{ok:true, summary}`; `{"key":"deploy_vps"}` → `unknown_action` (rejected). Open the cockpit → the action chips render; "run a health check" → she acks + a follow-up with the result.

## Self-Review

- **Spec coverage:** run curated skills/tools from chat (Tasks 1-4) ✓; tier-gated/safe (catalog is SAFE-only; state-changing rejected + still routed via the existing `{{DELEGATE}}`→approval) ✓; result as a follow-up (Task 3, `save_message`+poll) ✓; quick-action affordance (Task 4) ✓; thin-cockpit + internal-endpoint + proxy + rail pattern ✓; no `{{DELEGATE}}` duplication (distinct `{{ACTION}}` rail; sensitive work still uses DELEGATE) ✓.
- **Placeholder scan:** none.
- **Type consistency:** `run_action`/`run` return `{ok, label, summary}` (produced Task 1, proxied Task 2, rendered Task 3); `_CATALOG` keys (`health`/`qa`/`dep_drift`/`misroute_audit`/`briefing_health`) match the system prompt + the tests.
