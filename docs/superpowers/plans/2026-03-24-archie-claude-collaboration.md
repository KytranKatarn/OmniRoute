# ARCHIE Claude Collaboration — Implementation Plan (Plan 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable ARCHIE Engine to collaborate with Claude CLI — expose engine tools as an MCP server (so Claude can use them), and provide a context bridge that shares structured project context between ARCHIE and Claude sessions.

**Architecture:** `archie_engine/claude/` contains an MCP server (stdio transport) that exposes engine tools to Claude CLI, a context bridge that builds structured context documents, and escalation logic that detects when to suggest Claude involvement. The MCP server follows the Model Context Protocol spec — Claude CLI connects via `mcp.json` configuration.

**Tech Stack:** Python 3.11+, MCP SDK (mcp python package), stdio transport, JSON-RPC 2.0.

**Spec:** `docs/superpowers/specs/2026-03-23-archie-code-cli-design.md` (Section 6)

**Depends on:** Plan 2 (Engine Core), Plan 3 (Hub Connectivity).

**Rollback:** All tasks are additive. Rollback: `rm -rf archie_engine/claude/` and revert commits.

---

## File Structure

```
archie_engine/claude/
  __init__.py          — Module init
  mcp_server.py        — MCP server exposing engine tools via stdio
  context_bridge.py    — Structured context sharing protocol
  escalation.py        — Detect when to suggest Claude involvement
```

Tests:
```
archie_engine/tests/
  test_context_bridge.py
  test_escalation.py
  test_mcp_server.py
```

---

## Task Overview (6 Tasks)

| # | Task | Scope | Est. Steps |
|---|------|-------|------------|
| 5.1 | Claude package scaffold | __init__.py, install mcp SDK | 4 |
| 5.2 | Context bridge | Build structured context documents | 8 |
| 5.3 | Escalation logic | Complexity detection, failure counting | 8 |
| 5.4 | MCP server — tool exposure | Expose file/git/shell/skill tools via MCP | 8 |
| 5.5 | Engine integration | Wire claude module, generate mcp.json | 6 |
| 5.6 | Push and close out | Push, log decision | 4 |

---

### Task 5.1: Claude package scaffold

**Files:**
- Create: `archie_engine/claude/__init__.py`

- [ ] **Step 1: Create directory**

```bash
mkdir -p archie_engine/claude
```

- [ ] **Step 2: Install MCP SDK**

```bash
pip install --break-system-packages mcp
```

If `mcp` package is not available, we'll implement a lightweight JSON-RPC stdio server ourselves — the protocol is simple.

- [ ] **Step 3: Create __init__.py**

```python
"""Claude collaboration — MCP server, context bridge, escalation."""
```

- [ ] **Step 4: Commit**

```bash
git add archie_engine/claude/ && git commit -m "feat(engine): claude collaboration package scaffold"
```

---

### Task 5.2: Context bridge

**Files:**
- Create: `archie_engine/claude/context_bridge.py`
- Create: `archie_engine/tests/test_context_bridge.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from archie_engine.claude.context_bridge import ContextBridge


@pytest.fixture
def bridge():
    return ContextBridge(working_dir="/tmp/myproject")


def test_build_context_has_required_fields(bridge):
    ctx = bridge.build_context(
        task="Fix auth bug",
        files=["auth.py", "rbac.py"],
    )
    assert ctx["task"] == "Fix auth bug"
    assert ctx["working_dir"] == "/tmp/myproject"
    assert "files_involved" in ctx
    assert "auth.py" in ctx["files_involved"]


def test_build_context_with_intent(bridge):
    ctx = bridge.build_context(
        task="Fix auth bug",
        intent={"type": "code_task", "confidence": 0.9},
    )
    assert ctx["intent"]["type"] == "code_task"


def test_build_context_with_kb_context(bridge):
    ctx = bridge.build_context(
        task="Fix auth bug",
        kb_entries=[{"content": "Auth uses JWT tokens", "importance": 0.9}],
    )
    assert len(ctx["kb_context"]) == 1


def test_build_context_with_session_history(bridge):
    ctx = bridge.build_context(
        task="Fix auth bug",
        history=[
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "Looking at auth.py..."},
        ],
    )
    assert len(ctx["history"]) == 2


def test_to_markdown(bridge):
    ctx = bridge.build_context(task="Fix auth bug", files=["auth.py"])
    md = bridge.to_markdown(ctx)
    assert "Fix auth bug" in md
    assert "auth.py" in md


def test_to_json(bridge):
    import json
    ctx = bridge.build_context(task="Fix auth bug")
    j = bridge.to_json(ctx)
    parsed = json.loads(j)
    assert parsed["task"] == "Fix auth bug"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement context_bridge.py**

```python
"""Context bridge — structured context sharing between ARCHIE and Claude."""

import json
from datetime import datetime


