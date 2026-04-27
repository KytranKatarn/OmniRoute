# Sub-C: ARCHIE Delegation in Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Kytran ask ARCHIE to delegate tasks to agents from within the chat UI — via natural language or `/delegate` command — with live delegation cards showing status and results.

**Architecture:** Platform exposes two internal endpoints (`/api/internal/delegation/*`) protected by `INTERNAL_API_KEY`. archie_comms proxies those via `/api/delegation/*`. `stream_send_message` detects `{{DELEGATE}}` markers and yields `delegation_detected` events; `generate()` in `app_comms.py` fires the actual HTTP call. A `DelegationCard` JS class polls `/api/delegation/<id>/status` every 5s. The `/delegate` command bypasses the LLM entirely.

**Tech Stack:** Flask (both containers), PostgreSQL (`unified_tasks`), `requests` library, vanilla JS, CSS transitions.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `platform_v2/.env` | Add `INTERNAL_API_KEY` |
| Modify | `archie-comms/.env` | Add `INTERNAL_API_KEY`, `PLATFORM_INTERNAL_URL` |
| Modify | `platform_v2/app.py` | Add `require_internal_key` decorator + 2 internal delegation routes |
| Modify | `archie-comms/app_comms.py` | Add 2 delegation proxy routes; update `generate()` to handle `delegation_detected` |
| Modify | `archie-comms/services/conversation_service.py` | Inject delegation system prompt; strip `{{DELEGATE}}` markers; yield `delegation_detected` |
| Modify | `archie-comms/static/css/archie-chat.css` | `.ac-delegation-card` styles |
| Modify | `archie-comms/static/js/archie-chat.js` | `DelegationCard` class; `_parseDelegateCommand`; `/delegate` intercept in `doSend`; `delegation_queued` handler in `MessageStream` |
| Modify | `archie-comms/tests/test_chat_overhaul.py` | Tests for proxy routes + marker stripping |

---

## Task 1: Env Vars + Test Skeleton

**Files:**
- Modify: `platform_v2/.env`
- Modify: `archie-comms/.env`
- Modify: `archie-comms/tests/test_chat_overhaul.py`

- [ ] **Step 1: Generate INTERNAL_API_KEY**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output — it's your `INTERNAL_API_KEY`. Use it in the next two steps.

- [ ] **Step 2: Add env vars to platform_v2/.env**

```bash
echo "" >> /mnt/archie_brain/platform_v2/.env
echo "INTERNAL_API_KEY=<your-generated-key>" >> /mnt/archie_brain/platform_v2/.env
```

Verify:
```bash
grep "INTERNAL_API_KEY" /mnt/archie_brain/platform_v2/.env
```

- [ ] **Step 3: Add env vars to archie-comms/.env**

```bash
echo "" >> /mnt/archie_brain/archie-comms/.env
echo "INTERNAL_API_KEY=<same-key>" >> /mnt/archie_brain/archie-comms/.env
echo "PLATFORM_INTERNAL_URL=http://192.168.1.200:3000" >> /mnt/archie_brain/archie-comms/.env
```

Verify:
```bash
grep "INTERNAL_API_KEY\|PLATFORM_INTERNAL_URL" /mnt/archie_brain/archie-comms/.env
```

- [ ] **Step 4: Add test skeleton for delegation**

Append to `archie-comms/tests/test_chat_overhaul.py`:

```python
class TestDelegationRoutes:
    def test_delegation_submit_unauthenticated(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.post("/api/delegation/submit",
                          json={"capability": "health_check", "reason": "test"})
            assert resp.status_code == 401

    def test_delegation_submit_calls_platform(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None

        # Mock the platform call
        class MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"task_id": 42, "status": "queued",
                                    "capability": "health_check", "reason": "test"}

        monkeypatch.setattr(app_comms, "_call_platform_delegation_submit",
                            lambda cap, reason, args: MockResp().json())

        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post("/api/delegation/submit",
                          json={"capability": "health_check", "reason": "test"})
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["task_id"] == 42
            assert data["status"] == "queued"

    def test_delegate_marker_stripped_from_response(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 1)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")
        monkeypatch.setattr(
            "services.conversation_service._stream_ollama",
            lambda s, u: iter(["Hello! ", '{{DELEGATE capability="health_check" reason="check VPS"}}']),
        )
        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        tokens = [i for i in items if isinstance(i, str)]
        delegation_events = [i for i in items if isinstance(i, dict) and i.get("type") == "delegation_detected"]
        done_events = [i for i in items if isinstance(i, dict) and i.get("type") == "done"]
        # Marker should NOT appear in streamed tokens
        full_text = "".join(tokens)
        assert "{{DELEGATE" not in full_text
        assert len(delegation_events) == 1
        assert delegation_events[0]["capability"] == "health_check"
        assert len(done_events) == 1
```

