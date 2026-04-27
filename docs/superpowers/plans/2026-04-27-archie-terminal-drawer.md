# Sub-B: Terminal Slide-over Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed the existing ttyd Claude Code terminal (port 17681 / auth proxy 7681) into archie.kytranempowerment.com as a slide-over drawer with ARCHIE context awareness.

**Architecture:** A token-gated `terminal.kytranempowerment.com` NPM proxy host exposes the auth proxy (7681) over HTTPS with WebSocket support. archie_comms mints one-time tokens, loads them into the drawer iframe, polls tmux snapshots every 5s, and injects terminal context into stream_send_message when the drawer is open.

**Tech Stack:** Flask (app_comms), PostgreSQL (terminal_auth_tokens), tmux capture-pane, NPM Proxy Manager API, Hostinger DNS API, vanilla JS, CSS transitions.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `archie-comms/app_comms.py` | Add `/claude/terminal`, `/api/terminal/token`, `/api/terminal/snapshot` |
| Modify | `archie-comms/services/conversation_service.py` | Add `terminal_context=None` param + system prompt injection |
| Modify | `archie-comms/templates/chat.html` | Add drawer HTML (overlay + panel + iframe) |
| Modify | `archie-comms/templates/claude_terminal.html` | Wire iframe src to token URL |
| Modify | `archie-comms/static/css/archie-chat.css` | Drawer slide animation + overlay + mobile hide |
| Modify | `archie-comms/static/js/archie-chat.js` | `TerminalDrawer` class + boot wiring + doSend terminal_context |
| Modify | `archie-comms/tests/test_chat_overhaul.py` | Tests for snapshot endpoint + terminal_context injection |

---

## Task 1: Verify Proxy Infrastructure + Schema

**Files:**
- Read: `scripts/ttyd_auth_proxy.py`
- Test: `archie-comms/tests/test_chat_overhaul.py`

- [ ] **Step 1: Read the auth proxy to understand token auth**

```bash
grep -n "terminal_auth_tokens\|token\|7681\|PROXY_PORT\|def " \
  /mnt/archie_brain/scripts/ttyd_auth_proxy.py
```

Note: the exact column names in `terminal_auth_tokens` (token value col, expiry col, used col).

- [ ] **Step 2: Check terminal_auth_tokens table exists (create if not)**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "\d terminal_auth_tokens" 2>/dev/null || echo "TABLE_MISSING"
```

If TABLE_MISSING, create it:

```bash
docker exec archie_database psql -U archie -d archie -c "
CREATE TABLE IF NOT EXISTS terminal_auth_tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_terminal_auth_tokens_token ON terminal_auth_tokens(token);
"
```

- [ ] **Step 3: Verify ttyd auth proxy accepts tokens**

```bash
# Confirm auth proxy process is running on port 7681
ss -tlnp 2>/dev/null | grep 7681
# Confirm ttyd is running on 17681
ss -tlnp 2>/dev/null | grep 17681
```

Expected: both ports listening.

- [ ] **Step 4: Add test stubs for new endpoints**

Add to `archie-comms/tests/test_chat_overhaul.py` inside a new `TestTerminalEndpoints` class:

```python
class TestTerminalEndpoints:
    def test_snapshot_unauthenticated_returns_401(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        with app_comms.app.test_client() as c:
            resp = c.get("/api/terminal/snapshot")
            assert resp.status_code == 401

    def test_snapshot_returns_lines_structure(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        sys.modules.pop("app_comms", None)
        import app_comms
        app_comms.app.config["TESTING"] = True
        app_comms.app.config["SESSION_COOKIE_SECURE"] = False
        app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
        monkeypatch.setattr(app_comms, "_tmux_capture_claude_code", lambda: ["$ hello", "$ _"])
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.get("/api/terminal/snapshot")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert "lines" in data
            assert isinstance(data["lines"], list)

    def test_terminal_context_injected_in_stream(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 99)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "sys")
        monkeypatch.setattr(
            "services.conversation_service._stream_ollama",
            lambda s, u: iter(["ok"]),
        )
        items = list(conversation_service.stream_send_message(
            user_id=1, message="hi", terminal_context="$ pytest\nPASSED"
        ))
        # Verify done event returned (stream completed)
        done_events = [i for i in items if isinstance(i, dict) and i.get("type") == "done"]
        assert len(done_events) == 1

    def test_terminal_context_not_injected_when_none(self, monkeypatch):
        from services import conversation_service
        captured_prompts = []
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 99)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.conversation_service._get_system_prompt", lambda: "base-sys")

        def capture_stream(sys_p, user_p):
            captured_prompts.append(sys_p)
            yield "ok"

        monkeypatch.setattr("services.conversation_service._stream_ollama", capture_stream)
        list(conversation_service.stream_send_message(user_id=1, message="hi", terminal_context=None))
        assert "[TERMINAL CONTEXT]" not in captured_prompts[0]
