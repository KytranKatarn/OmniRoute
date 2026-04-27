# Sub-E: Unified Coding Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add coding slash commands (/review /test /debug /plan), quick-action pill buttons, feature planning via ARCHIE's LLM, and a Repair Bay proposal counter to the archie.kytranempowerment.com Command Center.

**Architecture:** New `/api/internal/repair/count` platform endpoint (uses existing `_require_internal_key`) proxied through archie_comms as `/api/repair/count`. `stream_send_message` gains `is_plan_request` param that injects `_PLANNING_SYSTEM_PROMPT`. `doSend()` in `archie-chat.js` gets four new command prefixes and StatusPanel gains a Repair Bay row. All delegation uses existing `DelegationCard` from Sub-C.

**Tech Stack:** Flask, PostgreSQL (`improvement_proposals`), vanilla JS, CSS.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `platform_v2/app.py` | Add `GET /api/internal/repair/count` |
| Modify | `archie-comms/app_comms.py` | Add `_call_platform_repair_count()`, `GET /api/repair/count`; accept `is_plan_request` in `api_chat_send_message` |
| Modify | `archie-comms/services/conversation_service.py` | Add `_PLANNING_SYSTEM_PROMPT`; add `is_plan_request=False` param to `stream_send_message` |
| Modify | `archie-comms/static/css/archie-chat.css` | `.ac-quick-actions`, `.ac-quick-btn`, `.ac-repair-bay-row` |
| Modify | `archie-comms/templates/chat.html` | Quick-action buttons + Repair Bay section in status panel |
| Modify | `archie-comms/static/js/archie-chat.js` | New commands, quick-action wiring, StatusPanel repair bay, MessageStream.send isPlanRequest |
| Modify | `archie-comms/tests/test_chat_overhaul.py` | Tests for repair count proxy + plan request injection |

---

## Task 1: Repair Count Endpoints + Tests

**Files:**
- Modify: `platform_v2/app.py`
- Modify: `archie-comms/app_comms.py`
- Modify: `archie-comms/tests/test_chat_overhaul.py`

- [ ] **Step 1: Add test skeleton**

Append to `archie-comms/tests/test_chat_overhaul.py`:

```python
class TestRepairCount:
    def test_repair_count_unauthenticated(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.get("/api/repair/count")
            assert resp.status_code == 401

    def test_repair_count_proxies_platform(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        monkeypatch.setattr(app_comms, "_call_platform_repair_count", lambda: {"count": 5})
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.get("/api/repair/count")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["count"] == 5
```

- [ ] **Step 2: Confirm tests fail (TDD)**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestRepairCount -v 2>&1 | tail -8
```

Expected: AttributeError on missing `_call_platform_repair_count`.

- [ ] **Step 3: Add platform endpoint to platform_v2/app.py**

Find the `api_internal_delegation_status` route (added in Sub-C) and add immediately after it:

```python
@app.route("/api/internal/repair/count")
@_require_internal_key
def api_internal_repair_count():
    """Return count of open repair proposals."""
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM improvement_proposals "
                "WHERE status IN ('pending', 'pending_approval', 'approved')"
            )
            return jsonify({"count": cur.fetchone()["cnt"]})
    except Exception as exc:
        logger.error("api_internal_repair_count failed: %s", exc)
        return jsonify({"count": 0})
