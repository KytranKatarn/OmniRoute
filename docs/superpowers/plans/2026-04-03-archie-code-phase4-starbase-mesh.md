# Phase 4: Starbase Node Registration & Inbound Work — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register the ARCHIE Code engine as a Starbase fleet node so it appears in the node list, sends real heartbeats, and accepts inbound work dispatched from the hub.

**Architecture:** The engine registers with Starbase via `/api/nodes/register` (returns a one-time `api_key` + `node_id`). It stores the node credentials locally and sends heartbeats with real system metrics using the `X-Node-API-Key` header. A lightweight aiohttp HTTP server accepts inbound work dispatched from the hub, processes it through the engine's existing router, and returns results.

**Tech Stack:** Python 3.12, aiohttp, asyncio, psutil (new dep for system metrics)

**Repo:** `/mnt/archie_brain/archie-code/`
**Venv:** `source .venv/bin/activate`
**Tests:** `python -m pytest archie_engine/tests/ -v`
**Engine:** `OLLAMA_HOST=http://192.168.1.200:11434 python -m archie_engine`

---

## File Structure

**Create:**
| File | Responsibility |
|------|---------------|
| `archie_engine/hub/system_info.py` | Gather CPU, RAM, GPU, OS info for registration + heartbeat |
| `archie_engine/hub/inbound.py` | HTTP server accepting dispatched work from hub |
| `archie_engine/tests/test_system_info.py` | Tests for system info gathering |
| `archie_engine/tests/test_inbound.py` | Tests for inbound HTTP server |

**Modify:**
| File | Changes |
|------|---------|
| `archie_engine/hub/auth.py` | Add `store_node_key()` / `load_node_key()` for node API key (separate from hub Bearer key) |
| `archie_engine/hub/connector.py` | Fix `register_node()` params (send `node_name`), add `get_node_headers()` for `X-Node-API-Key` |
| `archie_engine/hub/heartbeat.py` | Real system metrics, use `X-Node-API-Key` auth, persist node_id, reconnect logic |
| `archie_engine/engine.py` | Wire inbound server start/stop, add `handle_inbound_job()` |
| `archie_engine/config.py` | Add `inbound_port` config (default 9091) |

---

### Task 1: System Info Gathering

**Files:**
- Create: `archie_engine/hub/system_info.py`
- Create: `archie_engine/tests/test_system_info.py`

- [ ] **Step 1: Write the failing test**

```python
# archie_engine/tests/test_system_info.py
"""Tests for system info gathering."""

import pytest
from archie_engine.hub.system_info import get_system_info


def test_system_info_returns_required_fields():
    info = get_system_info()
    assert "hostname" in info
    assert "cpu_cores" in info
    assert "ram_gb" in info
    assert "os_info" in info
    assert isinstance(info["cpu_cores"], int)
    assert info["cpu_cores"] > 0
    assert isinstance(info["ram_gb"], (int, float))
    assert info["ram_gb"] > 0


def test_system_info_hostname_is_string():
    info = get_system_info()
    assert isinstance(info["hostname"], str)
    assert len(info["hostname"]) > 0


def test_system_info_gpu_field_present():
    """GPU fields should always be present (None if no GPU detected)."""
    info = get_system_info()
    assert "gpu_model" in info
    assert "gpu_vram_gb" in info


def test_get_heartbeat_metrics_returns_usage():
    from archie_engine.hub.system_info import get_heartbeat_metrics
    metrics = get_heartbeat_metrics()
    assert "cpu_usage" in metrics
    assert "memory_usage" in metrics
    assert isinstance(metrics["cpu_usage"], (int, float))
    assert isinstance(metrics["memory_usage"], (int, float))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_system_info.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'archie_engine.hub.system_info'`

- [ ] **Step 3: Install psutil dependency**

Run: `cd /mnt/archie_brain/archie-code && source .venv/bin/activate && pip install psutil`

Also add to `pyproject.toml` dependencies if it exists, or `requirements.txt`.

- [ ] **Step 4: Write the implementation**

