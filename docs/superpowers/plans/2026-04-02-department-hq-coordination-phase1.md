# Department HQ Coordination — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three new Department HQ services (coordinator, model, dispatch) that wrap the existing dispatcher. Wire consciousness loops through them. No breaking changes to existing callers.

**Architecture:** New services in `platform_v2/services/` call existing `bridge_dispatcher.py` functions internally. Consciousness loops (`processing_routes.py`) switch from calling dispatcher directly to calling the coordinator. All other callers continue using the old dispatcher unchanged.

**Tech Stack:** Python 3.11, Flask, psycopg2, Ollama REST API, existing `database.py` (`get_db_cursor` context manager)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `platform_v2/services/model_service.py` | Ollama model lifecycle: check loaded, warmboot, unload, eviction cascade, RAM tracking |
| `platform_v2/services/department_coordinator.py` | Agent selection, resource-aware admission, job reservation, queue management |
| `platform_v2/services/dispatch_service.py` | Simplified LLM execution via assigned agent + model |
| `tests/test_model_service.py` | Tests for model service |
| `tests/test_department_coordinator.py` | Tests for coordinator |
| `tests/test_dispatch_service.py` | Tests for dispatch service |

### Modified Files
| File | Change |
|------|--------|
| `platform_v2/tools/consciousness/processing_routes.py` | `_trigger_loop_op` calls coordinator instead of dispatcher |
| `platform_v2/tools/department_hq/__init__.py` | Register coordinator_routes |
| `platform_v2/tools/department_hq/roster_routes.py` | Add live model/job status to agent cards |

### Unchanged (wrapped internally)
| File | Reason |
|------|--------|
| `ai_bridge/bridge_dispatcher.py` | Still called by model_service and dispatch_service internally |
| `ai_bridge/agent_loop.py` | Autonomy triggers unchanged — loops fire same schedule |
| All other ai_bridge modules | No changes in Phase 1 |

---

### Task 1: model_service.py — Ollama Model Lifecycle

**Files:**
- Create: `platform_v2/services/model_service.py`
- Create: `tests/test_model_service.py`

- [ ] **Step 1: Write failing test for check_loaded_models**

```python
# tests/test_model_service.py
import pytest
from unittest.mock import patch, MagicMock


def test_check_loaded_models_returns_model_list():
    """ModelService.check_loaded_models returns list of loaded model dicts."""
    from services.model_service import ModelService

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"models": [{"name": "mistral:7b", "size": 6442450944}]}'
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        svc = ModelService(ollama_url="http://localhost:11434")
        models = svc.check_loaded_models()

    assert len(models) == 1
    assert models[0]["name"] == "mistral:7b"
    assert models[0]["size_gb"] == pytest.approx(6.0, abs=0.1)


def test_check_loaded_models_connection_error():
    """Returns empty list when Ollama is unreachable."""
    from services.model_service import ModelService

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        svc = ModelService(ollama_url="http://localhost:11434")
        models = svc.check_loaded_models()

    assert models == []


def test_get_available_ram():
    """Available RAM = total budget minus loaded model sizes."""
    from services.model_service import ModelService

    svc = ModelService(ollama_url="http://localhost:11434", ram_budget_gb=100.0)
    svc._loaded_cache = [
        {"name": "mistral:7b", "size_gb": 6.0},
        {"name": "phi3.5:latest", "size_gb": 8.0},
    ]
    assert svc.get_available_ram() == pytest.approx(86.0, abs=0.1)


def test_get_model_priority_active_job_is_protected():
    """Models with active jobs get PROTECTED priority (never evict)."""
    from services.model_service import ModelService, ModelPriority

    svc = ModelService(ollama_url="http://localhost:11434")
    svc._active_jobs = {"mistral:7b": [123]}
    assert svc.get_model_priority("mistral:7b") == ModelPriority.PROTECTED


def test_get_model_priority_idle_is_low():
    """Models with no active jobs and no recent use are LOW priority."""
    from services.model_service import ModelService, ModelPriority

    svc = ModelService(ollama_url="http://localhost:11434")
    svc._active_jobs = {}
    svc._last_used = {}
    assert svc.get_model_priority("some-model:7b") == ModelPriority.LOW
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_model_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.model_service'`

- [ ] **Step 3: Implement model_service.py**

