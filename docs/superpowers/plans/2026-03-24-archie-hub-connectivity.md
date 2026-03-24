# ARCHIE Hub Connectivity — Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the ARCHIE Engine to the ARCHIE Hub (platform at 192.168.1.200:3000) for agent orchestration, knowledge base access, skill sync, and model coordination. Enables the Node distribution tier.

**Architecture:** Hub connectivity lives in `archie_engine/hub/` — a REST API client that wraps the existing Starbase/mesh endpoints. Background heartbeat thread keeps registration alive. Sync pulls skills and model state. Auth uses encrypted API key storage. All hub features degrade gracefully when offline.

**Tech Stack:** Python 3.11+, aiohttp (REST client), asyncio, keyring (optional, for secure key storage).

**Spec:** `docs/superpowers/specs/2026-03-23-archie-code-cli-design.md` (Sections 5, 10, 11)

**Depends on:** Plan 2 (Engine Core) — complete.

**Rollback:** All tasks are additive (new hub/ subpackage). Rollback: `rm -rf archie_engine/hub/` and revert commits.

---

## File Structure

```
archie_engine/hub/
  __init__.py          — Hub status enum, is_connected helper
  connector.py         — REST API client wrapping Starbase endpoints
  heartbeat.py         — Background registration + keepalive
  sync.py              — Skill sync, model state, agent assignment cache
  auth.py              — API key storage, Bearer token, scope validation
```

Tests:
```
archie_engine/tests/
  test_connector.py    — Mock HTTP tests for all endpoints
  test_heartbeat.py    — Heartbeat lifecycle, offline resilience
  test_sync.py         — Sync protocol tests
  test_auth.py         — Key storage, token construction
  test_hub_integration.py — E2E with engine wiring
```

---

## Task Overview (8 Tasks)

| # | Task | Scope | Est. Steps |
|---|------|-------|------------|
| 3.1 | Hub package scaffold | __init__.py, HubStatus enum, config additions | 5 |
| 3.2 | Auth module | API key storage, Bearer token, scope check | 8 |
| 3.3 | Connector — core client | Base HTTP client, error handling, retry | 8 |
| 3.4 | Connector — endpoints | register, health, dispatch, kb_search, agents | 8 |
| 3.5 | Heartbeat | Background keepalive, offline detection, reconnect | 8 |
| 3.6 | Sync — skills | Pull skills from hub, cache locally | 8 |
| 3.7 | Sync — models + agents | Model state, agent assignment cache | 6 |
| 3.8 | Engine integration + E2E | Wire hub into Engine, graceful degradation | 8 |

---

### Task 3.1: Hub package scaffold

**Files:**
- Create: `archie_engine/hub/__init__.py`
- Modify: `archie_engine/config.py` — add hub-specific config fields

- [ ] **Step 1: Create hub directory**

```bash
mkdir -p archie_engine/hub
```

- [ ] **Step 2: Create hub/__init__.py with status enum**

```python
"""Hub connectivity — connects engine to ARCHIE platform."""

from enum import Enum


class HubStatus(Enum):
    DISCONNECTED = "disconnected"    # No hub configured
    CONNECTING = "connecting"        # Attempting to connect
    CONNECTED = "connected"          # Active connection
    OFFLINE = "offline"              # Was connected, now unreachable
    AUTH_FAILED = "auth_failed"      # Bad API key


def is_hub_configured(config) -> bool:
    """Check if hub URL and API key are set."""
    return bool(config.hub_url and config.hub_api_key)
```

- [ ] **Step 3: Add hub config fields to EngineConfig**

Add to `archie_engine/config.py`:
```python
    # Hub connectivity
    hub_heartbeat_interval: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_HUB_HEARTBEAT", "30"
    )))
    hub_timeout: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_HUB_TIMEOUT", "10"
    )))
    hub_retry_max: int = 3
    hub_skills_cache_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("ARCHIE_DATA_DIR", str(Path.home() / ".archie"))
    ) / "skills_cache")
```

- [ ] **Step 4: Test config additions**

```python
def test_hub_config_defaults():
    from archie_engine.config import EngineConfig
    config = EngineConfig()
    assert config.hub_heartbeat_interval == 30
    assert config.hub_timeout == 10
```