```python
# archie_engine/hub/system_info.py
"""System info gathering for node registration and heartbeat metrics."""

import os
import platform
import logging

import psutil

logger = logging.getLogger(__name__)


def get_system_info() -> dict:
    """Gather static system info for node registration.

    Returns dict with: hostname, cpu_cores, cpu_model, ram_gb, os_info,
    gpu_model (str|None), gpu_vram_gb (float|None).
    """
    info = {
        "hostname": platform.node(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "cpu_model": _get_cpu_model(),
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "os_info": f"{platform.system()} {platform.release()}",
        "gpu_model": None,
        "gpu_vram_gb": None,
    }

    gpu = _detect_gpu()
    if gpu:
        info["gpu_model"] = gpu["model"]
        info["gpu_vram_gb"] = gpu["vram_gb"]

    return info


def get_heartbeat_metrics() -> dict:
    """Gather dynamic system metrics for heartbeat updates.

    Returns dict with: cpu_usage, memory_usage, gpu_usage (float|None),
    current_load (int — number of active processes as a proxy).
    """
    return {
        "cpu_usage": psutil.cpu_percent(interval=0.1),
        "memory_usage": psutil.virtual_memory().percent,
        "gpu_usage": None,  # Would need nvidia-smi or pynvml
        "current_load": len([p for p in psutil.process_iter(["name"]) if "archie" in (p.info["name"] or "").lower()]),
    }


def _get_cpu_model() -> str:
    """Get CPU model string."""
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":")[1].strip()
        elif platform.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception as e:
        logger.debug("Could not detect CPU model: %s", e)
    return platform.processor() or "Unknown"


def _detect_gpu() -> dict | None:
    """Detect GPU model and VRAM. Returns None if no GPU found."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                return {
                    "model": parts[0].strip(),
                    "vram_gb": round(float(parts[1].strip()) / 1024, 1),
                }
    except (FileNotFoundError, Exception) as e:
        logger.debug("GPU detection skipped: %s", e)
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_system_info.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/hub/system_info.py archie_engine/tests/test_system_info.py
git commit -m "feat(hub): add system info gathering for node registration + heartbeat"
```

---

### Task 2: Node API Key Auth

**Files:**
- Modify: `archie_engine/hub/auth.py`
- Modify: `archie_engine/tests/test_auth.py`

**Context:** The Starbase heartbeat endpoint checks `X-Node-API-Key` header (not `Authorization: Bearer`). The registration endpoint returns a one-time `api_key` that must be stored separately from the hub API key. The hub API key (Bearer) is for platform API calls; the node API key is for heartbeat auth.

- [ ] **Step 1: Write the failing test**

```python
# Add to archie_engine/tests/test_auth.py

def test_store_and_load_node_key(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_key("test-node-api-key-123")
    assert auth.load_node_key() == "test-node-api-key-123"


def test_get_node_headers(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_key("node-key-abc")
    headers = auth.get_node_headers()
    assert headers["X-Node-API-Key"] == "node-key-abc"
    assert headers["Content-Type"] == "application/json"


def test_get_node_headers_no_key(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    headers = auth.get_node_headers()
    assert "X-Node-API-Key" not in headers


def test_store_node_id(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_id("node_abc123")
    assert auth.load_node_id() == "node_abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_auth.py::test_store_and_load_node_key -v`
Expected: FAIL with `AttributeError: 'HubAuth' object has no attribute 'store_node_key'`

- [ ] **Step 3: Implement node key methods in auth.py**

Add these methods to the `HubAuth` class in `archie_engine/hub/auth.py`:

```python
    @property
    def _node_key_file(self) -> Path:
        """Node API key file — stored alongside hub key."""
        return self.key_file.parent / ".node_key"

    @property
    def _node_id_file(self) -> Path:
        """Node ID file — persists across restarts."""
        return self.key_file.parent / ".node_id"

    def store_node_key(self, key: str) -> None:
        """Store node API key (returned by Starbase on registration)."""
        self._node_key_file.parent.mkdir(parents=True, exist_ok=True)
        self._node_key_file.write_text(key)
        try:
            os.chmod(self._node_key_file, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def load_node_key(self) -> str | None:
        """Load stored node API key."""
        if not self._node_key_file.exists():
            return None
        return self._node_key_file.read_text().strip()

    def store_node_id(self, node_id: str) -> None:
        """Store node ID (returned by Starbase on registration)."""
        self._node_id_file.parent.mkdir(parents=True, exist_ok=True)
        self._node_id_file.write_text(node_id)

    def load_node_id(self) -> str | None:
        """Load stored node ID."""
        if not self._node_id_file.exists():
            return None
        return self._node_id_file.read_text().strip()

    def get_node_headers(self) -> dict:
        """Get auth headers for node heartbeat (X-Node-API-Key)."""
        headers = {"Content-Type": "application/json"}
        key = self.load_node_key()
        if key:
            headers["X-Node-API-Key"] = key
        return headers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_auth.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/hub/auth.py archie_engine/tests/test_auth.py
git commit -m "feat(hub): add node API key + node ID storage for Starbase auth"
```