class ContextBridge:
    def __init__(self, working_dir: str = ""):
        self.working_dir = working_dir

    def build_context(
        self,
        task: str,
        files: list[str] | None = None,
        intent: dict | None = None,
        kb_entries: list[dict] | None = None,
        history: list[dict] | None = None,
        branch: str | None = None,
    ) -> dict:
        """Build a structured context document for Claude."""
        return {
            "session_id": None,
            "task": task,
            "working_dir": self.working_dir,
            "files_involved": files or [],
            "intent": intent or {},
            "kb_context": kb_entries or [],
            "history": history or [],
            "branch": branch or "",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def to_markdown(self, ctx: dict) -> str:
        """Render context as markdown for human/LLM consumption."""
        lines = [f"# Task: {ctx['task']}", ""]
        if ctx.get("working_dir"):
            lines.append(f"**Working directory:** `{ctx['working_dir']}`")
        if ctx.get("branch"):
            lines.append(f"**Branch:** `{ctx['branch']}`")
        if ctx.get("files_involved"):
            lines.append(f"**Files:** {', '.join(f'`{f}`' for f in ctx['files_involved'])}")
        if ctx.get("kb_context"):
            lines.append("\n## Knowledge Base Context")
            for entry in ctx["kb_context"]:
                lines.append(f"- {entry.get('content', '')}")
        if ctx.get("history"):
            lines.append("\n## Conversation History")
            for msg in ctx["history"]:
                lines.append(f"**{msg['role']}:** {msg['content']}")
        return "\n".join(lines)

    def to_json(self, ctx: dict) -> str:
        """Serialize context as JSON."""
        return json.dumps(ctx, indent=2, default=str)
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): context bridge — structured context sharing for Claude"
```

---

### Task 5.3: Escalation logic

**Files:**
- Create: `archie_engine/claude/escalation.py`
- Create: `archie_engine/tests/test_escalation.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from archie_engine.claude.escalation import EscalationDetector


@pytest.fixture
def detector():
    return EscalationDetector()


def test_no_escalation_simple_task(detector):
    result = detector.should_escalate(
        intent={"type": "file_operation", "confidence": 0.9},
        failure_count=0,
    )
    assert not result["escalate"]


def test_escalate_on_low_confidence(detector):
    result = detector.should_escalate(
        intent={"type": "code_task", "confidence": 0.3},
        failure_count=0,
    )
    assert result["escalate"]
    assert "confidence" in result["reason"].lower()


def test_escalate_on_repeated_failures(detector):
    result = detector.should_escalate(
        intent={"type": "code_task", "confidence": 0.8},
        failure_count=3,
    )
    assert result["escalate"]
    assert "failure" in result["reason"].lower()


def test_escalate_complex_code_task(detector):
    result = detector.should_escalate(
        intent={"type": "code_task", "confidence": 0.7},
        failure_count=0,
        context={"files_involved": ["a.py", "b.py", "c.py", "d.py", "e.py"]},
    )
    assert result["escalate"]
    assert "complex" in result["reason"].lower()


def test_no_escalate_simple_conversation(detector):
    result = detector.should_escalate(
        intent={"type": "conversation", "confidence": 0.9},
        failure_count=0,
    )
    assert not result["escalate"]


def test_user_override_always_escalates(detector):
    result = detector.should_escalate(
        intent={"type": "file_operation", "confidence": 0.9},
        failure_count=0,
        user_requested=True,
    )
    assert result["escalate"]
    assert "user" in result["reason"].lower()
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement escalation.py**

```python
"""Escalation logic — detect when to suggest Claude involvement."""

import logging

logger = logging.getLogger(__name__)

# Thresholds
CONFIDENCE_THRESHOLD = 0.4
FAILURE_THRESHOLD = 2
COMPLEXITY_FILE_THRESHOLD = 4


class EscalationDetector:
    def should_escalate(
        self,
        intent: dict,
        failure_count: int = 0,
        context: dict | None = None,
        user_requested: bool = False,
    ) -> dict:
        """Determine if a task should be escalated to Claude."""
        if user_requested:
            return {"escalate": True, "reason": "User requested Claude assistance"}

        # Low confidence on classification
        confidence = intent.get("confidence", 1.0)
        if confidence < CONFIDENCE_THRESHOLD:
            return {"escalate": True, "reason": f"Low confidence ({confidence:.1f}) on intent classification"}

        # Repeated failures
        if failure_count >= FAILURE_THRESHOLD:
            return {"escalate": True, "reason": f"Repeated failures ({failure_count}) on this task"}

        # Complex code tasks (many files involved)
        intent_type = intent.get("type", "")
        if intent_type == "code_task" and context:
            files = context.get("files_involved", [])
            if len(files) >= COMPLEXITY_FILE_THRESHOLD:
                return {"escalate": True, "reason": f"Complex task spanning {len(files)} files"}

        return {"escalate": False, "reason": ""}
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): escalation detector — confidence, failures, complexity thresholds"
```

---

### Task 5.4: MCP server — tool exposure

**Files:**
- Create: `archie_engine/claude/mcp_server.py`
- Create: `archie_engine/tests/test_mcp_server.py`

- [ ] **Step 1: Write tests**