- [ ] **Step 5: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub package scaffold with status enum and config"
```

---

### Task 3.2: Auth module

**Files:**
- Create: `archie_engine/hub/auth.py`
- Create: `archie_engine/tests/test_auth.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from pathlib import Path
from archie_engine.hub.auth import HubAuth


@pytest.fixture
def auth(tmp_path):
    return HubAuth(key_file=tmp_path / ".archie_key")


def test_store_and_load_key(auth):
    auth.store_key("test-api-key-12345")
    loaded = auth.load_key()
    assert loaded == "test-api-key-12345"


def test_load_key_missing(auth):
    loaded = auth.load_key()
    assert loaded is None


def test_bearer_header(auth):
    auth.store_key("mykey")
    headers = auth.get_headers()
    assert headers["Authorization"] == "Bearer mykey"


def test_clear_key(auth):
    auth.store_key("mykey")
    auth.clear_key()
    assert auth.load_key() is None


def test_has_key(auth):
    assert not auth.has_key()
    auth.store_key("mykey")
    assert auth.has_key()
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement auth.py**

Build `HubAuth` with:
- `__init__(self, key_file: Path)` — path to store API key
- `store_key(key: str)` — write key to file (chmod 600)
- `load_key() -> str | None` — read from file
- `clear_key()` — delete file
- `has_key() -> bool` — file exists check
- `get_headers() -> dict` — returns `{"Authorization": "Bearer <key>", "Content-Type": "application/json"}`

Simple file-based storage for now. Key file permissions set to 600 (owner-only).

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub auth module — API key storage and Bearer token"
```

---

### Task 3.3: Connector — core HTTP client

**Files:**
- Create: `archie_engine/hub/connector.py`
- Create: `archie_engine/tests/test_connector.py`

- [ ] **Step 1: Write tests for base client**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.auth import HubAuth


def _mock_response(status=200, json_data=None):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


@pytest.fixture
def connector(tmp_path):
    auth = HubAuth(key_file=tmp_path / ".key")
    auth.store_key("test-key")
    return HubConnector(hub_url="http://localhost:3000", auth=auth, timeout=5)


@pytest.mark.asyncio
async def test_get_success(connector):
    mock_resp = _mock_response(200, {"status": "ok"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_post_success(connector):
    mock_resp = _mock_response(200, {"result": "done"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.post("/api/action", data={"key": "val"})
    assert result["result"] == "done"


@pytest.mark.asyncio
async def test_auth_failure_returns_error(connector):
    mock_resp = _mock_response(401, {"error": "unauthorized"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert "error" in result


@pytest.mark.asyncio
async def test_connection_error_returns_error(connector):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Connection refused")):
        result = await connector.get("/api/health")
    assert "error" in result


@pytest.mark.asyncio
async def test_server_error_returns_error(connector):
    mock_resp = _mock_response(500, {"error": "internal"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert "error" in result
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement connector.py base client**

Build `HubConnector` with:
- `__init__(self, hub_url, auth, timeout=10)`
- `async get(path, params=None) -> dict` — GET with auth headers
- `async post(path, data=None) -> dict` — POST with auth headers
- Error handling: connection errors return `{"error": str(e), "status": 0}`, HTTP errors return `{"error": ..., "status": code}`
- Uses per-request `aiohttp.ClientSession` (same pattern as inference.py)

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub connector — core HTTP client with auth"
```

---

### Task 3.4: Connector — hub endpoints

**Files:**
- Modify: `archie_engine/hub/connector.py` — add endpoint methods
- Modify: `archie_engine/tests/test_connector.py` — add endpoint tests

- [ ] **Step 1: Write tests for hub endpoints**