---

### Task 3: Fix Registration + Connector

**Files:**
- Modify: `archie_engine/hub/connector.py`
- Modify: `archie_engine/tests/test_connector.py`

**Context:** The Starbase `/api/nodes/register` endpoint requires `node_name` (the current connector sends `hostname` but not `node_name`). It returns `{"success": true, "node": {"node_id": "..."}, "api_key": "..."}`. The connector needs a separate method for heartbeat that uses `X-Node-API-Key` header instead of Bearer.

- [ ] **Step 1: Write the failing test**

```python
# Add to archie_engine/tests/test_connector.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.auth import HubAuth


@pytest.fixture
def mock_auth(tmp_path):
    return HubAuth(key_file=tmp_path / ".hub_key")


@pytest.fixture
def connector(mock_auth):
    return HubConnector(hub_url="http://192.168.1.200:3000", auth=mock_auth)


@pytest.mark.asyncio
async def test_register_node_sends_node_name(connector):
    """register_node must send node_name (required by Starbase)."""
    with patch.object(connector, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {"success": True, "node": {"node_id": "node_abc"}, "api_key": "key123"}
        result = await connector.register_node(
            node_name="archie-code-test",
            hostname="192.168.1.50",
            cpu_cores=8,
            ram_gb=32,
        )
        call_data = mock_post.call_args[1]["data"]
        assert call_data["node_name"] == "archie-code-test"
        assert "hostname" in call_data


@pytest.mark.asyncio
async def test_send_heartbeat_uses_node_headers(connector):
    """Heartbeat must use X-Node-API-Key, not Bearer."""
    connector.auth.store_node_key("test-node-key")
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"success": True})
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        await connector.send_heartbeat(node_id="node_abc", metrics={"cpu_usage": 50})

        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["headers"]["X-Node-API-Key"] == "test-node-key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_connector.py::test_register_node_sends_node_name -v`