- [ ] **Step 5: Confirm new tests fail correctly**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestDelegationRoutes -v 2>&1 | tail -10
```

Expected: all 3 fail with AttributeError/ImportError (TDD state).

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/tests/test_chat_overhaul.py
# .env files are gitignored — do NOT add them
git commit -m "test(archie-comms): Sub-C delegation skeleton tests"
```

---

## Task 2: Platform Internal Delegation Endpoints

**Files:**
- Modify: `platform_v2/app.py` (add after last registered blueprint, ~line 2276)

- [ ] **Step 1: Add `require_internal_key` decorator and two routes**

Find the last `@app.route` or `app.register_blueprint` call near line 2276 of `platform_v2/app.py`. Add this block after it:

```python
# ── Internal Delegation API (Sub-C #2351) ──────────────────────────
import os as _os
from functools import wraps as _wraps


def _require_internal_key(f):
    """Protect internal endpoints with INTERNAL_API_KEY bearer token."""
    @_wraps(f)
    def decorated(*args, **kwargs):
        _key = _os.getenv("INTERNAL_API_KEY", "")
        _auth = request.headers.get("Authorization", "")
        if not _key or _auth != f"Bearer {_key}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/api/internal/delegation/submit", methods=["POST"])
@_require_internal_key
def api_internal_delegation_submit():
    """Submit a task for delegation via web_chat source."""
    import psycopg2.extras as _psyext
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "general").strip()
    reason = (data.get("reason") or "").strip()
    args = data.get("args") or {}
    priority = int(data.get("priority") or 5)

    if not reason:
        return jsonify({"error": "reason required"}), 400

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO unified_tasks
                    (title, description, status, priority, task_type,
                     delegation_source, delegation_args)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    f"{capability}: {reason[:80]}",
                    reason,
                    "pending",
                    priority,
                    "implementation",
                    "web_chat",
                    _psyext.Json({"capability": capability, "args": args}),
                ),
            )
            task_id = cur.fetchone()["id"]
    except Exception as exc:
        logger.error("api_internal_delegation_submit failed: %s", exc)
        return jsonify({"error": "DB insert failed"}), 500

    return jsonify({
        "task_id": task_id,
        "status": "queued",
        "capability": capability,
        "reason": reason,
    }), 201


@app.route("/api/internal/delegation/<int:task_id>/status")
@_require_internal_key
def api_internal_delegation_status(task_id):
    """Return current status and work_notes for a delegated task."""
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, title, status, work_notes, created_at, updated_at,
                       (delegation_args->>'capability') AS capability
                FROM unified_tasks
                WHERE id = %s AND delegation_source = 'web_chat'
                """,
                (task_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("api_internal_delegation_status %d failed: %s", task_id, exc)
        return jsonify({"error": "DB query failed"}), 500

    if not row:
        return jsonify({"error": "Not found"}), 404

    return jsonify({
        "task_id": row["id"],
        "status": row["status"],
        "capability": row["capability"],
        "work_notes": row["work_notes"],
        "title": row["title"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    })
```

- [ ] **Step 2: Restart platform and verify 401 for wrong key**

```bash
docker compose restart archie_platform
sleep 8
curl -s http://192.168.1.200:3000/api/internal/delegation/submit \
  -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer wrong-key" \
  -d '{"capability":"health_check","reason":"test"}' | python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{"error": "Unauthorized"}`

- [ ] **Step 3: Verify correct key returns 201**

```bash
KEY=$(grep INTERNAL_API_KEY /mnt/archie_brain/platform_v2/.env | cut -d= -f2)
curl -s http://192.168.1.200:3000/api/internal/delegation/submit \
  -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"capability":"health_check","reason":"integration test"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('task_id:', d.get('task_id'), 'status:', d.get('status'))"
```