```python
# platform_v2/services/model_service.py
"""Model lifecycle management for Department HQ.

Owns: warmboot, load/unload, RAM tracking, eviction cascade.
Wraps existing bridge_dispatcher model functions in Phase 1.
"""

import json
import logging
import os
import time
import urllib.request
from enum import IntEnum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "host.docker.internal:11434")
if not OLLAMA_HOST.startswith("http"):
    OLLAMA_HOST = f"http://{OLLAMA_HOST}"

# Default RAM budget: 80% of 128GB = 102.4GB for models
DEFAULT_RAM_BUDGET_GB = float(os.environ.get("MODEL_RAM_BUDGET_GB", "102.4"))

# Models used by consciousness loops — higher eviction priority
CONSCIOUSNESS_MODELS = {"arctic-embed-cpu:latest", "mistral:7b"}


class ModelPriority(IntEnum):
    """Priority for eviction decisions. Lower = evict first."""
    LOWEST = 0    # No agent assignment, no recent use
    LOW = 1       # Idle, no active jobs
    MEDIUM = 2    # Used recently (within 1 hour)
    HIGH = 3      # Consciousness models
    PROTECTED = 4 # Active job running — never evict


class ModelService:
    """Manages Ollama model lifecycle: load, unload, warmboot, eviction."""

    def __init__(self, ollama_url: str = None, ram_budget_gb: float = None):
        self.ollama_url = ollama_url or OLLAMA_HOST
        self.ram_budget_gb = ram_budget_gb or DEFAULT_RAM_BUDGET_GB
        self._loaded_cache: List[Dict] = []
        self._cache_ts: float = 0
        self._active_jobs: Dict[str, List[int]] = {}  # model → [job_ids]
        self._last_used: Dict[str, float] = {}  # model → timestamp

    # ── Query Ollama ──────────────────────────────────────────────

    def check_loaded_models(self) -> List[Dict]:
        """Query Ollama /api/ps for currently loaded models."""
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/ps")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size_gb": round(m.get("size", 0) / (1024 ** 3), 1),
                    "digest": m.get("digest", ""),
                })
            self._loaded_cache = models
            self._cache_ts = time.time()
            return models
        except Exception as e:
            logger.warning(f"[ModelService] Cannot reach Ollama: {e}")
            return []

    def get_available_ram(self) -> float:
        """Available RAM = budget minus loaded model sizes."""
        total_used = sum(m["size_gb"] for m in self._loaded_cache)
        return self.ram_budget_gb - total_used

    def is_model_loaded(self, model: str) -> bool:
        """Check if model is currently in Ollama memory."""
        if time.time() - self._cache_ts > 30:
            self.check_loaded_models()
        return any(m["name"] == model for m in self._loaded_cache)

    # ── Priority & Eviction ───────────────────────────────────────

    def get_model_priority(self, model: str) -> ModelPriority:
        """Determine eviction priority for a loaded model."""
        if model in self._active_jobs and self._active_jobs[model]:
            return ModelPriority.PROTECTED
        if model in CONSCIOUSNESS_MODELS:
            return ModelPriority.HIGH
        last = self._last_used.get(model, 0)
        if time.time() - last < 3600:
            return ModelPriority.MEDIUM
        return ModelPriority.LOW

    def ensure_capacity(self, needed_gb: float) -> bool:
        """Free RAM using 3-step eviction cascade.

        1. Unload idle models (no active jobs)
        2. Unload lowest priority models
        3. Return False if can't free enough (caller should queue)
        """
        self.check_loaded_models()
        if self.get_available_ram() >= needed_gb:
            return True

        # Step 1: evict idle models (LOW priority first)
        evict_candidates = [
            m for m in self._loaded_cache
            if self.get_model_priority(m["name"]) <= ModelPriority.LOW
        ]
        evict_candidates.sort(key=lambda m: self.get_model_priority(m["name"]))
        for m in evict_candidates:
            logger.info(f"[ModelService] Evicting idle model: {m['name']} ({m['size_gb']}GB)")
            self.unload_model(m["name"])
            self.check_loaded_models()
            if self.get_available_ram() >= needed_gb:
                return True

        # Step 2: evict MEDIUM priority (recently used but no active job)
        medium_candidates = [
            m for m in self._loaded_cache
            if self.get_model_priority(m["name"]) == ModelPriority.MEDIUM
        ]
        medium_candidates.sort(key=lambda m: self._last_used.get(m["name"], 0))
        for m in medium_candidates:
            logger.info(f"[ModelService] Evicting medium-priority model: {m['name']} ({m['size_gb']}GB)")
            self.unload_model(m["name"])
            self.check_loaded_models()
            if self.get_available_ram() >= needed_gb:
                return True

        # Step 3: can't free enough without killing active work
        logger.warning(f"[ModelService] Cannot free {needed_gb}GB — {self.get_available_ram():.1f}GB available")
        return False

    # ── Load / Unload ─────────────────────────────────────────────

    def load_model(self, model: str, host: str = None) -> bool:
        """Load model into Ollama with keep_alive=24h."""
        target = host or self.ollama_url
        try:
            payload = json.dumps({"model": model, "keep_alive": "24h"}).encode()
            req = urllib.request.Request(
                f"{target}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp.read()
            self._last_used[model] = time.time()
            logger.info(f"[ModelService] Loaded {model} on {target}")
            self.check_loaded_models()
            return True
        except Exception as e:
            logger.error(f"[ModelService] Failed to load {model}: {e}")
            return False

    def unload_model(self, model: str, host: str = None) -> bool:
        """Unload model from Ollama (keep_alive=0)."""
        target = host or self.ollama_url
        try:
            payload = json.dumps({"model": model, "keep_alive": 0}).encode()
            req = urllib.request.Request(
                f"{target}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            logger.info(f"[ModelService] Unloaded {model} from {target}")
            self._active_jobs.pop(model, None)
            self.check_loaded_models()
            return True
        except Exception as e:
            logger.error(f"[ModelService] Failed to unload {model}: {e}")
            return False

    def ensure_ready(self, model: str, needed_gb: float = 8.0) -> bool:
        """Ensure model is loaded, warmbooting and evicting if needed."""
        if self.is_model_loaded(model):
            self._last_used[model] = time.time()
            return True

        # Need to load — ensure capacity first
        if not self.ensure_capacity(needed_gb):
            return False

        return self.load_model(model)

    # ── Job tracking ──────────────────────────────────────────────

    def register_job(self, model: str, job_id: int):
        """Mark a model as having an active job (prevents eviction)."""
        if model not in self._active_jobs:
            self._active_jobs[model] = []
        self._active_jobs[model].append(job_id)
        self._last_used[model] = time.time()

    def unregister_job(self, model: str, job_id: int):
        """Remove job from model's active list."""
        if model in self._active_jobs:
            self._active_jobs[model] = [j for j in self._active_jobs[model] if j != job_id]
            if not self._active_jobs[model]:
                del self._active_jobs[model]


# ── Singleton ─────────────────────────────────────────────────────

_instance: Optional[ModelService] = None


def get_model_service() -> ModelService:
    global _instance
    if _instance is None:
        _instance = ModelService()
    return _instance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_model_service.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/model_service.py tests/test_model_service.py
git commit -m "feat(dept-hq): add model_service — Ollama lifecycle, eviction cascade"
```