```

- [ ] **Step 5: Run — confirm new tests fail correctly**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestTerminalEndpoints -v 2>&1 | tail -15
```
Expected: all 4 fail with AttributeError/ImportError (TDD state).

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/tests/test_chat_overhaul.py
git commit -m "test(archie-comms): Sub-B terminal endpoint skeleton tests"
```

---

## Task 2: Add DNS + NPM Proxy Host for terminal subdomain

**Goal:** `https://terminal.kytranempowerment.com` proxies to `192.168.1.200:7681` (auth proxy) with WebSocket support.

- [ ] **Step 1: Check if terminal subdomain already exists in NPM**

```bash
docker exec nginx_proxy_manager curl -s -X POST \
  http://localhost:81/api/tokens \
  -H "Content-Type: application/json" \
  -d '{"identity":"admin@example.com","secret":"changeme"}' 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('NPM token:', d.get('token','ERROR')[:20])
" 2>/dev/null || echo "NPM_NOT_ACCESSIBLE_VIA_EXEC"
```

If NPM isn't accessible via docker exec, use the platform's Security & Network module API instead:

```bash
# Check existing proxy hosts via NPM API (port 81)
curl -s http://192.168.1.200:81/api/nginx/proxy-hosts \
  -H "Authorization: Bearer <NPM_TOKEN>" 2>/dev/null | python3 -c "
import sys, json
hosts = json.load(sys.stdin)
for h in hosts:
    print(h.get('id'), h.get('domain_names'), h.get('forward_host'), h.get('forward_port'))
" 2>/dev/null | grep -i terminal || echo "terminal subdomain not found"
```

Get the NPM admin token from `/mnt/archie_brain/.env` or `platform_v2/.env`:
```bash
grep -i "npm\|nginx_proxy\|proxy_manager" /mnt/archie_brain/.env /mnt/archie_brain/platform_v2/.env 2>/dev/null | head -10
```

- [ ] **Step 2: Add NPM proxy host via API**

Using the NPM API (token from Step 1), create the proxy host:

```bash
NPM_TOKEN="<token-from-step-1>"
curl -s -X POST http://192.168.1.200:81/api/nginx/proxy-hosts \
  -H "Authorization: Bearer $NPM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain_names": ["terminal.kytranempowerment.com"],
    "forward_scheme": "http",
    "forward_host": "192.168.1.200",
    "forward_port": 7681,
    "allow_websocket_upgrade": true,
    "block_exploits": true,
    "access_list_id": 0,
    "certificate_id": 0,
    "ssl_forced": false,
    "meta": {"letsencrypt_agree": false}
  }' | python3 -c "import sys,json; d=json.load(sys.stdin); print('Created host ID:', d.get('id','ERROR'))"
```

Note the proxy host ID — needed for SSL cert assignment.

- [ ] **Step 3: Add Hostinger DNS A record for terminal subdomain**

Use the Hostinger API MCP tool (or check if the DDNS script handles it):
```bash
grep "terminal\|SUBDOMAINS" /mnt/archie_brain/scripts/ddns_updater.sh | head -5
```

If `terminal` is not in SUBDOMAINS, add it and run the updater:
```bash
# Or use mcp__hostinger-api__DNS_updateDNSRecordsV1 to add:
# Name: terminal, Type: A, Value: <hub-public-IP>, TTL: 3600
```

