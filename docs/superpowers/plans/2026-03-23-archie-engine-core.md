# ARCHIE Engine Core — Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python engine daemon that powers the ARCHIE Code CLI — intent classification, tool dispatch, inference routing, session management, and WebSocket server.

**Architecture:** Standalone Python package (`archie_engine/`) with asyncio event loop. WebSocket server accepts connections from Go TUI and Web Chat. Intent parser classifies user input, command router dispatches to tool handlers, inference client talks to Ollama. SQLite for local session storage. No Flask, no PostgreSQL, no platform_v2 dependencies.

**Tech Stack:** Python 3.11+, asyncio, websockets, aiosqlite, Ollama REST API, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-03-23-archie-code-cli-design.md` (Sections 4, 6, 13)

**Reference code:** `archie_engine_staging/` — 2,423 lines of platform-specific code. Use as logic reference only; do NOT import or depend on these files. The engine must be standalone.

**Rollback:** All tasks are additive (new package). Rollback: `rm -rf archie_engine/` and revert commits.

---

## File Structure

```
archie_engine/
  __init__.py              — Package init, version
  __main__.py              — CLI entry point (python -m archie_engine)
  config.py                — Settings, environment, paths
  database.py              — SQLite connection, schema, migrations
  session.py               — Session lifecycle, context management
  intent.py                — Intent classification (rule-based + LLM)
  router.py                — Intent to tool dispatch to response
  engine.py                — Main daemon, request/response loop
  server.py                — WebSocket server (asyncio)
  inference.py             — Ollama client, model management
  tools/
    __init__.py            — Tool registry
    base.py                — BaseTool abstract class
    file_ops.py            — read, write, edit, glob, grep
    git_ops.py             — status, diff, commit, branch, log
    shell_ops.py           — run commands with sandboxing
  tests/
    __init__.py
    conftest.py            — Shared fixtures (tmp dirs, mock Ollama)
    test_config.py
    test_database.py
    test_session.py
    test_intent.py
    test_router.py
    test_tools.py
    test_file_ops.py
    test_git_ops.py
    test_shell_ops.py
    test_inference.py
    test_server.py
    test_engine.py