```python
@pytest.mark.asyncio
async def test_register_node(connector):
    mock_resp = _mock_response(200, {"node_id": "abc-123", "status": "registered"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.register_node(
            hostname="my-machine", gpu_model="RTX 3070", ram_gb=32
        )
    assert result.get("node_id") == "abc-123"


@pytest.mark.asyncio
async def test_health_check(connector):
    mock_resp = _mock_response(200, {"status": "ok", "version": "5.32.0"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.health_check()
    assert result.get("status") == "ok"


@pytest.mark.asyncio
async def test_search_knowledge(connector):
    mock_resp = _mock_response(200, {"results": [{"content": "test"}]})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.search_knowledge("auth middleware")
    assert len(result.get("results", [])) > 0


@pytest.mark.asyncio
async def test_dispatch(connector):
    mock_resp = _mock_response(200, {"response": "Here's the fix", "agent_used": "ARCHIE"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.dispatch(
            prompt="fix the bug", model="qwen2.5:7b", agent_target="ARCHIE"
        )
    assert "response" in result


@pytest.mark.asyncio
async def test_list_agents(connector):
    mock_resp = _mock_response(200, {"agents": [{"name": "ARCHIE"}]})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.list_agents()
    assert len(result.get("agents", [])) > 0


@pytest.mark.asyncio
async def test_get_skills(connector):
    mock_resp = _mock_response(200, {"skills": [{"name": "commit"}]})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get_skills()
    assert len(result.get("skills", [])) > 0
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement endpoint methods**

Add to `HubConnector`:
- `async register_node(hostname, gpu_model=None, ram_gb=None) -> dict` — POST `/api/starbase/nodes/register`
- `async health_check() -> dict` — GET `/api/archie/health`
- `async search_knowledge(query, types=None, limit=10) -> dict` — POST `/api/archie/search`
- `async dispatch(prompt, model=None, agent_target=None, user_context=None) -> dict` — POST `/api/archie/chat` (or the Bridge dispatch endpoint)
- `async list_agents() -> dict` — GET `/api/starbase/agents`
- `async get_skills() -> dict` — GET `/api/starbase/skills`
- `async get_model_state() -> dict` — GET `/api/starbase/models`
- `async send_heartbeat(node_id, metrics) -> dict` — POST `/api/starbase/nodes/heartbeat`

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub connector endpoints — register, dispatch, KB search, agents"
```

---

### Task 3.5: Heartbeat

**Files:**
- Create: `archie_engine/hub/heartbeat.py`
- Create: `archie_engine/tests/test_heartbeat.py`

- [ ] **Step 1: Write tests**

```python
import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock, MagicMock
from archie_engine.hub.heartbeat import Heartbeat
from archie_engine.hub import HubStatus


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    conn.register_node = AsyncMock(return_value={"node_id": "test-node"})
    conn.send_heartbeat = AsyncMock(return_value={"status": "ok"})
    conn.health_check = AsyncMock(return_value={"status": "ok"})
    return conn


@pytest_asyncio.fixture
async def heartbeat(mock_connector):
    hb = Heartbeat(connector=mock_connector, interval=1)
    yield hb
    await hb.stop()


@pytest.mark.asyncio
async def test_start_registers_node(heartbeat, mock_connector):
    await heartbeat.start()
    mock_connector.register_node.assert_called_once()
    assert heartbeat.status == HubStatus.CONNECTED


@pytest.mark.asyncio
async def test_stop(heartbeat):
    await heartbeat.start()
    await heartbeat.stop()
    assert not heartbeat.is_running


@pytest.mark.asyncio
async def test_heartbeat_sends_periodically(heartbeat, mock_connector):
    await heartbeat.start()
    await asyncio.sleep(2.5)  # Should fire at least twice with interval=1
    assert mock_connector.send_heartbeat.call_count >= 2


@pytest.mark.asyncio
async def test_connection_failure_sets_offline(heartbeat, mock_connector):
    mock_connector.register_node = AsyncMock(side_effect=Exception("refused"))
    await heartbeat.start()
    assert heartbeat.status == HubStatus.OFFLINE


@pytest.mark.asyncio
async def test_auth_failure_sets_auth_failed(heartbeat, mock_connector):
    mock_connector.register_node = AsyncMock(return_value={"error": "unauthorized", "status": 401})
    await heartbeat.start()
    assert heartbeat.status == HubStatus.AUTH_FAILED
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement heartbeat.py**

Build `Heartbeat` with:
- `__init__(self, connector, interval=30)` — stores connector and interval
- `async start()` — register node, start background task
- `async stop()` — cancel background task
- `status: HubStatus` — current connection status
- `is_running: bool` — task is active
- `node_id: str | None` — assigned after registration
- Background task: loop that calls `connector.send_heartbeat()` every interval seconds
- On heartbeat failure: set status to OFFLINE, attempt reconnect on next tick
- On auth failure (401): set status to AUTH_FAILED, stop heartbeating

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub heartbeat — registration, keepalive, offline detection"
```