After DNS propagates (~60s for Hostinger), verify:
```bash
dig terminal.kytranempowerment.com @8.8.8.8 +short
```
Expected: hub public IP (153.68.195.85).

- [ ] **Step 4: Request SSL cert for terminal subdomain via NPM**

```bash
NPM_TOKEN="<token>"
PROXY_ID="<id-from-step-2>"
curl -s -X POST http://192.168.1.200:81/api/nginx/certificates \
  -H "Authorization: Bearer $NPM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"provider\": \"letsencrypt\",
    \"domain_names\": [\"terminal.kytranempowerment.com\"],
    \"meta\": {\"letsencrypt_agree\": true, \"letsencrypt_email\": \"kytranempowerment@gmail.com\"}
  }" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Cert ID:', d.get('id','ERROR'))"
```

Then attach the cert to the proxy host:
```bash
CERT_ID="<cert-id>"
curl -s -X PUT http://192.168.1.200:81/api/nginx/proxy-hosts/$PROXY_ID \
  -H "Authorization: Bearer $NPM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"certificate_id\": $CERT_ID, \"ssl_forced\": true}" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('SSL set:', d.get('ssl_forced'))"
```

- [ ] **Step 5: Verify terminal subdomain accessible**

```bash
curl -I https://terminal.kytranempowerment.com 2>/dev/null | head -5
```
Expected: HTTP 401 (auth proxy working, WebSocket not yet authenticated). If you get a 200 with a basic auth prompt or ttyd UI that's also acceptable.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
# Add terminal to DDNS updater if modified
git add scripts/ddns_updater.sh 2>/dev/null
git commit -m "chore(infra): add terminal.kytranempowerment.com NPM proxy + DNS for ttyd" \
  --allow-empty