Expected: FAIL (current `register_node` doesn't accept `node_name`)

- [ ] **Step 3: Update connector.py**

Replace the `register_node()` and `send_heartbeat()` methods in `archie_engine/hub/connector.py`:

```python
    async def register_node(self, node_name: str, hostname: str | None = None,
                            gpu_model: str | None = None, gpu_vram_gb: float | None = None,
                            ram_gb: float | None = None, cpu_cores: int | None = None,
                            cpu_model: str | None = None, os_info: str | None = None,
                            engine_version: str = "0.1.0", inbound_port: int | None = None) -> dict:
        """Register this engine as a node on the hub.

        Sends to /api/nodes/register (unauthenticated).
        Returns dict with node_id and api_key on success.
        """
        import platform as _platform
        data = {
            "node_name": node_name,
            "hostname": hostname or _platform.node(),
            "gpu_model": gpu_model,
            "gpu_vram_gb": gpu_vram_gb,
            "ram_gb": ram_gb,
            "cpu_cores": cpu_cores,
            "cpu_model": cpu_model,
            "os_info": os_info,
            "client_version": engine_version,
            "description": f"ARCHIE Code engine v{engine_version}",
            "node_type": "starship",
        }
        if inbound_port:
            data["port"] = inbound_port
        # Registration is unauthenticated — use plain POST
        url = f"{self.hub_url}/tools/starbase/api/nodes/register"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, json=data, headers={"Content-Type": "application/json"}) as resp:
                    result = await resp.json()
                    if resp.status >= 400:
                        return {"error": result.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    # Store node credentials if registration succeeded
                    if result.get("success"):
                        node_id = result.get("node", {}).get("node_id")
                        api_key = result.get("api_key")
                        if node_id:
                            self.auth.store_node_id(node_id)
                        if api_key:
                            self.auth.store_node_key(api_key)
                    return result
        except Exception as e:
            logger.warning("Node registration failed: %s", e)
            return {"error": str(e), "status": 0}

    async def send_heartbeat(self, node_id: str, metrics: dict | None = None) -> dict:
        """Send heartbeat to keep node registration alive.

        Uses X-Node-API-Key header (not Bearer token).
        """
        url = f"{self.hub_url}/tools/starbase/api/nodes/{node_id}/heartbeat"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    url,
                    json=metrics or {},
                    headers=self.auth.get_node_headers(),
                ) as resp:
                    result = await resp.json()
                    if resp.status >= 400:
                        return {"error": result.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    return result
        except Exception as e:
            logger.warning("Heartbeat failed: %s", e)
            return {"error": str(e), "status": 0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_connector.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v --timeout=30`
Expected: All existing tests pass (the pre-existing `test_unknown_slash_falls_through` timeout is known — ignore)

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/hub/connector.py archie_engine/tests/test_connector.py
git commit -m "fix(hub): registration sends node_name, heartbeat uses X-Node-API-Key"
```

---

### Task 4: Enhanced Heartbeat with Real Metrics

**Files:**
- Modify: `archie_engine/hub/heartbeat.py`
- Modify: `archie_engine/tests/test_heartbeat.py`

**Context:** The heartbeat currently sends `{"status": "active"}` as metrics. The Starbase heartbeat endpoint accepts: `cpu_usage`, `memory_usage`, `gpu_usage`, `current_load`, `client_version`, `cpu_cores`, `ram_gb`, `gpu_model`, `gpu_vram_gb`, `ollama_online`. The heartbeat should also persist `node_id` across restarts and auto-reconnect.

- [ ] **Step 1: Write the failing test**

```python
# Add to archie_engine/tests/test_heartbeat.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from archie_engine.hub.heartbeat import Heartbeat
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.auth import HubAuth
from archie_engine.hub import HubStatus


@pytest.fixture
def mock_auth(tmp_path):
    return HubAuth(key_file=tmp_path / ".hub_key")


@pytest.fixture
def mock_connector(mock_auth):
    c = HubConnector(hub_url="http://192.168.1.200:3000", auth=mock_auth)
    return c


@pytest.mark.asyncio
async def test_register_sends_system_info(mock_connector):
    """Registration should send real system info, not just hostname."""
    hb = Heartbeat(connector=mock_connector)
    mock_connector.register_node = AsyncMock(return_value={
        "success": True, "node": {"node_id": "node_abc"}, "api_key": "key123"
    })
    await hb._register()
    call_kwargs = mock_connector.register_node.call_args[1]
    assert "node_name" in call_kwargs
    assert "cpu_cores" in call_kwargs
    assert "ram_gb" in call_kwargs


@pytest.mark.asyncio
async def test_heartbeat_sends_real_metrics(mock_connector):
    """Heartbeat loop should send CPU/memory metrics, not just status."""
    hb = Heartbeat(connector=mock_connector)
    hb.node_id = "node_abc"
    hb.status = HubStatus.CONNECTED
    mock_connector.send_heartbeat = AsyncMock(return_value={"success": True})
    await hb._send_one_heartbeat()
    call_kwargs = mock_connector.send_heartbeat.call_args[1]
    metrics = call_kwargs["metrics"]
    assert "cpu_usage" in metrics
    assert "memory_usage" in metrics
    assert "client_version" in metrics


@pytest.mark.asyncio
async def test_persisted_node_id_reused(mock_connector, tmp_path):
    """If node_id is persisted from a previous session, reuse it."""
    mock_connector.auth.store_node_id("node_persisted_123")
    mock_connector.auth.store_node_key("key_persisted_456")
    hb = Heartbeat(connector=mock_connector)
    # With persisted credentials, registration should send heartbeat first
    mock_connector.send_heartbeat = AsyncMock(return_value={"success": True})
    await hb._register()
    assert hb.node_id == "node_persisted_123"
    assert hb.status == HubStatus.CONNECTED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_heartbeat.py::test_register_sends_system_info -v`
Expected: FAIL

- [ ] **Step 3: Rewrite heartbeat.py**

Replace the entire content of `archie_engine/hub/heartbeat.py`:

```python
"""Hub heartbeat — registration and keepalive with ARCHIE platform."""

import asyncio
import logging
from archie_engine.hub import HubStatus
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.system_info import get_system_info, get_heartbeat_metrics

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"


class Heartbeat:
    def __init__(self, connector: HubConnector, interval: int = 30):
        self.connector = connector
        self.interval = interval
        self.status = HubStatus.DISCONNECTED
        self.node_id: str | None = None
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Register with hub (or reconnect) and start heartbeat loop."""
        await self._register()
        if self.status == HubStatus.CONNECTED:
            self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop heartbeat loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _register(self) -> None:
        """Register this node with the hub, or reconnect using persisted credentials."""
        # Check for persisted credentials from a previous session
        persisted_id = self.connector.auth.load_node_id()
        persisted_key = self.connector.auth.load_node_key()

        if persisted_id and persisted_key:
            # Try reconnecting with existing credentials
            self.node_id = persisted_id
            self.status = HubStatus.CONNECTING
            result = await self.connector.send_heartbeat(
                node_id=persisted_id, metrics=self._build_metrics(),
            )
            if "error" not in result:
                self.status = HubStatus.CONNECTED
                logger.info("Reconnected to hub as node %s", persisted_id)
                return
            elif result.get("status") == 401:
                logger.warning("Persisted credentials rejected — re-registering")
            else:
                logger.warning("Reconnect heartbeat failed: %s — re-registering", result.get("error"))

        # Fresh registration
        self.status = HubStatus.CONNECTING
        sys_info = get_system_info()
        try:
            result = await self.connector.register_node(
                node_name=f"archie-code-{sys_info['hostname']}",
                hostname=sys_info["hostname"],
                cpu_cores=sys_info["cpu_cores"],
                cpu_model=sys_info.get("cpu_model"),
                ram_gb=sys_info["ram_gb"],
                gpu_model=sys_info.get("gpu_model"),
                gpu_vram_gb=sys_info.get("gpu_vram_gb"),
                os_info=sys_info.get("os_info"),
                engine_version=ENGINE_VERSION,
            )
            if "error" in result:
                if result.get("status") == 401:
                    self.status = HubStatus.AUTH_FAILED
                    logger.error("Hub registration auth failed")
                else:
                    self.status = HubStatus.OFFLINE
                    logger.warning("Hub registration failed: %s", result["error"])
                return

            self.node_id = result.get("node", {}).get("node_id")
            if not self.node_id:
                self.node_id = self.connector.auth.load_node_id()
            self.status = HubStatus.CONNECTED
            logger.info("Registered with hub as node %s", self.node_id)
        except Exception as e:
            self.status = HubStatus.OFFLINE
            logger.warning("Hub registration error: %s", e)

    async def _heartbeat_loop(self) -> None:
        """Background loop sending heartbeats."""
        while True:
            await asyncio.sleep(self.interval)
            await self._send_one_heartbeat()

    async def _send_one_heartbeat(self) -> None:
        """Send a single heartbeat with real system metrics."""
        try:
            result = await self.connector.send_heartbeat(
                node_id=self.node_id or "unknown",
                metrics=self._build_metrics(),
            )
            if "error" in result:
                if result.get("status") == 401:
                    self.status = HubStatus.AUTH_FAILED
                    logger.error("Heartbeat auth failed — stopping")
                    return
                self.status = HubStatus.OFFLINE
                logger.warning("Heartbeat failed: %s", result["error"])
            else:
                if self.status == HubStatus.OFFLINE:
                    logger.info("Hub connection restored")
                self.status = HubStatus.CONNECTED
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.status = HubStatus.OFFLINE
            logger.warning("Heartbeat error: %s", e)

    def _build_metrics(self) -> dict:
        """Build heartbeat metrics payload."""
        metrics = get_heartbeat_metrics()
        metrics["client_version"] = ENGINE_VERSION
        metrics["ollama_online"] = True  # Engine always has Ollama available
        return metrics
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_heartbeat.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v --timeout=30`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/hub/heartbeat.py archie_engine/tests/test_heartbeat.py
git commit -m "feat(hub): heartbeat sends real system metrics, reconnects with persisted credentials"
```

---

### Task 5: Inbound HTTP Server

**Files:**
- Create: `archie_engine/hub/inbound.py`
- Create: `archie_engine/tests/test_inbound.py`
- Modify: `archie_engine/config.py`

**Context:** The hub dispatches work to nodes. The engine needs an HTTP server that accepts POST requests with tasks, processes them through the existing router, and returns results. This runs alongside the WebSocket server on a separate port (default 9091). The hub identifies the engine's inbound port from the registration data.

- [ ] **Step 1: Add inbound_port to config**

Add to `archie_engine/config.py` EngineConfig dataclass:

```python
    # Inbound (hub dispatches work here)
    inbound_host: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_INBOUND_HOST", "0.0.0.0"
    ))
    inbound_port: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_INBOUND_PORT", "9091"
    )))
```

- [ ] **Step 2: Write the failing test**

```python
# archie_engine/tests/test_inbound.py
"""Tests for inbound HTTP server that accepts hub-dispatched work."""

import pytest
import json
from unittest.mock import AsyncMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop, TestClient, TestServer
from archie_engine.hub.inbound import InboundServer


@pytest.fixture
def mock_job_handler():
    """Mock handler that simulates engine processing a job."""
    handler = AsyncMock()
    handler.return_value = {
        "success": True,
        "response": "Task completed successfully",
        "agent": "ARCHIE",
    }
    return handler


@pytest.fixture
async def inbound_client(mock_job_handler):
    """Create test client for the inbound server."""
    server = InboundServer(host="127.0.0.1", port=0, node_api_key="test-key-123")
    server.set_job_handler(mock_job_handler)
    app = server._build_app()
    async with TestClient(TestServer(app)) as client:
        yield client, mock_job_handler


@pytest.mark.asyncio
async def test_dispatch_job_success(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={
        "task": "Review this code for security issues",
        "context": {"files": ["main.py"]},
    }, headers={"X-Node-API-Key": "test-key-123"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "response" in data
    handler.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_rejects_bad_auth(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={
        "task": "Do something",
    }, headers={"X-Node-API-Key": "wrong-key"})
    assert resp.status == 401
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_rejects_no_auth(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={"task": "Do something"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_dispatch_rejects_empty_task(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={
        "task": "",
    }, headers={"X-Node-API-Key": "test-key-123"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_health_endpoint(inbound_client):
    client, _ = inbound_client
    resp = await client.get("/api/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert "engine_version" in data
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_inbound.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement the inbound server**

```python
# archie_engine/hub/inbound.py
"""Inbound HTTP server — accepts work dispatched from ARCHIE hub."""

import logging
from typing import Callable, Awaitable
from aiohttp import web

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"


class InboundServer:
    """HTTP server that accepts dispatched work from the hub.

    The hub sends POST /api/dispatch with a task payload.
    Auth is via X-Node-API-Key header (same key returned at registration).
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9091,
                 node_api_key: str | None = None):
        self.host = host
        self.port = port
        self.node_api_key = node_api_key
        self._handler: Callable[[dict], Awaitable[dict]] | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def is_running(self) -> bool:
        return self._site is not None

    def set_job_handler(self, handler: Callable[[dict], Awaitable[dict]]) -> None:
        """Set the callback for processing inbound jobs."""
        self._handler = handler

    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/dispatch", self._handle_dispatch)
        app.router.add_get("/api/health", self._handle_health)
        return app

    async def start(self) -> None:
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("Inbound server listening on http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    def _verify_auth(self, request: web.Request) -> bool:
        """Verify X-Node-API-Key header matches our stored key."""
        if not self.node_api_key:
            return False
        incoming = request.headers.get("X-Node-API-Key", "")
        return incoming == self.node_api_key

    async def _handle_dispatch(self, request: web.Request) -> web.Response:
        """Handle POST /api/dispatch — process a hub-dispatched job."""
        if not self._verify_auth(request):
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON"}, status=400
            )

        task = data.get("task", "").strip()
        if not task:
            return web.json_response(
                {"success": False, "error": "task is required"}, status=400
            )

        if not self._handler:
            return web.json_response(
                {"success": False, "error": "No job handler configured"}, status=503
            )

        try:
            result = await self._handler({
                "task": task,
                "context": data.get("context", {}),
                "source": "hub_dispatch",
                "agent_target": data.get("agent_target"),
                "priority": data.get("priority", 5),
            })
            return web.json_response(result)
        except Exception as e:
            logger.error("Inbound job failed: %s", e)
            return web.json_response(
                {"success": False, "error": str(e)}, status=500
            )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /api/health — basic health check."""
        return web.json_response({
            "status": "ok",
            "engine_version": ENGINE_VERSION,
            "accepting_work": self._handler is not None,
        })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_inbound.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/hub/inbound.py archie_engine/tests/test_inbound.py archie_engine/config.py
git commit -m "feat(hub): inbound HTTP server accepts dispatched work from hub"
```

---

### Task 6: Engine Wiring — Inbound Server + Job Handler

**Files:**
- Modify: `archie_engine/engine.py`
- Modify: `archie_engine/tests/test_engine.py`

**Context:** Wire the inbound server into the engine lifecycle: start it alongside the WebSocket server, stop it on shutdown, and route inbound jobs through the engine's existing router. Also pass the inbound port to registration so the hub knows where to dispatch.

- [ ] **Step 1: Write the failing test**

```python
# Add to archie_engine/tests/test_engine.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig


@pytest.mark.asyncio
async def test_handle_inbound_job_processes_task(tmp_path):
    """Engine should process inbound hub-dispatched jobs."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)

    # Mock the router
    engine.router.route = AsyncMock(return_value={
        "response": "Code looks clean, no issues found.",
        "success": True,
    })

    result = await engine.handle_inbound_job({
        "task": "Review main.py for security issues",
        "context": {"files": ["main.py"]},
        "source": "hub_dispatch",
    })

    assert result["success"] is True
    assert "response" in result


