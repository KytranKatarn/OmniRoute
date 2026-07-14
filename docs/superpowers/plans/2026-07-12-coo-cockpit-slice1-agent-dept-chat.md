# COO Cockpit Slice 1 — Agent & Department Chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From her cockpit chat, A.R.C.H.I.E. can consult any agent/department — she dispatches to that agent via DHQ and relays the answer in her own voice with attribution ("V.I.G.I.L. reports —"), both by natural language ("ask V.I.G.I.L. about the firewall alert") and via a crew switcher affordance.

**Architecture:** Thin cockpit + platform internal endpoints. Platform adds `GET /api/internal/coo/agents` (consultable crew) + `POST /api/internal/coo/consult {target, prompt}` (resolve target → DHQ dispatch → answer). The cockpit adds a `{{CONSULT:<target>}}` marker rail — a near-clone of the shipped `{{DEEPEN}}` async-follow-up — so she acks inline and the consulted answer arrives as a new message via the 5s poll; plus a session-authed proxy `GET /api/coo/agents` and a header switcher.

**Tech Stack:** Flask (both apps), psycopg2, DHQ dispatcher, existing SSE chat + marker-rail pattern, vanilla JS (`_mk`/textContent).

## Global Constraints

- Thin cockpit: cockpit → platform internal endpoints behind `@_require_internal_key` (Bearer `INTERNAL_API_KEY`). NEVER expose `INTERNAL_API_KEY` to the browser — the cockpit proxy calls the platform server-side.
- All inference through DHQ `dispatch(...)` (ADR-013). No direct Ollama.
- Unified voice: A.R.C.H.I.E. is the sole outbound voice; crew answers are RELAYED by her with attribution (agent name in the text + `⟨agent·model⟩` where available). No agent DMs Kytran.
- Marker-rail convention: `{{...}}` detected by a compiled `_re`, collected into events, stripped from BOTH `clean_text` AND every re-emitted token; the SSE done-event carries `agent_name`/`model_used`.
- XSS: all dynamic DOM via `_mk(tag, cls)` + `.textContent`. Never `innerHTML`.
- Fail-soft: a degraded lane never breaks the chat — she says she couldn't reach that crew member.
- In `app.py`, import `dispatch` directly (`from tools.department_hq.services.department_dispatcher import dispatch`); do NOT call `_ensure_import_paths()` (that's for standalone workers).
- Timezone: `now_utc()` for storage; `format_local` for any user-facing time. No naive `utcnow()`.

## File Structure

**Platform (`platform_v2/`)**
- `services/coo_consult_service.py` — CREATE. `list_consultable_agents()` + `resolve_consult_target(target)` (pure resolution over `agent_service` + `CAPABILITY_DEPARTMENT_MAP`).
- `app.py` — MODIFY. Add `GET /api/internal/coo/agents` + `POST /api/internal/coo/consult` beside `/api/internal/dhq/chat` (~4431).
- `tests/test_coo_consult.py` — CREATE.

**Cockpit (`archie-comms/`)**
- `services/coo_consult.py` — CREATE. `list_agents()` + `consult(target, prompt, user_id)` (server-side proxy to platform).
- `services/conversation_service.py` — MODIFY. `_CONSULT_RE`, `_CONSULT_SYSTEM_PROMPT`, `_run_consult`, `_spawn_consult`; wire into `stream_send_message`.
- `app_comms.py` — MODIFY. Add session-authed `GET /api/coo/agents`.
- `static/js/archie-chat.js` — MODIFY. Populate + wire the crew switcher.
- `templates/chat.html` — MODIFY. Switcher affordance in `.ac-chat-header`.
- `static/css/archie-chat.css` — MODIFY. Switcher styles.
- `tests/test_coo_consult.py` + `tests/test_consult_rail.py` — CREATE.

---

### Task 1: Platform — consultable-crew directory

**Files:**
- Create: `platform_v2/services/coo_consult_service.py`
- Modify: `platform_v2/app.py` (add `GET /api/internal/coo/agents` near line 4431)
- Test: `platform_v2/tests/test_coo_consult.py`

**Interfaces:**
- Produces: `list_consultable_agents() -> list[dict]` — each `{name, department, is_department_ai, title}`; the endpoint returns `{"agents": [...], "departments": [...]}`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_coo_consult.py
def test_list_consultable_agents_returns_directors(monkeypatch):
    import services.coo_consult_service as svc
    monkeypatch.setattr(svc, "_list_agents", lambda **k: [
        {"name": "V.I.G.I.L.", "department": "Security & Compliance", "is_department_ai": True, "title": "Director"},
        {"name": "R.E.S.O.L.V.E.", "department": "Customer Success & Support", "is_department_ai": True, "title": "Director"},
    ])
    out = svc.list_consultable_agents()
    names = [a["name"] for a in out]
    assert "V.I.G.I.L." in names and "R.E.S.O.L.V.E." in names
    assert all({"name", "department", "is_department_ai"} <= set(a) for a in out)


def test_agents_endpoint_requires_key(client):
    r = client.get("/api/internal/coo/agents")
    assert r.status_code == 401


def test_agents_endpoint_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coo_consult_service as svc
    monkeypatch.setattr(svc, "list_consultable_agents", lambda: [
        {"name": "V.I.G.I.L.", "department": "Security & Compliance", "is_department_ai": True, "title": "Director"}])
    r = client.get("/api/internal/coo/agents", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["agents"][0]["name"] == "V.I.G.I.L."
    assert "Security & Compliance" in body["departments"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bash /home/kytran/.claude/jobs/991c52c2/tmp/run_keepwarm_tests.sh` pattern — sync then `python -m pytest tests/test_coo_consult.py -v`
Expected: FAIL (`coo_consult_service` missing / 404 on route).

- [ ] **Step 3: Implement the service**

```python
# platform_v2/services/coo_consult_service.py
"""COO consult — resolve a consult target (agent code-name or department) to a
dispatchable agent, and list the consultable crew. Pure resolution; the endpoint
in app.py does the DHQ dispatch. Slice 1 of the COO command surface."""
from __future__ import annotations


def _list_agents(**kwargs):
    from services.agent_service import list_agents
    return list_agents(**kwargs)


def _capability_department_map() -> dict:
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP
    return CAPABILITY_DEPARTMENT_MAP


def list_consultable_agents() -> list[dict]:
    """Department directors (is_department_ai) — the crew Kytran consults through her."""
    rows = _list_agents(is_department_ai=True, status="active", limit=200)
    out = []
    for a in rows:
        out.append({
            "name": a.get("name"),
            "department": a.get("department"),
            "is_department_ai": bool(a.get("is_department_ai")),
            "title": a.get("title") or "Director",
        })
    return [a for a in out if a["name"] and a["department"]]


def _dept_capability(department: str) -> str:
    for cap, dep in _capability_department_map().items():
        if dep == department:
            return cap
    return "conversation"


def resolve_consult_target(target: str) -> dict | None:
    """target (agent code-name OR department) -> {agent_name, department, capability} or None."""
    t = (target or "").strip()
    if not t:
        return None
    tl = t.lower()
    # 1. Agent code-name (case-insensitive), among active agents.
    for a in _list_agents(status="active", limit=500):
        if (a.get("name") or "").lower() == tl:
            dep = a.get("department")
            return {"agent_name": a["name"], "department": dep, "capability": _dept_capability(dep)}
    # 2. Department name (exact or substring, case-insensitive) -> its director.
    for dep in set(_capability_department_map().values()):
        if tl == dep.lower() or tl in dep.lower():
            directors = _list_agents(department=dep, is_department_ai=True, status="active", limit=1)
            if directors:
                return {"agent_name": directors[0]["name"], "department": dep, "capability": _dept_capability(dep)}
    return None
```

- [ ] **Step 4: Add the endpoint in `app.py`** (immediately after the `/api/internal/dhq/chat` handler, ~line 4520)

```python
@app.route("/api/internal/coo/agents", methods=["GET"])
@_require_internal_key
def api_internal_coo_agents():
    """Consultable crew (department directors) + department list for the cockpit switcher."""
    try:
        from services.coo_consult_service import list_consultable_agents
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP
        agents = list_consultable_agents()
        departments = sorted(set(CAPABILITY_DEPARTMENT_MAP.values()))
        return jsonify({"success": True, "agents": agents, "departments": departments})
    except Exception as e:
        app.logger.warning("coo/agents failed: %s", e)
        return jsonify({"success": False, "agents": [], "departments": []}), 200
```

- [ ] **Step 5: Run tests — expect PASS. Commit.**

```bash
git add platform_v2/services/coo_consult_service.py platform_v2/app.py platform_v2/tests/test_coo_consult.py
git commit -m "feat(coo): platform consultable-crew directory endpoint"
```

---

### Task 2: Platform — consult resolve + dispatch endpoint

**Files:**
- Modify: `platform_v2/app.py` (add `POST /api/internal/coo/consult`)
- Test: `platform_v2/tests/test_coo_consult.py`

**Interfaces:**
- Consumes: `resolve_consult_target(target)` (Task 1); `dispatch(capability, prompt, prefer_agent=, local_only=)` → `DispatchResult(.success, .response, .agent_name, .model_used)`.
- Produces: `POST /api/internal/coo/consult {target, prompt, user_id?}` → `{success, response, agent_name, model_used, resolved_target, department}`; unknown target → `{success: False, error: "unknown_target"}` 200; unauth → 401.

- [ ] **Step 1: Write the failing test**

```python
def test_consult_unknown_target(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coo_consult_service as svc
    monkeypatch.setattr(svc, "resolve_consult_target", lambda t: None)
    r = client.post("/api/internal/coo/consult", json={"target": "nobody", "prompt": "hi"},
                    headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["success"] is False
    assert r.get_json()["error"] == "unknown_target"


def test_consult_dispatches_to_resolved_agent(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coo_consult_service as svc
    monkeypatch.setattr(svc, "resolve_consult_target",
                        lambda t: {"agent_name": "V.I.G.I.L.", "department": "Security & Compliance", "capability": "security"})
    seen = {}
    import tools.department_hq.services.department_dispatcher as dd
    class _R:
        success = True; response = "Firewall is clean."; agent_name = "V.I.G.I.L."; model_used = "qwen2.5:7b"
    monkeypatch.setattr(dd, "dispatch", lambda **k: seen.update(k) or _R())
    r = client.post("/api/internal/coo/consult", json={"target": "V.I.G.I.L.", "prompt": "firewall?"},
                    headers={"Authorization": "Bearer k"})
    b = r.get_json()
    assert b["success"] and b["agent_name"] == "V.I.G.I.L." and b["resolved_target"] == "V.I.G.I.L."
    assert seen["prefer_agent"] == "V.I.G.I.L." and seen["capability"] == "security" and seen["local_only"] is True
```

- [ ] **Step 2: Run — expect FAIL (404 route).**

- [ ] **Step 3: Add the endpoint in `app.py`** (after Task 1's endpoint)

```python
@app.route("/api/internal/coo/consult", methods=["POST"])
@_require_internal_key
def api_internal_coo_consult():
    """Resolve a consult target (agent/department) and dispatch to it via DHQ; return the answer."""
    from tools.department_hq.services.department_dispatcher import dispatch
    from services.coo_consult_service import resolve_consult_target
    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    user_id = data.get("user_id")
    if not target or not prompt:
        return jsonify({"success": False, "error": "target_and_prompt_required"}), 200
    resolved = resolve_consult_target(target)
    if not resolved:
        return jsonify({"success": False, "error": "unknown_target", "target": target}), 200
    try:
        result = dispatch(
            capability=resolved["capability"], prompt=prompt, module_id="archie_comms_coo",
            user_id=user_id, prefer_agent=resolved["agent_name"], local_only=True, priority="normal",
        )
        if not getattr(result, "success", False):
            return jsonify({"success": False, "error": "dispatch_failed",
                            "resolved_target": resolved["agent_name"]}), 200
        return jsonify({
            "success": True, "response": (result.response or "").strip(),
            "agent_name": result.agent_name, "model_used": result.model_used,
            "resolved_target": resolved["agent_name"], "department": resolved["department"],
        })
    except Exception as e:
        app.logger.warning("coo/consult failed: %s", e)
        return jsonify({"success": False, "error": "exception"}), 200
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/app.py platform_v2/tests/test_coo_consult.py
git commit -m "feat(coo): platform consult resolve+dispatch endpoint"
```

---

### Task 3: Cockpit — consult proxy service + agent-list route

**Files:**
- Create: `archie-comms/services/coo_consult.py`
- Modify: `archie-comms/app_comms.py` (add `GET /api/coo/agents`)
- Test: `archie-comms/tests/test_coo_consult.py`

**Interfaces:**
- Produces: `list_agents() -> dict {"agents":[...], "departments":[...]}` (fail-soft `{}`); `consult(target, prompt, user_id=None) -> dict | None` (the platform consult JSON or None).

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_coo_consult.py
import services.coo_consult as cc


def test_consult_posts_target_and_prompt(monkeypatch):
    seen = {}
    class _R:
        status_code = 200
        def json(self): return {"success": True, "response": "clean", "agent_name": "V.I.G.I.L.",
                                "model_used": "qwen2.5:7b", "resolved_target": "V.I.G.I.L."}
    import requests as rq
    monkeypatch.setattr(rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(json=json, url=url) or _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = cc.consult("V.I.G.I.L.", "firewall?", 4)
    assert out["agent_name"] == "V.I.G.I.L."
    assert seen["json"]["target"] == "V.I.G.I.L." and seen["json"]["prompt"] == "firewall?"
    assert seen["url"].endswith("/api/internal/coo/consult")


def test_consult_none_on_failure(monkeypatch):
    import requests as rq
    monkeypatch.setattr(rq, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cc.consult("V.I.G.I.L.", "q", 4) is None


def test_list_agents_failsoft(monkeypatch):
    import requests as rq
    monkeypatch.setattr(rq, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cc.list_agents() == {"agents": [], "departments": []}
```

- [ ] **Step 2: Run — expect FAIL (module missing).**

- [ ] **Step 3: Implement the proxy service** (mirror `conversation_service._dhq_chat_reply`'s base-URL + bearer pattern)

```python
# archie-comms/services/coo_consult.py
"""Cockpit-side proxy to the platform COO consult endpoints. Server-side only —
the INTERNAL_API_KEY never reaches the browser. Slice 1 of the COO command surface."""
import os
import requests

_PLATFORM = os.getenv("PLATFORM_INTERNAL_URL", "http://localhost:3000")


def _headers():
    return {"Content-Type": "application/json", "Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def consult(target, prompt, user_id=None):
    """Dispatch a consult to an agent/department via the platform; return its JSON or None."""
    try:
        r = requests.post(f"{_PLATFORM}/api/internal/coo/consult",
                          json={"target": target, "prompt": prompt, "user_id": user_id},
                          headers=_headers(), timeout=120)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def list_agents():
    """Consultable crew + departments for the switcher; fail-soft to empty."""
    try:
        r = requests.get(f"{_PLATFORM}/api/internal/coo/agents", headers=_headers(), timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {"agents": d.get("agents", []), "departments": d.get("departments", [])}
    except Exception:
        pass
    return {"agents": [], "departments": []}
```

> Note: confirm the platform base-URL env var name used by `_dhq_chat_reply` (Task-anchor: `conversation_service.py:36-81`) and reuse the SAME one instead of `PLATFORM_INTERNAL_URL` if it differs (e.g. `ARCHIE_HUB_URL`). Match it during implementation.

- [ ] **Step 4: Add the session-authed proxy route in `app_comms.py`** (mirror `/api/archie/avatar` at 355-370)

```python
@app.route("/api/coo/agents", methods=["GET"])
def api_coo_agents():
    from flask import session as flask_session
    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.coo_consult import list_agents
    return jsonify(list_agents())
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add archie-comms/services/coo_consult.py archie-comms/app_comms.py archie-comms/tests/test_coo_consult.py
git commit -m "feat(coo): cockpit consult proxy service + agents route"
```

---

### Task 4: Cockpit — the `{{CONSULT}}` marker rail (natural-language routing)

**Files:**
- Modify: `archie-comms/services/conversation_service.py`
- Test: `archie-comms/tests/test_consult_rail.py`

**Interfaces:**
- Consumes: `coo_consult.consult(target, prompt, user_id)` (Task 3); `save_message(conv, channel, direction, sender, content, meta)`; the `{{DEEPEN}}` pattern (`_DEEPEN_RE`@967, `_spawn_deepen`@1297).
- Produces: `_CONSULT_RE` (`\{\{CONSULT:([^}]+)\}\}`), `_CONSULT_SYSTEM_PROMPT`, `_run_consult(conv_id, channel, target, user_prompt, user_id)`, `_spawn_consult(...)`; `stream_send_message` acks inline + fires the consult; the relayed answer is saved as a follow-up (rendered by the 5s poll), attributed in-text.

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_consult_rail.py
import services.conversation_service as cs


def test_consult_marker_regex():
    assert cs._CONSULT_RE.search("On it.\n{{CONSULT:V.I.G.I.L.}}").group(1) == "V.I.G.I.L."
    assert cs._CONSULT_RE.sub("", "Checking.\n{{CONSULT:V.I.G.I.L.}}").strip() == "Checking."
    assert cs._CONSULT_RE.search("plain reply") is None


def test_consult_system_prompt_mentions_marker():
    assert "{{CONSULT:" in cs._CONSULT_SYSTEM_PROMPT


def test_run_consult_saves_attributed_followup(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_coo_consult",
                        lambda target, prompt, user_id: {"success": True, "response": "Firewall is clean.",
                                                         "agent_name": "V.I.G.I.L.", "model_used": "qwen2.5:7b"})
    monkeypatch.setattr(cs, "save_message",
                        lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content, meta=meta or {}))
    cs._run_consult(42, "web", "V.I.G.I.L.", "firewall?", 4)
    assert "V.I.G.I.L." in saved["content"] and "Firewall is clean." in saved["content"]
    assert saved["meta"].get("consult") is True and saved["meta"].get("agent") == "V.I.G.I.L."


def test_run_consult_failsoft(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_coo_consult", lambda *a, **k: None)
    monkeypatch.setattr(cs, "save_message",
                        lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content))
    cs._run_consult(42, "web", "V.I.G.I.L.", "q", 4)
    assert "couldn" in saved["content"].lower() or "reach" in saved["content"].lower()
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the rail** (near the `{{DEEPEN}}` defs; import the proxy as `_coo_consult` for test seams)

```python
# near top with other imports
from services.coo_consult import consult as _coo_consult  # noqa: E402  (test seam)

import re as _re_consult
_CONSULT_RE = _re_consult.compile(r"\{\{CONSULT:([^}]+)\}\}")

_CONSULT_SYSTEM_PROMPT = (
    "You are the COO. When Kytran asks something a specific department or agent should answer "
    "(security -> V.I.G.I.L., mail/support -> R.E.S.O.L.V.E., backups -> W.A.R.D.E.N., etc.), "
    "briefly acknowledge you're checking with them, then on its own line emit exactly "
    "{{CONSULT:<AGENT-OR-DEPARTMENT>}} (e.g. {{CONSULT:V.I.G.I.L.}}). Emit at most ONE consult marker. "
    "For anything you can answer yourself, do NOT emit it."
)


def _run_consult(conv_id, channel, target, user_prompt, user_id):
    """Dispatch the consult and save the crew answer as an attributed follow-up message."""
    try:
        res = _coo_consult(target, user_prompt, user_id)
    except Exception:
        res = None
    if res and res.get("success") and (res.get("response") or "").strip():
        agent = res.get("agent_name") or target
        model = res.get("model_used") or ""
        badge = f" · {model}" if model else ""
        content = f"**{agent}{badge}** reports —\n\n{res['response'].strip()}"
        meta = {"role": "assistant", "conversation_id": conv_id, "consult": True,
                "agent": agent, "model": model}
    else:
        content = f"I couldn't reach {target} just now — I'll try again, or I can take it myself."
        meta = {"role": "assistant", "conversation_id": conv_id, "consult": True, "agent": target,
                "consult_failed": True}
    try:
        save_message(conv_id, channel, "outbound", "archie", content, meta)
    except Exception:
        pass


def _spawn_consult(conv_id, channel, target, user_prompt, user_id):
    import threading
    threading.Thread(target=_run_consult, args=(conv_id, channel, target, user_prompt, user_id),
                     daemon=True).start()
```

- [ ] **Step 4: Wire into `stream_send_message`** — mirror the `{{DEEPEN}}` handling (append the prompt at ~1226; detect/strip at ~1270; spawn after save at ~1297).

At prompt assembly (after `_DEEPEN_SYSTEM_PROMPT` is appended):
```python
        system_prompt = f"{system_prompt}\n\n{_CONSULT_SYSTEM_PROMPT}"
```
In the marker-handling block (alongside `wants_deepen`):
```python
        consult_match = _CONSULT_RE.search(clean_text)
        consult_target = consult_match.group(1).strip() if consult_match else None
        clean_text = _CONSULT_RE.sub("", clean_text).strip()
```
Ensure the per-token re-emit also strips `_CONSULT_RE` (add it to the same strip chain used for `_DEEPEN_RE` at ~1274-1279).
After the fast reply is saved (beside the `_spawn_deepen` call ~1297):
```python
        if consult_target and conv_id:
            _spawn_consult(conv_id, channel, consult_target, user_prompt, user_id)
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add archie-comms/services/conversation_service.py archie-comms/tests/test_consult_rail.py
git commit -m "feat(coo): {{CONSULT}} rail — she consults the crew, relays as an attributed follow-up"
```

---

### Task 5: Cockpit — crew switcher affordance (frontend)

**Files:**
- Modify: `archie-comms/templates/chat.html` (switcher in `.ac-chat-header`, ~57)
- Modify: `archie-comms/static/js/archie-chat.js` (populate + wire)
- Modify: `archie-comms/static/css/archie-chat.css`

**Interfaces:**
- Consumes: `GET /api/coo/agents` (Task 3); the send flow (`send()` @130-232); `_mk`/textContent (@7-11).
- Produces: a `#ac-crew-switcher` `<select>`; when a crew member is selected and Kytran sends, the message is prefixed so the `{{CONSULT}}` path targets that agent deterministically (explicit lane), then the switcher resets to "A.R.C.H.I.E.".

- [ ] **Step 1: Add the switcher to `chat.html`** (inside `.ac-chat-header`, after the focus toggle ~57)

```html
<select id="ac-crew-switcher" class="ac-crew-switcher" aria-label="Consult a department director">
  <option value="">A.R.C.H.I.E.</option>
</select>
```

- [ ] **Step 2: Populate + wire in `archie-chat.js`** (call on init; adjust `send` to honor the selection)

```javascript
async _loadCrew() {
  try {
    const r = await fetch('/api/coo/agents', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    const sel = document.getElementById('ac-crew-switcher');
    if (!sel || !Array.isArray(d.agents)) return;
    d.agents.forEach(a => {
      const opt = _mk('option');
      opt.value = a.name;                              // textContent-only: XSS-safe
      opt.textContent = a.name + ' — ' + a.department;
      sel.appendChild(opt);
    });
  } catch (e) { /* fail-soft: switcher stays A.R.C.H.I.E.-only */ }
}
```
In `send(...)`, before POSTing, if a crew member is selected, target them explicitly and reset:
```javascript
    const sel = document.getElementById('ac-crew-switcher');
    const crew = sel && sel.value;
    let outbound = message;
    if (crew) { outbound = 'Consult ' + crew + ': ' + message; sel.value = ''; }
    // ...use `outbound` as the POST body's message instead of `message`
```
Call `this._loadCrew()` where the cockpit initializes (beside `_loadAvatar()`).

- [ ] **Step 3: Style in `archie-chat.css`** (match the LCARS header controls)

```css
.ac-crew-switcher {
  background: var(--ac-panel, #10151c); color: var(--ac-text, #cfe3ff);
  border: 1px solid var(--ac-line, #24405c); border-radius: 6px;
  padding: 4px 8px; font-size: 12px; max-width: 220px;
}
```

- [ ] **Step 4: Verify** (no unit-test harness for the cockpit JS — match Slice-4 practice)

Run: `node --check archie-comms/static/js/archie-chat.js`
Expected: clean (no syntax error). Live click-through is covered in the deploy-verify below.

- [ ] **Step 5: Commit.**

```bash
git add archie-comms/templates/chat.html archie-comms/static/js/archie-chat.js archie-comms/static/css/archie-chat.css
git commit -m "feat(coo): crew switcher affordance in the cockpit header"
```

---

## Deploy & verify (after all tasks green)

- Platform is volume-mounted: `docker restart archie_platform` (new routes) — or `docker compose up -d --no-deps archie_platform` if env changed.
- Cockpit is image-baked: `cd archie-comms && docker compose up -d --build archie_comms`.
- Live check (sanctioned dispatch path, internal key server-side):
  - `GET /api/internal/coo/agents` returns directors.
  - A cockpit chat "ask V.I.G.I.L. about the firewall" → fast ack + a follow-up "**V.I.G.I.L. · <model>** reports — …" arriving via the poll.
  - The switcher lists the crew; picking one + sending routes to that agent.

## Self-Review

- **Spec coverage:** Consult lane (Tasks 1-4) ✓; NL routing (`{{CONSULT}}` rail, Task 4) ✓; department/agent switcher (Task 5) ✓; unified voice + attribution (relay framing + meta, Task 4) ✓; DHQ dispatch + local_only + welfare/cost (Task 2) ✓; fail-soft each lane (Tasks 2-4) ✓; auth split + no key in browser (Tasks 1-3) ✓. Module chats: a module's director is an agent target, so they fall out of the same resolver — no extra task.
- **Placeholder scan:** one deliberate implementation-time confirmation (the platform base-URL env var name in Task 3) — flagged inline with the exact function to copy from, not a blank TODO.
- **Type consistency:** `resolve_consult_target` returns `{agent_name, department, capability}` (produced Task 1, consumed Task 2); `consult(...)` returns the platform JSON with `agent_name`/`model_used`/`response` (produced Task 3, consumed Task 4); `_CONSULT_RE` group(1) = target throughout.