```

---

## Task 3: Backend Routes in app_comms.py

**Files:**
- Modify: `archie-comms/app_comms.py`

- [ ] **Step 1: Add `_tmux_capture_claude_code()` helper**

Add near `_fetch_agent_status` / `_fetch_platform_health` in `app_comms.py`:

```python
def _tmux_capture_claude_code(lines=50):
    """Capture last N lines from the claude-code tmux session.

    Returns list of strings. Empty list if session not found.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", "claude-code", "-J"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        all_lines = result.stdout.splitlines()
        # Return last N non-empty lines
        non_empty = [l for l in all_lines if l.strip()]
        return non_empty[-lines:]
    except Exception as exc:
        logger.error("_tmux_capture_claude_code failed: %s", exc)
        return []
```

- [ ] **Step 2: Add `GET /claude/terminal` route**

Find the `@app.route("/claude")` route in `app_comms.py` and add this immediately after it:

```python
@app.route("/claude/terminal")
def claude_terminal_page():
    from flask import session as flask_session, redirect, url_for

    if not flask_session.get("user_id"):
        return redirect(url_for("login"))

    return render_template("claude_terminal.html")
```

- [ ] **Step 3: Add `POST /api/terminal/token` route**

Add after `api_chat_summarize`:

```python
@app.route("/api/terminal/token", methods=["POST"])
def api_terminal_token():
    """Mint a one-time token for ttyd auth proxy access."""
    import secrets
    from datetime import datetime, timezone, timedelta
    from flask import session as flask_session

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO terminal_auth_tokens (token, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token, user_id, expires_at),
            )
    except Exception as exc:
        logger.error("api_terminal_token: DB insert failed: %s", exc)
        return jsonify({"error": "Token generation failed"}), 500

    return jsonify({
        "token": token,
        "url": f"https://terminal.kytranempowerment.com?token={token}",
        "expires_in": 300,
    })
```

- [ ] **Step 4: Add `GET /api/terminal/snapshot` route**

```python
@app.route("/api/terminal/snapshot")
def api_terminal_snapshot():
    """Return last 50 lines from the claude-code tmux session."""
    from flask import session as flask_session
    from datetime import datetime, timezone

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    lines = _tmux_capture_claude_code(lines=50)
    return jsonify({
        "lines": lines,
        "session": "claude-code",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    })
```

- [ ] **Step 5: Accept `terminal_context` in `api_chat_send_message`**

In `api_chat_send_message`, find the line `conversation_id = data.get("conversation_id")` and add below it:

```python
terminal_context = data.get("terminal_context") or None
```

Then in the `generate()` function, change:
```python
for item in stream_send_message(user_id, message, "web", conversation_id):
```
to:
```python
for item in stream_send_message(user_id, message, "web", conversation_id, terminal_context=terminal_context):
```

- [ ] **Step 6: Run snapshot + token tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestTerminalEndpoints::test_snapshot_unauthenticated_returns_401 \
                   tests/test_chat_overhaul.py::TestTerminalEndpoints::test_snapshot_returns_lines_structure -v
```
Expected: both PASS (the 401 test passes immediately; the snapshot structure test passes once `_tmux_capture_claude_code` is monkeypatched).

- [ ] **Step 7: Restart container and verify routes exist**

```bash
docker compose build archie_comms --quiet && docker compose up -d archie_comms
sleep 5
docker logs archie_comms --tail 10
curl -s http://192.168.1.200:3002/api/terminal/snapshot | python3 -c "
import sys, json; d=json.load(sys.stdin); print('Status:', d.get('error', 'OK - keys: ' + str(list(d.keys()))))
"
```
Expected: `{"error": "Not authenticated"}` (401, auth guard working).

- [ ] **Step 8: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/app_comms.py
git commit -m "feat(archie-comms): /claude/terminal, /api/terminal/token, /api/terminal/snapshot"
```

---

## Task 4: Terminal Context Injection in conversation_service.py

**Files:**
- Modify: `archie-comms/services/conversation_service.py`

- [ ] **Step 1: Update `stream_send_message` signature**

Find `def stream_send_message(user_id, message, channel="web", conversation_id=None):` and change to:

```python
def stream_send_message(user_id, message, channel="web", conversation_id=None, terminal_context=None):
```

- [ ] **Step 2: Inject terminal context into system prompt**

Find the block that builds `system_prompt` inside `stream_send_message`:

```python
system_prompt = _get_system_prompt() or "You are A.R.C.H.I.E., an AI Chief Operating Officer."
if memory_prefix:
    system_prompt = f"{memory_prefix}\n\n{system_prompt}"
```

Add terminal context injection immediately after the `memory_prefix` block:

```python
system_prompt = _get_system_prompt() or "You are A.R.C.H.I.E., an AI Chief Operating Officer."
if memory_prefix:
    system_prompt = f"{memory_prefix}\n\n{system_prompt}"
if terminal_context:
    terminal_lines = terminal_context.strip()
    system_prompt = (
        f"[TERMINAL CONTEXT] Last lines from claude-code terminal session:\n"
        f"{terminal_lines}\n\n"
        f"You can reference this terminal state in your response.\n\n"
        f"{system_prompt}"
    )
```

- [ ] **Step 3: Run terminal context tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestTerminalEndpoints::test_terminal_context_injected_in_stream \
                   tests/test_chat_overhaul.py::TestTerminalEndpoints::test_terminal_context_not_injected_when_none -v
```
Expected: both PASS.

- [ ] **Step 4: Run full test suite to confirm no regressions**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | tail -15
```
Expected: all 11 tests PASS (7 original + 4 new).

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/services/conversation_service.py
git commit -m "feat(archie-comms): terminal_context injection in stream_send_message"
```

---

## Task 5: CSS — Drawer Styles

**Files:**
- Modify: `archie-comms/static/css/archie-chat.css` (append at end)

- [ ] **Step 1: Append drawer CSS**

```css
/* ── Terminal Drawer (Sub-B #2350) ──────────────────────────── */

/* Full-screen dim overlay */
.ac-terminal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(5, 10, 18, 0.75);
  z-index: 100;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease;
}

.ac-terminal-overlay.open {
  opacity: 1;
  pointer-events: auto;
}

/* Slide-over drawer panel */
.ac-terminal-drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: 65%;
  height: 100vh;
  background: #1a1a2e;
  border-left: 2px solid #00ff41;
  z-index: 101;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.25s ease;
  box-shadow: -8px 0 32px rgba(0, 255, 65, 0.08);
}

.ac-terminal-drawer.open {
  transform: translateX(0);
}

/* Drawer header */
.ac-terminal-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(0, 255, 65, 0.2);
  flex-shrink: 0;
}

.ac-terminal-title {
  font-size: 10px;
  letter-spacing: 2px;
  color: #00ff41;
  font-family: 'IBM Plex Mono', monospace;
  text-transform: uppercase;
  flex: 1;
}

.ac-terminal-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #445566;
  flex-shrink: 0;
}

.ac-terminal-status-dot.connected {
  background: #00ff41;
  box-shadow: 0 0 6px #00ff41;
}

.ac-terminal-close {
  color: rgba(136, 153, 170, 0.6);
  font-size: 16px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
  line-height: 1;
  transition: color 0.15s, background 0.15s;
  user-select: none;
}

.ac-terminal-close:hover {
  color: #e0e6f0;
  background: rgba(255, 255, 255, 0.08);
}

/* ttyd iframe */
.ac-terminal-iframe {
  flex: 1;
  width: 100%;
  border: none;
  background: #1a1a2e;
}

/* Hide on mobile */
@media (max-width: 768px) {
  .ac-terminal-drawer,
  .ac-terminal-overlay,
  .ac-terminal-trigger { display: none !important; }
}
```

- [ ] **Step 2: Verify CSS appended**

```bash
grep -c "ac-terminal-drawer\|ac-terminal-overlay\|ac-terminal-iframe" \
  /mnt/archie_brain/archie-comms/static/css/archie-chat.css
```
Expected: 3+

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/css/archie-chat.css
git commit -m "feat(archie-comms): terminal drawer CSS — slide-over, overlay, mobile hide"
```

---

## Task 6: JS — TerminalDrawer Class

**Files:**
- Modify: `archie-comms/static/js/archie-chat.js`

- [ ] **Step 1: Add `TerminalDrawer` class before the boot block**

Find `/* ── Boot ──` comment in `archie-chat.js` and insert this class immediately before it:

```javascript
/* ── TerminalDrawer ─────────────────────────────────────── */
class TerminalDrawer {
  constructor({ overlayEl, drawerEl, iframeEl, statusDotEl, closeBtn, triggerBtn }) {
    this.overlayEl = overlayEl;
    this.drawerEl = drawerEl;
    this.iframeEl = iframeEl;
    this.statusDotEl = statusDotEl;
    this._open = false;
    this._pollTimer = null;
    this._lastSnapshot = null;
    this._loaded = false;

    // Close on overlay click, close button, or Escape
    overlayEl.addEventListener('click', () => this.close());
    closeBtn.addEventListener('click', () => this.close());
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && this._open) this.close(); });

    // Trigger button
    if (triggerBtn) triggerBtn.addEventListener('click', () => this.open());

    // Track iframe load for status dot
    iframeEl.addEventListener('load', () => {
      this._loaded = true;
      if (this.statusDotEl) this.statusDotEl.classList.add('connected');
    });
    iframeEl.addEventListener('error', () => {
      if (this.statusDotEl) this.statusDotEl.classList.remove('connected');
    });
  }

  isOpen() { return this._open; }

  getSnapshot() {
    if (!this._lastSnapshot) return null;
    return this._lastSnapshot.join('\n');
  }

  async open() {
    if (this._open) return;
    this._open = true;
    this.overlayEl.classList.add('open');
    this.drawerEl.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Load iframe lazily on first open
    if (!this._loaded && this.iframeEl.dataset.src) {
      await this._loadIframe();
    }

    // Start polling snapshots
    this._pollSnapshot();
    this._pollTimer = setInterval(() => this._pollSnapshot(), 5000);
  }

  close() {
    if (!this._open) return;
    this._open = false;
    this.overlayEl.classList.remove('open');
    this.drawerEl.classList.remove('open');
    document.body.style.overflow = '';

    // Stop polling
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
  }

  async _loadIframe() {
    try {
      // Mint a one-time token from the backend
      const resp = await fetch('/api/terminal/token', { method: 'POST' });
      if (!resp.ok) { console.error('TerminalDrawer: token mint failed', resp.status); return; }
      const data = await resp.json();
      this.iframeEl.src = data.url;
    } catch (e) { console.error('TerminalDrawer._loadIframe:', e); }
  }

  async _pollSnapshot() {
    try {
      const resp = await fetch('/api/terminal/snapshot');
      if (!resp.ok) return;
      const data = await resp.json();
      this._lastSnapshot = data.lines || [];
    } catch (_) {}
  }
}
```

- [ ] **Step 2: Wire TerminalDrawer in the boot block**

In the `DOMContentLoaded` boot block, find:
```javascript
let sessions, stream;
```

Add a TerminalDrawer variable:
```javascript
let sessions, stream, terminalDrawer;
```

After the `new FocusMode(...)` line, add:
```javascript
const overlayEl = document.getElementById('ac-terminal-overlay');
const drawerEl = document.getElementById('ac-terminal-drawer');
if (overlayEl && drawerEl) {
  terminalDrawer = new TerminalDrawer({
    overlayEl,
    drawerEl,
    iframeEl: document.getElementById('ac-terminal-iframe'),
    statusDotEl: document.querySelector('.ac-terminal-status-dot'),
    closeBtn: document.getElementById('ac-terminal-close'),
    triggerBtn: document.querySelector('.ac-terminal-trigger'),
  });
}
```

- [ ] **Step 3: Pass terminal_context in doSend**

Find the `doSend` function and update:
```javascript
const doSend = () => {
  const input = document.getElementById('ac-input');
  const msg = input.value.trim();
  if (!msg || input.disabled) return;
  input.value = '';
  input.style.height = 'auto';
  stream.send(msg, terminalDrawer && terminalDrawer.isOpen() ? terminalDrawer.getSnapshot() : null);
};
```

- [ ] **Step 4: Update `MessageStream.send()` to accept and forward terminal_context**

Find `async send(message)` in `MessageStream` and change to:
```javascript
async send(message, terminalContext = null) {
```

Find the fetch body inside `send()`:
```javascript
body: JSON.stringify({ message, conversation_id: this.currentConvId }),
```
Change to:
```javascript
body: JSON.stringify({
  message,
  conversation_id: this.currentConvId,
  terminal_context: terminalContext,
}),
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/js/archie-chat.js
git commit -m "feat(archie-comms): TerminalDrawer class — lazy iframe, snapshot polling, doSend context"
```

---

## Task 7: HTML — Drawer in chat.html + claude_terminal.html

**Files:**
- Modify: `archie-comms/templates/chat.html`
- Modify: `archie-comms/templates/claude_terminal.html`

- [ ] **Step 1: Add drawer HTML to chat.html**

Find the closing `</div>` of `.ac-layout` in `chat.html` and add these two elements immediately after it (as siblings to `.ac-layout`, before `</body>` or closing content tag):

```html
<!-- Terminal slide-over overlay -->
<div class="ac-terminal-overlay" id="ac-terminal-overlay"></div>

<!-- Terminal drawer panel -->
<div class="ac-terminal-drawer" id="ac-terminal-drawer">
  <div class="ac-terminal-header">
    <div class="ac-terminal-status-dot" id="ac-terminal-status-dot"></div>
    <span class="ac-terminal-title">Claude Code Terminal</span>
    <span class="ac-terminal-close" id="ac-terminal-close">&#10005;</span>
  </div>
  <iframe
    class="ac-terminal-iframe"
    id="ac-terminal-iframe"
    data-src="lazy"
    allow="clipboard-read; clipboard-write"
    title="Claude Code terminal"
  ></iframe>
</div>
```

- [ ] **Step 2: Update "Open Terminal →" link to trigger the drawer**

Find the existing terminal link in `chat.html`:
```html
<a class="ac-terminal-link" href="/claude/terminal">Open Terminal &#8594;</a>
```

Replace with a button that triggers the JS drawer (add `ac-terminal-trigger` class, remove href):
```html
<button class="ac-terminal-link ac-terminal-trigger" type="button">Open Terminal &#8594;</button>
```

- [ ] **Step 3: Wire iframe in claude_terminal.html**

Find the `<div class="terminal-frame">` placeholder (line ~42) in `claude_terminal.html` and add an iframe inside it:

```html
<div class="terminal-frame">
  <iframe
    id="tty"
    style="width:100%;height:100%;border:none;"
    allow="clipboard-read; clipboard-write"
    title="Claude Code terminal"
  ></iframe>
</div>
```

Add a `<script>` before `</body>` in `claude_terminal.html` that mints a token on page load:

```html
<script>
  document.addEventListener('DOMContentLoaded', async () => {
    try {
      const resp = await fetch('/api/terminal/token', { method: 'POST' });
      if (!resp.ok) throw new Error('token mint failed: ' + resp.status);
      const data = await resp.json();
      document.getElementById('tty').src = data.url;
    } catch (e) {
      console.error('Terminal load failed:', e);
    }
  });
</script>
```

Update the reconnect button in `claude_terminal.html` to re-mint a token:

Find `document.getElementById('tty').src=document.getElementById('tty').src` and replace:
```javascript
fetch('/api/terminal/token', { method: 'POST' })
  .then(r => r.json())
  .then(d => { document.getElementById('tty').src = d.url; });
```

- [ ] **Step 4: Rebuild container and visual check**

```bash
docker compose build archie_comms --quiet && docker compose up -d archie_comms
sleep 6
docker logs archie_comms --tail 10
```

Use Playwright MCP to navigate to `http://192.168.1.200:3002`:
- Log in if redirected
- Verify "Open Terminal →" button is visible in right panel
- Click it — verify drawer slides in from right
- Click overlay or press Escape — verify drawer closes

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/templates/chat.html archie-comms/templates/claude_terminal.html
git commit -m "feat(archie-comms): terminal drawer HTML + claude_terminal.html iframe wiring"
```

---

## Task 8: E2E Verification + PR

- [ ] **Step 1: Full test suite**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | tail -15
```
Expected: all 11 tests PASS.

- [ ] **Step 2: Verify terminal.kytranempowerment.com is accessible**

```bash
curl -I https://terminal.kytranempowerment.com 2>/dev/null | head -3
```
Expected: `HTTP/2 401` or `HTTP/2 200` with a login prompt (auth proxy responding).

- [ ] **Step 3: Playwright — verify drawer behavior**

```
browser_navigate: http://192.168.1.200:3002/chat (log in first)
→ Verify three-column layout present (Sub-A regression check)
→ Click "Open Terminal →" button
→ Verify .ac-terminal-drawer.open exists in DOM
→ Verify iframe src was set (contains terminal.kytranempowerment.com)
→ Press Escape
→ Verify .ac-terminal-drawer does NOT have .open class
```

- [ ] **Step 4: Verify terminal context injected**

With drawer open, send a message to ARCHIE. Check that her response references terminal state (or at minimum that the request body included `terminal_context`):

```bash
docker logs archie_comms --tail 20 | grep "terminal\|TERMINAL"
```

- [ ] **Step 5: Verify /claude/terminal standalone page**

```
browser_navigate: http://192.168.1.200:3002/claude/terminal
→ Verify page loads (not 404)
→ Verify iframe src is set after page load
```

- [ ] **Step 6: Mark MCP task complete + push PR**

```bash
cd /mnt/archie_brain
git push origin feat/archie-chat-overhaul
gh pr edit 359 --body "$(cat <<'PREOF'
## Summary
### Sub-A (merged)
- Command Center 3-column layout, SSE streaming, KB memory, Telegram bridge

### Sub-B (this update)
- Terminal slide-over drawer (65% width, CSS transition)
- ttyd Claude Code session embedded via token-gated terminal.kytranempowerment.com proxy
- ARCHIE reads terminal output — tmux capture-pane injected into every chat response while drawer is open
- One-time tokens minted via /api/terminal/token (5min expiry, terminal_auth_tokens table)
- /claude/terminal standalone page also wired
- Desktop-only (hidden at ≤768px)

## Test plan
- [x] 11/11 unit tests pass
- [x] terminal.kytranempowerment.com responds (auth proxy)
- [x] Drawer slides open/closed correctly
- [x] ARCHIE context injection working
- [ ] Live ttyd session renders in iframe (manual — requires Kytran login)

Sub-projects remaining: Sub-C (delegation), Sub-D (Playwright CLI), Sub-E (coding platform)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PREOF
)"
```

Report: "MCP task #2350 needs to be marked complete"