@pytest.mark.asyncio
async def test_handle_inbound_job_returns_error_on_failure(tmp_path):
    """Engine should return error dict if router raises."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)

    engine.router.route = AsyncMock(side_effect=Exception("Model unavailable"))

    result = await engine.handle_inbound_job({
        "task": "Do something",
        "context": {},
        "source": "hub_dispatch",
    })

    assert result["success"] is False
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_engine.py::test_handle_inbound_job_processes_task -v`
Expected: FAIL with `AttributeError: 'Engine' object has no attribute 'handle_inbound_job'`

- [ ] **Step 3: Add inbound server wiring and job handler to engine.py**

Add import at top of `engine.py`:

```python
from archie_engine.hub.inbound import InboundServer
```

Add to `__init__` after the hub_sync setup (around line 88):

```python
        # Inbound server (hub dispatches work here)
        self.inbound_server: InboundServer | None = None
```

Modify `start()` method — after hub_heartbeat start, add inbound server:

```python
    async def start(self) -> None:
        self.config.ensure_dirs()
        await self.db.initialize()
        self.server.set_handler(self.handle_message)
        await self.server.start()
        if self.hub_heartbeat:
            await self.hub_heartbeat.start()
            self.dispatch_strategy.hub_available = (self.hub_heartbeat.status == HubStatus.CONNECTED)
            if self.hub_sync and self.hub_heartbeat.status == HubStatus.CONNECTED:
                await self.hub_sync.sync_all()
            if self.hub_connector and self.hub_heartbeat and self.hub_heartbeat.status == HubStatus.CONNECTED:
                await self._fetch_personality()
                # Start inbound server for accepting hub-dispatched work
                node_key = self.hub_connector.auth.load_node_key()
                if node_key:
                    self.inbound_server = InboundServer(
                        host=self.config.inbound_host,
                        port=self.config.inbound_port,
                        node_api_key=node_key,
                    )
                    self.inbound_server.set_job_handler(self.handle_inbound_job)
                    await self.inbound_server.start()
        self.skill_registry.load()
        logger.info("ARCHIE Engine started")
```

Modify `stop()` method:

```python
    async def stop(self) -> None:
        if self.inbound_server:
            await self.inbound_server.stop()
        if self.hub_heartbeat:
            await self.hub_heartbeat.stop()
        await self.server.stop()
        await self.db.close()
        logger.info("ARCHIE Engine stopped")
```

Add `handle_inbound_job()` method:

```python
    async def handle_inbound_job(self, job: dict) -> dict:
        """Process a job dispatched from the hub.

        Called by InboundServer when the hub sends work to this node.
        Routes through the engine's intent parser and router.
        """
        task = job.get("task", "")
        context = job.get("context", {})

        try:
            # Create a session for this inbound job
            session = await self.sessions.create(working_dir=str(Path.cwd()))
            session_id = session["id"]
            await self.sessions.add_message(session_id, "user", f"[hub-dispatch] {task}")

            # Classify and route
            intent = self.intent_parser.classify(task)
            decision = self.dispatch_strategy.decide(intent)

            # For inbound hub work, always process locally (don't re-dispatch to hub)
            build_ctx = await self.sessions.build_context(session_id)
            build_ctx.update(context)
            result = await self.router.route(intent, build_ctx)

            response = result.get("response", "")
            await self.sessions.add_message(session_id, "assistant", response)

            # Log job completion back to hub
            if self.hub_connector:
                import time
                await self.hub_connector.log_job(
                    task=task,
                    agent_name="ARCHIE Code Engine",
                    result_summary=response[:200],
                    duration_ms=0,
                )

            return {
                "success": True,
                "response": response,
                "intent": intent["type"],
                "session_id": session_id,
            }
        except Exception as e:
            logger.error("Inbound job failed: %s", e)
            return {"success": False, "error": str(e)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_engine.py -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v --timeout=30`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/engine.py archie_engine/tests/test_engine.py
git commit -m "feat(engine): wire inbound server for hub-dispatched work"
```

---

### Task 7: Integration Test — Full Round Trip

**Files:**
- Modify: `archie_engine/tests/test_hub_integration.py`

**Context:** Verify the full flow: registration → heartbeat → inbound dispatch → result. This uses mocks for the hub API but exercises the real engine components end-to-end.

- [ ] **Step 1: Write the integration test**

```python
# Add to archie_engine/tests/test_hub_integration.py

import pytest
from unittest.mock import AsyncMock, patch
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig
from archie_engine.hub import HubStatus


@pytest.mark.asyncio
async def test_full_node_lifecycle(tmp_path):
    """Test: register → heartbeat → accept inbound work → result."""
    config = EngineConfig(
        data_dir=tmp_path,
        hub_url="http://192.168.1.200:3000",
        hub_api_key="test-key",
    )

    engine = Engine(config)

    # Mock hub registration response
    engine.hub_connector.register_node = AsyncMock(return_value={
        "success": True,
        "node": {"node_id": "node_test123", "node_name": "test-node"},
        "api_key": "node-api-key-456",
    })
    engine.hub_connector.send_heartbeat = AsyncMock(return_value={"success": True})
    engine.hub_connector.get_personality = AsyncMock(return_value={"error": "not found"})
    engine.hub_connector.log_job = AsyncMock(return_value={"success": True})

    # Mock router to avoid needing Ollama
    engine.router.route = AsyncMock(return_value={
        "response": "No security issues found in main.py",
        "success": True,
    })

    # 1. Registration
    await engine.hub_heartbeat._register()
    assert engine.hub_heartbeat.status == HubStatus.CONNECTED
    assert engine.hub_heartbeat.node_id == "node_test123"

    # 2. Verify system info was sent
    reg_call = engine.hub_connector.register_node.call_args[1]
    assert "cpu_cores" in reg_call
    assert "ram_gb" in reg_call

    # 3. Heartbeat with real metrics
    await engine.hub_heartbeat._send_one_heartbeat()
    hb_call = engine.hub_connector.send_heartbeat.call_args[1]
    assert "cpu_usage" in hb_call["metrics"]
    assert hb_call["metrics"]["client_version"] == "0.1.0"

    # 4. Inbound work
    await engine.db.initialize()
    result = await engine.handle_inbound_job({
        "task": "Review main.py for security issues",
        "context": {"files": ["main.py"]},
        "source": "hub_dispatch",
    })
    assert result["success"] is True
    assert "response" in result
    await engine.db.close()


@pytest.mark.asyncio
async def test_persisted_credentials_reconnect(tmp_path):
    """Persisted node_id + api_key should skip fresh registration."""
    config = EngineConfig(
        data_dir=tmp_path,
        hub_url="http://192.168.1.200:3000",
        hub_api_key="test-key",
    )

    engine = Engine(config)

    # Simulate persisted credentials from previous session
    engine.hub_connector.auth.store_node_id("node_prev_session")
    engine.hub_connector.auth.store_node_key("prev_api_key")

    # Heartbeat succeeds = node still recognized
    engine.hub_connector.send_heartbeat = AsyncMock(return_value={"success": True})
    engine.hub_connector.register_node = AsyncMock()  # Should NOT be called

    await engine.hub_heartbeat._register()

    assert engine.hub_heartbeat.status == HubStatus.CONNECTED
    assert engine.hub_heartbeat.node_id == "node_prev_session"
    engine.hub_connector.register_node.assert_not_called()
```

- [ ] **Step 2: Run the integration tests**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_hub_integration.py -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite — final verification**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v --timeout=30`
Expected: All tests pass (except pre-existing `test_unknown_slash_falls_through` timeout)

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/tests/test_hub_integration.py
git commit -m "test(hub): integration test for full node lifecycle — register, heartbeat, inbound work"
```

- [ ] **Step 5: Push all Phase 4 commits**

```bash
cd /mnt/archie_brain/archie-code && git push origin main
```

---

## Post-Implementation

After all tasks pass:

1. **Mark task #1608 complete**: `mcp complete_task` with verification notes
2. **Close Project #217**: All 19/19 tasks complete
3. **Log decision**: Node registration approach (persisted credentials + inbound HTTP server)
4. **Update session handoff**: Phase 4 complete, project closed
5. **Optional**: Live test by running engine with `ARCHIE_HUB_URL=http://192.168.1.200:3000` and checking Starbase node list