```

**Design principles:**
- Each file has one responsibility with a clear interface
- All I/O is async (aiosqlite, aiohttp/websockets, asyncio.subprocess)
- Tools are registered via a registry pattern — easy to add new ones
- Intent parser uses rule-based matching first, LLM classification as fallback
- No platform_v2 imports — this package must run standalone on any machine

---

## Task Overview (12 Tasks)

| # | Task | Scope | Est. Steps |
|---|------|-------|------------|
| 2.1 | Package scaffold | pyproject.toml, __init__, __main__, config | 5 |
| 2.2 | SQLite database layer | Schema, migrations, async connection | 8 |
| 2.3 | Tool base + registry | BaseTool ABC, ToolRegistry, discovery | 6 |
| 2.4 | File operations tool | read, write, edit, glob, grep | 8 |
| 2.5 | Git operations tool | status, diff, commit, branch, log | 8 |
| 2.6 | Shell operations tool | run with allowlist/denylist sandbox | 8 |
| 2.7 | Inference client | Ollama REST client, model warm-up, streaming | 8 |
| 2.8 | Session manager | Create, resume, context, history in SQLite | 8 |
| 2.9 | Intent parser | Rule-based + LLM classification, 6 intent types | 8 |
| 2.10 | Command router | Intent to tool selection to response | 8 |
| 2.11 | WebSocket server | asyncio server, JSON protocol, connection mgmt | 8 |
| 2.12 | Engine daemon + E2E | Main loop, CLI entry, integration test | 8 |

---

### Task 2.1: Package scaffold

**Files:**
- Create: `archie_engine/__init__.py`
- Create: `archie_engine/__main__.py`
- Create: `archie_engine/config.py`
- Create: `archie_engine/pyproject.toml`

- [ ] **Step 1: Create package directory**

```bash
mkdir -p archie_engine/tests
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "archie-engine"
version = "0.1.0"
description = "ARCHIE Code CLI — Python engine daemon"
requires-python = ">=3.11"
dependencies = [
    "websockets>=12.0",
    "aiosqlite>=0.19.0",
    "aiohttp>=3.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
archie-engine = "archie_engine.__main__:main"
```

- [ ] **Step 3: Write __init__.py**

```python
"""ARCHIE Engine — Python daemon for the ARCHIE Code CLI."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Write config.py**

```python
"""Engine configuration — environment variables and defaults."""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class EngineConfig:
    """Engine settings loaded from environment."""

    # Paths
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("ARCHIE_DATA_DIR", Path.home() / ".archie")
    ))

    # Ollama
    ollama_host: str = field(default_factory=lambda: os.environ.get(
        "OLLAMA_HOST", "http://localhost:11434"
    ))
    default_model: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_MODEL", "qwen2.5:7b"
    ))

    # Server
    ws_host: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_WS_HOST", "127.0.0.1"
    ))
    ws_port: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_WS_PORT", "9090"
    )))

    # Hub (optional — Plan 3)
    hub_url: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_HUB_URL", ""
    ))
    hub_api_key: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_HUB_API_KEY", ""
    ))

    # Safety
    shell_denylist: list[str] = field(default_factory=lambda: [
        "rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:",
        "chmod -R 777", "> /dev/sda",
    ])

    @property
    def db_path(self) -> Path:
        return self.data_dir / "engine.db"

    def ensure_dirs(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: Write __main__.py and commit**

```python
"""CLI entry point — python -m archie_engine."""

import sys


def main():
    """Start the ARCHIE engine daemon."""
    print("ARCHIE Engine v0.1.0")
    print("Engine starting... (not yet implemented)")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

```bash
git add archie_engine/
git commit -m "feat(engine): scaffold package with config and entry point"
```

---

### Task 2.2: SQLite database layer

**Files:**
- Create: `archie_engine/database.py`
- Create: `archie_engine/tests/conftest.py`
- Create: `archie_engine/tests/__init__.py`
- Create: `archie_engine/tests/test_database.py`

- [ ] **Step 1: Write test for database creation and schema**

```python
# archie_engine/tests/test_database.py
import pytest
from archie_engine.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_initialize_creates_tables(db):
    """All required tables should exist after init."""
    tables = await db.list_tables()
    assert "sessions" in tables
    assert "messages" in tables
    assert "tool_calls" in tables


@pytest.mark.asyncio
async def test_schema_version(db):
    """Schema version should be tracked."""
    version = await db.get_schema_version()
    assert version >= 1
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_database.py -v
```

Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write conftest.py with shared fixtures**

```python
# archie_engine/tests/conftest.py
import pytest


@pytest.fixture
def engine_config(tmp_path):
    """Config pointing to temp directory."""
    from archie_engine.config import EngineConfig
    return EngineConfig(data_dir=tmp_path)
```

- [ ] **Step 4: Implement database.py**

Build `Database` class with:
- `initialize()` — open aiosqlite connection, create schema (sessions, messages, tool_calls tables)
- `close()` — close connection
- `list_tables()` — query sqlite_master
- `get_schema_version()` — track migrations
- `fetchone(sql, params)` / `fetchall(sql, params)` — query helpers
- `commit()` — explicit commit
- Schema version tracking via `schema_version` table

Schema tables:
- `sessions` (id TEXT PK, created_at, updated_at, working_dir, metadata)
- `messages` (id INTEGER PK, session_id FK, role CHECK, content, created_at, metadata)
- `tool_calls` (id INTEGER PK, session_id FK, message_id FK, tool_name, arguments, result, status CHECK, started_at, completed_at)

- [ ] **Step 5: Run tests**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_database.py -v
```

Expected: PASS

- [ ] **Step 6: Add message CRUD tests**

```python
@pytest.mark.asyncio
async def test_insert_and_fetch_message(db):
    """Messages round-trip through the database."""
    await db.execute(
        "INSERT INTO sessions (id, working_dir) VALUES (?, ?)",
        ("test-session", "/tmp"),
    )
    await db.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        ("test-session", "user", "hello"),
    )
    await db.commit()

    messages = await db.fetchall(
        "SELECT * FROM messages WHERE session_id = ?", ("test-session",)
    )
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
```

- [ ] **Step 7: Run all tests**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_database.py -v
```

- [ ] **Step 8: Commit**

```bash
git add archie_engine/database.py archie_engine/tests/
git commit -m "feat(engine): SQLite database layer with session and message storage"
```

---

### Task 2.3: Tool base class and registry

**Files:**
- Create: `archie_engine/tools/__init__.py`
- Create: `archie_engine/tools/base.py`
- Create: `archie_engine/tests/test_tools.py`

- [ ] **Step 1: Write test for tool registry**

```python
# archie_engine/tests/test_tools.py
import pytest
from archie_engine.tools.base import BaseTool, ToolResult
from archie_engine.tools import ToolRegistry


class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes input back"

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output=kwargs.get("text", ""))


@pytest.mark.asyncio
async def test_registry_register_and_get():
    registry = ToolRegistry()
    registry.register(EchoTool())
    tool = registry.get("echo")
    assert tool is not None
    assert tool.name == "echo"


@pytest.mark.asyncio
async def test_registry_execute():
    registry = ToolRegistry()
    registry.register(EchoTool())
    result = await registry.execute("echo", text="hello")
    assert result.success is True
    assert result.output == "hello"


def test_registry_list_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"


@pytest.mark.asyncio
async def test_registry_unknown_tool():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent")
    assert result.success is False
    assert "not found" in result.error.lower()
```

- [ ] **Step 2: Run — verify fail**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_tools.py -v
```

- [ ] **Step 3: Implement base.py**

Build `BaseTool` (ABC) with:
- `name: str` and `description: str` class attributes
- `execute(**kwargs) -> ToolResult` abstract method
- `to_dict() -> dict` for discovery metadata

Build `ToolResult` dataclass with: `success: bool`, `output: str`, `error: str`, `metadata: dict`

- [ ] **Step 4: Implement tools/__init__.py (ToolRegistry)**

Build `ToolRegistry` with:
- `register(tool)` — add tool by name
- `get(name) -> BaseTool | None` — lookup
- `list_tools() -> list[dict]` — all tool metadata
- `execute(name, **kwargs) -> ToolResult` — execute with error handling

- [ ] **Step 5: Run tests**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_tools.py -v
```

- [ ] **Step 6: Commit**

```bash
git add archie_engine/tools/
git commit -m "feat(engine): tool base class and registry pattern"
```

---

### Task 2.4: File operations tool

**Files:**
- Create: `archie_engine/tools/file_ops.py`
- Create: `archie_engine/tests/test_file_ops.py`

- [ ] **Step 1: Write tests for file operations**

```python
# archie_engine/tests/test_file_ops.py
import pytest
from pathlib import Path
from archie_engine.tools.file_ops import FileOpsTool


@pytest.fixture
def file_tool(tmp_path):
    return FileOpsTool(workspace=tmp_path)


@pytest.mark.asyncio
async def test_read_file(file_tool, tmp_path):
    (tmp_path / "test.txt").write_text("hello world")
    result = await file_tool.execute(operation="read", path="test.txt")
    assert result.success
    assert "hello world" in result.output


@pytest.mark.asyncio
async def test_write_file(file_tool, tmp_path):
    result = await file_tool.execute(
        operation="write", path="new.txt", content="created"
    )
    assert result.success
    assert (tmp_path / "new.txt").read_text() == "created"


@pytest.mark.asyncio
async def test_edit_file(file_tool, tmp_path):
    (tmp_path / "edit.txt").write_text("old value")
    result = await file_tool.execute(
        operation="edit", path="edit.txt",
        old_string="old value", new_string="new value"
    )
    assert result.success
    assert (tmp_path / "edit.txt").read_text() == "new value"


@pytest.mark.asyncio
async def test_glob(file_tool, tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = await file_tool.execute(operation="glob", pattern="*.py")
    assert result.success
    assert "a.py" in result.output
    assert "b.py" in result.output
    assert "c.txt" not in result.output


@pytest.mark.asyncio
async def test_grep(file_tool, tmp_path):
    (tmp_path / "search.py").write_text("def hello():\n    return 'world'\n")
    result = await file_tool.execute(
        operation="grep", pattern="hello", path="search.py"
    )
    assert result.success
    assert "def hello" in result.output


@pytest.mark.asyncio
async def test_read_outside_workspace_blocked(file_tool):
    result = await file_tool.execute(operation="read", path="/etc/passwd")
    assert not result.success
    assert "outside workspace" in result.error.lower()


@pytest.mark.asyncio
async def test_write_outside_workspace_blocked(file_tool):
    result = await file_tool.execute(
        operation="write", path="/tmp/evil.txt", content="bad"
    )
    assert not result.success
```

- [ ] **Step 2: Run — verify fail**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_file_ops.py -v
```

- [ ] **Step 3: Implement file_ops.py**

Build `FileOpsTool(BaseTool)` with:
- `workspace` path that all operations are sandboxed to
- `_resolve_path()` that rejects traversal outside workspace
- Operations: read, write, edit (string replacement), glob, grep
- Glob uses `pathlib.Path.glob()`
- Grep uses `asyncio.subprocess` running `grep -rn`

- [ ] **Step 4: Run tests**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/test_file_ops.py -v
```

- [ ] **Step 5: Handle edge cases**

Add tests for: read nonexistent file (error), edit with no match (error), empty pattern (error).

- [ ] **Step 6: Run all tests**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/ -v
```

- [ ] **Step 7: Verify tool registers correctly**

Quick test: instantiate FileOpsTool, register in ToolRegistry, list_tools().

- [ ] **Step 8: Commit**

```bash
git add archie_engine/tools/file_ops.py archie_engine/tests/test_file_ops.py
git commit -m "feat(engine): file operations tool — read, write, edit, glob, grep"
```

---

### Task 2.5: Git operations tool

**Files:**
- Create: `archie_engine/tools/git_ops.py`
- Create: `archie_engine/tests/test_git_ops.py`

- [ ] **Step 1: Write tests for git operations**

```python
# archie_engine/tests/test_git_ops.py
import pytest
import subprocess
from pathlib import Path
from archie_engine.tools.git_ops import GitOpsTool


@pytest.fixture
def git_repo(tmp_path):
    """Create a temp git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        capture_output=True,
    )
    return tmp_path