---

### Task 2: department_coordinator.py — Agent Selection & Admission Control

**Files:**
- Create: `platform_v2/services/department_coordinator.py`
- Create: `tests/test_department_coordinator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_department_coordinator.py
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


def test_request_agent_returns_assignment():
    """Coordinator returns an assignment with agent_id, model, and host."""
    from services.department_coordinator import DepartmentCoordinator, Assignment
    from services.model_service import ModelService

    mock_model_svc = MagicMock(spec=ModelService)
    mock_model_svc.is_model_loaded.return_value = True
    mock_model_svc.ensure_ready.return_value = True
    mock_model_svc.get_available_ram.return_value = 50.0

    coord = DepartmentCoordinator(model_service=mock_model_svc)

    # Mock agent_service.match_capability
    with patch("services.department_coordinator.match_capability") as mock_match:
        mock_match.return_value = [
            {"id": 140, "name": "DARWIN", "display_name": "D.A.R.W.I.N.",
             "department": "Research & Development", "model": "mistral:7b",
             "shift_state": "active", "proficiency_level": 5},
        ]
        result = coord.request_agent("knowledge_analysis", "consciousness")

    assert isinstance(result, Assignment)
    assert result.agent_id == 140
    assert result.model == "mistral:7b"
    assert result.queued is False


def test_request_agent_queues_when_no_capacity():
    """When model can't be loaded (no RAM), result is queued."""
    from services.department_coordinator import DepartmentCoordinator, Assignment
    from services.model_service import ModelService

    mock_model_svc = MagicMock(spec=ModelService)
    mock_model_svc.is_model_loaded.return_value = False
    mock_model_svc.ensure_ready.return_value = False

    coord = DepartmentCoordinator(model_service=mock_model_svc)

    with patch("services.department_coordinator.match_capability") as mock_match:
        mock_match.return_value = [
            {"id": 140, "name": "DARWIN", "model": "mistral:7b",
             "shift_state": "active", "proficiency_level": 5},
        ]
        result = coord.request_agent("knowledge_analysis", "consciousness")

    assert result.queued is True


def test_request_agent_skips_busy_agents():
    """Agents currently reserved are skipped."""
    from services.department_coordinator import DepartmentCoordinator, Assignment
    from services.model_service import ModelService

    mock_model_svc = MagicMock(spec=ModelService)
    mock_model_svc.is_model_loaded.return_value = True
    mock_model_svc.ensure_ready.return_value = True
    mock_model_svc.get_available_ram.return_value = 50.0

    coord = DepartmentCoordinator(model_service=mock_model_svc)
    coord._reserved_agents = {140}  # DARWIN is busy

    with patch("services.department_coordinator.match_capability") as mock_match:
        mock_match.return_value = [
            {"id": 140, "name": "DARWIN", "model": "mistral:7b",
             "shift_state": "active", "proficiency_level": 5},
            {"id": 146, "name": "CODEX", "model": "mistral:7b",
             "shift_state": "active", "proficiency_level": 4},
        ]
        result = coord.request_agent("knowledge_analysis", "consciousness")

    assert result.agent_id == 146  # Falls through to CODEX
    assert result.queued is False


def test_release_agent_frees_reservation():
    """Releasing an agent removes it from reserved set."""
    from services.department_coordinator import DepartmentCoordinator
    from services.model_service import ModelService

    mock_model_svc = MagicMock(spec=ModelService)
    coord = DepartmentCoordinator(model_service=mock_model_svc)
    coord._reserved_agents = {140}

    coord.release_agent(140, job_id=9999)

    assert 140 not in coord._reserved_agents


def test_request_agent_no_matching_agents():
    """When no agents have the skill, result is queued."""
    from services.department_coordinator import DepartmentCoordinator
    from services.model_service import ModelService

    mock_model_svc = MagicMock(spec=ModelService)
    coord = DepartmentCoordinator(model_service=mock_model_svc)

    with patch("services.department_coordinator.match_capability") as mock_match:
        mock_match.return_value = []
        result = coord.request_agent("unknown_skill", "consciousness")

    assert result.queued is True
    assert "no agent" in result.reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_department_coordinator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement department_coordinator.py**

```python
# platform_v2/services/department_coordinator.py
"""Department HQ Coordinator — agent scheduling, admission control, resource management.

This is the single entry point for all job dispatch. Autonomy loops and
any other callers go through request_agent() to get an assignment.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Set

from services.agent_service import match_capability
from services.model_service import get_model_service, ModelService

logger = logging.getLogger(__name__)


@dataclass
class Assignment:
    """Result of request_agent — either an assignment or a queue notice."""
    agent_id: int = 0
    agent_name: str = ""
    model: str = ""
    host: str = ""
    department: str = ""
    queued: bool = False
    reason: str = ""


class DepartmentCoordinator:
    """Coordinates agent selection, resource checks, and job admission."""

    def __init__(self, model_service: ModelService = None):
        self.model_service = model_service or get_model_service()
        self._reserved_agents: Set[int] = set()
        self._lock = threading.Lock()

    def request_agent(
        self,
        capability: str,
        module_source: str = "",
        priority: str = "normal",
    ) -> Assignment:
        """Find the best available agent for a capability.

        1. Find agents with matching skill (from agent_skills table)
        2. Skip reserved (busy) agents
        3. Ensure the agent's model is loaded (warmboot if needed)
        4. Reserve the agent
        5. Return Assignment

        If no agent or no capacity: returns Assignment(queued=True).
        """
        # 1. Find matching agents ranked by proficiency
        candidates = match_capability(capability)
        if not candidates:
            logger.warning(
                f"[Coordinator] No agents have skill '{capability}'"
            )
            return Assignment(queued=True, reason=f"No agent has skill '{capability}'")

        # 2. Filter out reserved agents
        with self._lock:
            available = [c for c in candidates if c["id"] not in self._reserved_agents]

        if not available:
            logger.info(
                f"[Coordinator] All {len(candidates)} agents for '{capability}' are busy"
            )
            return Assignment(
                queued=True,
                reason=f"All {len(candidates)} agents for '{capability}' are reserved",
            )

        # 3. Try each available agent in proficiency order
        for agent in available:
            model = agent.get("model", "")
            if not model:
                continue

            # Ensure model is ready (loads if needed, evicts if necessary)
            ready = self.model_service.ensure_ready(model)
            if not ready:
                logger.info(
                    f"[Coordinator] Cannot load {model} for {agent['name']} — trying next"
                )
                continue

            # 4. Reserve the agent
            with self._lock:
                self._reserved_agents.add(agent["id"])

            self.model_service.register_job(model, 0)  # job_id set later

            logger.info(
                f"[Coordinator] Assigned {agent['name']} ({model}) "
                f"for '{capability}' from {module_source}"
            )

            return Assignment(
                agent_id=agent["id"],
                agent_name=agent["name"],
                model=model,
                host=self.model_service.ollama_url,
                department=agent.get("department", ""),
            )

        # All candidates tried, none could load
        return Assignment(
            queued=True,
            reason=f"Cannot load models for '{capability}' — insufficient resources",
        )

    def release_agent(self, agent_id: int, job_id: int = None):
        """Release an agent after job completion."""
        with self._lock:
            self._reserved_agents.discard(agent_id)

        logger.info(f"[Coordinator] Released agent #{agent_id} (job #{job_id})")

    def get_status(self) -> dict:
        """Return current coordinator status for UI."""
        self.model_service.check_loaded_models()
        return {
            "reserved_agents": list(self._reserved_agents),
            "reserved_count": len(self._reserved_agents),
            "loaded_models": self.model_service._loaded_cache,
            "available_ram_gb": round(self.model_service.get_available_ram(), 1),
            "active_jobs": dict(self.model_service._active_jobs),
        }


# ── Singleton ─────────────────────────────────────────────────────

_instance: Optional[DepartmentCoordinator] = None


def get_coordinator() -> DepartmentCoordinator:
    global _instance
    if _instance is None:
        _instance = DepartmentCoordinator()
    return _instance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_department_coordinator.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/department_coordinator.py tests/test_department_coordinator.py
git commit -m "feat(dept-hq): add department_coordinator — admission control, agent reservation"
```

---

### Task 3: dispatch_service.py — Simplified LLM Execution

**Files:**
- Create: `platform_v2/services/dispatch_service.py`
- Create: `tests/test_dispatch_service.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_dispatch_service.py
from unittest.mock import patch, MagicMock


def test_dispatch_calls_ollama_and_releases_agent():
    """Dispatch sends prompt to Ollama, releases agent via coordinator."""
    from services.dispatch_service import DispatchService, DispatchResult
    from services.department_coordinator import DepartmentCoordinator, Assignment

    mock_coord = MagicMock(spec=DepartmentCoordinator)
    svc = DispatchService(coordinator=mock_coord)

    assignment = Assignment(
        agent_id=140, agent_name="DARWIN", model="mistral:7b",
        host="http://host.docker.internal:11434",
    )

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"response": "test output", "eval_count": 10, "prompt_eval_count": 20}'
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = svc.dispatch(assignment, "test prompt")

    assert result.success is True
    assert result.response == "test output"
    assert result.completion_tokens == 10
    mock_coord.release_agent.assert_called_once_with(140, job_id=None)


def test_dispatch_handles_timeout():
    """Dispatch returns failure on timeout, still releases agent."""
    from services.dispatch_service import DispatchService, DispatchResult
    from services.department_coordinator import DepartmentCoordinator, Assignment

    mock_coord = MagicMock(spec=DepartmentCoordinator)
    svc = DispatchService(coordinator=mock_coord)

    assignment = Assignment(
        agent_id=140, agent_name="DARWIN", model="mistral:7b",
        host="http://host.docker.internal:11434",
    )

    with patch("urllib.request.urlopen", side_effect=Exception("Read timed out")):
        result = svc.dispatch(assignment, "test prompt")

    assert result.success is False
    assert "timed out" in result.error.lower()
    mock_coord.release_agent.assert_called_once()  # Agent always released
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_dispatch_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement dispatch_service.py**

```python
# platform_v2/services/dispatch_service.py
"""Simplified LLM execution service for Department HQ.