Expected: `task_id: <N> status: queued`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/app.py
git commit -m "feat(platform): internal delegation endpoints — submit + status"
```

---

## Task 3: archie_comms Delegation Proxy Routes

**Files:**
- Modify: `archie-comms/app_comms.py`

- [ ] **Step 1: Add `_call_platform_delegation_submit` helper** (monkeypatch seam for tests)

Add near `_fetch_agent_status` / `_fetch_platform_health` in `app_comms.py`:

```python
def _call_platform_delegation_submit(capability, reason, args=None):
    """POST to platform internal delegation endpoint. Returns response dict.

    Extracted as a function so tests can monkeypatch without touching requests.
    Raises on HTTP error or network failure — caller handles.
    """
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.post(
        f"{platform_url}/api/internal/delegation/submit",
        json={"capability": capability, "reason": reason, "args": args or {}},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _call_platform_delegation_status(task_id):
    """GET platform delegation status. Returns response dict."""
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.get(
        f"{platform_url}/api/internal/delegation/{task_id}/status",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 2: Add `POST /api/delegation/submit` route**

Add after `api_terminal_snapshot`:

```python
@app.route("/api/delegation/submit", methods=["POST"])
def api_delegation_submit():
    """Proxy delegation submission to platform. Auth: session cookie."""
    from flask import session as flask_session

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "general").strip()
    reason = (data.get("reason") or "").strip()
    args = data.get("args") or {}

    if not reason:
        return jsonify({"error": "reason required"}), 400

    try:
        result = _call_platform_delegation_submit(capability, reason, args)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("api_delegation_submit: platform call failed: %s", exc)
        return jsonify({"error": "Platform delegation unavailable"}), 503


@app.route("/api/delegation/<int:task_id>/status")
def api_delegation_status(task_id):
    """Proxy delegation status from platform. Auth: session cookie."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    try:
        result = _call_platform_delegation_status(task_id)
        return jsonify(result), 200
    except Exception as exc:
        logger.error("api_delegation_status %d: platform call failed: %s", task_id, exc)
        return jsonify({"error": "Status unavailable"}), 503
```

- [ ] **Step 3: Run delegation route tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestDelegationRoutes::test_delegation_submit_unauthenticated \
                   tests/test_chat_overhaul.py::TestDelegationRoutes::test_delegation_submit_calls_platform -v 2>&1 | tail -10
```

Expected: both PASS.

- [ ] **Step 4: Rebuild archie_comms and verify route**

```bash
docker compose build archie_comms --quiet && docker compose up -d archie_comms
sleep 5
curl -s http://192.168.1.200:3002/api/delegation/submit -X POST \
  -H "Content-Type: application/json" -d '{"capability":"health_check","reason":"test"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{"error": "Not authenticated"}` (401 guard working).

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/app_comms.py
git commit -m "feat(archie-comms): delegation proxy routes — submit + status"
```

---

## Task 4: {{DELEGATE}} Marker Detection in conversation_service.py

**Files:**
- Modify: `archie-comms/services/conversation_service.py`

- [ ] **Step 1: Add DELEGATION_SYSTEM_PROMPT constant and regex near top of Sub-A block**

After the `# Sub-A KB Memory Helpers` comment, add:

```python
import re as _re

_DELEGATE_RE = _re.compile(
    r'\{\{DELEGATE\s+capability="([^"]+)"\s+reason="([^"]*?)"\s*\}\}',
    _re.DOTALL,
)

_DELEGATION_SYSTEM_PROMPT = """
[DELEGATION] When the user explicitly asks you to delegate a task to an agent or the \
platform, include this marker anywhere in your response:
{{DELEGATE capability="X" reason="Y"}}

Valid capabilities: code_review, health_check, run_qa_suite, documentation, \
analyze, check_dep_drift, run_misroute_audit, summarize, research, security, general.

Example: If the user says "ask F.O.R.G.E. to review the dispatch code", respond \
naturally AND include: {{DELEGATE capability="code_review" reason="review dispatch \
routing code for gaps"}}

Only include {{DELEGATE}} when the user explicitly asks you to delegate. Never \
include it for regular conversation.
""".strip()
```

- [ ] **Step 2: Inject delegation system prompt in stream_send_message**

Inside `stream_send_message`, find where `system_prompt` is built:
```python
system_prompt = _get_system_prompt() or "You are A.R.C.H.I.E., an AI Chief Operating Officer."
if memory_prefix:
    system_prompt = f"{memory_prefix}\n\n{system_prompt}"
```

Add the delegation instruction AFTER the memory prefix injection:
```python
system_prompt = f"{system_prompt}\n\n{_DELEGATION_SYSTEM_PROMPT}"
```

- [ ] **Step 3: Strip markers and yield delegation_detected in the finally block**

Inside the `try/except/finally` streaming block in `stream_send_message`, find:
```python
    finally:
        complete_text = "".join(full_parts)
        if complete_text:
            save_message(...)
        yield {"type": "done", "conversation_id": conv_id}
```

Replace the `finally` block with:
```python
    finally:
        complete_text = "".join(full_parts)

        # Strip {{DELEGATE}} markers and collect delegation events
        delegation_events = []

        def _collect_delegate(m):
            delegation_events.append({
                "type": "delegation_detected",
                "capability": m.group(1).strip(),
                "reason": m.group(2).strip(),
            })
            return ""

        clean_text = _DELEGATE_RE.sub(_collect_delegate, complete_text).strip()

        if clean_text:
            save_message(
                conv_id,
                channel,
                "outbound",
                "archie",
                clean_text,
                {"role": "assistant", "conversation_id": conv_id},
            )

        # Yield delegation events AFTER done so frontend gets text first
        yield {"type": "done", "conversation_id": conv_id}
        for evt in delegation_events:
            yield evt
```

- [ ] **Step 4: Run marker-stripping test**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestDelegationRoutes::test_delegate_marker_stripped_from_response -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | tail -15
```

Expected: all 14 tests PASS (11 previous + 3 new).

- [ ] **Step 6: Update `generate()` in app_comms.py to fire delegation on detection**

Find the `generate()` inner function inside `api_chat_send_message` in `app_comms.py`. After the `for item in stream_send_message(...)` loop, the function currently just catches errors. Update it to handle `delegation_detected`:

```python
    def generate():
        try:
            for item in stream_send_message(
                user_id, message, "web", conversation_id,
                terminal_context=terminal_context,
            ):
                if isinstance(item, dict) and item.get("type") == "delegation_detected":
                    # Fire delegation to platform, convert to delegation_queued event
                    try:
                        result = _call_platform_delegation_submit(
                            item["capability"], item["reason"]
                        )
                        queued_evt = {
                            "type": "delegation_queued",
                            "task_id": result.get("task_id"),
                            "capability": item["capability"],
                            "reason": item["reason"],
                        }
                        yield f"data: {_json.dumps(queued_evt)}\n\n"
                    except Exception as exc:
                        logger.error("delegation fire failed: %s", exc)
                        yield f"data: {_json.dumps({'type': 'delegation_failed', 'reason': item['reason']})}\n\n"
                elif isinstance(item, dict):
                    yield f"data: {_json.dumps(item)}\n\n"
                else:
                    yield f"data: {_json.dumps({'type': 'token', 'content': item})}\n\n"
        except Exception as exc:
            logger.error("SSE generate failed: %s", exc)
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Stream failed'})}\n\n"
```

- [ ] **Step 7: Rebuild and commit**

```bash
docker compose build archie_comms --quiet && docker compose up -d archie_comms
sleep 5
docker logs archie_comms --tail 5
cd /mnt/archie_brain
git add archie-comms/services/conversation_service.py archie-comms/app_comms.py
git commit -m "feat(archie-comms): {{DELEGATE}} marker detection + delegation_queued SSE event"
```

---

## Task 5: CSS Delegation Card Styles

**Files:**
- Modify: `archie-comms/static/css/archie-chat.css` (append at end)

- [ ] **Step 1: Append delegation card CSS**

```css
/* ── Delegation Cards (Sub-C #2351) ─────────────────────────── */

.ac-delegation-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid rgba(0, 255, 255, 0.2);
  background: rgba(0, 20, 30, 0.6);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  align-self: flex-start;
  max-width: 85%;
  transition: border-color 0.3s ease;
}

.ac-delegation-card.pending {
  border-color: rgba(0, 255, 255, 0.3);
}

.ac-delegation-card.done {
  border-color: rgba(0, 255, 136, 0.4);
}

.ac-delegation-card.blocked,
.ac-delegation-card.failed {
  border-color: rgba(255, 68, 68, 0.4);
}

.ac-delegation-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  letter-spacing: 1px;
}