---

### Task 3.6: Sync — skills

**Files:**
- Create: `archie_engine/hub/sync.py`
- Create: `archie_engine/tests/test_sync.py`

- [ ] **Step 1: Write tests**

```python
import pytest
import pytest_asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
from archie_engine.hub.sync import HubSync


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    conn.get_skills = AsyncMock(return_value={
        "skills": [
            {"name": "commit", "content": "# Commit skill\nCreate commits.", "version": "1.0"},
            {"name": "review", "content": "# Review skill\nReview PRs.", "version": "1.0"},
        ]
    })
    conn.get_model_state = AsyncMock(return_value={
        "models": [{"name": "qwen2.5:7b", "loaded": True}]
    })
    conn.list_agents = AsyncMock(return_value={
        "agents": [{"name": "ARCHIE", "station": "COMMAND", "shift_state": "active"}]
    })
    return conn


@pytest.fixture
def sync(mock_connector, tmp_path):
    return HubSync(connector=mock_connector, cache_dir=tmp_path / "cache")


@pytest.mark.asyncio
async def test_sync_skills_downloads(sync, tmp_path):
    await sync.sync_skills()
    skills_dir = tmp_path / "cache" / "skills"
    assert skills_dir.exists()
    assert (skills_dir / "commit.md").exists()
    assert (skills_dir / "review.md").exists()


@pytest.mark.asyncio
async def test_sync_skills_content(sync, tmp_path):
    await sync.sync_skills()
    content = (tmp_path / "cache" / "skills" / "commit.md").read_text()
    assert "Commit skill" in content


@pytest.mark.asyncio
async def test_get_cached_skills(sync):
    await sync.sync_skills()
    skills = sync.get_cached_skills()
    assert len(skills) == 2
    assert any(s["name"] == "commit" for s in skills)


@pytest.mark.asyncio
async def test_sync_agents(sync):
    await sync.sync_agents()
    agents = sync.get_cached_agents()
    assert len(agents) == 1
    assert agents[0]["name"] == "ARCHIE"


@pytest.mark.asyncio
async def test_sync_models(sync):
    await sync.sync_models()
    models = sync.get_cached_models()
    assert len(models) == 1


@pytest.mark.asyncio
async def test_sync_all(sync):
    await sync.sync_all()
    assert len(sync.get_cached_skills()) == 2
    assert len(sync.get_cached_agents()) == 1
    assert len(sync.get_cached_models()) == 1
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement sync.py**

Build `HubSync` with:
- `__init__(self, connector, cache_dir: Path)`
- `async sync_skills()` — fetch from hub, write to `cache_dir/skills/` as .md files
- `async sync_agents()` — fetch agent list, cache in memory + `cache_dir/agents.json`
- `async sync_models()` — fetch model state, cache in memory + `cache_dir/models.json`
- `async sync_all()` — run all three
- `get_cached_skills() -> list[dict]` — read from cache dir
- `get_cached_agents() -> list[dict]` — read from memory/file cache
- `get_cached_models() -> list[dict]` — read from memory/file cache

Cache dir created automatically. Skills cached as individual .md files. Agents and models cached as JSON files.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub sync — skill download, agent/model cache"
```

---

### Task 3.7: Sync — models and agent assignment

**Files:**
- Modify: `archie_engine/hub/sync.py` — add model warm-up coordination
- Modify: `archie_engine/tests/test_sync.py` — add model/agent tests

- [ ] **Step 1: Write additional tests**

