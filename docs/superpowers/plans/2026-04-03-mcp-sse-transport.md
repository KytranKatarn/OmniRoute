# MCP SSE Transport — Run Inside Docker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the MCP server from a standalone stdio process into the Docker container, accessible via SSE over HTTP. This means `docker compose restart archie_platform` also restarts the MCP server — no more stale code in a separate Python process.

**Architecture:** Add an SSE endpoint to the existing Flask app at `/mcp/sse`. The MCP protocol handler (`MCPProtocolHandler`) already exists — we just need a new transport layer that reads/writes via SSE instead of stdio. Claude Code connects via `url: "http://192.168.1.200:3000/mcp/sse"` in `.mcp.json`.

**Tech Stack:** Flask (existing), Server-Sent Events (SSE), existing custom MCP server code

**CRITICAL:** Change `.mcp.json` as the LAST step. Once changed, the current session's MCP breaks. The user must restart Claude after this change.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `platform_v2/mcp_server/sse_transport.py` | SSE transport for MCP (replaces stdio) | Create |
| `platform_v2/mcp_server/server.py` | Add `run_sse()` method to MCPProtocolHandler | Modify |
| `platform_v2/app.py` | Mount MCP SSE endpoint at `/mcp/sse` | Modify |
| `.mcp.json` | Switch from `command` to `url` transport | Modify (LAST) |

---

### Task 1: Create SSE Transport

**Files:**
- Create: `platform_v2/mcp_server/sse_transport.py`

The SSE transport implements MCP over HTTP using Server-Sent Events:
- **GET `/mcp/sse`** — Client connects, receives SSE stream. Server sends MCP responses as SSE events.
- **POST `/mcp/message`** — Client sends MCP requests as JSON POST. Server processes and pushes response via the SSE stream.

- [ ] **Step 1: Create the SSE transport module**

```python
"""MCP SSE Transport — runs MCP protocol over HTTP Server-Sent Events.

Replaces stdio transport. Mounted on Flask app so it lives inside Docker.
Claude Code connects via url: "http://192.168.1.200:3000/mcp/sse"

Usage:
    from mcp_server.sse_transport import mcp_sse_bp
    app.register_blueprint(mcp_sse_bp)
"""

import json
import queue
import logging
import threading
import uuid
from datetime import datetime
from flask import Blueprint, Response, request, jsonify

logger = logging.getLogger(__name__)

mcp_sse_bp = Blueprint("mcp_sse", __name__)

# Active SSE sessions: session_id -> message_queue
_sessions = {}
_sessions_lock = threading.Lock()

# MCP handler instance (set during init)
_mcp_handler = None


def init_mcp_sse(handler):
    """Initialize with the MCPProtocolHandler instance."""
    global _mcp_handler
    _mcp_handler = handler
    logger.info("MCP SSE transport initialized")


@mcp_sse_bp.route("/mcp/sse")
def sse_stream():
    """SSE endpoint — client connects here for the event stream."""
    session_id = str(uuid.uuid4())
    msg_queue = queue.Queue()

    with _sessions_lock:
        _sessions[session_id] = msg_queue

    logger.info("MCP SSE session connected: %s", session_id)

    # Send the session endpoint URL as the first event
    endpoint_url = f"/mcp/message?session_id={session_id}"

    def generate():
        # First event: tell client where to POST messages
        yield f"event: endpoint\ndata: {endpoint_url}\n\n"

        try:
            while True:
                try:
                    # Wait for messages from the handler
                    msg = msg_queue.get(timeout=30)
                    if msg is None:
                        break
                    yield f"event: message\ndata: {json.dumps(msg, default=str)}\n\n"
                except queue.Empty:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            with _sessions_lock:
                _sessions.pop(session_id, None)
            logger.info("MCP SSE session disconnected: %s", session_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@mcp_sse_bp.route("/mcp/message", methods=["POST"])
def receive_message():
    """Receive MCP request from client, process, push response via SSE."""
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    with _sessions_lock:
        msg_queue = _sessions.get(session_id)
    if not msg_queue:
        return jsonify({"error": "session not found"}), 404

    if not _mcp_handler:
        return jsonify({"error": "MCP handler not initialized"}), 500

    try:
        message = request.get_json()
        if not message:
            return jsonify({"error": "invalid JSON"}), 400

        # Process the MCP message (reuse existing handler logic)
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                _mcp_handler.handle_message(message)
            )
        finally:
            loop.close()

        if response:
            msg_queue.put(response)

        return jsonify({"ok": True}), 202

    except Exception as e:
        logger.error("MCP SSE message error: %s", e)
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Verify it loads**

```bash
docker exec archie_platform python3 -c "from mcp_server.sse_transport import mcp_sse_bp; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/mcp_server/sse_transport.py
git commit -m "feat(mcp): add SSE transport for in-Docker MCP server"
```

---

### Task 2: Add handle_message Method to MCPProtocolHandler

**Files:**
- Modify: `platform_v2/mcp_server/server.py`

The existing `run_stdio()` method reads JSON from stdin, processes it, and writes to stdout. We need to extract the processing logic into a `handle_message(message)` method that both stdio and SSE can use.

- [ ] **Step 1: Read the existing `run_stdio` method** to understand the message processing flow

- [ ] **Step 2: Extract message handling into `handle_message()`**

Find the core message processing logic inside `run_stdio()` (the part between reading from stdin and writing to stdout). Extract it into:

```python
async def handle_message(self, message: dict) -> Optional[dict]:
    """Process a single MCP message and return response.

    Used by both stdio and SSE transports.
    """
    # ... existing processing logic from run_stdio ...
