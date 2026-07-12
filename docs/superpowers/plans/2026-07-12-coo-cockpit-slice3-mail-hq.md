# COO Cockpit Slice 3 — Mail HQ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Mail HQ tab in the cockpit — read the owner/business inbox with AI triage, get an R.E.S.O.L.V.E. draft reply, and QUEUE a reply into the existing approve-to-send gate. She never sends directly.

**Architecture:** Thin cockpit + platform internal endpoints (the Slice-1/2 pattern). Platform `mail_hq_service.py` reproduces the email_manager READ SELECTs over `email_messages`, drafts via DHQ `dispatch(capability="support")`, and — for send — inserts the SAME `autonomy_approval_queue` (`action_type='email_reply'`) row the Smart-Inbox uses, so the existing Telegram [Send/Cancel] + `execute_email_reply` (and the cockpit's Slice-1 Approvals panel) send it. Cockpit proxy + session routes + a `panel-mail` tab. Slice 3 of `docs/superpowers/specs/2026-07-12-archie-coo-command-surface-design.md`.

**Tech Stack:** Flask (both apps), psycopg2 (`get_db_cursor` RealDict rows, `psycopg2.extras.Json` for JSONB), DHQ dispatch, the LCARS tab system, vanilla JS (`_mk`/textContent).

## Global Constraints

- Thin cockpit → platform internal endpoints behind `@_require_internal_key` (Bearer `INTERNAL_API_KEY`); key NEVER reaches the browser.
- **Reads free; send GATED.** The cockpit drafts + queues an `email_reply` approval; it NEVER calls `execute_email_reply` / `send_email_via_stalwart` directly. The existing gate (Telegram tap or the Slice-1 Approvals panel) sends.
- Owner/business scope only: `mailbox_type = ANY(('owner','business','human_agent'))` — never the 38 AI-agent boxes.
- Column names (email_manager gotchas): body = `body_text`/`body_html`, snippet = `body_preview`, RFC id = `message_id` (thread a reply via it — there is no `in_reply_to` column on the message).
- `autonomy_approval_queue` insert columns are EXACTLY `(action_type, action_data, tier, status, priority, requested_by, reason)` with `action_type='email_reply'`; `action_data` matches `_create_proposal`'s keys so `execute_email_reply` reads it (`from_address`/`to_address`/`subject`/`in_reply_to`/`draft_reply`).
- All inference through DHQ dispatch (ADR-013). XSS: `_mk`+textContent only. Fail-soft. `PLATFORM_URL` base. Import `dispatch` directly in app.py handlers.

## File Structure

**Platform (`platform_v2/`)**
- `services/mail_hq_service.py` — CREATE. `list_inbox()` + `read_message()` + `draft_reply()` + `queue_reply()`.
- `app.py` — MODIFY. 4 endpoints after the coms endpoint (~4610).
- `tests/test_mail_hq.py` — CREATE.

**Cockpit (`archie-comms/`)**
- `services/mail_hq.py` — CREATE. `inbox()`/`message()`/`draft_reply()`/`queue_reply()` proxies.
- `app_comms.py` — MODIFY. 4 session-authed routes.
- `templates/chat.html` — MODIFY. `("mail","Mail","mail")` tab + `panel-mail`.
- `static/js/archie-chat.js` — MODIFY. `loadMail()` + `onLcarsTabSwitch`.
- `static/css/archie-chat.css` — MODIFY. Mail panel styles.
- `tests/test_mail_hq.py` — CREATE.

---

### Task 1: Platform — Mail read service + endpoints (inbox + message)

**Files:**
- Create: `platform_v2/services/mail_hq_service.py`
- Modify: `platform_v2/app.py` (add `GET /api/internal/mail/inbox` + `GET /api/internal/mail/message/<int:mid>`)
- Test: `platform_v2/tests/test_mail_hq.py`

**Interfaces:**
- Produces: `list_inbox(limit=40, mailbox_id=None) -> list[dict]`; `read_message(message_id) -> dict | None`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_mail_hq.py
import contextlib


def _fake_cursor(rows, capture=None):
    class _Cur:
        def execute(self, q, params=None):
            if capture is not None:
                capture["q"] = q
                capture["params"] = params

        def fetchall(self):
            return rows

        def fetchone(self):
            return rows[0] if rows else None

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


def test_list_inbox_scopes_owner_business(monkeypatch):
    import services.mail_hq_service as svc
    cap = {}
    monkeypatch.setattr(svc, "_get_cursor", lambda: _fake_cursor(
        [{"id": 1, "from_address": "a@b.com", "subject": "Hi", "ai_priority": "action", "received_at": "2026-07-12"}], cap))
    rows = svc.list_inbox(limit=10)
    assert rows[0]["subject"] == "Hi"
    assert "mailbox_type = ANY(%s)" in cap["q"] and cap["params"][0] == ["owner", "business", "human_agent"]


def test_read_message_returns_body(monkeypatch):
    import services.mail_hq_service as svc
    monkeypatch.setattr(svc, "_get_cursor", lambda: _fake_cursor(
        [{"id": 5, "body_text": "hello", "from_address": "a@b.com", "mailbox_address": "owner@x.com"}]))
    m = svc.read_message(5)
    assert m["body_text"] == "hello" and m["mailbox_address"] == "owner@x.com"


def test_inbox_endpoint_requires_key(client):
    assert client.get("/api/internal/mail/inbox").status_code == 401


def test_inbox_endpoint_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.mail_hq_service as svc
    monkeypatch.setattr(svc, "list_inbox", lambda **k: [{"id": 1, "subject": "Hi"}])
    r = client.get("/api/internal/mail/inbox?limit=5", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["messages"][0]["subject"] == "Hi"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the read half of the service**

```python
# platform_v2/services/mail_hq_service.py
"""COO command surface — Mail HQ read + draft + queue-for-send (Slice 3). Reads the
owner/business inbox (email_messages), drafts via R.E.S.O.L.V.E., and queues a reply into the
EXISTING approve-to-send gate (autonomy_approval_queue, action_type='email_reply'). NEVER sends
directly — the Approvals panel / Telegram [Send/Cancel] + execute_email_reply do that."""
from __future__ import annotations

_OWNER_TYPES = ("owner", "business", "human_agent")


def _get_cursor():
    from database import get_db_cursor

    return get_db_cursor


def list_inbox(limit=40, mailbox_id=None):
    q = (
        "SELECT em.id, em.mailbox_id, mb.address AS mailbox_address, em.from_address, em.subject, "
        "em.body_preview, em.received_at, em.is_read, em.ai_priority "
        "FROM email_messages em JOIN email_mailboxes mb ON mb.id = em.mailbox_id "
        "WHERE mb.active = TRUE AND mb.mailbox_type = ANY(%s)"
    )
    params = [list(_OWNER_TYPES)]
    if mailbox_id:
        q += " AND em.mailbox_id = %s"
        params.append(int(mailbox_id))
    q += " ORDER BY em.received_at DESC LIMIT %s"
    params.append(int(limit))
    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(q, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("received_at") is not None:
            d["received_at"] = str(d["received_at"])
        out.append(d)
    return out


def read_message(message_id):
    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT em.id, em.mailbox_id, mb.address AS mailbox_address, mb.mailbox_type, "
            "em.from_address, em.to_address, em.subject, em.body_text, em.body_html, "
            "em.received_at, em.ai_priority, em.ai_suggestion, em.message_id "
            "FROM email_messages em JOIN email_mailboxes mb ON mb.id = em.mailbox_id "
            "WHERE em.id = %s",
            (int(message_id),),
        )
        row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("received_at") is not None:
        d["received_at"] = str(d["received_at"])
    return d
```

- [ ] **Step 4: Add the 2 read endpoints in `app.py`** (after `api_internal_coms_overview`)

```python
@app.route("/api/internal/mail/inbox", methods=["GET"])
@_require_internal_key
def api_internal_mail_inbox():
    """Owner/business inbox for the cockpit Mail tab (read-only). Fail-soft."""
    try:
        from services.mail_hq_service import list_inbox

        msgs = list_inbox(
            limit=int(request.args.get("limit", 40) or 40),
            mailbox_id=(request.args.get("mailbox_id") or None),
        )
        return jsonify({"success": True, "messages": msgs})
    except Exception as e:
        logger.warning(f"mail/inbox failed: {e}")
        return jsonify({"success": False, "messages": []}), 200


@app.route("/api/internal/mail/message/<int:mid>", methods=["GET"])
@_require_internal_key
def api_internal_mail_message(mid):
    """Read a single owner/business message (full body). Fail-soft."""
    try:
        from services.mail_hq_service import read_message

        m = read_message(mid)
        if not m:
            return jsonify({"success": False, "error": "not_found"}), 200
        return jsonify({"success": True, "message": m})
    except Exception as e:
        logger.warning(f"mail/message failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add platform_v2/services/mail_hq_service.py platform_v2/app.py platform_v2/tests/test_mail_hq.py
git commit -m "feat(coo): platform Mail HQ read lane — inbox + message endpoints (Slice 3)"
```

---

### Task 2: Platform — draft (R.E.S.O.L.V.E.) + queue-for-send (gated)

**Files:**
- Modify: `platform_v2/services/mail_hq_service.py` (add `draft_reply` + `queue_reply`)
- Modify: `platform_v2/app.py` (add `POST /api/internal/mail/draft-reply` + `POST /api/internal/mail/queue-reply`)
- Test: `platform_v2/tests/test_mail_hq.py`

**Interfaces:**
- Consumes: `read_message()` (Task 1); `dispatch(capability, prompt, prefer_agent, local_only)`.
- Produces: `draft_reply(message_id) -> {draft, agent} | None`; `queue_reply(message_id, body) -> {queued: True, approval_id} | None`.

- [ ] **Step 1: Write the failing test**

```python
def test_draft_reply_uses_support_dispatch(monkeypatch):
    import services.mail_hq_service as svc
    monkeypatch.setattr(svc, "read_message", lambda mid: {"from_address": "a@b.com", "subject": "Q", "body_text": "help?"})
    seen = {}
    import tools.department_hq.services.department_dispatcher as dd

    class _R:
        success = True
        response = "Happy to help."
        agent_name = "R.E.S.O.L.V.E."

    monkeypatch.setattr(dd, "dispatch", lambda **k: seen.update(k) or _R())
    out = svc.draft_reply(7)
    assert out["draft"] == "Happy to help." and out["agent"] == "R.E.S.O.L.V.E."
    assert seen["capability"] == "support" and seen["prefer_agent"] == "R.E.S.O.L.V.E."


def test_queue_reply_inserts_gated_approval(monkeypatch):
    import services.mail_hq_service as svc
    cap = {}

    class _Cur:
        def execute(self, q, params=None):
            cap.setdefault("qs", []).append(q)
            cap["last_params"] = params

        def fetchone(self):
            if "SELECT" in cap["qs"][-1]:
                return {"mailbox_id": 2, "from_address": "sender@x.com", "subject": "Hello",
                        "message_id": "<abc@x>", "thread_id": None, "our_address": "owner@k.com"}
            return {"id": 99}  # RETURNING id

    import contextlib

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    monkeypatch.setattr(svc, "_get_cursor", lambda: _cm)
    out = svc.queue_reply(7, "My reply body")
    assert out == {"queued": True, "approval_id": 99}
    ins = [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q][0]
    assert "'email_reply'" in ins and "'cockpit'" in ins


def test_queue_reply_empty_body(monkeypatch):
    import services.mail_hq_service as svc
    assert svc.queue_reply(7, "  ") is None
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Add `draft_reply` + `queue_reply` to the service**

```python
def draft_reply(message_id):
    """R.E.S.O.L.V.E. AI draft reply (DHQ dispatch, capability='support'). Returns {draft, agent} or None."""
    msg = read_message(message_id)
    if not msg:
        return None
    from tools.department_hq.services.department_dispatcher import dispatch

    prompt = (
        "You are R.E.S.O.L.V.E., Customer Success. Draft a concise, professional reply to this email "
        "in the owner's voice. Return only the reply body, no preamble.\n"
        f"From: {msg.get('from_address')}\nSubject: {msg.get('subject')}\n\n"
        f"{(msg.get('body_text') or msg.get('body_preview') or '')[:2000]}\n\nReply:"
    )
    try:
        res = dispatch(capability="support", prompt=prompt, prefer_agent="R.E.S.O.L.V.E.", local_only=True)
        if getattr(res, "success", False) and (res.response or "").strip():
            return {"draft": res.response.strip(), "agent": res.agent_name or "R.E.S.O.L.V.E."}
    except Exception:
        pass
    return None


def queue_reply(message_id, body):
    """Create a GATED email_reply approval (autonomy_approval_queue). Does NOT send — the existing
    approve-to-send gate (Telegram / Slice-1 Approvals panel) executes it. Returns {queued, approval_id}."""
    body = (body or "").strip()
    if not body:
        return None
    from psycopg2.extras import Json

    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT em.mailbox_id, em.from_address, em.subject, em.message_id, em.thread_id, "
            "mb.address AS our_address FROM email_messages em "
            "JOIN email_mailboxes mb ON mb.id = em.mailbox_id WHERE em.id = %s",
            (int(message_id),),
        )
        m = cur.fetchone()
        if not m:
            return None
        m = dict(m)
        subject = m.get("subject") or ""
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        action_data = {
            "message_id": int(message_id),
            "mailbox_id": m.get("mailbox_id"),
            "from_address": m.get("our_address"),
            "to_address": m.get("from_address"),
            "subject": subject,
            "in_reply_to": m.get("message_id"),
            "thread_id": m.get("thread_id"),
            "draft_reply": body,
            "agent": "R.E.S.O.L.V.E.",
            "original_subject": m.get("subject"),
        }
        cur.execute(
            "INSERT INTO autonomy_approval_queue (action_type, action_data, tier, status, priority, "
            "requested_by, reason) VALUES ('email_reply', %s, 2, 'pending', 5, 'cockpit', %s) RETURNING id",
            (Json(action_data), f"Cockpit Mail HQ reply to {m.get('from_address')}"),
        )
        approval_id = cur.fetchone()["id"]
    return {"queued": True, "approval_id": approval_id}
```

- [ ] **Step 4: Add the 2 endpoints in `app.py`** (after the Task-1 mail endpoints)

```python
@app.route("/api/internal/mail/draft-reply", methods=["POST"])
@_require_internal_key
def api_internal_mail_draft_reply():
    """R.E.S.O.L.V.E. drafts a reply (read-only; nothing is sent or queued here). Fail-soft."""
    try:
        from services.mail_hq_service import draft_reply

        data = request.get_json(silent=True) or {}
        d = draft_reply(int(data.get("message_id") or 0))
        if not d:
            return jsonify({"success": False, "error": "no_draft"}), 200
        return jsonify({"success": True, **d})
    except Exception as e:
        logger.warning(f"mail/draft-reply failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200


@app.route("/api/internal/mail/queue-reply", methods=["POST"])
@_require_internal_key
def api_internal_mail_queue_reply():
    """Queue a reply into the EXISTING approve-to-send gate (never sends). Fail-soft."""
    try:
        from services.mail_hq_service import queue_reply

        data = request.get_json(silent=True) or {}
        q = queue_reply(int(data.get("message_id") or 0), data.get("body") or "")
        if not q:
            return jsonify({"success": False, "error": "not_queued"}), 200
        return jsonify({"success": True, **q})
    except Exception as e:
        logger.warning(f"mail/queue-reply failed: {e}")
        return jsonify({"success": False, "error": "exception"}), 200
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add platform_v2/services/mail_hq_service.py platform_v2/app.py platform_v2/tests/test_mail_hq.py
git commit -m "feat(coo): platform Mail HQ draft (R.E.S.O.L.V.E.) + gated queue-reply (Slice 3)"
```

---

### Task 3: Cockpit — Mail proxy + session routes

**Files:**
- Create: `archie-comms/services/mail_hq.py`
- Modify: `archie-comms/app_comms.py` (4 session routes)
- Test: `archie-comms/tests/test_mail_hq.py`

**Interfaces:**
- Produces: `inbox(limit=40)`, `message(mid)`, `draft_reply(mid)`, `queue_reply(mid, body)` — each returns the platform JSON or a fail-soft default.

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_mail_hq.py
import services.mail_hq as mh


def test_inbox_proxy(monkeypatch):
    class _R:
        status_code = 200

        def json(self):
            return {"success": True, "messages": [{"id": 1, "subject": "Hi"}]}

    import requests as rq
    monkeypatch.setattr(rq, "get", lambda url, headers=None, params=None, timeout=None: _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert mh.inbox()["messages"][0]["subject"] == "Hi"


def test_queue_reply_proxy_posts_body(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"success": True, "queued": True, "approval_id": 3}

    import requests as rq
    monkeypatch.setattr(rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(url=url, json=json) or _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = mh.queue_reply(7, "body text")
    assert out["approval_id"] == 3
    assert seen["url"].endswith("/api/internal/mail/queue-reply") and seen["json"]["body"] == "body text"


def test_inbox_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert mh.inbox() == {"messages": []}
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement the proxy**

```python
# archie-comms/services/mail_hq.py
"""Cockpit-side proxy to the platform Mail HQ endpoints. Server-side only — INTERNAL_API_KEY
never reaches the browser. Reads free; the SEND is gated (queue_reply creates an approval the
existing gate executes). Slice 3 of the COO command surface."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def _timeout():
    return float(os.getenv("MAIL_TIMEOUT", "20"))


def inbox(limit=40):
    try:
        r = requests.get(f"{_base()}/api/internal/mail/inbox", headers=_headers(), params={"limit": limit}, timeout=_timeout())
        if r.status_code == 200:
            return {"messages": r.json().get("messages", [])}
    except Exception as e:
        logger.warning("mail inbox proxy failed: %s", e)
    return {"messages": []}


def message(mid):
    try:
        r = requests.get(f"{_base()}/api/internal/mail/message/{int(mid)}", headers=_headers(), timeout=_timeout())
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("mail message proxy failed: %s", e)
    return {"success": False}


def draft_reply(mid):
    try:
        r = requests.post(f"{_base()}/api/internal/mail/draft-reply", json={"message_id": int(mid)}, headers=_headers(), timeout=float(os.getenv("MAIL_DRAFT_TIMEOUT", "120")))
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("mail draft proxy failed: %s", e)
    return {"success": False}


def queue_reply(mid, body):
    try:
        r = requests.post(f"{_base()}/api/internal/mail/queue-reply", json={"message_id": int(mid), "body": body}, headers=_headers(), timeout=_timeout())
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("mail queue proxy failed: %s", e)
    return {"success": False}
```

- [ ] **Step 4: Add the 4 session routes in `app_comms.py`** (after `api_coms_overview`)

```python
@app.route("/api/mail/inbox", methods=["GET"])
def api_mail_inbox():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import inbox

    return jsonify(inbox(limit=int(fr.args.get("limit", 40) or 40)))


@app.route("/api/mail/message/<int:mid>", methods=["GET"])
def api_mail_message(mid):
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import message

    return jsonify(message(mid))


@app.route("/api/mail/draft-reply", methods=["POST"])
def api_mail_draft_reply():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import draft_reply

    return jsonify(draft_reply(int((fr.get_json(silent=True) or {}).get("message_id") or 0)))


@app.route("/api/mail/queue-reply", methods=["POST"])
def api_mail_queue_reply():
    from flask import request as fr
    from flask import session as fs

    if not fs.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.mail_hq import queue_reply

    data = fr.get_json(silent=True) or {}
    return jsonify(queue_reply(int(data.get("message_id") or 0), data.get("body") or ""))
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add archie-comms/services/mail_hq.py archie-comms/app_comms.py archie-comms/tests/test_mail_hq.py
git commit -m "feat(coo): cockpit Mail HQ proxy + session routes (Slice 3)"
```

---

### Task 4: Cockpit — the Mail tab (frontend)

**Files:**
- Modify: `archie-comms/templates/chat.html` (tab tuple + `panel-mail`)
- Modify: `archie-comms/static/js/archie-chat.js` (`loadMail()` + read/draft/queue + `onLcarsTabSwitch`)
- Modify: `archie-comms/static/css/archie-chat.css`

**Interfaces:**
- Consumes: `/api/mail/inbox`, `/api/mail/message/<id>`, `/api/mail/draft-reply`, `/api/mail/queue-reply` (Task 3); `_mk`/textContent; the `onLcarsTabSwitch` pattern.

- [ ] **Step 1: Add the tab tuple + panel in `chat.html`**

Add to `header_tabs` (after the `coms` tuple):
```html
    ("mail", "Mail", "mail")
```
Add the panel (after `panel-coms` closes):
```html
<div id="panel-mail" class="comms-panel">
  <div class="ac-mail-wrap">
    <div class="ac-mail-list" id="ac-mail-list">Loading inbox&#8230;</div>
    <div class="ac-mail-read" id="ac-mail-read"></div>
  </div>
</div>
```

- [ ] **Step 2: Add `loadMail()` + read/draft/queue + wire the tab in `archie-chat.js`**

Extend the `onLcarsTabSwitch` wrapper — add:
```javascript
    if (tabId === 'mail') loadMail();
```
Define (top-level, near `loadComs`):
```javascript
async function loadMail() {
  const listEl = document.getElementById('ac-mail-list');
  const readEl = document.getElementById('ac-mail-read');
  if (!listEl || !readEl) return;
  try {
    const r = await fetch('/api/mail/inbox?limit=40', { credentials: 'same-origin' });
    const d = r.ok ? await r.json() : { messages: [] };
    listEl.textContent = '';
    const msgs = Array.isArray(d.messages) ? d.messages : [];
    if (!msgs.length) { listEl.textContent = 'Inbox is empty (owner/business mailboxes).'; return; }
    msgs.forEach((m) => {
      const row = _mk('div', 'ac-mail-row' + (m.is_read ? '' : ' ac-mail-unread'));
      const pri = _mk('span', 'ac-mail-pri ac-mail-pri-' + (m.ai_priority || 'info'));
      pri.textContent = (m.ai_priority || 'info');
      const from = _mk('span', 'ac-mail-from'); from.textContent = m.from_address || '';
      const subj = _mk('div', 'ac-mail-subj'); subj.textContent = m.subject || '(no subject)';
      const prev = _mk('div', 'ac-mail-prev'); prev.textContent = m.body_preview || '';
      row.appendChild(pri); row.appendChild(from); row.appendChild(subj); row.appendChild(prev);
      row.addEventListener('click', () => _openMail(m.id));
      listEl.appendChild(row);
    });
  } catch (e) { listEl.textContent = 'Mail unavailable right now.'; }
}

async function _openMail(id) {
  const readEl = document.getElementById('ac-mail-read');
  if (!readEl) return;
  readEl.textContent = 'Loading message…';
  try {
    const r = await fetch('/api/mail/message/' + id, { credentials: 'same-origin' });
    const d = await r.json();
    const m = d && d.message;
    if (!m) { readEl.textContent = 'Message unavailable.'; return; }
    readEl.textContent = '';
    const h = _mk('div', 'ac-mail-read-head');
    h.textContent = (m.from_address || '') + '  —  ' + (m.subject || '');
    const body = _mk('div', 'ac-mail-read-body'); body.textContent = m.body_text || m.body_preview || '';
    const actions = _mk('div', 'ac-mail-actions');
    const draftBtn = _mk('button', 'ac-mail-btn'); draftBtn.textContent = '✍ Draft reply (R.E.S.O.L.V.E.)';
    const ta = _mk('textarea', 'ac-mail-reply'); ta.placeholder = 'Reply… (Queue sends it via the Approvals gate)';
    const queueBtn = _mk('button', 'ac-mail-btn'); queueBtn.textContent = '↗ Queue for send (gated)';
    const note = _mk('div', 'ac-mail-note');
    draftBtn.addEventListener('click', async () => {
      draftBtn.disabled = true; note.textContent = 'R.E.S.O.L.V.E. is drafting…';
      try {
        const rr = await fetch('/api/mail/draft-reply', { method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: id }) });
        const dd = await rr.json();
        if (dd && dd.draft) { ta.value = dd.draft; note.textContent = 'Draft ready — edit, then Queue.'; }
        else note.textContent = 'Could not draft right now.';
      } catch (e) { note.textContent = 'Draft failed.'; }
      draftBtn.disabled = false;
    });
    queueBtn.addEventListener('click', async () => {
      if (!ta.value.trim()) { note.textContent = 'Write or draft a reply first.'; return; }
      queueBtn.disabled = true;
      try {
        const rr = await fetch('/api/mail/queue-reply', { method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: id, body: ta.value }) });
        const dd = await rr.json();
        note.textContent = (dd && dd.queued) ? '✓ Queued — approve it in the Approvals panel or Telegram to send.'
          : 'Could not queue the reply.';
      } catch (e) { note.textContent = 'Queue failed.'; }
      queueBtn.disabled = false;
    });
    actions.appendChild(draftBtn); actions.appendChild(queueBtn);
    readEl.appendChild(h); readEl.appendChild(body); readEl.appendChild(actions);
    readEl.appendChild(ta); readEl.appendChild(note);
  } catch (e) { readEl.textContent = 'Message unavailable.'; }
}
```

- [ ] **Step 3: Style in `archie-chat.css`** (append)

```css
/* Mail HQ tab (Slice 3) */
#panel-mail { display: flex; height: 100%; overflow: hidden; }
.ac-mail-wrap { display: flex; width: 100%; height: 100%; }
.ac-mail-list { width: 42%; overflow-y: auto; border-right: 1px solid var(--ac-line, #24405c); padding: 8px; }
.ac-mail-read { flex: 1; overflow-y: auto; padding: 12px 16px; color: var(--ac-text, #cfe3ff); }
.ac-mail-row { padding: 8px 10px; border-bottom: 1px solid var(--ac-line, #24405c); cursor: pointer; }
.ac-mail-row:hover { background: var(--ac-panel, #10151c); }
.ac-mail-unread .ac-mail-subj { font-weight: 700; }
.ac-mail-pri { font-size: 9px; padding: 1px 5px; border-radius: 3px; margin-right: 6px; text-transform: uppercase; }
.ac-mail-pri-action { background: #b3261e; color: #fff; }
.ac-mail-pri-review { background: #a06a00; color: #fff; }
.ac-mail-pri-info { background: #24405c; color: #cfe3ff; }
.ac-mail-from { font-size: 11px; color: var(--ac-text-dim, #7f95a8); }
.ac-mail-subj { font-size: 13px; color: var(--ac-text, #cfe3ff); margin: 2px 0; }
.ac-mail-prev { font-size: 11px; color: var(--ac-text-dim, #556677); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ac-mail-read-head { font-size: 13px; color: var(--ac-accent, #00e5ff); padding-bottom: 8px; border-bottom: 1px solid var(--ac-line, #24405c); }
.ac-mail-read-body { font-size: 13px; white-space: pre-wrap; padding: 10px 0; line-height: 1.5; }
.ac-mail-actions { display: flex; gap: 8px; margin: 8px 0; }
.ac-mail-btn { background: var(--ac-panel, #10151c); color: var(--ac-text, #cfe3ff); border: 1px solid var(--ac-line, #24405c); border-radius: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer; }
.ac-mail-reply { width: 100%; min-height: 100px; background: var(--ac-panel, #10151c); color: var(--ac-text, #cfe3ff); border: 1px solid var(--ac-line, #24405c); border-radius: 6px; padding: 8px; font-size: 13px; }
.ac-mail-note { font-size: 11px; color: var(--ac-text-dim, #7f95a8); margin-top: 6px; }
```

- [ ] **Step 4: Verify** `node --check archie-comms/static/js/archie-chat.js` — clean.

- [ ] **Step 5: Commit.**

```bash
git add archie-comms/templates/chat.html archie-comms/static/js/archie-chat.js archie-comms/static/css/archie-chat.css
git commit -m "feat(coo): Mail HQ tab in the cockpit — inbox + read + R.E.S.O.L.V.E. draft + gated queue (Slice 3)"
```

---

## Deploy & verify (after all tasks green)

- Platform: `docker restart archie_platform`. Cockpit: `docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_comms`.
- Live: `GET /api/internal/mail/inbox` returns owner/business messages; a `POST /api/internal/mail/queue-reply` inserts a `pending` `email_reply` row in `autonomy_approval_queue` (visible in the Slice-1 Approvals panel / Telegram) — and does NOT send. Open the cockpit **Mail** tab → inbox renders → open a message → Draft → Queue → note confirms it's queued.

## Self-Review

- **Spec coverage:** inbox/triage read (Tasks 1,4) ✓; R.E.S.O.L.V.E. draft (Task 2,4) ✓; send GATED via the existing approve-to-send (Task 2 `queue_reply` → `autonomy_approval_queue action_type='email_reply'` → existing `execute_email_reply`; NEVER a direct send) ✓; owner/business scope only ✓; thin-cockpit + internal-endpoint + session-proxy + tab pattern ✓.
- **Placeholder scan:** none.
- **Type consistency:** `read_message` dict keys (`from_address`/`subject`/`body_text`/`message_id`/`mailbox_id`) consumed by `queue_reply` + the frontend; `queue_reply` returns `{queued, approval_id}` (produced Task 2, proxied Task 3, shown Task 4); `draft_reply` returns `{draft, agent}` throughout.