.ac-delegation-status-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.ac-delegation-capability {
  color: #00ffff;
  text-transform: uppercase;
  font-weight: 600;
}

.ac-delegation-state {
  color: #8899aa;
  margin-left: auto;
}

.ac-delegation-card.pending .ac-delegation-state { color: #8899aa; }
.ac-delegation-card.done .ac-delegation-state { color: #00ff88; }
.ac-delegation-card.blocked .ac-delegation-state,
.ac-delegation-card.failed .ac-delegation-state { color: #ff4444; }

.ac-delegation-duration {
  color: #445566;
  font-size: 9px;
  margin-left: 4px;
}

.ac-delegation-reason {
  color: #aabbcc;
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ac-delegation-result {
  color: #88aacc;
  font-size: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid rgba(0, 255, 255, 0.1);
  padding-top: 6px;
  margin-top: 2px;
  display: none;
}

.ac-delegation-card.done .ac-delegation-result,
.ac-delegation-card.blocked .ac-delegation-result,
.ac-delegation-card.failed .ac-delegation-result {
  display: block;
}
```

- [ ] **Step 2: Verify appended**

```bash
grep -c "ac-delegation-card\|ac-delegation-header\|ac-delegation-result" \
  /mnt/archie_brain/archie-comms/static/css/archie-chat.css
```

Expected: 3+

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/css/archie-chat.css
git commit -m "feat(archie-comms): delegation card CSS — pending/done/blocked states"
```

---

## Task 6: DelegationCard JS + /delegate Command

**Files:**
- Modify: `archie-comms/static/js/archie-chat.js`

- [ ] **Step 1: Add `_parseDelegateCommand(text)` utility before the boot block**

Find `/* ── Boot ──` and insert before it:

```javascript
/* ── Delegation helpers ─────────────────────────────────────── */

const _DELEGATE_KEYWORD_MAP = [
  [/health|healthy|vps|platform|status/i, 'health_check'],
  [/\bqa\b|test suite|suite|probe/i, 'run_qa_suite'],
  [/dep.*drift|drift|dependency/i, 'check_dep_drift'],
  [/misroute|rout(e|ing)/i, 'run_misroute_audit'],
  [/review|code|forge/i, 'code_review'],
  [/doc(umentation|s)?/i, 'documentation'],
  [/analyz|intel|watch/i, 'analyze'],
  [/secur|vigil/i, 'security'],
  [/summar/i, 'summarize'],
  [/research|darwin/i, 'research'],
];

function _parseDelegateCommand(text) {
  // Try structured: capability=X reason="Y" or capability=X reason=Y
  const structuredMatch = text.match(/capability=([^\s"]+)/i);
  const reasonMatch = text.match(/reason="([^"]+)"|reason=([^\s]+)/i);
  if (structuredMatch) {
    return {
      capability: structuredMatch[1],
      reason: reasonMatch ? (reasonMatch[1] || reasonMatch[2]) : text,
    };
  }
  // Keyword heuristic
  for (const [pattern, capability] of _DELEGATE_KEYWORD_MAP) {
    if (pattern.test(text)) return { capability, reason: text };
  }
  return { capability: 'general', reason: text };
}
```

- [ ] **Step 2: Add `DelegationCard` class before the boot block**

```javascript
/* ── DelegationCard ─────────────────────────────────────────── */
class DelegationCard {
  constructor({ messageListEl, taskId, capability, reason }) {
    this.messageListEl = messageListEl;
    this.taskId = taskId;
    this.capability = capability;
    this._startedAt = Date.now();
    this._pollTimer = null;
    this._el = this._render(reason, 'pending');
    messageListEl.appendChild(this._el);
    this.startPolling();
  }

  startPolling() {
    let polls = 0;
    const MAX_POLLS = 20; // 100s timeout
    this._pollTimer = setInterval(async () => {
      polls++;
      try {
        const resp = await fetch(`/api/delegation/${this.taskId}/status`);
        if (!resp.ok) return;
        const data = await resp.json();
        this._update(data.status, data.work_notes);
        if (['completed', 'blocked', 'failed'].includes(data.status)) {
          clearInterval(this._pollTimer);
        }
      } catch (_) {}
      if (polls >= MAX_POLLS) {
        clearInterval(this._pollTimer);
        this._update('blocked', 'Timed out — check Dev HQ for results.');
      }
    }, 5000);
  }

  _render(reason, status) {
    const card = _mk('div', `ac-delegation-card ${status}`);
    const header = _mk('div', 'ac-delegation-header');

    const icon = _mk('span', 'ac-delegation-status-icon');
    icon.textContent = status === 'done' ? '✓' : status === 'blocked' ? '✗' : '⟳';

    const cap = _mk('span', 'ac-delegation-capability');
    cap.textContent = this.capability;

    const state = _mk('span', 'ac-delegation-state');
    state.textContent = status;

    const dur = _mk('span', 'ac-delegation-duration');
    dur.id = `ac-del-dur-${this.taskId}`;

    header.appendChild(icon);
    header.appendChild(cap);
    header.appendChild(state);
    header.appendChild(dur);

    const reasonEl = _mk('div', 'ac-delegation-reason');
    reasonEl.textContent = reason;

    const result = _mk('div', 'ac-delegation-result');
    result.id = `ac-del-result-${this.taskId}`;

    card.appendChild(header);
    card.appendChild(reasonEl);
    card.appendChild(result);
    return card;
  }

  _update(status, workNotes) {
    const cssStatus = status === 'completed' ? 'done'
      : status === 'blocked' || status === 'failed' ? 'blocked' : 'pending';
    this._el.className = `ac-delegation-card ${cssStatus}`;

    const icon = this._el.querySelector('.ac-delegation-status-icon');
    const state = this._el.querySelector('.ac-delegation-state');
    if (icon) icon.textContent = cssStatus === 'done' ? '✓' : cssStatus === 'blocked' ? '✗' : '⟳';
    if (state) state.textContent = status;

    const dur = document.getElementById(`ac-del-dur-${this.taskId}`);
    if (dur && cssStatus !== 'pending') {
      const secs = Math.round((Date.now() - this._startedAt) / 1000);
      dur.textContent = ` [${secs}s]`;
    }

    const resultEl = document.getElementById(`ac-del-result-${this.taskId}`);
    if (resultEl && workNotes) {
      resultEl.textContent = workNotes.length > 200
        ? workNotes.slice(0, 200) + '…' : workNotes;
    }
  }
}
```

- [ ] **Step 3: Add `delegation_queued` handler to `MessageStream`**

In `MessageStream._finaliseStream()` — wait, we need to handle `delegation_queued` in the SSE reading loop inside `send()`. Find the SSE event handling in `send()`:

```javascript
            if (evt.type === 'token') {
```

Add a new branch for `delegation_queued`:

```javascript
            } else if (evt.type === 'delegation_queued') {
              new DelegationCard({
                messageListEl: this.messageListEl,
                taskId: evt.task_id,
                capability: evt.capability,
                reason: evt.reason,
              });
              if (!this._userScrolled) this._scrollToBottom();
            } else if (evt.type === 'delegation_failed') {
              // Show inline error — just append as token
              this._appendToken('\n[Delegation failed: ' + (evt.reason || 'unknown') + ']');
            }
```

- [ ] **Step 4: Add `/delegate` command intercept in `doSend`**

Find the `doSend` function and update:

```javascript
  const doSend = () => {
    const input = document.getElementById('ac-input');
    const msg = input.value.trim();
    if (!msg || input.disabled) return;

    // /delegate command — bypass ARCHIE's LLM entirely
    if (msg.startsWith('/delegate ') || msg === '/delegate') {
      input.value = '';
      input.style.height = 'auto';
      const cmdText = msg.slice('/delegate'.length).trim();
      if (!cmdText) return;
      const { capability, reason } = _parseDelegateCommand(cmdText);
      // Show system message in chat
      const wrap = _mk('div', 'ac-message outbound');
      const bubble = _mk('div', 'ac-message-bubble');
      bubble.textContent = msg;
      const meta = _mk('div', 'ac-message-meta');
      meta.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      wrap.appendChild(bubble);
      wrap.appendChild(meta);
      stream.messageListEl.appendChild(wrap);
      // Fire delegation
      fetch('/api/delegation/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capability, reason }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.task_id) {
            new DelegationCard({
              messageListEl: stream.messageListEl,
              taskId: data.task_id,
              capability: data.capability || capability,
              reason: data.reason || reason,
            });
            stream._scrollToBottom();
          }
        })
        .catch(e => console.error('delegation submit failed:', e));
      return;
    }

    // Normal message
    input.value = '';
    input.style.height = 'auto';
    stream.send(msg, terminalDrawer && terminalDrawer.isOpen() ? terminalDrawer.getSnapshot() : null);
  };
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/js/archie-chat.js
git commit -m "feat(archie-comms): DelegationCard + /delegate command + delegation_queued SSE handler"
```

---

## Task 7: E2E Verification + PR

- [ ] **Step 1: Full test suite**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | tail -15
```

Expected: all 14 tests PASS.

- [ ] **Step 2: Rebuild archie_comms with final changes**

```bash
docker compose build archie_comms --quiet && docker compose up -d archie_comms
sleep 6
docker logs archie_comms --tail 5
```

- [ ] **Step 3: Verify end-to-end delegation path**

Test that a real delegation goes through:

```bash
# Get an internal API key
KEY=$(grep INTERNAL_API_KEY /mnt/archie_brain/platform_v2/.env | cut -d= -f2)

# Submit via platform API directly
curl -s http://192.168.1.200:3000/api/internal/delegation/submit \
  -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"capability":"health_check","reason":"E2E test from Sub-C"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('task_id:', d.get('task_id'))"
```

Note the task_id. After 30s (delegate_task_worker interval), poll status:

```bash
TASK_ID=<id-from-above>
curl -s "http://192.168.1.200:3000/api/internal/delegation/$TASK_ID/status" \
  -H "Authorization: Bearer $KEY" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('status:', d.get('status'), '| notes:', str(d.get('work_notes',''))[:80])"
```

Expected: `status: completed | notes: <platform health result>`

- [ ] **Step 4: Playwright visual check**

Use Playwright to navigate to the chat and test `/delegate`:

```
browser_navigate: http://192.168.1.200:3002
```

Log in, navigate to `/chat`, type `/delegate health_check reason="visual test"` in the input and press Enter.

Expected:
- User message bubble appears with the `/delegate` command text
- A delegation card appears below it with `health_check · pending`
- Card updates to `done` within 60s with health check results

- [ ] **Step 5: Push and update PR**

```bash
cd /mnt/archie_brain
git push origin feat/archie-chat-overhaul

gh pr edit 359 --body "$(cat <<'PREOF'
## Summary

### Sub-A ✅ (Chat Overhaul)
- Three-column Command Center layout, SSE streaming, KB memory, Telegram bridge, Focus Mode

### Sub-B ✅ (Terminal Drawer)
- Slide-over drawer, ttyd iframe via token-gated terminal.kytranempowerment.com, ARCHIE terminal context

### Sub-C ✅ (Delegation in Chat)
- Natural language: ARCHIE detects \`{{DELEGATE capability="X" reason="Y"}}\` in her response, fires delegation to agent team
- \`/delegate\` command: bypasses LLM, keyword-parses capability, shows card immediately
- \`DelegationCard\` JS class: polls \`/api/delegation/<id>/status\` every 5s, shows work_notes on completion
- Platform internal endpoints: \`POST /api/internal/delegation/submit\`, \`GET /api/internal/delegation/<id>/status\`
- INTERNAL_API_KEY shared secret bridges archie_comms ↔ platform

## Test plan
- [x] 14/14 unit tests pass
- [x] Platform internal delegation endpoint returns 401 for wrong key
- [x] Full delegation E2E: submit → delegate_task_worker picks up → status polls to completed
- [ ] /delegate command creates card in chat (manual)
- [ ] Natural language delegation fires correctly (manual)

## Sub-projects remaining (Project #288)
- Sub-D: Playwright browser agent (Project #287, Task #2352)
- Sub-E: Unified coding platform (Task #2353)

Closes Task #2351 · Project #288

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PREOF
)"
```

- [ ] **Step 6: Mark MCP task complete**

Report: "MCP task #2351 needs to be marked complete"
