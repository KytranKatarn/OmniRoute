# COO Cockpit — Slice 1: Approvals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Kytran approve/deny Tier-2 findings (including the 77 red Code-Health cards) directly from the `archie_comms` cockpit — both by talking to A.R.C.H.I.E. ("approve the family_tree one") and by clicking a right-rail Approvals panel.

**Architecture:** The cockpit stays a thin presentation layer. New `@_require_internal_key` platform endpoints wrap the *existing* `_approve_autonomy`/`_deny_autonomy`/`approvals_pending` logic; the cockpit adds thin proxy routes (Bearer `INTERNAL_API_KEY`), a `{{APPROVE}}`/`{{APPROVALS}}` chat-marker rail beside the existing `{{DELEGATE}}` one, and a panel that reuses the existing `DelegationCard`.

**Tech Stack:** Python 3.11 / Flask (platform + comms), SSE, `requests` (comms→platform), vanilla JS (comms LCARS frontend). Spec: `docs/superpowers/specs/2026-07-11-archie-coo-cockpit-design.md`.

## Global Constraints

*(Every task's requirements implicitly include this section — values verbatim from the spec + grounding.)*

- **Thin sovereign cockpit:** comms adds UI + thin proxies only. All approval *execution* stays on the platform behind `@_require_internal_key` (the `/api/internal/dhq/chat` pattern). No business logic, no new secrets, no persistence in comms.
- **Owner-only:** the cockpit is admin-gated (kytran_auth OIDC). Kytran = `user_id=2`. Internal calls carry no `current_user` → the cockpit passes the logged-in `user_id` explicitly; the platform internal endpoint defaults to `2` when absent.
- **Approvals fail-CLOSED:** any proxy/exec error surfaces the failure and leaves the approval **pending** — never optimistically "approved". (Contrast: chat reply is fail-soft.)
- **Reuse, don't duplicate:** `_approve_autonomy`/`_deny_autonomy`/`approvals_pending`/`_code_fix_label` (PR #2205) already exist — wrap them, do not reimplement.
- **`approval_id` is source-prefixed** — e.g. `autonomy:123`. Every endpoint takes the full prefixed id (Flask `<path:approval_id>`), same as the existing session routes.
- **Deploy:** comms is **image-baked** → `docker compose up -d --build archie_comms`. Platform `platform_v2/` is **volume-mounted** → `docker compose restart archie_platform`.
- **Testing harness:** platform tests import from `/app` (= main checkout). Because a feature branch is NOT mounted, run platform unit tests against a synced bundle of the worktree: `tar -C <worktree> -cf - platform_v2 | docker exec -i archie_platform sh -c 'rm -rf /tmp/wt && mkdir -p /tmp/wt && tar -xf - -C /tmp/wt'` then `docker exec -w /tmp/wt/platform_v2 archie_platform python3 -m pytest tests/<file> -v`. Comms tests run in a host venv with flask/flask-login/requests/pytest installed, `cwd=archie-comms`.
- **Never push to main; feature branch + PR; per-task commits** with the messages below.

---

## File Structure

| File | Responsibility |
|---|---|
| `platform_v2/tools/department_hq/approvals_routes.py` | **modify** — extract `list_pending_approvals()` + `parse_approval_id()` as callables the session routes AND the new internal endpoints share |
| `platform_v2/app.py` | **modify** — 3 new `@_require_internal_key` endpoints: internal pending/approve/deny |
| `platform_v2/tests/test_internal_approvals.py` | new — platform internal-endpoint tests |
| `archie-comms/services/approvals_proxy.py` | new — `list_pending()/approve()/deny()` → platform internal (Bearer key); fail-closed |
| `archie-comms/app_comms.py` | **modify** — cockpit routes `GET /api/approvals/pending`, `POST /api/approvals/<id>/approve|deny`; handle the new chat SSE events |
| `archie-comms/services/conversation_service.py` | **modify** — `{{APPROVALS}}`/`{{APPROVE}}`/`{{DENY}}` markers + `_APPROVALS_SYSTEM_PROMPT` |
| `archie-comms/tests/test_approvals_proxy.py` | new — proxy + fail-closed tests |
| `archie-comms/tests/test_approval_markers.py` | new — marker parse/strip tests |
| `archie-comms/static/js/archie-chat.js` | **modify** — `ApprovalCard` + right-rail panel + chat-native rendering |
| `archie-comms/templates/chat.html` | **modify** — right-rail Approvals panel container |

---

## Task 1: Platform — extract shared approvals helpers + internal pending endpoint

Refactor the session route's query into a plain callable so the internal endpoint reuses it, then expose an internal-key pending list.

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`
- Modify: `platform_v2/app.py`
- Test: `platform_v2/tests/test_internal_approvals.py`

**Interfaces:**
- Produces: `list_pending_approvals() -> list[dict]` (the unified pending list, no Flask/session) and `parse_approval_id(approval_id) -> (source: str, source_id: int)` in `approvals_routes.py`.
- Produces: `GET /api/internal/approvals/pending` → `{"approvals": [...]}`.

- [ ] **Step 1: Read the current route to extract cleanly**

Run: `docker exec archie_platform sh -c "sed -n '305,360p' /app/tools/department_hq/approvals_routes.py; grep -n 'def approvals_pending\|split(.:.)\|def _approve_autonomy\|def approvals_approve' /app/tools/department_hq/approvals_routes.py"`
Confirm: the pending query body, and exactly how `approvals_approve` splits `approval_id` into `(source, source_id)` (reuse it verbatim in `parse_approval_id`).

- [ ] **Step 2: Write the failing test**

```python
# platform_v2/tests/test_internal_approvals.py
import importlib


def test_parse_approval_id_splits_source_and_int():
    ar = importlib.import_module("tools.department_hq.approvals_routes")
    assert ar.parse_approval_id("autonomy:123") == ("autonomy", 123)
    assert ar.parse_approval_id("contractor:7") == ("contractor", 7)


def test_list_pending_approvals_is_callable_without_flask():
    ar = importlib.import_module("tools.department_hq.approvals_routes")
    # must be a plain function (no request/current_user access) returning a list
    result = ar.list_pending_approvals()
    assert isinstance(result, list)
```

- [ ] **Step 3: Run test to verify it fails**

Sync the bundle (Global Constraints), then:
Run: `docker exec -w /tmp/wt/platform_v2 archie_platform python3 -m pytest tests/test_internal_approvals.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'parse_approval_id'`

- [ ] **Step 4: Extract the helpers in `approvals_routes.py`**

At module level (before `register_approvals_routes`), add:

```python
def parse_approval_id(approval_id):
    """('autonomy:123') -> ('autonomy', 123). Mirrors the split the session
    approve/deny routes already do."""
    source, _, sid = str(approval_id).partition(":")
    return source, int(sid)


def list_pending_approvals():
    """Unified pending Tier-2 approvals (autonomy + contractor + bridge), as a
    plain list of dicts — no Flask/session. Shared by the @admin_required route
    and the @_require_internal_key internal endpoint."""
    from database import get_db_cursor

    approvals = []
    with get_db_cursor() as (conn, cur):
        # ... MOVE the exact query + row-shaping body of approvals_pending() here,
        # returning `approvals` (the code-fix label logic from PR #2205 stays) ...
        pass
    return approvals
```

Then change the existing `approvals_pending()` route body to `return jsonify({"approvals": list_pending_approvals()})` (preserve its current top-level key — confirm in Step 1 whether it's `approvals` or a bare list, and match it).

- [ ] **Step 5: Add the internal pending endpoint in `app.py`**

Beside the other `@_require_internal_key` endpoints (after `api_internal_session_link`):

```python
@app.route("/api/internal/approvals/pending", methods=["GET"])
@_require_internal_key
def api_internal_approvals_pending():
    """Cockpit-facing pending Tier-2 approvals. Service-to-service: Bearer
    INTERNAL_API_KEY. Reuses the same list the DHQ Approvals tab renders."""
    from tools.department_hq.approvals_routes import list_pending_approvals

    return jsonify({"approvals": list_pending_approvals()})
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker exec -w /tmp/wt/platform_v2 archie_platform python3 -m pytest tests/test_internal_approvals.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py platform_v2/app.py platform_v2/tests/test_internal_approvals.py
git commit -m "feat(approvals): shared list_pending_approvals + parse_approval_id + internal pending endpoint"
```

---

## Task 2: Platform — internal approve/deny endpoints

Wrap the existing `_approve_autonomy`/`_deny_autonomy` behind the internal key, defaulting the owner id.

**Files:**
- Modify: `platform_v2/app.py`
- Test: `platform_v2/tests/test_internal_approvals.py` (extend)

**Interfaces:**
- Consumes: `parse_approval_id` (Task 1), `_approve_autonomy(source_id, user_id) -> (ok, action_type)`, `_deny_autonomy(source_id, user_id, reason) -> (ok, ...)` from `approvals_routes`.
- Produces: `POST /api/internal/approvals/<path:approval_id>/approve {user_id?}` → `{ok, action_type}`; `.../deny {user_id?, reason?}` → `{ok}`.

- [ ] **Step 1: Confirm the executor signatures**

Run: `docker exec archie_platform sh -c "grep -n 'def _approve_autonomy\|def _deny_autonomy\|def _approve_contractor\|def _approve_bridge' /app/tools/department_hq/approvals_routes.py"`
Confirm the exact params + return of `_approve_autonomy`/`_deny_autonomy` (Task 3 of the grounding said `(source_id, user_id)` → `(ok, action_type)`). Note whether contractor/bridge sources need separate branches (Slice 1 targets `autonomy:*` — the red cards; branch on `source` and 501 the others for now).

- [ ] **Step 2: Write the failing test**

```python
# append to platform_v2/tests/test_internal_approvals.py
import json


def _client(monkeypatch):
    # load app.py directly (conftest pattern) and stub the executor
    import importlib
    app_mod = importlib.import_module("app") if importlib.util.find_spec("app") else None
    from app import app as flask_app  # conftest _load_flask_app also works
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_internal_approve_requires_key(client):
    r = client.post("/api/internal/approvals/autonomy:123/approve", json={})
    assert r.status_code == 401


def test_internal_approve_routes_to_executor(client, monkeypatch):
    import tools.department_hq.approvals_routes as ar
    seen = {}
    monkeypatch.setattr(ar, "_approve_autonomy", lambda sid, uid: seen.update(sid=sid, uid=uid) or (True, "improvement_approve_red"))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/approvals/autonomy:123/approve",
                    json={"user_id": 2}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert seen == {"sid": 123, "uid": 2}
```

*(Use the repo's `client` fixture from `platform_v2/tests/conftest.py`; it loads `app.py` and sets `INTERNAL_API_KEY` via env — confirm and adapt the key-setting to how `_require_internal_key` reads it.)*

- [ ] **Step 3: Run test to verify it fails**

Run: `docker exec -w /tmp/wt/platform_v2 archie_platform python3 -m pytest tests/test_internal_approvals.py -k internal_approve -v`
Expected: FAIL — 404 (route missing)

- [ ] **Step 4: Add the endpoints in `app.py`**

```python
@app.route("/api/internal/approvals/<path:approval_id>/approve", methods=["POST"])
@_require_internal_key
def api_internal_approvals_approve(approval_id):
    """Cockpit approve. Bearer INTERNAL_API_KEY; owner user_id from body
    (default 2 — Kytran). Fail-closed: any error -> 500, row stays pending."""
    from tools.department_hq.approvals_routes import parse_approval_id, _approve_autonomy

    user_id = (request.get_json(silent=True) or {}).get("user_id") or 2
    source, source_id = parse_approval_id(approval_id)
    if source != "autonomy":
        return jsonify({"ok": False, "error": f"source '{source}' not supported yet"}), 501
    ok, action_type = _approve_autonomy(source_id, user_id)
    return jsonify({"ok": bool(ok), "action_type": action_type}), (200 if ok else 409)


@app.route("/api/internal/approvals/<path:approval_id>/deny", methods=["POST"])
@_require_internal_key
def api_internal_approvals_deny(approval_id):
    from tools.department_hq.approvals_routes import parse_approval_id, _deny_autonomy

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or 2
    reason = data.get("reason") or "denied via cockpit"
    source, source_id = parse_approval_id(approval_id)
    if source != "autonomy":
        return jsonify({"ok": False, "error": f"source '{source}' not supported yet"}), 501
    ok = _deny_autonomy(source_id, user_id, reason)
    ok_bool = ok[0] if isinstance(ok, tuple) else bool(ok)
    return jsonify({"ok": ok_bool}), (200 if ok_bool else 409)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker exec -w /tmp/wt/platform_v2 archie_platform python3 -m pytest tests/test_internal_approvals.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add platform_v2/app.py platform_v2/tests/test_internal_approvals.py
git commit -m "feat(approvals): internal approve/deny endpoints (owner-id default, fail-closed)"
```

---

## Task 3: Comms — approvals proxy service + cockpit routes

The cockpit's thin proxy to the platform internal endpoints, plus the session-auth routes the panel calls.

**Files:**
- Create: `archie-comms/services/approvals_proxy.py`
- Modify: `archie-comms/app_comms.py`
- Test: `archie-comms/tests/test_approvals_proxy.py`

**Interfaces:**
- Consumes: platform `/api/internal/approvals/{pending,<id>/approve,<id>/deny}` (Tasks 1–2).
- Produces: `list_pending() -> list`, `approve(approval_id, user_id) -> dict`, `deny(approval_id, user_id, reason) -> dict` in `approvals_proxy.py`; cockpit routes `GET /api/approvals/pending`, `POST /api/approvals/<approval_id>/approve|deny`.

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_approvals_proxy.py
import services.approvals_proxy as ap


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
    def json(self):
        return self._p


def test_list_pending_hits_internal_endpoint(monkeypatch):
    seen = {}
    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url; seen["auth"] = headers.get("Authorization")
        return _Resp(200, {"approvals": [{"id": "autonomy:1"}]})
    monkeypatch.setattr(ap.requests, "get", fake_get)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ap.list_pending()
    assert out == [{"id": "autonomy:1"}]
    assert seen["url"].endswith("/api/internal/approvals/pending")
    assert seen["auth"] == "Bearer k"


def test_approve_posts_user_id(monkeypatch):
    seen = {}
    monkeypatch.setattr(ap.requests, "post",
                        lambda url, json=None, headers=None, timeout=None: seen.update(url=url, body=json) or _Resp(200, {"ok": True, "action_type": "improvement_approve_red"}))
    out = ap.approve("autonomy:9", user_id=2)
    assert out["ok"] is True
    assert seen["url"].endswith("/api/internal/approvals/autonomy:9/approve")
    assert seen["body"]["user_id"] == 2


def test_approve_fail_closed_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("platform down")
    monkeypatch.setattr(ap.requests, "post", boom)
    out = ap.approve("autonomy:9", user_id=2)
    assert out["ok"] is False and "error" in out  # never optimistic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd archie-comms && python -m pytest tests/test_approvals_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: services.approvals_proxy`

- [ ] **Step 3: Implement `approvals_proxy.py`**

```python
# archie-comms/services/approvals_proxy.py
"""Thin cockpit->platform approvals proxy. Mirrors conversation_service._dhq_chat_reply:
POST/GET the platform's @_require_internal_key approval endpoints with Bearer
INTERNAL_API_KEY. Fail-CLOSED on approve/deny (never optimistic)."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"}


def list_pending():
    try:
        r = requests.get(f"{_base()}/api/internal/approvals/pending", headers=_headers(), timeout=10)
        if r.status_code == 200:
            return (r.json() or {}).get("approvals", [])
    except Exception as exc:
        logger.warning("approvals list failed: %s", exc)
    return []


def approve(approval_id, user_id):
    return _act(approval_id, "approve", {"user_id": user_id})


def deny(approval_id, user_id, reason=""):
    return _act(approval_id, "deny", {"user_id": user_id, "reason": reason})


def _act(approval_id, verb, body):
    try:
        r = requests.post(f"{_base()}/api/internal/approvals/{approval_id}/{verb}",
                          json=body, headers=_headers(), timeout=15)
        data = r.json() if r.content else {}
        if r.status_code == 200 and data.get("ok"):
            return data
        return {"ok": False, "error": data.get("error") or f"HTTP {r.status_code}"}
    except Exception as exc:  # fail-CLOSED
        logger.warning("approval %s failed: %s", verb, exc)
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 4: Add the cockpit routes in `app_comms.py`**

Beside the delegation routes (session-auth like the others):

```python
@app.route("/api/approvals/pending", methods=["GET"])
def api_approvals_pending():
    from flask import session as fs
    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.approvals_proxy import list_pending
    return jsonify({"approvals": list_pending()})


@app.route("/api/approvals/<path:approval_id>/<verb>", methods=["POST"])
def api_approvals_act(approval_id, verb):
    from flask import session as fs, request as rq
    uid = fs.get("user_id")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    if verb not in ("approve", "deny"):
        return jsonify({"error": "bad verb"}), 400
    from services.approvals_proxy import approve, deny
    if verb == "approve":
        out = approve(approval_id, uid)
    else:
        out = deny(approval_id, uid, (rq.get_json(silent=True) or {}).get("reason", ""))
    return jsonify(out), (200 if out.get("ok") else 502)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd archie-comms && python -m pytest tests/test_approvals_proxy.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add archie-comms/services/approvals_proxy.py archie-comms/app_comms.py archie-comms/tests/test_approvals_proxy.py
git commit -m "feat(comms): approvals proxy service + cockpit approve/deny/pending routes"
```

---

## Task 4: Comms — chat-native approval markers

Give A.R.C.H.I.E. the ability to list + approve in conversation, on the same rail as `{{DELEGATE}}`.

**Files:**
- Modify: `archie-comms/services/conversation_service.py`
- Modify: `archie-comms/app_comms.py`
- Test: `archie-comms/tests/test_approval_markers.py`

**Interfaces:**
- Consumes: `approvals_proxy` (Task 3).
- Produces: markers `{{APPROVALS}}`, `{{APPROVE id="autonomy:N"}}`, `{{DENY id="autonomy:N" reason="..."}}`; `stream_send_message` yields dict events `{"type": "approvals_list_request"}` and `{"type": "approval_action", "verb": "approve"|"deny", "approval_id": "...", "reason": "..."}` with markers stripped from the visible text.

- [ ] **Step 1: Read the exact delegation-marker block to mirror**

Run: `docker exec archie_comms sh -c "grep -n '_DELEGATE_RE\|_DELEGATION_SYSTEM_PROMPT\|_collect_delegate\|delegation_detected' /app/services/conversation_service.py"` then read that region.

- [ ] **Step 2: Write the failing test**

```python
# archie-comms/tests/test_approval_markers.py
import services.conversation_service as cs


def test_parse_approvals_list_marker():
    text = 'Sure, here are your pending items. {{APPROVALS}}'
    events, clean = cs._extract_approval_markers(text)
    assert {"type": "approvals_list_request"} in events
    assert "{{APPROVALS}}" not in clean


def test_parse_approve_marker():
    text = 'Approving that now. {{APPROVE id="autonomy:2782"}}'
    events, clean = cs._extract_approval_markers(text)
    assert {"type": "approval_action", "verb": "approve", "approval_id": "autonomy:2782", "reason": ""} in events
    assert "{{APPROVE" not in clean


def test_parse_deny_marker_with_reason():
    text = 'Denying. {{DENY id="autonomy:5" reason="not now"}}'
    events, clean = cs._extract_approval_markers(text)
    assert {"type": "approval_action", "verb": "deny", "approval_id": "autonomy:5", "reason": "not now"} in events
    assert "{{DENY" not in clean
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd archie-comms && python -m pytest tests/test_approval_markers.py -v`
Expected: FAIL — `AttributeError: _extract_approval_markers`

- [ ] **Step 4: Implement the markers in `conversation_service.py`**

Add beside `_DELEGATE_RE`:

```python
import re as _re

_APPROVALS_RE = _re.compile(r'\{\{APPROVALS\}\}')
_APPROVE_RE = _re.compile(r'\{\{APPROVE\s+id="([^"]+)"\s*\}\}')
_DENY_RE = _re.compile(r'\{\{DENY\s+id="([^"]+)"(?:\s+reason="([^"]*)")?\s*\}\}')

_APPROVALS_SYSTEM_PROMPT = (
    "You can help the owner manage pending approvals. When he asks to SEE pending "
    "approvals, emit the marker {{APPROVALS}} (nothing else needed). When he tells "
    'you to approve a specific one, emit {{APPROVE id="autonomy:N"}} using the id '
    'from the list you last showed him; to deny, emit {{DENY id="autonomy:N" '
    'reason="..."}}. Resolve references like "the family_tree one" to the matching '
    "id from that list. Emit a marker ONLY when he explicitly asks; never invent ids."
)


def _extract_approval_markers(text):
    """Return (events, clean_text): harvest approval markers, strip them from text."""
    events = []
    if _APPROVALS_RE.search(text):
        events.append({"type": "approvals_list_request"})
    for m in _APPROVE_RE.finditer(text):
        events.append({"type": "approval_action", "verb": "approve", "approval_id": m.group(1), "reason": ""})
    for m in _DENY_RE.finditer(text):
        events.append({"type": "approval_action", "verb": "deny", "approval_id": m.group(1), "reason": m.group(2) or ""})
    clean = _APPROVALS_RE.sub("", text)
    clean = _APPROVE_RE.sub("", clean)
    clean = _DENY_RE.sub("", clean)
    return events, clean
```

Wire `_APPROVALS_SYSTEM_PROMPT` into `stream_send_message`'s system-prompt assembly (append it exactly like `_DELEGATION_SYSTEM_PROMPT`), and in the post-stream harvest block call `_extract_approval_markers(complete_text)` alongside `_collect_delegate`, yielding its events and using its `clean` text for the final strip.

- [ ] **Step 5: Handle the events in `app_comms.py`**

In `api_chat_send_message`'s generate loop, beside the `delegation_detected` handling:

```python
elif isinstance(item, dict) and item.get("type") == "approvals_list_request":
    from services.approvals_proxy import list_pending
    yield f"data: {_json.dumps({'type': 'approvals_list', 'approvals': list_pending()})}\n\n"
elif isinstance(item, dict) and item.get("type") == "approval_action":
    from services.approvals_proxy import approve, deny
    uid = flask_session.get("user_id")
    res = (approve(item["approval_id"], uid) if item["verb"] == "approve"
           else deny(item["approval_id"], uid, item.get("reason", "")))
    yield f"data: {_json.dumps({'type': 'approval_done', 'approval_id': item['approval_id'], 'verb': item['verb'], 'ok': res.get('ok', False)})}\n\n"
```

- [ ] **Step 6: Run tests + verify no delegation regression**

Run: `cd archie-comms && python -m pytest tests/test_approval_markers.py tests/test_v1_cli_api.py -v`
Expected: PASS (approval markers + existing v1 API untouched)

- [ ] **Step 7: Commit**

```bash
git add archie-comms/services/conversation_service.py archie-comms/app_comms.py archie-comms/tests/test_approval_markers.py
git commit -m "feat(comms): chat-native {{APPROVALS}}/{{APPROVE}}/{{DENY}} markers + system prompt"
```

---

## Task 5: Comms frontend — Approvals panel + ApprovalCard + chat rendering

The visual half: a right-rail panel and inline chat cards, reusing `DelegationCard`.

**Files:**
- Modify: `archie-comms/templates/chat.html`
- Modify: `archie-comms/static/js/archie-chat.js`
- Verify: browser (P.R.O.B.E./Playwright) — JS has no unit harness here.

**Interfaces:**
- Consumes: `GET /api/approvals/pending`, `POST /api/approvals/<id>/approve|deny` (Task 3); SSE events `approvals_list`, `approval_done` (Task 4).
- Produces: an `ApprovalCard` render + a `loadApprovals()` right-rail panel.

- [ ] **Step 1: Read the DelegationCard + right-rail + SSE handler**

Run: `sed -n '1,60p' archie-comms/static/js/archie-chat.js; grep -n 'class DelegationCard\|ac-dispatch-feed\|case .delegation_queued\|_appendToken\|right' archie-comms/static/js/archie-chat.js` and read `templates/chat.html`'s right-rail section. Match its patterns exactly.

- [ ] **Step 2: Add the panel container to `chat.html`**

In the right rail (beside `ac-dispatch-feed`), add:
```html
<section class="ac-panel" id="ac-approvals">
  <header class="ac-panel-head">Approvals <span id="ac-approvals-count" class="ac-badge">0</span></header>
  <div id="ac-approvals-list" class="ac-approvals-list"></div>
</section>
```

- [ ] **Step 3: Implement `ApprovalCard` + `loadApprovals()` in `archie-chat.js`**

Representative (match the file's existing class/DOM style found in Step 1):
```javascript
function renderApprovalCard(a) {
  // a.display_name + a.reason come pre-formatted from _code_fix_label (PR #2205)
  const el = document.createElement('div');
  el.className = 'ac-approval-card';
  el.dataset.id = a.id;
  el.innerHTML = ''; // build with textContent for XSS safety:
  const title = document.createElement('div'); title.className = 'ac-approval-title';
  title.textContent = a.display_name || a.action_type || a.id;
  const reason = document.createElement('div'); reason.className = 'ac-approval-reason';
  reason.textContent = a.reason || '';
  const btns = document.createElement('div'); btns.className = 'ac-approval-btns';
  const ok = document.createElement('button'); ok.textContent = 'Approve';
  ok.onclick = () => actApproval(a.id, 'approve', el);
  const no = document.createElement('button'); no.textContent = 'Deny';
  no.onclick = () => actApproval(a.id, 'deny', el);
  btns.append(ok, no); el.append(title, reason, btns);
  return el;
}

async function loadApprovals() {
  const r = await fetch('/api/approvals/pending');
  const { approvals = [] } = await r.json();
  const list = document.getElementById('ac-approvals-list');
  list.innerHTML = '';
  approvals.forEach(a => list.appendChild(renderApprovalCard(a)));
  document.getElementById('ac-approvals-count').textContent = approvals.length;
}

async function actApproval(id, verb, el) {
  el.classList.add('ac-busy');
  const r = await fetch(`/api/approvals/${encodeURIComponent(id)}/${verb}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  const out = await r.json();
  if (out.ok) { el.remove(); loadApprovals(); }        // fail-closed: only remove on real ok
  else { el.classList.remove('ac-busy'); el.classList.add('ac-error'); }
}
```
Call `loadApprovals()` on load + poll every 30s. In the SSE handler add `case 'approvals_list':` → render the returned list inline as a chat message of `ApprovalCard`s; `case 'approval_done':` → toast + `loadApprovals()`.

- [ ] **Step 4: Add minimal CSS** for `.ac-approval-card/.ac-approval-btns/.ac-busy/.ac-error` in `static/css/archie-chat.css`, matching the LCARS cyan theme (reuse the `DelegationCard` styles).

- [ ] **Step 5: Commit** (browser verification happens in Task 6)

```bash
git add archie-comms/templates/chat.html archie-comms/static/js/archie-chat.js archie-comms/static/css/archie-chat.css
git commit -m "feat(comms): Approvals panel + ApprovalCard + chat-native rendering"
```

---

## Task 6: End-to-end deploy + live verification

**Files:** none (deploy + verify).

- [ ] **Step 1: Deploy both sides**

```bash
git -C /mnt/archie_brain pull   # after the PR merges to main
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform          # volume-mounted
docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_comms        # image-baked
```

- [ ] **Step 2: Backend live smoke (internal → executor)**

```bash
docker exec archie_comms python3 -c "
import services.approvals_proxy as ap
items = ap.list_pending()
print('pending via cockpit proxy:', len(items))
print('sample:', items[0] if items else None)
"
```
Expected: the same count the DHQ Approvals tab shows (77 reds + others), sample carries the `display_name`/`reason` from PR #2205.

- [ ] **Step 3: Panel approve (browser, P.R.O.B.E./Playwright)**

Log into `archie.kytranempowerment.com` as Kytran → the right-rail Approvals panel lists the pending cards with the friendly labels → click **Approve** on one → it disappears and the count drops. Confirm in the DB that the queue row flipped to `approved` and the proposal advanced (fix will dispatch on the next autoheal cycle).

- [ ] **Step 4: Chat-native approve (browser)**

Type "show my pending approvals" → A.R.C.H.I.E. lists them (cards render inline). Type "approve the family_tree one" → she emits `{{APPROVE id="autonomy:N"}}`, the card confirms `approval_done ok=true`. Verify the same DB flip.

- [ ] **Step 5: Fail-closed check**

Temporarily point `PLATFORM_URL` wrong (or stop the platform) and click Approve → the card shows an error state and the row stays pending (never optimistic). Restore.

- [ ] **Step 6: Commit any fixes + open the PR / hand to /merge-pr.**

---

## Self-Review

**Spec coverage (§4.2 of the design):**
- Platform internal endpoints (pending/approve/deny) → Tasks 1–2. Comms proxy routes → Task 3. Chat-native markers + system prompt → Task 4. Right-rail panel + `DelegationCard` reuse + shared backend → Task 5. Owner-id default, fail-closed, source-prefixed ids, thin-cockpit → Global Constraints + enforced in Tasks 2/3. Reuse of `_code_fix_label` labels → Task 5 (the proxy passes them through untouched). Live verification incl. the 77 reds → Task 6.
- **Gap check:** contractor/bridge approval sources are intentionally 501'd in Slice 1 (spec targets the red Code-Health cards = `autonomy:*`); noted in Task 2 Step 1. A follow-up can extend `_act`/the internal endpoint to the other two `_approve_contractor`/`_approve_bridge` branches.

**Placeholder scan:** two grounded read-first steps (Task 1 Step 1 exact query body to move; Task 4 Step 1 delegation block to mirror) are read-then-implement, not vague placeholders — the tests pin the contract. The `list_pending_approvals()` body in Task 1 Step 4 is explicitly "move the existing query verbatim," which the engineer copies from the route they just read.

**Type consistency:** `parse_approval_id -> (source, source_id:int)` used identically in Tasks 1/2. Proxy returns `{"ok": bool, ...}` consumed identically by the cockpit routes (Task 3), the chat events (Task 4), and the panel `actApproval` (Task 5). SSE event names `approvals_list`/`approval_done` match between Task 4 (emit) and Task 5 (render). Marker event shapes (`approvals_list_request`, `approval_action{verb,approval_id,reason}`) match between Task 4's `_extract_approval_markers` and `app_comms.py`.