@pytest.fixture
def git_tool(git_repo):
    return GitOpsTool(workspace=git_repo)


@pytest.mark.asyncio
async def test_status_clean(git_tool):
    result = await git_tool.execute(operation="status")
    assert result.success


@pytest.mark.asyncio
async def test_status_with_changes(git_tool, git_repo):
    (git_repo / "new.txt").write_text("changed")
    result = await git_tool.execute(operation="status")
    assert result.success
    assert "new.txt" in result.output


@pytest.mark.asyncio
async def test_diff(git_tool, git_repo):
    (git_repo / "README.md").write_text("# Modified")
    result = await git_tool.execute(operation="diff")
    assert result.success
    assert "Modified" in result.output


@pytest.mark.asyncio
async def test_log(git_tool):
    result = await git_tool.execute(operation="log", count=5)
    assert result.success
    assert "init" in result.output


@pytest.mark.asyncio
async def test_commit(git_tool, git_repo):
    (git_repo / "new.txt").write_text("content")
    subprocess.run(["git", "-C", str(git_repo), "add", "new.txt"], capture_output=True)
    result = await git_tool.execute(operation="commit", message="add new file")
    assert result.success


@pytest.mark.asyncio
async def test_branch_list(git_tool):
    result = await git_tool.execute(operation="branch")
    assert result.success
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement git_ops.py**

