# Sub-A: ARCHIE Chat Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace archie.kytranempowerment.com chat UI with a persistent streaming Command Center — sessions sidebar, SSE token-by-token streaming, live agent status panel, and KB memory that grows with every conversation.

**Architecture:** Extend `conversation_service.py` with streaming + KB memory helpers. Add three routes to `app_comms.py`. Replace `chat.html` with a three-column LCARS Command Center backed by `archie-chat.css` and `archie-chat.js`. All dynamic content uses DOM textContent (never innerHTML) to prevent XSS.

**Tech Stack:** Flask SSE (stream_with_context), Ollama streaming API, PostgreSQL (unified_conversations + unified_messages + knowledge_base), vanilla JS (DOM API, no framework), LCARS CSS tokens.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `archie-comms/services/archie_voice_service.py` | Add `_stream_ollama()` generator |
| Modify | `archie-comms/services/conversation_service.py` | Add `stream_send_message()`, `summarize_conversation()`, `get_session_context()`, `get_or_create_conversation()`, `_fetch_kb_conversation_memory()` |
| Modify | `archie-comms/app_comms.py` | Convert `send_message` to SSE; add `GET /api/status`; add `POST /api/chat/sessions/<id>/summarize`; add `_fetch_agent_status()`, `_fetch_platform_health()` helpers |
| Create | `archie-comms/static/css/archie-chat.css` | Three-column layout, message bubbles, Focus Mode |
| Create | `archie-comms/static/js/archie-chat.js` | SessionManager, MessageStream, StatusPanel, FocusMode — all DOM API, no innerHTML for user content |
| Replace | `archie-comms/templates/chat.html` | Command Center template |
| Create | `archie-comms/tests/__init__.py` | Test package |
| Create | `archie-comms/tests/test_chat_overhaul.py` | Backend unit tests |

---

## Task 1: Schema Verification + Test Skeleton

**Files:**
- Create: `archie-comms/tests/__init__.py`
- Create: `archie-comms/tests/test_chat_overhaul.py`

- [ ] **Step 1: Verify DB tables are accessible from archie_comms**

```bash
docker exec archie_comms python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='unified_conversations' ORDER BY ordinal_position\")
    print('unified_conversations:', [r['column_name'] for r in cur.fetchall()])
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='unified_messages' ORDER BY ordinal_position\")
    print('unified_messages:', [r['column_name'] for r in cur.fetchall()])
    cur.execute(\"SELECT COUNT(*) AS cnt FROM knowledge_base WHERE knowledge_type='conversation_memory'\")
    print('KB conversation_memory rows:', cur.fetchone()['cnt'])
"
```
Expected: all three queries return without error. Note the exact column names — use them verbatim in subsequent tasks.

- [ ] **Step 2: Create tests directory and skeleton**

```bash
mkdir -p /mnt/archie_brain/archie-comms/tests
touch /mnt/archie_brain/archie-comms/tests/__init__.py
```

Write `archie-comms/tests/test_chat_overhaul.py`:

```python
"""Tests for Sub-A ARCHIE Chat Overhaul: streaming, memory, status routes."""
import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGetSessionContext:
    def test_returns_string_always(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "_fetch_kb_conversation_memory", lambda limit: [])
        assert isinstance(conversation_service.get_session_context(user_id=1), str)

    def test_empty_when_no_entries(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "_fetch_kb_conversation_memory", lambda limit: [])
        assert conversation_service.get_session_context(user_id=1) == ""

    def test_prefix_when_entries_exist(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(
            conversation_service,
            "_fetch_kb_conversation_memory",
            lambda limit: [{"title": "Health check", "content": "All nominal."}],
        )
        result = conversation_service.get_session_context(user_id=1)
        assert result.startswith("[ARCHIE MEMORY]")
        assert "Health check" in result


class TestStreamSendMessage:
    def test_yields_tokens_then_done(self, monkeypatch):
        from services import conversation_service

        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: 42)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        monkeypatch.setattr(conversation_service, "get_conversation_messages", lambda *a, **kw: [])
        monkeypatch.setattr(conversation_service, "get_session_context", lambda *a, **kw: "")
        monkeypatch.setattr("services.archie_voice_service._get_system_prompt", lambda: "sys")
        monkeypatch.setattr(
            "services.archie_voice_service._stream_ollama",
            lambda s, u: iter(["Hello", " world"]),
        )

        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        tokens = [i for i in items if isinstance(i, str)]
        done_events = [i for i in items if isinstance(i, dict) and i.get("type") == "done"]
        assert tokens == ["Hello", " world"]
        assert len(done_events) == 1
        assert done_events[0]["conversation_id"] == 42

    def test_error_when_no_conversation(self, monkeypatch):
        from services import conversation_service
        monkeypatch.setattr(conversation_service, "get_or_create_conversation", lambda uid: None)
        monkeypatch.setattr(conversation_service, "save_message", lambda *a, **kw: {"id": 1})
        items = list(conversation_service.stream_send_message(user_id=1, message="hi"))
        assert any(isinstance(i, dict) and i.get("type") == "error" for i in items)


class TestStatusEndpoint:
    def test_unauthenticated_returns_401(self):
        import app_comms
        app_comms.app.config["TESTING"] = True
        with app_comms.app.test_client() as c:
            resp = c.get("/api/status")
            assert resp.status_code == 401

    def test_returns_expected_keys(self, monkeypatch):
        import app_comms
        app_comms.app.config["TESTING"] = True
        monkeypatch.setattr(app_comms, "_fetch_agent_status", lambda: [])
        monkeypatch.setattr(app_comms, "_fetch_platform_health", lambda: {"db": "healthy"})
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.get("/api/status")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert "agents" in data
            assert "platform" in data
```