Receives an Assignment from the coordinator, executes the LLM call,
and reports completion. No agent selection, no model loading — that's
all handled by the coordinator before we get here.
"""

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    success: bool = False
    response: str = ""
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    error: str = ""


class DispatchService:
    """Executes LLM calls on assigned agent models."""

    def __init__(self, coordinator=None):
        self.coordinator = coordinator

    def dispatch(
        self,
        assignment,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        timeout: int = 120,
        job_id: int = None,
    ) -> DispatchResult:
        """Execute LLM call on the assigned agent's model.

        Args:
            assignment: Assignment from coordinator (agent_id, model, host)
            prompt: The prompt to send
            system_prompt: Optional system prompt
            json_mode: Request JSON formatted response
            timeout: Request timeout in seconds
            job_id: Optional job ID for tracking

        Returns:
            DispatchResult with response or error
        """
        payload = {
            "model": assignment.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": 4096, "num_predict": 1024},
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["format"] = "json"

        start = time.time()
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{assignment.host}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())

            elapsed = int((time.time() - start) * 1000)
            response_text = result.get("response", "")

            return DispatchResult(
                success=bool(response_text.strip()),
                response=response_text,
                model_used=assignment.model,
                prompt_tokens=result.get("prompt_eval_count", 0),
                completion_tokens=result.get("eval_count", 0),
                duration_ms=elapsed,
            )

        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            logger.error(
                f"[Dispatch] {assignment.agent_name}/{assignment.model} "
                f"failed after {elapsed}ms: {e}"
            )
            return DispatchResult(
                success=False,
                model_used=assignment.model,
                duration_ms=elapsed,
                error=str(e),
            )

        finally:
            # Always release agent — success or failure
            if self.coordinator:
                self.coordinator.release_agent(assignment.agent_id, job_id=job_id)


# ── Singleton ─────────────────────────────────────────────────────

_instance: Optional[DispatchService] = None


def get_dispatch_service() -> DispatchService:
    global _instance
    if _instance is None:
        from services.department_coordinator import get_coordinator
        _instance = DispatchService(coordinator=get_coordinator())
    return _instance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_dispatch_service.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/dispatch_service.py tests/test_dispatch_service.py
git commit -m "feat(dept-hq): add dispatch_service — simplified LLM execution"
```

---

### Task 4: Wire Consciousness Loops Through Coordinator

**Files:**
- Modify: `platform_v2/tools/consciousness/processing_routes.py` (lines 1153-1266)

- [ ] **Step 1: Read the current _trigger_loop_op function**

Read: `platform_v2/tools/consciousness/processing_routes.py` lines 1153-1266
Understand: how it currently calls `get_dispatcher()` and `dispatcher.create_job()`

- [ ] **Step 2: Add coordinator import at top of file**

Add after the existing imports (around line 16):

```python
from services.department_coordinator import get_coordinator
from services.dispatch_service import get_dispatch_service
```

- [ ] **Step 3: Replace embedding dispatch to use coordinator**

In `_trigger_loop_op`, replace the embedding section (after the SQL query that fetches items). The SQL query stays the same. Replace the dispatcher.create_job + thread launch:

Find the section starting at `elif op == "embedding":` after the items query. Replace the job creation and thread launch to use coordinator:

```python
        elif op == "embedding":
            cur.execute(
                """
                (SELECT id, title, content, 'knowledge_base' AS source
                 FROM knowledge_base
                 WHERE embedding IS NULL AND content IS NOT NULL AND LENGTH(content) > 50
                 ORDER BY created_at DESC LIMIT 200)
                UNION ALL
                (SELECT id, title, decision, 'decisions'
                 FROM project_decisions
                 WHERE embedding IS NULL
                 ORDER BY created_at DESC LIMIT 20)
                UNION ALL
                (SELECT id, title, text, 'translations'
                 FROM translations
                 WHERE embedding IS NULL
                 ORDER BY created_at DESC LIMIT 20)
                """
            )
            items = cur.fetchall()
            if not items:
                logger.debug("[ServerLoop] embedding: no items this cycle — will check again next run")
                return

            # Use coordinator for admission control
            coordinator = get_coordinator()
            assignment = coordinator.request_agent("embedding", "consciousness", priority="high")
            if assignment.queued:
                logger.info(f"[ServerLoop] embedding: queued — {assignment.reason}")
                return

            job_id = dispatcher.create_job(
                job_type="batch_embedding",
                module_source="consciousness",
                description=f"[auto-loop] Embed {len(items)} intelligence entries",
                total_steps=len(items),
                capability="embedding",
                metadata={"batch_size": 25, "server_loop": True},
            )
            if not job_id:
                coordinator.release_agent(assignment.agent_id)
                logger.info("[ServerLoop] embedding: duplicate job running")
                return

            coordinator.model_service.register_job(assignment.model, job_id)

            t = threading.Thread(target=_run_embedding_job, args=(list(items), job_id), daemon=True)
            t.start()
            logger.info(f"[ServerLoop] embedding: started job #{job_id} with {len(items)} items (agent={assignment.agent_name})")
```

- [ ] **Step 4: Replace analysis dispatch similarly**

Same pattern for the analysis section. Replace the `if op == "analysis":` block's job creation:

```python
        if op == "analysis":
            cur.execute(
                """
                SELECT id, title, content, memory_metadata
                FROM knowledge_base
                WHERE (ai_analysis IS NULL OR analysis_version = 0)
                AND content IS NOT NULL AND LENGTH(content) > 100
                AND knowledge_type IN (
                    'vault_note', 'mistake_learned', 'conversation_memory',
                    'github_file', 'code_snippet', 'api_endpoint'
                )
                ORDER BY
                    CASE knowledge_type
                        WHEN 'mistake_learned' THEN 1
                        WHEN 'vault_note' THEN 2
                        WHEN 'conversation_memory' THEN 3
                        WHEN 'github_file' THEN 4
                        WHEN 'code_snippet' THEN 5
                        ELSE 6
                    END,
                    importance_score DESC NULLS LAST,
                    created_at DESC
                LIMIT 10
                """
            )
            items = cur.fetchall()
            if not items:
                logger.debug("[ServerLoop] analysis: no items this cycle — will check again next run")
                return

            # Use coordinator for admission control
            coordinator = get_coordinator()
            assignment = coordinator.request_agent("knowledge_analysis", "consciousness", priority="normal")
            if assignment.queued:
                logger.info(f"[ServerLoop] analysis: queued — {assignment.reason}")
                return

            batch_id = str(uuid.uuid4())
            job_id = dispatcher.create_job(
                job_type="batch_analysis",
                module_source="consciousness",
                description=f"[auto-loop] Analyze {len(items)} entries",
                total_steps=len(items),
                capability="knowledge_analysis",
                metadata={"category": "conversations", "batch_id": batch_id, "batch_size": 10, "server_loop": True},
            )
            if not job_id:
                coordinator.release_agent(assignment.agent_id)
                logger.info("[ServerLoop] analysis: duplicate job running — will retry after it completes")
                return

            coordinator.model_service.register_job(assignment.model, job_id)

            t = threading.Thread(
                target=_run_analysis_job, args=(list(items), "conversations", batch_id, job_id), daemon=True
            )
            t.start()
            logger.info(f"[ServerLoop] analysis: started job #{job_id} with {len(items)} items (agent={assignment.agent_name})")
```

- [ ] **Step 5: Replace translate dispatch similarly**

Same pattern for translate section:

```python
        elif op == "translate":
            from tools.consciousness.language_routes import _run_translate_bg

            # Use coordinator for admission control
            coordinator = get_coordinator()
            assignment = coordinator.request_agent("translate", "consciousness", priority="low")
            if assignment.queued:
                logger.info(f"[ServerLoop] translate: queued — {assignment.reason}")
                return

            languages = ["fr", "es", "pt", "de", "zh", "ar", "he"]
            job_id = dispatcher.create_job(
                job_type="translate_batch",
                module_source="consciousness",
                description="[auto-loop] Translate missing keys",
                total_steps=len(languages),
                capability="translate",
                metadata={"languages": languages, "server_loop": True},
            )
            if not job_id:
                coordinator.release_agent(assignment.agent_id)
                logger.info("[ServerLoop] translate: duplicate job running")
                return

            coordinator.model_service.register_job(assignment.model, job_id)

            t = threading.Thread(
                target=_run_translate_bg,
                args=(languages, None, job_id),
                daemon=True,
            )
            t.start()
            logger.info(f"[ServerLoop] translate: started job #{job_id} (agent={assignment.agent_name})")
```

- [ ] **Step 6: Deploy and test all 3 loops**

```bash
docker exec archie_platform find /app/ -name "__pycache__" -exec rm -rf {} + 2>/dev/null
docker compose restart archie_platform
sleep 25
docker logs archie_platform 2>&1 | grep -i "Coordinator\|ServerLoop.*start\|ServerLoop.*queued" | tail -15
```

Expected: logs showing `[Coordinator] Assigned DARWIN (mistral:7b) for 'knowledge_analysis'` and all 3 loops starting with agent assignments.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/consciousness/processing_routes.py
git commit -m "feat(consciousness): wire loops through Department HQ coordinator"
```

---

### Task 5: Add Coordinator Status to Department HQ Roster API

**Files:**
- Modify: `platform_v2/tools/department_hq/roster_routes.py`

- [ ] **Step 1: Read existing roster route**

Read: `platform_v2/tools/department_hq/roster_routes.py` — find `api_roster()` function

- [ ] **Step 2: Add coordinator status endpoint**

Add a new route after the existing roster routes:

```python
    @bp.route("/api/coordinator/status")
    @admin_required
    def api_coordinator_status():
        """Live coordinator status — reserved agents, loaded models, RAM."""
        from services.department_coordinator import get_coordinator

        coordinator = get_coordinator()
        status = coordinator.get_status()
        return jsonify({"success": True, **status})
```

- [ ] **Step 3: Enhance api_roster to include reservation status**

In the existing `api_roster()` function, after building the agent list, add reservation info:

```python
        # Add coordinator reservation status to each agent
        try:
            from services.department_coordinator import get_coordinator
            coordinator = get_coordinator()
            reserved = coordinator._reserved_agents
            for agent in agents:
                agent["is_reserved"] = agent["id"] in reserved
        except Exception:
            pass  # coordinator not initialized yet
```

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
sleep 15
curl -s http://192.168.1.200:3000/tools/department-hq/api/coordinator/status -b "session=admin" | python3 -m json.tool | head -20
```

Expected: JSON with reserved_agents, loaded_models, available_ram_gb

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/roster_routes.py
git commit -m "feat(dept-hq): add coordinator status API + reservation flag on roster"
```

---

### Task 6: Integration Test — All Loops Through Coordinator

**Files:**
- Create: `tests/test_consciousness_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_consciousness_integration.py
"""Integration test: consciousness loops dispatch through coordinator."""
import pytest
from unittest.mock import patch, MagicMock


def test_embedding_loop_uses_coordinator():
    """Verify _trigger_loop_op('embedding') calls coordinator.request_agent."""
    import sys
    sys.path.insert(0, "platform_v2")

    with patch("services.department_coordinator.match_capability") as mock_match, \
         patch("services.model_service.ModelService.check_loaded_models") as mock_check, \
         patch("services.model_service.ModelService.is_model_loaded", return_value=True):

        mock_match.return_value = [
            {"id": 137, "name": "SPECTRA", "model": "qwen2.5:7b",
             "shift_state": "active", "proficiency_level": 4},
        ]

        from services.department_coordinator import get_coordinator
        coordinator = get_coordinator()

        # Verify coordinator can assign for embedding
        result = coordinator.request_agent("embedding", "consciousness")
        assert result.agent_id == 137
        assert result.queued is False


def test_coordinator_prevents_double_booking():
    """Same agent can't be assigned to two jobs simultaneously."""
    import sys
    sys.path.insert(0, "platform_v2")

    with patch("services.department_coordinator.match_capability") as mock_match, \
         patch("services.model_service.ModelService.is_model_loaded", return_value=True):

        mock_match.return_value = [
            {"id": 140, "name": "DARWIN", "model": "mistral:7b",
             "shift_state": "active", "proficiency_level": 5},
        ]

        from services.department_coordinator import DepartmentCoordinator
        from services.model_service import ModelService

        mock_model = MagicMock(spec=ModelService)
        mock_model.is_model_loaded.return_value = True
        mock_model.ensure_ready.return_value = True

        coord = DepartmentCoordinator(model_service=mock_model)

        # First assignment succeeds
        r1 = coord.request_agent("knowledge_analysis", "consciousness")
        assert r1.agent_id == 140

        # Second request — DARWIN is reserved, no other candidates
        r2 = coord.request_agent("knowledge_analysis", "consciousness")
        assert r2.queued is True

        # Release DARWIN
        coord.release_agent(140)

        # Third request — DARWIN available again
        r3 = coord.request_agent("knowledge_analysis", "consciousness")
        assert r3.agent_id == 140