Build `GitOpsTool(BaseTool)` with:
- Operations: status, diff, log, commit, branch (list/create/switch)
- All via `asyncio.create_subprocess_exec("git", ...)`
- Workspace-scoped (all commands run with `-C workspace`)

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Edge case tests**

Not a git repo (clear error), commit with nothing staged (error).

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Verify register**

- [ ] **Step 8: Commit**

```bash
git add archie_engine/tools/git_ops.py archie_engine/tests/test_git_ops.py
git commit -m "feat(engine): git operations tool — status, diff, log, commit, branch"
```

---

### Task 2.6: Shell operations tool

**Files:**
- Create: `archie_engine/tools/shell_ops.py`
- Create: `archie_engine/tests/test_shell_ops.py`

- [ ] **Step 1: Write tests**

```python
# archie_engine/tests/test_shell_ops.py
import pytest
from archie_engine.tools.shell_ops import ShellOpsTool
from archie_engine.config import EngineConfig


@pytest.fixture
def shell_tool(tmp_path):
    config = EngineConfig(data_dir=tmp_path)
    return ShellOpsTool(workspace=tmp_path, config=config)


@pytest.mark.asyncio
async def test_simple_command(shell_tool):
    result = await shell_tool.execute(command="echo hello")
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_cwd_is_workspace(shell_tool, tmp_path):
    result = await shell_tool.execute(command="pwd")
    assert result.success
    assert str(tmp_path) in result.output


@pytest.mark.asyncio
async def test_denylist_blocks_dangerous(shell_tool):
    result = await shell_tool.execute(command="rm -rf /")
    assert not result.success
    assert "blocked" in result.error.lower() or "denied" in result.error.lower()


@pytest.mark.asyncio
async def test_timeout(shell_tool):
    result = await shell_tool.execute(command="sleep 30", timeout=1)
    assert not result.success
    assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_stderr_captured(shell_tool):
    result = await shell_tool.execute(command="ls /nonexistent_dir_12345")
    assert not result.success
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement shell_ops.py**

Build `ShellOpsTool(BaseTool)` with:
- `config.shell_denylist` checked before running (substring match)
- `asyncio.create_subprocess_shell()` with timeout
- stdout + stderr captured
- Non-zero exit code sets `success=False`
- Configurable timeout (default 120s)

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Add denylist pattern matching tests**

Test partial matches (e.g., `"rm -rf / --no-preserve-root"` also blocked).

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Verify register**

- [ ] **Step 8: Commit**

```bash
git add archie_engine/tools/shell_ops.py archie_engine/tests/test_shell_ops.py
git commit -m "feat(engine): shell operations tool with denylist sandboxing"
```

---

### Task 2.7: Inference client

**Files:**
- Create: `archie_engine/inference.py`
- Create: `archie_engine/tests/test_inference.py`

- [ ] **Step 1: Write tests with mock Ollama**

```python
# archie_engine/tests/test_inference.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from archie_engine.inference import InferenceClient