- [ ] **Step 3: Run skeleton — confirm all tests fail with ImportError**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v 2>&1 | head -30
```
Expected: ImportError or AttributeError on missing functions. That is correct.

- [ ] **Step 4: Create feature branch and commit skeleton**

```bash
cd /mnt/archie_brain
git checkout -b feat/archie-chat-overhaul
git add archie-comms/tests/
git commit -m "test(archie-comms): skeleton tests for Sub-A chat overhaul"
```

---

## Task 2: Add `_stream_ollama()` to archie_voice_service.py

**Files:**
- Modify: `archie-comms/services/archie_voice_service.py`

- [ ] **Step 1: Read `_call_ollama` to match its config**

```bash
grep -n "OLLAMA_HOST\|ARCHIE_MODEL\|dolphin\|def _call_ollama" \
  /mnt/archie_brain/archie-comms/services/archie_voice_service.py
```
Note the exact env var names and model name. Use the same values below.

- [ ] **Step 2: Confirm `import json` exists at top of file**

```bash
head -25 /mnt/archie_brain/archie-comms/services/archie_voice_service.py | grep "^import json"
```
If absent, add `import json` with the existing imports before proceeding.

- [ ] **Step 3: Append `_stream_ollama()` after `_call_ollama`**

Find the end of `_call_ollama` and add this function immediately after it. Match the `ollama_host` and `model` env var names you found in Step 1:

```python
def _stream_ollama(system_prompt, user_prompt):
    """Yield str tokens from Ollama streaming API.

    Mirrors _call_ollama config. Yields a single error string on failure
    so callers always receive output without raising.
    """
    import requests as _requests

    ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    model = os.getenv("ARCHIE_MODEL", "dolphin3:8b")
    url = f"{ollama_host}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": True,
    }
    try:
        with _requests.post(url, json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = data.get("message", {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    break
    except Exception as exc:
        logger.error("_stream_ollama failed: %s", exc)
        yield "[ARCHIE is temporarily unavailable. Please try again.]"
```

- [ ] **Step 4: Smoke test**

```bash
docker exec archie_comms python3 -c "
from services.archie_voice_service import _stream_ollama
tokens = list(_stream_ollama('You are ARCHIE.', 'Say hello in five words.'))
print('Tokens:', len(tokens), '| Response:', ''.join(tokens))
"
```
Expected: 5+ tokens, a short greeting. If Ollama unavailable: single error string.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/services/archie_voice_service.py
git commit -m "feat(archie-comms): add _stream_ollama() token generator"
```

---

## Task 3: KB Memory + Streaming Helpers in conversation_service.py

**Files:**
- Modify: `archie-comms/services/conversation_service.py` (append all functions at end of file)

- [ ] **Step 1: Append KB helpers**

```python
# ---------------------------------------------------------------------------
# Sub-A KB Memory Helpers (Task #2349)
# ---------------------------------------------------------------------------

def _fetch_kb_conversation_memory(limit=5):
    """Fetch recent conversation_memory entries from knowledge_base.

    Isolated as its own function so tests can monkeypatch the DB call.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT title, content
                FROM knowledge_base
                WHERE knowledge_type = 'conversation_memory'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("_fetch_kb_conversation_memory failed: %s", exc)
        return []


def get_session_context(user_id, limit=5):
    """Return KB memory prefix to inject into ARCHIE system prompt.

    Returns empty string when no entries exist or on DB error.
    """
    rows = _fetch_kb_conversation_memory(limit)
    if not rows:
        return ""
    parts = [f"- {r['title']}: {r['content']}" for r in rows]
    return "[ARCHIE MEMORY] Recent conversation context:\n" + "\n".join(parts)


def summarize_conversation(conv_id):
    """Generate a 2-3 sentence summary and store to knowledge_base.

    Called when a chat session closes. Silently returns if fewer than
    2 messages exist (nothing worth summarising).
    """
    messages = get_conversation_messages(conv_id, limit=50)
    if len(messages) < 2:
        return

    lines = []
    for m in messages:
        role = "User" if m.get("direction") == "inbound" else "ARCHIE"
        lines.append(f"{role}: {m.get('content', '')}")
    transcript = "\n".join(lines)[:3000]

    title = f"Conversation {conv_id}"
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT title FROM unified_conversations WHERE id = %s", (conv_id,)
            )
            row = cur.fetchone()
            if row and row["title"]:
                title = row["title"]
    except Exception as exc:
        logger.error("summarize_conversation: title fetch failed: %s", exc)

    from services.archie_voice_service import _call_ollama

    system = (
        "Summarize this conversation in 2-3 sentences. "
        "Be factual and concise. Focus on decisions made and tasks discussed."
    )
    summary = _call_ollama(system, f"Conversation:\n\n{transcript}")
    if not summary:
        return

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                    (knowledge_type, title, content, category, importance_score, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                ("conversation_memory", title, summary, "chat_history", 0.75),
            )
    except Exception as exc:
        logger.error("summarize_conversation: KB store failed: %s", exc)


def get_or_create_conversation(user_id):
    """Return the most recent active conversation id, or create one."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id FROM unified_conversations
                WHERE user_id = %s AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
    except Exception as exc:
        logger.error("get_or_create_conversation: fetch failed: %s", exc)

    return new_conversation(user_id, "New conversation")


def stream_send_message(user_id, message, channel="web", conversation_id=None):
    """Generator: yield str tokens then a final dict with type='done'.

    Usage in Flask SSE route::

        for item in stream_send_message(user_id, message):
            if isinstance(item, dict):
                yield f"data: {json.dumps(item)}\\n\\n"
            else:
                yield f"data: {json.dumps({'type':'token','content':item})}\\n\\n"
    """
    conv_id = conversation_id or get_or_create_conversation(user_id)
    if conv_id is None:
        yield {"type": "error", "message": "Failed to create conversation"}
        return

    save_message(conv_id, channel, "inbound", "user", message, {"role": "user"})

    memory_prefix = get_session_context(user_id)

    history = get_conversation_messages(conv_id, limit=10)
    history_text = ""
    if history:
        history_text = "\n\nRecent conversation:\n"
        for msg in history[-10:]:
            role_label = "User" if msg.get("direction") == "inbound" else "ARCHIE"
            history_text += f"{role_label}: {msg.get('content', '')}\n"

    from services.archie_voice_service import _get_system_prompt, _stream_ollama

    system_prompt = _get_system_prompt() or "You are A.R.C.H.I.E., an AI Chief Operating Officer."
    if memory_prefix:
        system_prompt = f"{memory_prefix}\n\n{system_prompt}"
    user_prompt = f"{history_text}\nUser: {message}\nARCHIE:"

    full_parts = []
    for token in _stream_ollama(system_prompt, user_prompt):
        full_parts.append(token)
        yield token

    complete_text = "".join(full_parts)
    save_message(
        conv_id,
        channel,
        "outbound",
        "archie",
        complete_text,
        {"role": "assistant", "conversation_id": conv_id},
    )
    yield {"type": "done", "conversation_id": conv_id}
```

- [ ] **Step 2: Run memory + streaming tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestGetSessionContext \
                   tests/test_chat_overhaul.py::TestStreamSendMessage -v
```
Expected: all 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/services/conversation_service.py
git commit -m "feat(archie-comms): stream_send_message, summarize_conversation, get_session_context"
```

---

## Task 4: New Routes in app_comms.py

**Files:**
- Modify: `archie-comms/app_comms.py`

- [ ] **Step 1: Add `_fetch_agent_status()` and `_fetch_platform_health()` near top of app_comms.py (after imports)**

```python
def _fetch_agent_status():
    """Return list of active AI agents. Called by /api/status."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.display_name, a.shift_state,
                       COALESCE(d.name, 'Unknown') AS department
                FROM agents a
                LEFT JOIN departments d ON a.department_id = d.id
                WHERE a.worker_type = 'ai'
                  AND a.shift_state NOT IN ('decommissioned', 'barracked', 'off_duty')
                ORDER BY a.shift_state, a.display_name
                LIMIT 15
                """,
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("_fetch_agent_status failed: %s", exc)
        return []


def _fetch_platform_health():
    """Return basic platform health dict. Called by /api/status."""
    health = {}
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1")
        health["db"] = "healthy"
    except Exception:
        health["db"] = "error"
    return health
```

- [ ] **Step 2: Add `GET /api/status` route (after the existing `/api/health` route)**

```python
@app.route("/api/status")
def api_status():
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    return jsonify(
        {
            "agents": _fetch_agent_status(),
            "platform": _fetch_platform_health(),
            "anomaly_count": 0,
        }
    )
```

- [ ] **Step 3: Add `POST /api/chat/sessions/<id>/summarize` route (after `/api/chat/new`)**

```python
@app.route("/api/chat/sessions/<int:conv_id>/summarize", methods=["POST"])
def api_chat_summarize(conv_id):
    """Called via sendBeacon on session close. Stores KB summary."""
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401

    from services.conversation_service import summarize_conversation

    try:
        summarize_conversation(conv_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("api_chat_summarize %d failed: %s", conv_id, exc)
        return jsonify({"success": False}), 500
```

- [ ] **Step 4: Replace the `send_message` route body with SSE streaming**

Find `@app.route("/api/chat/send_message", methods=["POST"])` and replace its function body:

```python
@app.route("/api/chat/send_message", methods=["POST"])
def api_chat_send_message():
    """SSE streaming endpoint. Emits token events then a done event."""
    import json as _json
    from flask import Response, session as flask_session, stream_with_context

    user_id = flask_session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    conversation_id = data.get("conversation_id")

    if not message:
        return jsonify({"error": "Empty message"}), 400

    from services.conversation_service import stream_send_message

    def generate():
        try:
            for item in stream_send_message(user_id, message, "web", conversation_id):
                if isinstance(item, dict):
                    yield f"data: {_json.dumps(item)}\n\n"
                else:
                    yield f"data: {_json.dumps({'type': 'token', 'content': item})}\n\n"
        except Exception as exc:
            logger.error("SSE generate failed: %s", exc)
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Stream failed'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

- [ ] **Step 5: Run status endpoint tests**

```bash
cd /mnt/archie_brain/archie-comms && \
  python -m pytest tests/test_chat_overhaul.py::TestStatusEndpoint -v
```
Expected: both tests PASS.

- [ ] **Step 6: Restart + smoke test**

```bash
docker compose restart archie_comms && sleep 5
docker logs archie_comms --tail 20
```
Expected: no ImportError. "Running on" visible.

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/app_comms.py
git commit -m "feat(archie-comms): SSE send_message + /api/status + /api/chat/sessions/summarize"
```

---

## Task 5: Create archie-chat.css

**Files:**
- Create: `archie-comms/static/css/archie-chat.css`

Write the complete CSS file. Key rules:

```css
/* archie-chat.css - Command Center layout (Sub-A #2349) */

/* Layout shell */
.ac-layout {
  display: flex;
  height: calc(100vh - 60px);
  overflow: hidden;
  background: var(--archie-bg-primary, #0a0f1a);
  color: var(--archie-text-primary, #e0e6f0);
  font-family: 'IBM Plex Mono', monospace;
  transition: all 0.25s ease;
}

/* Left sidebar */
.ac-sidebar-left {
  width: 220px;
  flex-shrink: 0;
  background: var(--archie-bg-secondary, #050a12);
  border-right: 1px solid rgba(0,255,255,0.15);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.25s ease, opacity 0.2s ease;
}
.ac-sidebar-header {
  padding: 12px 14px 8px;
  font-size: 9px;
  letter-spacing: 2px;
  color: #00ffff;
  border-bottom: 1px solid rgba(0,255,255,0.1);
  text-transform: uppercase;
}
.ac-session-list { flex: 1; overflow-y: auto; padding: 6px 0; }
.ac-session-item {
  padding: 7px 14px;
  cursor: pointer;
  border-left: 2px solid transparent;
  font-size: 11px;
  color: #8899aa;
  transition: background 0.15s, border-color 0.15s;
}
.ac-session-item:hover { background: rgba(0,255,255,0.05); color: #e0e6f0; }
.ac-session-item.active { background: rgba(0,255,255,0.08); border-left-color: #00ffff; color: #00ffff; }
.ac-session-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ac-session-date { font-size: 9px; color: rgba(136,153,170,0.6); margin-top: 2px; }
.ac-new-session {
  padding: 10px 14px;
  border-top: 1px solid rgba(0,255,255,0.1);
  font-size: 10px;
  color: #00ffff;
  cursor: pointer;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.ac-new-session:hover { background: rgba(0,255,255,0.08); }

/* Chat center */
.ac-chat-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.ac-chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(0,255,255,0.1);
  font-size: 10px;
  color: #00ffff;
  letter-spacing: 1px;
  flex-shrink: 0;
}
.ac-focus-toggle {
  cursor: pointer;
  font-size: 12px;
  color: rgba(0,255,255,0.5);
  padding: 2px 6px;
  border-radius: 3px;
  user-select: none;
}
.ac-focus-toggle:hover { color: #00ffff; background: rgba(0,255,255,0.1); }
.ac-message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ac-message { display: flex; flex-direction: column; max-width: 82%; }
.ac-message.inbound { align-self: flex-end; }
.ac-message.outbound { align-self: flex-start; }
.ac-message-bubble {
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ac-message.inbound .ac-message-bubble {
  background: rgba(30,40,60,0.8);
  color: #d0dae8;
  border-bottom-right-radius: 3px;
}
.ac-message.outbound .ac-message-bubble {
  background: rgba(0,255,255,0.08);
  color: #00ffff;
  border: 1px solid rgba(0,255,255,0.15);
  border-bottom-left-radius: 3px;
}
.ac-message.telegram .ac-message-bubble { opacity: 0.75; border-style: dashed; }
.ac-message-meta { font-size: 9px; color: rgba(136,153,170,0.5); margin-top: 3px; padding: 0 4px; }
.ac-message.inbound .ac-message-meta { text-align: right; }

/* Streaming cursor */
.ac-streaming-cursor::after {
  content: '\25ae';
  animation: ac-blink 0.8s step-end infinite;
  color: #00ffff;
}
@keyframes ac-blink { 0%,100% { opacity:1; } 50% { opacity:0; } }

/* Jump to latest */
.ac-jump-latest {
  position: absolute;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0,255,255,0.15);
  border: 1px solid rgba(0,255,255,0.3);
  color: #00ffff;
  padding: 5px 14px;
  border-radius: 20px;
  font-size: 11px;
  cursor: pointer;
  display: none;
  z-index: 10;
}
.ac-jump-latest.visible { display: block; }

/* Input bar */
.ac-input-bar {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid rgba(0,255,255,0.1);
  flex-shrink: 0;
}
.ac-input {
  flex: 1;
  background: rgba(0,255,255,0.04);
  border: 1px solid rgba(0,255,255,0.2);
  border-radius: 6px;
  padding: 9px 14px;
  color: #e0e6f0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  resize: none;
  outline: none;
}
.ac-input:focus { border-color: rgba(0,255,255,0.5); }
.ac-input:disabled { opacity: 0.5; cursor: not-allowed; }
.ac-send-btn {
  background: rgba(0,255,255,0.15);
  border: 1px solid rgba(0,255,255,0.3);
  color: #00ffff;
  border-radius: 6px;
  padding: 9px 18px;
  font-size: 12px;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  letter-spacing: 1px;
  align-self: flex-end;
}
.ac-send-btn:hover { background: rgba(0,255,255,0.25); }
.ac-send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Right sidebar */
.ac-sidebar-right {
  width: 200px;
  flex-shrink: 0;
  background: var(--archie-bg-secondary, #050a12);
  border-left: 1px solid rgba(255,200,0,0.15);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.25s ease, opacity 0.2s ease;
  font-size: 11px;
}
.ac-status-section { padding: 10px 12px; border-bottom: 1px solid rgba(255,200,0,0.1); }
.ac-status-section-title {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #ffc800;
  margin-bottom: 8px;
}
.ac-agent-row { display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 10px; }
.ac-agent-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.ac-agent-dot.working { background: #00ff88; box-shadow: 0 0 4px #00ff88; }
.ac-agent-dot.active { background: #00ffff; }
.ac-agent-dot.idle { background: #445566; }
.ac-agent-name { color: #aabbcc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ac-health-row { display: flex; justify-content: space-between; padding: 2px 0; font-size: 10px; color: #8899aa; }
.ac-health-dot { width: 6px; height: 6px; border-radius: 50%; }
.ac-health-dot.healthy { background: #00ff88; }
.ac-health-dot.error { background: #ff4444; }
.ac-health-dot.warning { background: #ffc800; }
.ac-terminal-link {
  margin: 10px 12px;
  padding: 7px 10px;
  border: 1px solid rgba(0,255,255,0.2);
  border-radius: 4px;
  color: #00ffff;
  font-size: 10px;
  text-align: center;
  cursor: pointer;
  letter-spacing: 1px;
  text-decoration: none;
  display: block;
}
.ac-terminal-link:hover { background: rgba(0,255,255,0.08); }

/* Focus mode hides both sidebars */
.ac-layout.focus-mode .ac-sidebar-left,
.ac-layout.focus-mode .ac-sidebar-right {
  width: 0;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
}

/* Scrollbars */
.ac-message-list::-webkit-scrollbar,
.ac-session-list::-webkit-scrollbar { width: 4px; }
.ac-message-list::-webkit-scrollbar-thumb,
.ac-session-list::-webkit-scrollbar-thumb { background: rgba(0,255,255,0.15); border-radius: 2px; }

/* Responsive */
@media (max-width: 768px) { .ac-sidebar-right { display: none; } .ac-sidebar-left { width: 180px; } }
@media (max-width: 480px) { .ac-sidebar-left { width: 0; opacity: 0; overflow: hidden; } }
```

- [ ] **Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/css/archie-chat.css
git commit -m "feat(archie-comms): Command Center CSS - three-column, focus mode, message bubbles"
```

---

## Task 6: Create archie-chat.js

**Files:**
- Create: `archie-comms/static/js/archie-chat.js`

Security rule: **all user/DB content is set via `el.textContent = value`, never via innerHTML**. Static structure (no user data) may use innerHTML.

Write the complete file with four classes. The `_mk(tag, cls)` helper creates elements safely:

```javascript
/* archie-chat.js - Command Center JS (Sub-A #2349)
 * Security: all dynamic content uses textContent, not innerHTML.
 */

/* Utility: create element with optional class */
function _mk(tag, cls) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  return el;
}

/* ── SessionManager ── */
class SessionManager {
  constructor({ listEl, onSelect }) {
    this.listEl = listEl;
    this.onSelect = onSelect;
    this.activeId = null;
    this.sessions = [];
  }

  async load() {
    try {
      const resp = await fetch('/api/chat/conversations');
      if (!resp.ok) return;
      const data = await resp.json();
      this.sessions = data.conversations || [];
      this._render();
      if (this.sessions.length && !this.activeId) this.select(this.sessions[0].id);
    } catch (e) { console.error('SessionManager.load:', e); }
  }

  select(id) {
    this.activeId = id;
    this._render();
    this.onSelect(id);
  }

  async createNew() {
    try {
      const resp = await fetch('/api/chat/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: 'New conversation' }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      await this.load();
      if (data.conversation_id) this.select(data.conversation_id);
    } catch (e) { console.error('SessionManager.createNew:', e); }
  }

  markActive(id) { this.activeId = id; this._render(); }

  _render() {
    this.listEl.textContent = '';
    this.sessions.forEach(s => {
      const item = _mk('div', 'ac-session-item' + (s.id === this.activeId ? ' active' : ''));
      const title = _mk('div', 'ac-session-title');
      title.textContent = s.title || 'Conversation';
      const date = _mk('div', 'ac-session-date');
      date.textContent = s.updated_at ? new Date(s.updated_at).toLocaleDateString() : '';
      item.appendChild(title);
      item.appendChild(date);
      item.addEventListener('click', () => this.select(s.id));
      this.listEl.appendChild(item);
    });
  }
}

/* ── MessageStream ── */
class MessageStream {
  constructor({ messageListEl, inputEl, sendBtn, jumpBtn, onConvCreated }) {
    this.messageListEl = messageListEl;
    this.inputEl = inputEl;
    this.sendBtn = sendBtn;
    this.jumpBtn = jumpBtn;
    this.onConvCreated = onConvCreated;
    this.currentConvId = null;
    this._userScrolled = false;
    this._streamingBubble = null;

    messageListEl.addEventListener('scroll', () => {
      const el = messageListEl;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      this._userScrolled = !atBottom;
      if (jumpBtn) jumpBtn.classList.toggle('visible', this._userScrolled);
    });
    if (jumpBtn) {
      jumpBtn.addEventListener('click', () => {
        this._scrollToBottom();
        this._userScrolled = false;
        jumpBtn.classList.remove('visible');
      });
    }
  }

  async loadHistory(convId) {
    this.currentConvId = convId;
    this.messageListEl.textContent = '';
    try {
      const resp = await fetch('/api/chat/messages?conv_id=' + convId);
      if (!resp.ok) return;
      const data = await resp.json();
      (data.messages || []).forEach(m => this._appendMessage(m));
      this._scrollToBottom();
    } catch (e) { console.error('loadHistory:', e); }
  }

  async send(message) {
    if (!message.trim()) return;
    this.inputEl.disabled = true;
    this.sendBtn.disabled = true;

    this._appendBubble('inbound', message, '');
    this._scrollToBottom();
    this._streamingBubble = this._appendBubble('outbound', '', '');
    this._streamingBubble.querySelector('.ac-message-bubble').classList.add('ac-streaming-cursor');

    try {
      const resp = await fetch('/api/chat/send_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, conversation_id: this.currentConvId }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.type === 'token') {
              this._appendToken(evt.content);
              if (!this._userScrolled) this._scrollToBottom();
            } else if (evt.type === 'done') {
              this._finaliseStream();
              if (evt.conversation_id && !this.currentConvId) {
                this.currentConvId = evt.conversation_id;
                if (this.onConvCreated) this.onConvCreated(evt.conversation_id);
              }
            } else if (evt.type === 'error') {
              this._appendToken('\n[Error: ' + evt.message + ']');
              this._finaliseStream();
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      console.error('send failed:', e);
      this._appendToken('\n[Connection error. Please try again.]');
      this._finaliseStream();
    } finally {
      this.inputEl.disabled = false;
      this.sendBtn.disabled = false;
      this.inputEl.focus();
    }
  }

  _appendMessage(msg) {
    const direction = msg.direction === 'inbound' ? 'inbound' : 'outbound';
    const extra = msg.channel === 'telegram' ? ' telegram' : '';
    const date = msg.created_at
      ? new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : '';
    const metaText = date + (msg.channel === 'telegram' ? ' · via Telegram' : '');
    return this._appendBubble(direction + extra, msg.content || '', metaText);
  }

  _appendBubble(direction, text, metaText) {
    const wrap = _mk('div', 'ac-message ' + direction);
    const bubble = _mk('div', 'ac-message-bubble');
    bubble.textContent = text;
    const meta = _mk('div', 'ac-message-meta');
    meta.textContent = metaText;
    wrap.appendChild(bubble);
    wrap.appendChild(meta);
    this.messageListEl.appendChild(wrap);
    return wrap;
  }

  _appendToken(token) {
    if (!this._streamingBubble) return;
    const bubble = this._streamingBubble.querySelector('.ac-message-bubble');
    bubble.textContent += token;
  }

  _finaliseStream() {
    if (!this._streamingBubble) return;
    const bubble = this._streamingBubble.querySelector('.ac-message-bubble');
    bubble.classList.remove('ac-streaming-cursor');
    const meta = this._streamingBubble.querySelector('.ac-message-meta');
    meta.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    this._streamingBubble = null;
    this._scheduleSummary();
  }

  _scheduleSummary() {
    const convId = this.currentConvId;
    if (!convId) return;
    document.addEventListener('visibilitychange', function once() {
      if (document.visibilityState === 'hidden') {
        navigator.sendBeacon('/api/chat/sessions/' + convId + '/summarize');
        document.removeEventListener('visibilitychange', once);
      }
    });
  }

  _scrollToBottom() { this.messageListEl.scrollTop = this.messageListEl.scrollHeight; }
}

/* ── StatusPanel ── */
class StatusPanel {
  constructor({ agentsEl, platformEl }) {
    this.agentsEl = agentsEl;
    this.platformEl = platformEl;
    this._timer = null;
  }

  start() { this.refresh(); this._timer = setInterval(() => this.refresh(), 10000); }
  stop() { if (this._timer) clearInterval(this._timer); }

  async refresh() {
    try {
      const resp = await fetch('/api/status');
      if (!resp.ok) return;
      const data = await resp.json();
      this._renderAgents(data.agents || []);
      this._renderPlatform(data.platform || {});
    } catch (_) {}
  }

  _renderAgents(agents) {
    if (!this.agentsEl) return;
    this.agentsEl.textContent = '';
    if (!agents.length) {
      const row = _mk('div', 'ac-agent-row');
      row.style.color = '#556677';
      row.textContent = 'No active agents';
      this.agentsEl.appendChild(row);
      return;
    }
    agents.forEach(a => {
      const row = _mk('div', 'ac-agent-row');
      const dotCls = ['working','deployed'].includes(a.shift_state) ? 'working'
        : a.shift_state === 'active' ? 'active' : 'idle';
      const dot = _mk('div', 'ac-agent-dot ' + dotCls);
      const name = _mk('span', 'ac-agent-name');
      name.textContent = a.display_name || a.name || '';
      row.appendChild(dot);
      row.appendChild(name);
      this.agentsEl.appendChild(row);
    });
  }

  _renderPlatform(platform) {
    if (!this.platformEl) return;
    this.platformEl.textContent = '';
    Object.entries(platform).forEach(([key, val]) => {
      const row = _mk('div', 'ac-health-row');
      const label = _mk('span');
      label.textContent = key.toUpperCase();
      const dotCls = val === 'healthy' ? 'healthy' : String(val).startsWith('error') ? 'error' : 'warning';
      const dot = _mk('div', 'ac-health-dot ' + dotCls);
      row.appendChild(label);
      row.appendChild(dot);
      this.platformEl.appendChild(row);
    });
  }
}

/* ── FocusMode ── */
class FocusMode {
  constructor({ layoutEl, toggleEl }) {
    this.layoutEl = layoutEl;
    this.toggleEl = toggleEl;
    this.focused = localStorage.getItem('ac-focus-mode') === 'true';
    this._apply();
    toggleEl.addEventListener('click', () => this.toggle());
  }
  toggle() { this.focused = !this.focused; localStorage.setItem('ac-focus-mode', this.focused); this._apply(); }
  _apply() {
    this.layoutEl.classList.toggle('focus-mode', this.focused);
    this.toggleEl.title = this.focused ? 'Exit Focus Mode' : 'Focus Mode';
    this.toggleEl.textContent = this.focused ? '⊞' : '⊟';
  }
}

/* ── Boot ── */
document.addEventListener('DOMContentLoaded', () => {
  const layout = document.getElementById('ac-layout');
  if (!layout) return;

  const stream = new MessageStream({
    messageListEl: document.getElementById('ac-message-list'),
    inputEl: document.getElementById('ac-input'),
    sendBtn: document.getElementById('ac-send-btn'),
    jumpBtn: document.getElementById('ac-jump-latest'),
    onConvCreated: id => sessions.markActive(id),
  });

  const sessions = new SessionManager({
    listEl: document.getElementById('ac-session-list'),
    onSelect: id => stream.loadHistory(id),
  });

  const status = new StatusPanel({
    agentsEl: document.getElementById('ac-agents'),
    platformEl: document.getElementById('ac-platform'),
  });

  new FocusMode({
    layoutEl: layout,
    toggleEl: document.getElementById('ac-focus-toggle'),
  });

  const doSend = () => {
    const msg = document.getElementById('ac-input').value.trim();
    if (!msg || document.getElementById('ac-input').disabled) return;
    document.getElementById('ac-input').value = '';
    document.getElementById('ac-input').style.height = 'auto';
    stream.send(msg);
  };

  document.getElementById('ac-send-btn').addEventListener('click', doSend);
  document.getElementById('ac-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  document.getElementById('ac-input').addEventListener('input', e => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  });
  document.getElementById('ac-new-session').addEventListener('click', () => sessions.createNew());

  sessions.load();
  status.start();
});
```

- [ ] **Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/static/js/archie-chat.js
git commit -m "feat(archie-comms): Command Center JS - SessionManager, MessageStream, StatusPanel, FocusMode"
```

---

## Task 7: Replace chat.html

**Files:**
- Replace: `archie-comms/templates/chat.html`

- [ ] **Step 1: Back up existing template**

```bash
cp /mnt/archie_brain/archie-comms/templates/chat.html \
   /mnt/archie_brain/archie-comms/templates/chat.html.bak
```

- [ ] **Step 2: Check actual base template name and block names**

```bash
head -5 /mnt/archie_brain/archie-comms/templates/chat.html.bak
```
Note the `{% extends "..." %}` value and the block names (`{% block content %}`, etc). Use the exact same values below.

- [ ] **Step 3: Write the new template (adjust extends/block names from Step 2)**

```html
{% extends "base_comms.html" %}
{% block title %}A.R.C.H.I.E. Command Center{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/archie-chat.css') }}">
{% endblock %}

{% block content %}
<div class="ac-layout" id="ac-layout">

  <div class="ac-sidebar-left">
    <div class="ac-sidebar-header">Conversations</div>
    <div class="ac-session-list" id="ac-session-list"></div>
    <div class="ac-new-session" id="ac-new-session">+ New Conversation</div>
  </div>

  <div class="ac-chat-center">
    <div class="ac-chat-header">
      <span>&#9679; A.R.C.H.I.E. &middot; ONLINE</span>
      <span class="ac-focus-toggle" id="ac-focus-toggle">&#8863;</span>
    </div>
    <div style="position:relative;flex:1;overflow:hidden;display:flex;flex-direction:column;">
      <div class="ac-message-list" id="ac-message-list"></div>
      <div class="ac-jump-latest" id="ac-jump-latest">&#8595; Jump to latest</div>
    </div>
    <div class="ac-input-bar">
      <textarea class="ac-input" id="ac-input" rows="1"
        placeholder="Ask ARCHIE anything&hellip; or delegate a task to her team"
      ></textarea>
      <button class="ac-send-btn" id="ac-send-btn">SEND &#8629;</button>
    </div>
  </div>

  <div class="ac-sidebar-right">
    <div class="ac-status-section">
      <div class="ac-status-section-title">Agent Activity</div>
      <div id="ac-agents"></div>
    </div>
    <div class="ac-status-section">
      <div class="ac-status-section-title">Platform</div>
      <div id="ac-platform"></div>
    </div>
    <a class="ac-terminal-link" href="/claude/terminal">Open Terminal &#8594;</a>
  </div>

</div>
{% endblock %}

{% block extra_scripts %}
<script src="{{ url_for('static', filename='js/archie-chat.js') }}"></script>
{% endblock %}
```

- [ ] **Step 4: Restart and visual check**

```bash
docker compose restart archie_comms && sleep 5
docker logs archie_comms --tail 20
```
Open https://archie.kytranempowerment.com. Verify:
- Three-column layout renders
- No JS console errors
- Status panel populates within 10s
- Session list loads past conversations

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-comms/templates/chat.html
git commit -m "feat(archie-comms): replace chat.html with Command Center template"
```

---

## Task 8: End-to-End Verification + PR

- [ ] **Step 1: Run full test suite**

```bash
cd /mnt/archie_brain/archie-comms && python -m pytest tests/test_chat_overhaul.py -v
```
Expected: all tests PASS.

- [ ] **Step 2: Test streaming in browser**
Type a message, press Enter. Verify tokens stream one by one with blinking cursor, cursor removes when done.

- [ ] **Step 3: Test session persistence**
Refresh page. Verify message history reloads from DB. Switch to a past session, verify its history loads.

- [ ] **Step 4: Test KB summary**
Send 3+ messages, close tab (triggers sendBeacon). Wait 30s. Run:

```bash
docker exec archie_database psql -U archie -d archie \
  -c "SELECT id, title, LEFT(content,80) FROM knowledge_base WHERE knowledge_type='conversation_memory' ORDER BY id DESC LIMIT 3;"
```
Expected: a new row appears.

- [ ] **Step 5: Test Focus Mode**
Click toggle to enter focus mode. Refresh page. Sidebars should remain hidden (localStorage).

- [ ] **Step 6: Test Telegram bridge**
Send a message to ARCHIE via Telegram. Open web UI. Verify the message appears tagged "via Telegram".

- [ ] **Step 7: Mark task in progress**

```
mcp__archie__start_working_on(task_id=2349)
```

- [ ] **Step 8: Open PR**

```bash
cd /mnt/archie_brain
git push -u origin feat/archie-chat-overhaul
gh pr create \
  --title "feat(archie-comms): Sub-A Chat Overhaul - Command Center + SSE streaming + KB memory" \
  --body "$(cat <<'PREOF'
## Summary
- Replaces chat.html with Command Center (3-col: sessions, chat, status)
- SSE token-by-token streaming (Claude CLI feel)
- KB memory: session summaries on close, recall_context injected on open
- Live agent status + platform health panel (10s / 30s poll)
- Telegram messages appear in web history tagged via Telegram
- Focus Mode toggle persisted in localStorage
- All dynamic content via textContent (no XSS vectors)

## Test plan
- [ ] All unit tests pass
- [ ] Chat history persists across page refresh
- [ ] Messages stream token by token
- [ ] KB summaries appear after closing tab
- [ ] Status panel shows live agent data
- [ ] Focus mode collapses sidebars and persists
- [ ] Telegram messages tagged in web UI
- [ ] No regression to director reports or triage routes

Closes Task #2349 / Project #288

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
PREOF
)"
```

- [ ] **Step 9: Mark task complete**

```
mcp__archie__complete_task(task_id=2349, notes="Sub-A shipped. PR open on feat/archie-chat-overhaul. Command Center, SSE streaming, KB B+C memory model, Telegram bridge preserved.")
```