```

- [ ] **Step 4: Add helper + proxy route to app_comms.py**

Find `_call_platform_delegation_status` in `app_comms.py` and add these two functions immediately after it:

```python
def _call_platform_repair_count():
    """GET improvement_proposals count from platform. Returns dict."""
    import requests as _req
    import os as _os

    platform_url = _os.getenv("PLATFORM_INTERNAL_URL", "http://192.168.1.200:3000")
    api_key = _os.getenv("INTERNAL_API_KEY", "")
    resp = _req.get(
        f"{platform_url}/api/internal/repair/count",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()
```

Add the proxy route after `api_delegation_status`:

```python
@app.route("/api/repair/count")
def api_repair_count():
    """Proxy repair proposal count from platform."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    try:
        result = _call_platform_repair_count()
        return jsonify(result)
    except Exception as exc:
        logger.error("api_repair_count failed: %s", exc)
        return jsonify({"count": 0})
```

- [ ] **Step 5: Run tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestRepairCount -v 2>&1 | tail -8
```

Expected: 2/2 PASS.

- [ ] **Step 6: Restart platform and verify endpoint**

```bash
docker compose restart archie_platform
sleep 8
KEY=$(grep "^INTERNAL_API_KEY" /mnt/archie_brain/platform_v2/.env | cut -d= -f2)
curl -s http://192.168.1.200:3000/api/internal/repair/count \
  -H "Authorization: Bearer $KEY" | \
  python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{"count": <N>}` where N is the current open proposals count.

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/app.py archie-comms/app_comms.py archie-comms/tests/test_chat_overhaul.py
git commit -m "feat(sub-e): repair count endpoints — platform internal + archie_comms proxy"
```

---

## Task 2: _PLANNING_SYSTEM_PROMPT + is_plan_request in conversation_service

**Files:**
- Modify: `archie-comms/services/conversation_service.py`
- Modify: `archie-comms/app_comms.py`
- Modify: `archie-comms/tests/test_chat_overhaul.py`

- [ ] **Step 1: Add test for planning prompt injection**

Append to `TestDelegationRoutes` (or add a new class) in `test_chat_overhaul.py`:

```python
class TestPlanningRequest:
    def test_planning_prompt_injected_when_is_plan_request(self, monkeypatch):
        from services import conversation_service
        captured = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 1)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "base-sys")

        def capture_ollama(sys_p, user_p):
            captured.append(sys_p)
            yield "plan"

        monkeypatch.setattr("services.conversation_service._stream_ollama", capture_ollama)
        list(conversation_service.stream_send_message(
            user_id=1, message="build a scheduler", is_plan_request=True
        ))
        assert "[FEATURE PLANNING]" in captured[0]

    def test_planning_prompt_not_injected_by_default(self, monkeypatch):
        from services import conversation_service
        captured = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 1)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "base-sys")

        def capture_ollama(sys_p, user_p):
            captured.append(sys_p)
            yield "normal"

        monkeypatch.setattr("services.conversation_service._stream_ollama", capture_ollama)
        list(conversation_service.stream_send_message(
            user_id=1, message="hello", is_plan_request=False
        ))
        assert "[FEATURE PLANNING]" not in captured[0]
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestPlanningRequest -v 2>&1 | tail -8
```

Expected: TypeError on unexpected `is_plan_request` kwarg.

- [ ] **Step 3: Add _PLANNING_SYSTEM_PROMPT and update stream_send_message**

In `archie-comms/services/conversation_service.py`, find the `_DELEGATION_SYSTEM_PROMPT` constant and add immediately after it:

```python
_PLANNING_SYSTEM_PROMPT = (
    "[FEATURE PLANNING] The user wants to plan a software feature. Your job:\n"
    "1. Decompose the feature into 3-5 concrete implementation tasks (ordered).\n"
    "2. Present the plan clearly in your response.\n"
    "3. Include ONE {{DELEGATE}} marker for the FIRST task only:\n"
    '   {{DELEGATE capability="code_review" reason="implement: <task 1 description>"}}\n\n'
    "Format: 'Here is the plan for [feature]:\\n1. [Task 1]...\\nDelegating task 1 to "
    "F.O.R.G.E. now.'\n"
    "Only include one {{DELEGATE}} marker. The user will kick off remaining tasks manually."
)
```

Find `def stream_send_message(user_id, message, channel="web", conversation_id=None, terminal_context=None):` and change to:

```python
def stream_send_message(user_id, message, channel="web", conversation_id=None, terminal_context=None, is_plan_request=False):
```

Inside `stream_send_message`, find:
```python
system_prompt = f"{system_prompt}\n\n{_DELEGATION_SYSTEM_PROMPT}"
```

Add the planning injection AFTER it:
```python
if is_plan_request:
    system_prompt = f"{_PLANNING_SYSTEM_PROMPT}\n\n{system_prompt}"
```

- [ ] **Step 4: Accept is_plan_request in api_chat_send_message**

In `archie-comms/app_comms.py`, inside `api_chat_send_message`, find:
```python
terminal_context = data.get("terminal_context") or None
```

Add below it:
```python
is_plan_request = bool(data.get("is_plan_request", False))
```

Find the `stream_send_message(...)` call inside `generate()` and update:
```python
for item in stream_send_message(
    user_id, message, "web", conversation_id,
    terminal_context=terminal_context,
    is_plan_request=is_plan_request,
):
```

- [ ] **Step 5: Run planning tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestPlanningRequest -v 2>&1 | tail -8
```

Expected: 2/2 PASS.

- [ ] **Step 6: Run full test suite**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | tail -8
```

Expected: all 18 tests PASS (14 previous + 2 repair + 2 planning).

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/services/conversation_service.py archie-comms/app_comms.py \
        archie-comms/tests/test_chat_overhaul.py
git commit -m "feat(sub-e): _PLANNING_SYSTEM_PROMPT + is_plan_request in stream_send_message"
```

---

## Task 3: CSS + HTML

**Files:**
- Modify: `archie-comms/static/css/archie-chat.css` (append)
- Modify: `archie-comms/templates/chat.html`

- [ ] **Step 1: Append CSS**

```css
/* ── Sub-E Quick Actions + Repair Bay (Task #2353) ──────────── */

.ac-quick-actions {
  display: flex;
  gap: 6px;
  padding: 0 16px 8px;
  flex-shrink: 0;
}

.ac-quick-btn {
  background: rgba(0, 255, 255, 0.06);
  border: 1px solid rgba(0, 255, 255, 0.2);
  color: #88aabb;
  border-radius: 12px;
  padding: 4px 10px;
  font-size: 10px;
  font-family: 'IBM Plex Mono', monospace;
  cursor: pointer;
  letter-spacing: 0.5px;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
}

.ac-quick-btn:hover {
  background: rgba(0, 255, 255, 0.12);
  color: #00ffff;
}

.ac-repair-bay-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: #8899aa;
  padding: 2px 0;
  cursor: pointer;
  transition: color 0.15s;
}

.ac-repair-bay-row:hover { color: #ffc800; }

@media (max-width: 768px) {
  .ac-quick-actions { display: none; }
}
```

- [ ] **Step 2: Update chat.html — add quick-action buttons**

Find the `.ac-input-bar` div in `chat.html`. Add the quick-actions div IMMEDIATELY BEFORE it:

```html
<!-- Quick-action coding shortcuts -->
<div class="ac-quick-actions" id="ac-quick-actions">
  <button class="ac-quick-btn" data-cmd="/review " type="button">Review Code</button>
  <button class="ac-quick-btn" data-cmd="/test" type="button">Run Tests</button>
  <button class="ac-quick-btn" data-cmd="/plan " type="button">Plan Feature</button>
</div>
```

- [ ] **Step 3: Update chat.html — add Repair Bay section in status panel**

Find the `.ac-terminal-link` anchor in `chat.html` (in the right sidebar). Add a new section BEFORE it:

```html
<div class="ac-status-section">
  <div class="ac-status-section-title">Repair Bay</div>
  <div id="ac-repair-bay"></div>
</div>
```

- [ ] **Step 4: Verify HTML structure**

```bash
grep -n "ac-quick-actions\|ac-repair-bay\|ac-input-bar\|ac-terminal-link" \
  /mnt/archie_brain/archie-comms/templates/chat.html
```

Expected: all 4 IDs/classes present in correct order (quick-actions before input-bar, repair-bay before terminal-link).

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/css/archie-chat.css archie-comms/templates/chat.html
git commit -m "feat(sub-e): quick-action buttons CSS+HTML + repair bay status section"
```

---

## Task 4: JS — Commands + StatusPanel + Boot Wiring

**Files:**
- Modify: `archie-comms/static/js/archie-chat.js`

- [ ] **Step 1: Add repair bay render method to StatusPanel**

Find `_renderPlatform(platform)` in `StatusPanel` and add this method AFTER it:

```javascript
_renderRepairBay(count) {
  if (!this.repairBayEl) return;
  this.repairBayEl.textContent = '';
  const row = _mk('div', 'ac-repair-bay-row');
  row.title = 'Open Repair Bay';
  const icon = _mk('span');
  icon.textContent = count > 0 ? '⟳' : '●';
  icon.style.color = count > 0 ? '#ffc800' : '#00ff88';
  icon.style.marginRight = '4px';
  const label = _mk('span');
  label.textContent = `${count} proposal${count !== 1 ? 's' : ''} pending`;
  row.appendChild(icon);
  row.appendChild(label);
  row.addEventListener('click', () => {
    window.open('http://192.168.1.200:3000/tools/repair-bay', '_blank');
  });
  this.repairBayEl.appendChild(row);
}
```

- [ ] **Step 2: Update StatusPanel constructor to accept repairBayEl**

Find `constructor({ agentsEl, platformEl })` in `StatusPanel` and change to:

```javascript
constructor({ agentsEl, platformEl, repairBayEl }) {
  this.agentsEl = agentsEl;
  this.platformEl = platformEl;
  this.repairBayEl = repairBayEl;
  this._timer = null;
}
```

- [ ] **Step 3: Update StatusPanel.refresh() to fetch repair count**

Find `async refresh()` in `StatusPanel`. After the existing `_renderPlatform` call, add:

```javascript
    try {
      const repairResp = await fetch('/api/repair/count');
      if (repairResp.ok) {
        const repairData = await repairResp.json();
        this._renderRepairBay(repairData.count || 0);
      }
    } catch (_) {}
```

- [ ] **Step 4: Update MessageStream.send() to accept isPlanRequest**

Find `async send(message, terminalContext = null)` and change to:

```javascript
async send(message, terminalContext = null, isPlanRequest = false) {
```

Find `body: JSON.stringify({` inside `send()` and add `is_plan_request`:

```javascript
        body: JSON.stringify({
          message,
          conversation_id: this.currentConvId,
          terminal_context: terminalContext,
          is_plan_request: isPlanRequest,
        }),
```

- [ ] **Step 5: Add coding command handlers to doSend**

Find `const doSend = () => {` in the boot block. The function currently starts with the `/delegate` check. Add new command checks BEFORE the `/delegate` check:

```javascript
  const doSend = () => {
    const input = document.getElementById('ac-input');
    const msg = input.value.trim();
    if (!msg || input.disabled) return;

    // /plan — feature planning via ARCHIE's LLM with planning prompt
    if (msg.startsWith('/plan ') || msg === '/plan') {
      input.value = '';
      input.style.height = 'auto';
      const feature = msg.slice('/plan'.length).trim();
      if (!feature) return;
      stream.send(feature, null, true);
      return;
    }

    // Coding shortcuts — /review /debug /test
    const _CODING_SHORTCUTS = {
      '/review ': 'code_review',
      '/debug ': 'debug',
    };
    const _INSTANT_SHORTCUTS = {
      '/test': 'run_qa_suite',
    };

    for (const [prefix, capability] of Object.entries(_INSTANT_SHORTCUTS)) {
      if (msg === prefix) {
        input.value = '';
        input.style.height = 'auto';
        _fireCodingDelegation(capability, capability);
        return;
      }
    }

    for (const [prefix, capability] of Object.entries(_CODING_SHORTCUTS)) {
      if (msg.startsWith(prefix)) {
        input.value = '';
        input.style.height = 'auto';
        const reason = msg.slice(prefix.length).trim() || capability;
        _fireCodingDelegation(capability, reason);
        return;
      }
    }

    // /delegate command (from Sub-C)
    if (msg.startsWith('/delegate ') || msg === '/delegate') {
```

Note: Keep the rest of the `/delegate` block unchanged.

- [ ] **Step 6: Add _fireCodingDelegation helper before the doSend function**

Insert this helper function BEFORE `const doSend = () => {`:

```javascript
  function _fireCodingDelegation(capability, reason) {
    const wrap = _mk('div', 'ac-message inbound');
    const bubble = _mk('div', 'ac-message-bubble');
    bubble.textContent = `/${capability === 'run_qa_suite' ? 'test' : capability.replace('_', ' ')}${reason !== capability ? ' ' + reason : ''}`;
    const meta = _mk('div', 'ac-message-meta');
    meta.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    wrap.appendChild(bubble);
    wrap.appendChild(meta);
    stream.messageListEl.appendChild(wrap);
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
      .catch(e => console.error('coding shortcut failed:', e));
  }
```

- [ ] **Step 7: Pass repairBayEl to StatusPanel in boot block**

Find `const status = new StatusPanel({` in the boot block and change to:

```javascript
  const status = new StatusPanel({
    agentsEl: document.getElementById('ac-agents'),
    platformEl: document.getElementById('ac-platform'),
    repairBayEl: document.getElementById('ac-repair-bay'),
  });
```

- [ ] **Step 8: Wire quick-action buttons in boot block**

After the `status.start()` line in the boot block, add:

```javascript
  // Wire quick-action buttons
  document.querySelectorAll('.ac-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      const inp = document.getElementById('ac-input');
      if (!cmd) return;
      if (cmd === '/test') {
        inp.value = '/test';
        doSend();
      } else {
        inp.value = cmd;
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
      }
    });
  });
```

- [ ] **Step 9: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/js/archie-chat.js
git commit -m "feat(sub-e): coding shortcuts, /plan command, repair bay in status panel"
```

---

## Task 5: Rebuild + E2E + PR

- [ ] **Step 1: Full test suite**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | tail -10
```

Expected: all 18 tests PASS.

- [ ] **Step 2: Rebuild archie_comms**

```bash
docker compose build archie_comms --quiet && docker compose up -d archie_comms
sleep 6
docker logs archie_comms --tail 5
```

- [ ] **Step 3: Verify repair count endpoint**

```bash
# Via archie_comms (unauthenticated → 401)
curl -s http://192.168.1.200:3002/api/repair/count | python3 -c "import sys,json; print(json.load(sys.stdin))"

# Via platform directly (authenticated)
KEY=$(grep "^INTERNAL_API_KEY" /mnt/archie_brain/platform_v2/.env | cut -d= -f2)
curl -s http://192.168.1.200:3000/api/internal/repair/count \
  -H "Authorization: Bearer $KEY" | python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: 401 from comms (unauthed), `{"count": N}` from platform.

- [ ] **Step 4: Playwright visual check**

Navigate to `http://192.168.1.200:3002`:
- Log in → go to `/chat`
- Take screenshot — verify three quick-action pill buttons appear above the input bar
- Verify right panel shows "REPAIR BAY" section with proposal count
- Type `/test` and press Enter — verify a `DelegationCard` appears with `run_qa_suite · pending`

- [ ] **Step 5: Verify /plan works**

In the chat input, type `/plan add a dark mode toggle to the platform dashboard` and press Enter.

Expected: ARCHIE responds with a structured plan (3-5 tasks) AND a DelegationCard fires for task 1 (`code_review`).

- [ ] **Step 6: Push and update PR**

```bash
cd /mnt/archie_brain
git push origin feat/archie-chat-overhaul

gh pr edit 359 --body "$(cat <<'PREOF'
## Summary

### Sub-A ✅ (Chat Overhaul)
- Three-column Command Center, SSE streaming, KB memory, Focus Mode, IDOR fix

### Sub-B ✅ (Terminal Drawer)
- Slide-over drawer, ttyd via terminal.kytranempowerment.com, ARCHIE terminal context

### Sub-C ✅ (Delegation in Chat)
- Natural language {{DELEGATE}} detection, /delegate command, DelegationCard polling

### Sub-D ✅ (Browser Agent — Phase 1)
- archie_browser container (Playwright + Fernet sessions), LinkedIn/Meta skills

### Sub-E ✅ (Unified Coding Platform)
- /review, /test, /debug, /plan coding slash commands
- Quick-action pill buttons: Review Code | Run Tests | Plan Feature
- /plan fires ARCHIE's LLM with decomposition prompt + delegates task 1 to F.O.R.G.E.
- Repair Bay indicator in status panel (live proposal count, links to platform)

## Closes
Task #2353 (Sub-E) · Project #288 ARCHIE Command Center — ALL 5 sub-projects complete ✅

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PREOF
)"
```

- [ ] **Step 7: Mark MCP tasks complete**

Report: "MCP tasks #2353 (Sub-E) and #288 project update need to be marked complete."