@pytest.fixture
def client():
    return InferenceClient(ollama_host="http://localhost:11434")


@pytest.mark.asyncio
async def test_generate_returns_response(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "response": "Hello! How can I help?",
        "model": "qwen2.5:7b",
        "done": True,
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await client.generate(prompt="hello", model="qwen2.5:7b")
    assert result["response"] == "Hello! How can I help?"


@pytest.mark.asyncio
async def test_chat_returns_message(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Hi there!"},
        "model": "qwen2.5:7b",
        "done": True,
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="qwen2.5:7b",
        )
    assert result["message"]["content"] == "Hi there!"


@pytest.mark.asyncio
async def test_list_models(client):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2:3b"}]
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        models = await client.list_models()
    assert len(models) == 2


@pytest.mark.asyncio
async def test_connection_error_handled(client):
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Connection refused")):
        result = await client.generate(prompt="test", model="test")
    assert "error" in result
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement inference.py**

Build `InferenceClient` with:
- `generate(prompt, model, system=None, context=None)` — POST `/api/generate`
- `chat(messages, model, system=None)` — POST `/api/chat`
- `list_models()` — GET `/api/tags`
- `is_available()` — health check
- `warm_model(model)` — POST `/api/generate` with empty prompt to preload
- All using `aiohttp.ClientSession`
- Structured error handling (no crashes on connection failure)
- Timeout configurable (default 300s for generation)

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Add streaming support test**

Test streaming generate with mock chunked response.

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Verify with live Ollama (manual, optional)**

```bash
python -c "
import asyncio
from archie_engine.inference import InferenceClient
async def test():
    c = InferenceClient()
    print(await c.is_available())
asyncio.run(test())
"
```

- [ ] **Step 8: Commit**

```bash
git add archie_engine/inference.py archie_engine/tests/test_inference.py
git commit -m "feat(engine): Ollama inference client with generate, chat, streaming"
```

---

### Task 2.8: Session manager

**Files:**
- Create: `archie_engine/session.py`
- Create: `archie_engine/tests/test_session.py`

- [ ] **Step 1: Write tests**

```python
# archie_engine/tests/test_session.py
import pytest
from archie_engine.database import Database
from archie_engine.session import SessionManager


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def session_mgr(db):
    return SessionManager(db)


@pytest.mark.asyncio
async def test_create_session(session_mgr):
    session = await session_mgr.create(working_dir="/tmp/project")
    assert session["id"] is not None
    assert session["working_dir"] == "/tmp/project"


@pytest.mark.asyncio
async def test_resume_session(session_mgr):
    created = await session_mgr.create(working_dir="/tmp/project")
    resumed = await session_mgr.get(created["id"])
    assert resumed is not None
    assert resumed["id"] == created["id"]


@pytest.mark.asyncio
async def test_add_message(session_mgr):
    session = await session_mgr.create(working_dir="/tmp")
    await session_mgr.add_message(session["id"], role="user", content="hello")
    await session_mgr.add_message(session["id"], role="assistant", content="hi!")
    history = await session_mgr.get_history(session["id"])
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_get_history_limit(session_mgr):
    session = await session_mgr.create(working_dir="/tmp")
    for i in range(20):
        await session_mgr.add_message(session["id"], "user", f"msg {i}")
    history = await session_mgr.get_history(session["id"], limit=5)
    assert len(history) == 5


@pytest.mark.asyncio
async def test_record_tool_call(session_mgr):
    session = await session_mgr.create(working_dir="/tmp")
    tool_id = await session_mgr.record_tool_call(
        session_id=session["id"],
        tool_name="file_ops",
        arguments={"operation": "read", "path": "test.py"},
    )
    assert tool_id is not None


@pytest.mark.asyncio
async def test_build_context(session_mgr):
    session = await session_mgr.create(working_dir="/tmp/myproject")
    await session_mgr.add_message(session["id"], "user", "fix the bug")
    context = await session_mgr.build_context(session["id"])
    assert context["working_dir"] == "/tmp/myproject"
    assert len(context["history"]) == 1
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement session.py**

Build `SessionManager` with:
- `create(working_dir) -> dict` — create new session with UUID
- `get(session_id) -> dict | None` — resume existing
- `add_message(session_id, role, content, metadata=None)` — append message
- `get_history(session_id, limit=50) -> list[dict]` — fetch recent history
- `record_tool_call(session_id, tool_name, arguments) -> int` — log tool usage
- `update_tool_result(tool_id, result, status)` — update after running
- `build_context(session_id) -> dict` — session info + recent history for LLM
- All async, using Database instance

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Run all tests**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add archie_engine/session.py archie_engine/tests/test_session.py
git commit -m "feat(engine): session manager with history, context, tool tracking"
```

---

### Task 2.9: Intent parser

**Files:**
- Create: `archie_engine/intent.py`
- Create: `archie_engine/tests/test_intent.py`

**Reference:** `archie_engine_staging/intent_parser.py` has 18 intent types. The engine uses 6 core types for local CLI operations. Hub-specific types (team_task, station_management, etc.) are deferred to Plan 3.

**Intent types for CLI:**
- `code_task` — write/modify/fix code
- `file_operation` — read/search/navigate files
- `git_operation` — git commands
- `shell_command` — run terminal commands
- `knowledge_query` — ask questions about codebase
- `conversation` — general chat (fallback)

- [ ] **Step 1: Write tests**

```python
# archie_engine/tests/test_intent.py
import pytest
from archie_engine.intent import IntentParser


@pytest.fixture
def parser():
    return IntentParser()


def test_classify_code_task(parser):
    result = parser.classify("fix the authentication bug in login.py")
    assert result["type"] == "code_task"
    assert 0.0 <= result["confidence"] <= 1.0


def test_classify_file_operation(parser):
    result = parser.classify("read the contents of config.py")
    assert result["type"] == "file_operation"


def test_classify_git_operation(parser):
    result = parser.classify("show me the git diff")
    assert result["type"] == "git_operation"


def test_classify_shell_command(parser):
    result = parser.classify("run npm test")
    assert result["type"] == "shell_command"


def test_classify_conversation_fallback(parser):
    result = parser.classify("how are you today?")
    assert result["type"] == "conversation"


def test_classify_knowledge_query(parser):
    result = parser.classify("what does the auth middleware do?")
    assert result["type"] == "knowledge_query"


def test_classify_returns_required_fields(parser):
    result = parser.classify("do something")
    assert "type" in result
    assert "confidence" in result
    assert "raw_input" in result
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement intent.py (rule-based)**

Build `IntentParser` with:
- `classify(text) -> dict` — returns `{type, confidence, raw_input, entities}`
- Rule-based keyword matching first (fast, no LLM needed)
- Keyword patterns per intent type
- Confidence based on keyword match strength
- Fallback to "conversation" if no pattern matches
- `classify_with_llm(text, inference_client)` — async stub for ambiguous cases (wired in Task 2.10)

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Test ambiguous inputs**

```python
def test_classify_ambiguous_defaults_conversation(parser):
    result = parser.classify("hmm interesting")
    assert result["type"] == "conversation"
    assert result["confidence"] < 0.5
```

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Verify entity extraction**

Test that file paths, git refs, etc. are extracted from input.

- [ ] **Step 8: Commit**

```bash
git add archie_engine/intent.py archie_engine/tests/test_intent.py
git commit -m "feat(engine): intent parser with rule-based classification, 6 types"
```

---

### Task 2.10: Command router

**Files:**
- Create: `archie_engine/router.py`
- Create: `archie_engine/tests/test_router.py`

- [ ] **Step 1: Write tests**

```python
# archie_engine/tests/test_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from archie_engine.router import CommandRouter
from archie_engine.tools.base import ToolResult


@pytest.fixture
def mock_tools():
    from archie_engine.tools import ToolRegistry
    registry = ToolRegistry()

    mock_file = MagicMock()
    mock_file.name = "file_ops"
    mock_file.execute = AsyncMock(return_value=ToolResult(success=True, output="file content"))
    registry.register(mock_file)

    mock_git = MagicMock()
    mock_git.name = "git_ops"
    mock_git.execute = AsyncMock(return_value=ToolResult(success=True, output="clean"))
    registry.register(mock_git)

    return registry


@pytest.fixture
def mock_inference():
    client = AsyncMock()
    client.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Here's the fix..."}
    })
    return client