```python
import pytest
import json
from archie_engine.claude.mcp_server import MCPToolServer


@pytest.fixture
def tool_defs():
    return [
        {"name": "file_read", "description": "Read a file", "parameters": {"path": {"type": "string"}}},
        {"name": "git_status", "description": "Git status", "parameters": {}},
        {"name": "shell_exec", "description": "Run shell command", "parameters": {"command": {"type": "string"}}},
    ]


@pytest.fixture
def server(tool_defs):
    return MCPToolServer(tools=tool_defs)


def test_handle_initialize(server):
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = server.handle_message(json.dumps(request))
    result = json.loads(response)
    assert result["result"]["capabilities"]["tools"] is not None


def test_handle_tools_list(server):
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    response = server.handle_message(json.dumps(request))
    result = json.loads(response)
    tools = result["result"]["tools"]
    assert len(tools) == 3
    names = [t["name"] for t in tools]
    assert "file_read" in names


def test_handle_unknown_method(server):
    request = {"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}}
    response = server.handle_message(json.dumps(request))
    result = json.loads(response)
    assert "error" in result


def test_build_tool_definitions(server):
    defs = server.get_tool_definitions()
    assert len(defs) == 3
    for d in defs:
        assert "name" in d
        assert "description" in d
        assert "inputSchema" in d
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement mcp_server.py**

Build a lightweight MCP-compatible JSON-RPC server (no SDK dependency needed):

```python
"""MCP server — exposes engine tools to Claude CLI via JSON-RPC."""

import json
import logging

logger = logging.getLogger(__name__)

MCP_VERSION = "2024-11-05"


class MCPToolServer:
    """Lightweight MCP server for tool exposure via stdio."""

    def __init__(self, tools: list[dict]):
        self._tools = tools
        self._tool_handler = None

    def set_tool_handler(self, handler):
        """Set callback for tool/call: async fn(name, args) -> result."""
        self._tool_handler = handler

    def get_tool_definitions(self) -> list[dict]:
        """Get MCP-formatted tool definitions."""
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {
                    "type": "object",
                    "properties": t.get("parameters", {}),
                },
            }
            for t in self._tools
        ]

    def handle_message(self, raw: str) -> str:
        """Handle a JSON-RPC message. Returns JSON-RPC response string."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return self._error_response(None, -32700, "Parse error")

        msg_id = msg.get("id")
        method = msg.get("method", "")

        if method == "initialize":
            return self._success_response(msg_id, {
                "protocolVersion": MCP_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "archie-engine",
                    "version": "0.1.0",
                },
            })

        if method == "tools/list":
            return self._success_response(msg_id, {
                "tools": self.get_tool_definitions(),
            })

        if method == "notifications/initialized":
            return ""  # No response needed for notifications

        return self._error_response(msg_id, -32601, f"Method not found: {method}")

    def _success_response(self, msg_id, result: dict) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error_response(self, msg_id, code: int, message: str) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): MCP server — expose tools to Claude CLI via JSON-RPC"
```

---

### Task 5.5: Engine integration

**Files:**
- Modify: `archie_engine/engine.py` — wire claude module
- Create: `archie_engine/tests/test_claude_integration.py`

- [ ] **Step 1: Write test**

```python
import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig


@pytest_asyncio.fixture
async def engine(tmp_path):
    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config)
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_engine_has_context_bridge(engine):
    assert engine.context_bridge is not None


@pytest.mark.asyncio
async def test_engine_has_escalation_detector(engine):
    assert engine.escalation_detector is not None


@pytest.mark.asyncio
async def test_engine_has_mcp_server(engine):
    assert engine.mcp_server is not None


@pytest.mark.asyncio
async def test_mcp_tool_count(engine):
    tools = engine.mcp_server.get_tool_definitions()
    assert len(tools) >= 3  # file_ops, git_ops, shell_ops at minimum
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Wire claude into Engine**

Add to engine.py `__init__`:
```python
from archie_engine.claude.context_bridge import ContextBridge
from archie_engine.claude.escalation import EscalationDetector
from archie_engine.claude.mcp_server import MCPToolServer

# In __init__:
self.context_bridge = ContextBridge(working_dir=str(Path.cwd()))
self.escalation_detector = EscalationDetector()
self.mcp_server = MCPToolServer(tools=[
    {"name": "file_read", "description": "Read a file", "parameters": {"path": {"type": "string"}}},
    {"name": "file_write", "description": "Write a file", "parameters": {"path": {"type": "string"}, "content": {"type": "string"}}},
    {"name": "git_status", "description": "Git repository status", "parameters": {}},
    {"name": "git_diff", "description": "Git diff of changes", "parameters": {}},
    {"name": "shell_exec", "description": "Execute shell command", "parameters": {"command": {"type": "string"}}},
    {"name": "search_knowledge", "description": "Search ARCHIE knowledge base", "parameters": {"query": {"type": "string"}}},
])
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run FULL suite**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): claude integration — context bridge, escalation, MCP server wired

Completes Plan 5 — Claude Collaboration. Components:
- Context bridge (structured context sharing)
- Escalation detector (confidence, failures, complexity)
- MCP server (JSON-RPC tool exposure for Claude CLI)
- Engine wired with all claude components"
```

---

### Task 5.6: Push and close out

- [ ] **Step 1: Push**
- [ ] **Step 2: Log decision**
- [ ] **Step 3: Update project understanding to 75%**