```

- [ ] **Step 3: Update `run_stdio()` to call `handle_message()`**

Replace the inline processing in `run_stdio()` with a call to `handle_message()`.

- [ ] **Step 4: Verify stdio still works** (important — don't break current transport)

```bash
docker exec archie_platform python3 -c "from mcp_server.server import MCPProtocolHandler; h = MCPProtocolHandler(None); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/mcp_server/server.py
git commit -m "refactor(mcp): extract handle_message from stdio loop for transport reuse"
```

---

### Task 3: Mount SSE Blueprint in Flask App

**Files:**
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Register the MCP SSE blueprint and initialize the handler**

In `app.py`, after other blueprint registrations, add:

```python
# MCP SSE transport (allows MCP to run inside Docker)
try:
    from mcp_server.sse_transport import mcp_sse_bp, init_mcp_sse
    from mcp_server.server import MCPProtocolHandler, MCPServer

    mcp_server_instance = MCPServer()
    mcp_protocol_handler = MCPProtocolHandler(mcp_server_instance)
    init_mcp_sse(mcp_protocol_handler)
    app.register_blueprint(mcp_sse_bp)
    logger.info("MCP SSE transport mounted at /mcp/sse")
except Exception as e:
    logger.warning("MCP SSE transport not available: %s", e)
```

Note: Read the existing `MCPServer` and `MCPProtocolHandler` constructors to understand required args. Adapt as needed.

- [ ] **Step 2: Deploy and verify endpoint exists**

```bash
docker compose restart archie_platform
sleep 15
curl -s http://192.168.1.200:3000/mcp/sse -H "Accept: text/event-stream" --max-time 5 2>&1 | head -3
```

Expected: SSE stream starts with `event: endpoint` line.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(mcp): mount SSE transport on Flask app at /mcp/sse"
```

---

### Task 4: Update .mcp.json (DO THIS LAST)

**Files:**
- Modify: `.mcp.json`

**WARNING:** This change breaks the current session's MCP connection. User must restart Claude after this.

- [ ] **Step 1: Verify SSE endpoint works end-to-end**

Test with a manual MCP handshake:
```bash
# In one terminal, connect SSE:
curl -N http://192.168.1.200:3000/mcp/sse -H "Accept: text/event-stream"
# Note the session_id from the endpoint event

# In another terminal, send initialize:
curl -X POST "http://192.168.1.200:3000/mcp/message?session_id=<SESSION_ID>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}'
```

- [ ] **Step 2: Update .mcp.json**

Replace the `archie` server config:

```json
{
  "mcpServers": {
    "archie": {
      "url": "http://192.168.1.200:3000/mcp/sse"
    }
  }
}
```

Keep all other MCP servers unchanged.

- [ ] **Step 3: Commit and push**

```bash
git add .mcp.json
git commit -m "feat(mcp): switch to SSE transport inside Docker — restart Claude to activate"
git push origin main
```

- [ ] **Step 4: Tell user to restart Claude**

---

## Verification

After restarting Claude:
1. `mcp search_knowledge "test query"` — should work
2. Make a code change, deploy, search again — results should reflect new code immediately
3. Check `docker logs archie_platform | grep "MCP SSE"` for connection logs

## Rollback

If SSE doesn't work, revert `.mcp.json` to the stdio config:
```json
{
  "mcpServers": {
    "archie": {
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/mnt/archie_brain/platform_v2"
    }
  }
}
```