@pytest.fixture
def router(mock_tools, mock_inference):
    return CommandRouter(tools=mock_tools, inference=mock_inference)


@pytest.mark.asyncio
async def test_route_file_operation(router):
    intent = {"type": "file_operation", "confidence": 0.9, "raw_input": "read config.py"}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["success"]


@pytest.mark.asyncio
async def test_route_git_operation(router):
    intent = {"type": "git_operation", "confidence": 0.9, "raw_input": "git status"}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["success"]


@pytest.mark.asyncio
async def test_route_conversation_uses_llm(router, mock_inference):
    intent = {"type": "conversation", "confidence": 0.8, "raw_input": "hello"}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["response"]
    mock_inference.chat.assert_called_once()


@pytest.mark.asyncio
async def test_route_code_task_uses_llm(router, mock_inference):
    intent = {"type": "code_task", "confidence": 0.9, "raw_input": "fix the bug"}
    context = {"working_dir": "/tmp", "history": []}
    result = await router.route(intent, context=context)
    mock_inference.chat.assert_called_once()


@pytest.mark.asyncio
async def test_route_tool_error_handled(router, mock_tools):
    mock_tools.get("file_ops").execute = AsyncMock(
        return_value=ToolResult(success=False, error="file not found")
    )
    intent = {"type": "file_operation", "confidence": 0.9, "raw_input": "read missing.py"}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert not result["success"] or "not found" in result.get("response", "").lower()
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement router.py**