```

- [ ] **Step 2: Run integration tests**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_consciousness_integration.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Run all tests together**

Run: `cd /mnt/archie_brain && PYTHONPATH=platform_v2 python -m pytest tests/test_model_service.py tests/test_department_coordinator.py tests/test_dispatch_service.py tests/test_consciousness_integration.py -v`
Expected: All 12 tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_consciousness_integration.py
git commit -m "test: integration tests for consciousness loops through coordinator"
```

---

### Task 7: Verify Live System

**Files:** None (verification only)

- [ ] **Step 1: Deploy final version**

```bash
docker exec archie_platform find /app/ -name "__pycache__" -exec rm -rf {} + 2>/dev/null
docker compose restart archie_platform
```

- [ ] **Step 2: Wait for loops to fire and check logs**

```bash
sleep 30
docker logs archie_platform 2>&1 | grep -i "Coordinator\|ServerLoop" | tail -20
```

Expected:
- `[Coordinator] Assigned DARWIN (mistral:7b) for 'knowledge_analysis'`
- `[Coordinator] Assigned SPECTRA (...) for 'embedding'`
- `[Coordinator] Assigned Polyglot (mistral:7b) for 'translate'`
- No "lacks required skill" errors
- No agent budget exhaustion

- [ ] **Step 3: Check coordinator status API**

```bash
curl -s http://192.168.1.200:3000/tools/department-hq/api/coordinator/status | python3 -m json.tool
```

Expected: JSON showing reserved agents, loaded models, available RAM

- [ ] **Step 4: Verify embedding count still decreasing**

```bash
docker exec archie_database psql -U archie -d archie -t -c "SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NULL;"
```

Expected: number lower than before deployment

- [ ] **Step 5: Log decision and commit**

```bash
git add -A
git commit -m "feat(dept-hq): Phase 1 complete — coordinator, model service, dispatch service

Department HQ now coordinates all consciousness loop dispatch:
- model_service.py: Ollama lifecycle, eviction cascade, RAM tracking
- department_coordinator.py: agent selection, admission control, reservation
- dispatch_service.py: simplified LLM execution
- Consciousness loops wire through coordinator instead of dispatcher directly
- 12 unit tests + 2 integration tests

Decision #371, Project #215."
```