```python
@pytest.mark.asyncio
async def test_get_best_agent_for_task(sync):
    await sync.sync_agents()
    agent = sync.get_best_agent(intent_type="code_task")
    assert agent is not None  # Should find ARCHIE or similar


@pytest.mark.asyncio
async def test_get_loaded_models(sync):
    await sync.sync_models()
    loaded = sync.get_loaded_models()
    assert any(m["name"] == "qwen2.5:7b" for m in loaded)


@pytest.mark.asyncio
async def test_offline_returns_cached(sync, tmp_path):
    """After sync, cached data survives connector failure."""
    await sync.sync_all()
    # Simulate offline
    sync.connector.get_skills = AsyncMock(side_effect=Exception("offline"))
    # Cached data still available
    assert len(sync.get_cached_skills()) == 2
    assert len(sync.get_cached_agents()) == 1
```

- [ ] **Step 2: Run — verify fail (new methods don't exist)**

- [ ] **Step 3: Add methods to sync.py**

Add:
- `get_best_agent(intent_type) -> dict | None` — simple mapping from intent type to best available agent based on cached roster
- `get_loaded_models() -> list[dict]` — filter cached models where loaded=True

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub sync — agent assignment and model state coordination"
```

---

### Task 3.8: Engine integration and E2E

**Files:**
- Modify: `archie_engine/engine.py` — wire hub connector
- Create: `archie_engine/tests/test_hub_integration.py`

- [ ] **Step 1: Write integration tests**

```python
import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from unittest.mock import AsyncMock, patch, MagicMock
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig
from archie_engine.hub import HubStatus


@pytest_asyncio.fixture
async def engine_with_hub(tmp_path):
    config = EngineConfig(
        data_dir=tmp_path,
        ws_port=0,
        hub_url="http://fake-hub:3000",
        hub_api_key="test-key",
    )
    eng = Engine(config)
    # Mock the hub connector to avoid real HTTP
    eng.hub_connector.get = AsyncMock(return_value={"status": "ok"})
    eng.hub_connector.post = AsyncMock(return_value={"status": "ok"})
    await eng.start()
    yield eng
    await eng.stop()


@pytest_asyncio.fixture
async def engine_no_hub(tmp_path):
    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config)
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_engine_without_hub_works(engine_no_hub):
    """Engine works in Community mode without hub."""
    assert engine_no_hub.is_running
    assert engine_no_hub.hub_status == HubStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_engine_with_hub_configured(engine_with_hub):
    """Engine initializes hub connector when configured."""
    assert engine_with_hub.is_running
    assert engine_with_hub.hub_connector is not None


@pytest.mark.asyncio
async def test_hub_status_via_websocket(engine_no_hub):
    uri = f"ws://{engine_no_hub.config.ws_host}:{engine_no_hub.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "hub_status"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response.get("hub_status") == "disconnected"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Wire hub into Engine**

Update `archie_engine/engine.py`:
- Import hub modules
- In `__init__`: create `HubAuth`, `HubConnector`, `HubSync` if hub is configured
- Add `hub_status` property
- Add `hub_status` message type handler in `handle_message`
- In router: if hub connected, use hub dispatch for code_task/knowledge_query (prefer hub over local)
- Graceful degradation: if hub unavailable, fall back to local inference

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run FULL suite**

```bash
cd /mnt/archie_brain && python -m pytest archie_engine/tests/ -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): hub integration — graceful degradation, hub_status endpoint

Completes Plan 3 — Hub Connectivity. Components:
- Auth module (API key storage, Bearer token)
- REST connector (8 hub endpoints)
- Heartbeat (registration, keepalive, offline detection)
- Sync (skills download, agent/model cache)
- Engine integration with graceful degradation

Community mode works without hub. Node mode unlocks orchestration."
```

---

## Post-Plan Checklist

After all 8 tasks complete:

```bash
python -m pytest archie_engine/tests/ -v
git push
mcp log_decision: "Hub Connectivity complete — engine connects to ARCHIE platform"
mcp update_project_understanding: project 185 to 60%
```

## What's Next

- **Plan 4 (Skill System):** Slash commands, skill loader, custom skills
- **Plan 5 (Claude Collaboration):** MCP server/client, context bridge
- **Plan 6 (Go TUI):** Bubble Tea interface connecting to engine WebSocket