Build `CommandRouter` with:
- `route(intent, context) -> dict` — main dispatch
- Intent type to handler mapping:
  - `file_operation` — parse operation + path from input, call `file_ops` tool
  - `git_operation` — parse git subcommand, call `git_ops` tool
  - `shell_command` — extract command, call `shell_ops` tool
  - `code_task` — build prompt with context, call inference client
  - `knowledge_query` — build prompt with context, call inference client
  - `conversation` — call inference with chat history
- Response format: `{success, response, tool_calls: [], model_used}`

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Test error handling**

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Verify all tools integrate**

- [ ] **Step 8: Commit**

```bash
git add archie_engine/router.py archie_engine/tests/test_router.py
git commit -m "feat(engine): command router — intent to tool/inference dispatch"
```

---

### Task 2.11: WebSocket server

**Files:**
- Create: `archie_engine/server.py`
- Create: `archie_engine/tests/test_server.py`

- [ ] **Step 1: Write tests**

```python
# archie_engine/tests/test_server.py
import pytest
import json
import asyncio
from archie_engine.server import EngineServer


@pytest.fixture
async def server():
    srv = EngineServer(host="127.0.0.1", port=0)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.mark.asyncio
async def test_server_starts_and_stops(server):
    assert server.is_running


@pytest.mark.asyncio
async def test_server_accepts_connection(server):
    import websockets
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "pong"


@pytest.mark.asyncio
async def test_multiple_connections(server):
    import websockets
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        await ws1.send(json.dumps({"type": "ping"}))
        await ws2.send(json.dumps({"type": "ping"}))
        r1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5))
        r2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=5))
        assert r1["type"] == "pong"
        assert r2["type"] == "pong"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement server.py**

Build `EngineServer` with:
- `start()` / `stop()` — lifecycle
- WebSocket handler that accepts JSON messages
- Message types: ping (pong), message (route through engine), session_create, session_resume
- Connection tracking
- Graceful shutdown
- `set_handler(fn)` — callback for message processing (wired by Engine)

JSON Protocol:
- Request: `{"type": "message", "session_id": "abc", "content": "fix the bug"}`
- Response: `{"type": "response", "session_id": "abc", "content": "...", "tool_calls": [...]}`
- Streaming (future): `{"type": "chunk"/"done", "session_id": "abc"}`

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Test malformed messages handled**

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Verify graceful shutdown**

- [ ] **Step 8: Commit**

```bash
git add archie_engine/server.py archie_engine/tests/test_server.py
git commit -m "feat(engine): WebSocket server with JSON protocol"
```

---

### Task 2.12: Engine daemon and end-to-end test

**Files:**
- Create: `archie_engine/engine.py`
- Modify: `archie_engine/__main__.py` (wire up)
- Create: `archie_engine/tests/test_engine.py`

- [ ] **Step 1: Write integration test**

```python
# archie_engine/tests/test_engine.py
import pytest
import json
import asyncio
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig


@pytest.fixture
async def engine(tmp_path):
    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config)
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_engine_starts_and_stops(engine):
    assert engine.is_running


@pytest.mark.asyncio
async def test_engine_processes_message(engine):
    import websockets
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "hello",
        }))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        assert response["type"] in ("response", "error")


@pytest.mark.asyncio
async def test_engine_creates_session(engine):
    import websockets
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "session_create", "working_dir": "/tmp"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response.get("session_id") is not None
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement engine.py**

Build `Engine` — the main orchestrator wiring everything together:
- Constructor takes `EngineConfig`, creates Database, SessionManager, InferenceClient, IntentParser, ToolRegistry (with all 3 tools), CommandRouter, EngineServer
- `start()` — ensure dirs, init DB, set server handler, start server
- `stop()` — stop server, close DB
- `handle_message(msg) -> dict` — create/resume session, parse intent, route, record in session, return response
- `is_running` property

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Wire up __main__.py**

Update `__main__.py` to create `Engine(config)`, start it with asyncio, handle SIGINT/SIGTERM for graceful shutdown. Print startup banner with version and WebSocket URL.

- [ ] **Step 6: Run full test suite**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 7: Manual smoke test (optional, needs Ollama)**

```bash
# Start engine
python -m archie_engine

# Connect and send message
python -c "
import asyncio, json, websockets
async def test():
    async with websockets.connect('ws://127.0.0.1:9090') as ws:
        await ws.send(json.dumps({'type': 'message', 'content': 'hello'}))
        print(json.loads(await ws.recv()))
asyncio.run(test())
"
```

- [ ] **Step 8: Commit**

```bash
git add archie_engine/engine.py archie_engine/__main__.py archie_engine/tests/test_engine.py
git commit -m "feat(engine): daemon with WebSocket server, intent routing, tool dispatch

Completes Plan 2 — Engine Core. Components:
- SQLite session storage
- 3 tool types (file, git, shell) via registry
- Ollama inference client
- Rule-based intent parser (6 types)
- Command router (intent to tool/inference dispatch)
- WebSocket server (JSON protocol)
- Engine daemon wiring it all together

Ready for Plan 3 (Hub Connectivity) and Plan 6 (Go TUI)."
```

---

## Post-Plan Checklist

After all 12 tasks complete:

```bash
# Full test suite
python -m pytest archie_engine/tests/ -v

# Push
git push

# Log in Dev HQ
mcp log_decision: "ARCHIE Engine Core complete — standalone Python package"
mcp update_project_understanding: project 185 to 50%
```

## What's Next

- **Plan 3 (Hub Connectivity):** hub/connector.py, heartbeat, sync, auth
- **Plan 4 (Skill System):** skills/loader.py, registry, executor
- **Plan 5 (Claude Collaboration):** MCP server/client, context bridge
- **Plan 6 (Go TUI):** Bubble Tea interface connecting to engine WebSocket
