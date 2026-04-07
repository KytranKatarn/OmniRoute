# Department HQ Coordination — Phase 2: Service Expansion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `ensure_model_ready()`, agent selection/scoring, and job CRUD from the 7800-line `bridge_dispatcher.py` monolith into the three Department HQ services created in Phase 1 (`model_service.py`, `department_coordinator.py`, `dispatch_service.py`), then wire the dispatcher to call those services. Fix 3 agents with non-existent models.

**Architecture:** Phase 1 created the three services with basic functionality. Phase 2 expands them to absorb the dispatcher's complex logic — model readiness with 3-tier warm boot, multi-factor agent scoring, and job lifecycle with duplicate guards. The dispatcher keeps its public API (`request_work`, `create_job`, `complete_job`) but internally delegates to services. Callers (`agent_loop.py`, `mission_manager.py`, `translation_service.py`, consciousness loops) are unaffected.

**Tech Stack:** Python 3.11, Flask, psycopg2, PostgreSQL, Ollama REST API

**Spec:** `docs/superpowers/specs/2026-04-02-department-hq-coordination-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `platform_v2/services/model_service.py` | Add `ensure_model_ready()` with 3-tier warm boot, `_estimate_model_size()`, RAM eviction, node support |
| Modify | `platform_v2/services/department_coordinator.py` | Add `_score_agent()`, `select_agent_by_department()`, `_find_cross_department_agent()`, `_resolve_department()` |
| Modify | `platform_v2/services/dispatch_service.py` | Add `create_job()`, `complete_job()`, `update_job_progress()` with duplicate guards |
| Modify | `ai_bridge/bridge_dispatcher.py` | Replace internal method calls with service calls |
| Modify | Database | Fix 3 agent model assignments |
| Create | `platform_v2/services/tests/test_phase2_model_service.py` | Tests for expanded model_service |
| Create | `platform_v2/services/tests/test_phase2_coordinator.py` | Tests for expanded coordinator |
| Create | `platform_v2/services/tests/test_phase2_dispatch.py` | Tests for expanded dispatch_service |

---

### Task 1: Fix 3 broken agent models

**Why first:** Broken models cause dispatch failures in every subsequent test. Fix the data before touching code.

**Current state (from DB query):**
- Maven (id:27) → `samantha-mistral:7b` — not in Ollama
- Sage (id:33) → `codellama:13b` — not in Ollama
- W.A.T.C.H. (id:152) → `qwen2.5:7b` — not in Ollama (have `qwen2.5-coder:7b`)

**Available models that fit:** `mistral:7b` (general), `qwen2.5-coder:7b` (code/analytics), `phi3.5:latest` (general), `gemma2:9b` (general)

- [ ] **Step 1: Fix Maven — R&D agent, needs general reasoning**

```bash
docker exec archie_database psql -U archie -d archie -c "
  UPDATE agents SET model = 'mistral:7b' WHERE id = 27 AND name = 'Maven';
"
```

Expected: `UPDATE 1`

- [ ] **Step 2: Fix Sage — Analytics agent, needs analytical model**

```bash
docker exec archie_database psql -U archie -d archie -c "
  UPDATE agents SET model = 'gemma2:9b' WHERE id = 33 AND name = 'Sage';
"
```

Expected: `UPDATE 1`

- [ ] **Step 3: Fix W.A.T.C.H. — Analytics agent, needs coding/analysis**

```bash
docker exec archie_database psql -U archie -d archie -c "
  UPDATE agents SET model = 'qwen2.5-coder:7b' WHERE id = 152 AND name = 'W.A.T.C.H.';
"
```

Expected: `UPDATE 1`

- [ ] **Step 4: Verify all 3 fixes**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT id, name, model FROM agents WHERE id IN (27, 33, 152);
"
```

Expected: Maven→mistral:7b, Sage→gemma2:9b, W.A.T.C.H.→qwen2.5-coder:7b

- [ ] **Step 5: Log decision**

```bash
# Via MCP: log_decision with context about why each model was chosen
```

---

### Task 2: Expand model_service.py — 3-tier ensure_model_ready with node support

**Files:**
- Modify: `platform_v2/services/model_service.py`
- Create: `platform_v2/services/tests/test_phase2_model_service.py`

The existing `ensure_ready()` in model_service.py is a simplified version (check→capacity→load). The dispatcher's `ensure_model_ready()` has: VRAM tier detection, CPU vs GPU distinction, node routing, RAM capacity checks with eviction, `_estimate_model_size()`, and warm boot timing. We need to absorb that logic.

- [ ] **Step 1: Write failing tests**

Create `platform_v2/services/tests/test_phase2_model_service.py`:

```python
"""Tests for expanded model_service (Phase 2).

Run: docker exec archie_platform python -m pytest services/tests/test_phase2_model_service.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import patch, MagicMock
from services.model_service import ModelService, ModelPriority


def test_ensure_model_ready_returns_tier_dict():
    """ensure_model_ready should return dict with ready, tier, host, warm_boot_ms."""
    svc = ModelService(ollama_host="http://fake:11434")
    with patch.object(svc, "_fetch_ps", return_value=[
        {"name": "mistral:7b", "size_gb": 4.0, "size_vram": 4_000_000_000, "size": 4_000_000_000}
    ]):
        result = svc.ensure_model_ready("TestAgent", "mistral:7b")
    assert result["ready"] is True
    assert result["tier"] in ("gpu", "cpu")
    assert "host" in result
    assert "warm_boot_ms" in result


def test_ensure_model_ready_cold_model():
    """Cold model should attempt load and return tier='cold'."""
    svc = ModelService(ollama_host="http://fake:11434")
    with patch.object(svc, "_fetch_ps", return_value=[]):
        with patch.object(svc, "load_model", return_value=True):
            with patch.object(svc, "ensure_capacity", return_value=True):
                result = svc.ensure_model_ready("TestAgent", "phi3.5:latest")
    assert result["ready"] is True
    assert result["tier"] == "cold"


def test_ensure_model_ready_no_capacity():
    """If no capacity and eviction fails, return ready=False."""
    svc = ModelService(ollama_host="http://fake:11434", ram_budget_gb=4.0)
    with patch.object(svc, "_fetch_ps", return_value=[]):
        with patch.object(svc, "ensure_capacity", return_value=False):
            result = svc.ensure_model_ready("TestAgent", "phi4:14b")
    assert result["ready"] is False


def test_estimate_model_size_known():
    """Known model sizes should return correct estimates."""
    svc = ModelService(ollama_host="http://fake:11434")
    assert svc.estimate_model_size("mistral:7b") >= 3.0
    assert svc.estimate_model_size("mistral:7b") <= 8.0


def test_ensure_model_ready_node_target():
    """Node target should use the node's host, not hub."""
    svc = ModelService(ollama_host="http://fake:11434")
    target = {"hostname": "192.168.1.246", "port": 11434}
    with patch.object(svc, "_fetch_ps", return_value=[
        {"name": "llama3.2:3b", "size_gb": 2.0, "size_vram": 2_000_000_000, "size": 2_000_000_000}
    ]):
        result = svc.ensure_model_ready("TestAgent", "llama3.2:3b", target_host=target)
    assert result["ready"] is True
    assert "192.168.1.246" in result["host"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase2_model_service.py -v 2>&1 | tail -15
```

Expected: FAIL — `AttributeError: 'ModelService' object has no attribute 'ensure_model_ready'`

- [ ] **Step 3: Add estimate_model_size() to ModelService**

In `model_service.py`, add after the `ensure_ready()` method:

```python
    # Known model size estimates (GB in RAM)
    _MODEL_SIZE_ESTIMATES = {
        "mistral:7b": 4.1, "llama3.2:3b": 2.0, "phi3.5:latest": 5.5,
        "phi4:14b": 8.5, "gemma2:9b": 5.5, "gemma3:12b": 7.2,
        "qwen2.5-coder:7b": 4.5, "qwen2.5:1.5b": 1.0,
        "dolphin3:latest": 4.8, "deepseek-coder-v2:16b": 9.5,
        "qwen2.5vl:7b": 4.5, "arctic-embed-cpu:latest": 0.3,
        "smollm2:1.7b": 1.2, "qwen3-coder-cpu:latest": 55.0,
    }

    def estimate_model_size(self, model: str) -> float:
        """Estimate model RAM usage in GB. Falls back to parameter-count heuristic."""
        if model in self._MODEL_SIZE_ESTIMATES:
            return self._MODEL_SIZE_ESTIMATES[model]
        # Heuristic: extract parameter count from name (e.g. "7b" → 7 * 0.6)
        import re
        match = re.search(r"(\d+(?:\.\d+)?)b", model.lower())
        if match:
            params = float(match.group(1))
            return params * 0.6  # ~0.6 GB per billion params (quantized)
        return 4.0  # conservative default
```

- [ ] **Step 4: Add ensure_model_ready() with 3-tier warm boot**

In `model_service.py`, add after `estimate_model_size()`:

```python
    def ensure_model_ready(
        self,
        agent_name: str,
        model: str,
        target_host: Optional[Dict] = None,
    ) -> Dict:
        """Ensure model is loaded and ready for inference.

        3-tier strategy:
            1. GPU (VRAM) — already loaded with VRAM allocation
            2. CPU (RAM)  — loaded but no/partial VRAM
            3. Cold (disk) — not loaded, needs warm boot

        Args:
            agent_name: Agent requesting the model (for logging).
            model: Ollama model tag.
            target_host: {"hostname": str, "port": int} for node, None for hub.

        Returns:
            {"ready": bool, "tier": "gpu"|"cpu"|"cold", "host": str, "warm_boot_ms": int}
        """
        import time as _time
        start_ms = _time.time() * 1000

        # Resolve target
        if target_host:
            host = target_host.get("hostname", "unknown")
            port = target_host.get("port", 11434)
            ollama_url = f"http://{host}:{port}"
        else:
            ollama_url = self.ollama_host
            host = ollama_url.replace("http://", "").replace("https://", "")
            port = 11434

        host_label = f"{host}:{port}" if ":" not in host else host

        # Step 1: Check if already loaded
        try:
            url = f"{ollama_url}/api/ps"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for m in data.get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    size_vram = m.get("size_vram", 0)
                    size_total = m.get("size", 0)
                    if size_vram > 0 and size_vram >= size_total * 0.5:
                        tier = "gpu"
                    else:
                        tier = "cpu"
                    self._last_used[model] = _time.time()
                    logger.info("[ModelService] %s hot on %s @ %s", model, tier, host_label)
                    return {"ready": True, "tier": tier, "host": host_label, "warm_boot_ms": 0}
        except Exception as exc:
            logger.error("[ModelService] /api/ps failed on %s: %s", host_label, exc)
            return {"ready": False, "tier": "cold", "host": host_label, "warm_boot_ms": 0}

        # Step 2: Model is cold — check capacity
        needed_gb = self.estimate_model_size(model)
        if not self.ensure_capacity(needed_gb):
            logger.warning(
                "[ModelService] Not enough RAM for %s on %s (need %.1fGB)",
                model, host_label, needed_gb,
            )
            return {
                "ready": False, "tier": "cold", "host": host_label,
                "warm_boot_ms": int(_time.time() * 1000 - start_ms),
            }

        # Step 3: Load the model
        if self.load_model(model):
            elapsed_ms = int(_time.time() * 1000 - start_ms)
            logger.info("[ModelService] %s cold-loaded on %s in %dms", model, host_label, elapsed_ms)
            return {"ready": True, "tier": "cold", "host": host_label, "warm_boot_ms": elapsed_ms}

        return {
            "ready": False, "tier": "cold", "host": host_label,
            "warm_boot_ms": int(_time.time() * 1000 - start_ms),
        }
```

- [ ] **Step 5: Update _fetch_ps to include VRAM fields**

In the existing `_fetch_ps()` method, update the return dict:

```python
    def _fetch_ps(self) -> List[Dict]:
        """Hit /api/ps and return parsed model list."""
        try:
            url = f"{self.ollama_host}/api/ps"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            models = data.get("models", [])
            return [
                {
                    "name": m["name"],
                    "size_gb": m.get("size", 0) / (1024**3),
                    "size_vram": m.get("size_vram", 0),
                    "size": m.get("size", 0),
                }
                for m in models
            ]
        except Exception as exc:
            logger.warning("model_service: /api/ps failed — %s", exc)
            return []
```

- [ ] **Step 6: Run tests**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase2_model_service.py -v 2>&1 | tail -15
```

Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add platform_v2/services/model_service.py platform_v2/services/tests/test_phase2_model_service.py
git commit -m "feat(model-service): add ensure_model_ready with 3-tier warm boot

Phase 2: ModelService now has ensure_model_ready() with GPU/CPU/cold
tier detection, estimate_model_size() with parameter heuristics, and
VRAM-aware _fetch_ps(). Dispatcher's ensure_model_ready can now delegate."
```

---

### Task 3: Expand department_coordinator.py — agent scoring + selection

**Files:**
- Modify: `platform_v2/services/department_coordinator.py`
- Modify: `platform_v2/services/agent_service.py` (add `get_agent_cache()` + `get_welfare_cache()`)
- Create: `platform_v2/services/tests/test_phase2_coordinator.py`

The coordinator currently does simple `match_capability()` + reservation. The dispatcher has a sophisticated scoring system (`_score_agent`) with: status checks, budget limits, stress/welfare, specialization, proficiency, and model tier matching. We need to bring that scoring into the coordinator.

- [ ] **Step 1: Write failing tests**

Create `platform_v2/services/tests/test_phase2_coordinator.py`:

```python
"""Tests for expanded department_coordinator (Phase 2).

Run: docker exec archie_platform python -m pytest services/tests/test_phase2_coordinator.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from database import get_db_cursor


def test_score_agent_blocks_inactive():
    """Agents with status != 'active' should score 0."""
    from services.department_coordinator import get_coordinator
    coord = get_coordinator()
    agent_info = {"id": 999, "status": "paused", "model": "mistral:7b"}
    score, reason = coord.score_agent("TestAgent", agent_info, "general", "Research & Development")
    assert score == 0.0
    assert "paused" in reason


def test_score_agent_active_gets_positive():
    """Active agent with budget should get positive score."""
    from services.department_coordinator import get_coordinator
    coord = get_coordinator()
    agent_info = {
        "id": 999, "status": "active", "model": "mistral:7b",
        "shift_state": "active",
    }
    score, reason = coord.score_agent("TestAgent", agent_info, "general", "Research & Development")
    assert score > 0.0
    assert reason is None


def test_select_agent_returns_best():
    """select_agent should return the highest-scoring available agent."""
    from services.department_coordinator import get_coordinator
    coord = get_coordinator()
    # Use a real department that has agents
    result = coord.select_agent("general", "Engineering & Technology")
    # Should return a dict or None (depending on agent availability)
    assert result is None or isinstance(result, dict)


def test_resolve_department():
    """Known capabilities should map to departments."""
    from services.department_coordinator import get_coordinator
    coord = get_coordinator()
    dept = coord.resolve_department("code")
    assert dept is not None
    assert isinstance(dept, str)


def test_find_cross_department_agent():
    """Cross-department fallback should skip the blocked department."""
    from services.department_coordinator import get_coordinator
    coord = get_coordinator()
    result = coord.find_cross_department_agent("general", "Executive Office")
    # May return None if no agents match — that's OK
    assert result is None or isinstance(result, dict)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase2_coordinator.py -v 2>&1 | tail -15
```

Expected: FAIL — `AttributeError: 'DepartmentCoordinator' has no attribute 'score_agent'`

- [ ] **Step 3: Add agent cache + welfare cache accessors to agent_service.py**

The dispatcher maintains `_agent_cache` and `_welfare_cache`. The coordinator needs access. Add to `agent_service.py` after the existing functions:

```python
def get_agent_cache() -> Dict:
    """Return dict of {agent_name: agent_info} for all active agents.

    Used by department_coordinator for scoring and selection.
    """
    cache = {}
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT a.id, a.name, a.display_name, a.department, a.floor,
                   a.model, a.status, a.shift_state,
                   a.is_department_ai,
                   COALESCE(json_agg(
                       json_build_object('skill', s.skill_category, 'level', s.proficiency_level)
                   ) FILTER (WHERE s.id IS NOT NULL), '[]') AS skills_list
            FROM agents a
            LEFT JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.status = 'active'
            GROUP BY a.id
        """)
        for row in cur.fetchall():
            skills = {}
            for s in (row["skills_list"] if isinstance(row["skills_list"], list) else []):
                if isinstance(s, dict) and s.get("skill"):
                    skills[s["skill"]] = s.get("level", 1)
            cache[row["name"]] = {
                "id": row["id"],
                "name": row["name"],
                "display_name": row["display_name"],
                "department": row["department"],
                "floor": row["floor"],
                "model": row["model"],
                "status": row["status"],
                "shift_state": row["shift_state"],
                "is_department_ai": row["is_department_ai"],
                "skills": skills,
            }
    return cache


def get_welfare_cache() -> Dict:
    """Return dict of {agent_id: welfare_info} for budget/stress scoring.

    Used by department_coordinator for agent scoring.
    """
    cache = {}
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT a.id,
                   COALESCE(es.stress_level, 0.0) AS stress,
                   COALESCE(es.energy_level, 0.5) AS energy,
                   COALESCE(ab.current_task_count, 0) AS task_count,
                   COALESCE(ab.task_queue_limit, 10) AS task_limit,
                   COALESCE(ab.tokens_used_today, 0) AS tokens_used,
                   COALESCE(ab.token_limit_per_day, 100000) AS token_limit
            FROM agents a
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            WHERE a.status = 'active'
        """)
        for row in cur.fetchall():
            task_limit = row["task_limit"] or 10
            token_limit = row["token_limit"] or 100000
            cache[row["id"]] = {
                "stress": float(row["stress"]),
                "energy": float(row["energy"]),
                "budget": {
                    "current_task_count": row["task_count"],
                    "task_queue_limit": task_limit,
                    "tokens_used_today": row["tokens_used"],
                    "token_limit_per_day": token_limit,
                    "utilization_pct": max(
                        row["task_count"] / task_limit,
                        row["tokens_used"] / token_limit,
                    ) if task_limit > 0 and token_limit > 0 else 0.0,
                },
            }
    return cache
```

- [ ] **Step 4: Add scoring and selection to department_coordinator.py**

Replace the imports section and add new methods. Full updated file:

Add these imports at the top of `department_coordinator.py`:

```python
from services.agent_service import match_capability, get_agent_cache, get_welfare_cache
```

Add the `CAPABILITY_DEPARTMENT_MAP` constant after the `Assignment` dataclass:

```python
# Capability → Department mapping (from bridge_dispatcher.py)
CAPABILITY_DEPARTMENT_MAP = {
    "code": "Engineering & Technology",
    "code_review": "Engineering & Technology",
    "debug": "Engineering & Technology",
    "general": "Engineering & Technology",
    "classify": "Analytics & Intelligence",
    "analyze": "Analytics & Intelligence",
    "knowledge_analysis": "Analytics & Intelligence",
    "summarize": "Documentation & Knowledge",
    "translate": "Documentation & Knowledge",
    "embedding": "Documentation & Knowledge",
    "creative": "Creative & Design",
    "image": "Creative & Design",
    "security": "Security & Compliance",
    "compliance": "Security & Compliance",
    "support": "Customer Success & Support",
    "research": "Research & Development",
}
```

Add these methods to the `DepartmentCoordinator` class:

```python
    # ------------------------------------------------------------------
    # Agent scoring (Phase 2 — absorbed from bridge_dispatcher)
    # ------------------------------------------------------------------

    def _refresh_caches(self) -> None:
        """Refresh agent and welfare caches if stale (>30s)."""
        import time as _time
        now = _time.time()
        if not hasattr(self, "_cache_time") or (now - self._cache_time) > 30:
            self._agent_cache = get_agent_cache()
            self._welfare_cache = get_welfare_cache()
            self._cache_time = now

    def score_agent(
        self,
        agent_name: str,
        agent_info: Dict,
        capability: str,
        department: str,
    ) -> tuple:
        """Score an agent for capability dispatch. Returns (score, block_reason_or_None).

        Scoring factors:
        - Status/shift must be active (hard block if not)
        - Budget utilization (hard block at 95%+)
        - Welfare: stress penalty, energy bonus
        - Specialization: skill match bonus
        - Department match bonus
        """
        agent_id = agent_info.get("id")

        # Hard blocks
        if agent_info.get("status") != "active":
            return (0.0, f"{agent_name} is {agent_info.get('status')} (not available)")

        shift = agent_info.get("shift_state", "active")
        if shift not in ("active", "winding_down"):
            return (0.0, f"{agent_name} shift_state={shift}")

        # Budget check
        self._refresh_caches()
        welfare = self._welfare_cache.get(agent_id, {})
        budget = welfare.get("budget", {})
        util_pct = budget.get("utilization_pct", 0.0)
        if util_pct >= 0.95:
            return (0.0, f"{agent_name} budget exhausted ({util_pct:.0%})")

        # Base score
        score = 1.0

        # Welfare modifiers
        stress = welfare.get("stress", 0.0)
        energy = welfare.get("energy", 0.5)
        score += (1.0 - stress) * 0.3   # low stress → bonus up to 0.3
        score += energy * 0.2            # high energy → bonus up to 0.2
        score -= util_pct * 0.5          # budget usage → penalty up to 0.5

        # Winding down penalty
        if shift == "winding_down":
            score -= 0.3

        # Specialization bonus
        skills = agent_info.get("skills", {})
        if capability in skills:
            proficiency = skills[capability]
            score += proficiency * 0.2  # up to 1.0 bonus for Level 5

        # Department match bonus
        if agent_info.get("department") == department:
            score += 0.2

        # Department AI coordinator bonus
        if agent_info.get("is_department_ai"):
            score += 0.3

        return (max(score, 0.01), None)

    def resolve_department(self, capability: str) -> str:
        """Map a capability to its home department."""
        return CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology")

    def select_agent(
        self,
        capability: str,
        department: str,
    ) -> Optional[Dict]:
        """Select the best agent for a capability within a department.

        Scores all agents in the department, returns the highest-scoring
        available agent. Skips reserved agents.
        """
        self._refresh_caches()

        candidates = []
        for name, info in self._agent_cache.items():
            if info.get("department") != department:
                continue
            score, block_reason = self.score_agent(name, info, capability, department)
            if score > 0 and block_reason is None:
                with self._lock:
                    if info["id"] in self._reserved_agents:
                        continue
                candidates.append((score, name, info))

        if not candidates:
            return None

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_name, best_info = candidates[0]

        logger.info(
            "coordinator: selected %s (score=%.2f) for %s in %s",
            best_name, best_score, capability, department,
        )
        return best_info

    def find_cross_department_agent(
        self,
        capability: str,
        blocked_department: str,
    ) -> Optional[Dict]:
        """Find an agent in another department that has the requested skill."""
        self._refresh_caches()

        all_departments = set(
            info.get("department") for info in self._agent_cache.values()
            if info.get("department")
        )
        skip = {blocked_department, "Executive Office"}

        for dept in sorted(all_departments - skip):
            for name, info in self._agent_cache.items():
                if info.get("department") != dept:
                    continue
                skills = info.get("skills", {})
                if capability not in skills:
                    continue
                score, block_reason = self.score_agent(name, info, capability, dept)
                if score > 0 and block_reason is None:
                    with self._lock:
                        if info["id"] in self._reserved_agents:
                            continue
                    logger.info(
                        "coordinator: cross-dept fallback %s→%s (%s) for %s",
                        blocked_department, dept, name, capability,
                    )
                    return info

        return None
```

- [ ] **Step 5: Run tests**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase2_coordinator.py -v 2>&1 | tail -15
```

Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/department_coordinator.py platform_v2/services/agent_service.py platform_v2/services/tests/test_phase2_coordinator.py
git commit -m "feat(coordinator): add agent scoring, selection, cross-dept fallback

Phase 2: DepartmentCoordinator now has score_agent() with multi-factor
scoring (welfare, budget, specialization, department match), select_agent()
for ranked candidate selection, find_cross_department_agent() fallback,
and resolve_department() capability mapping. agent_service.py gets
get_agent_cache() and get_welfare_cache() for coordinator consumption."
```

---

### Task 4: Expand dispatch_service.py — job lifecycle (create/complete/update)

**Files:**
- Modify: `platform_v2/services/dispatch_service.py`
- Create: `platform_v2/services/tests/test_phase2_dispatch.py`

The dispatcher's `create_job()` is ~400 lines with: advisory locks, duplicate guards, agent assignment, cross-department fallback, station capacity checks, model warm-boot, and governance logging. We extract the core job CRUD into dispatch_service while keeping agent selection in the coordinator.

- [ ] **Step 1: Write failing tests**

Create `platform_v2/services/tests/test_phase2_dispatch.py`:

```python
"""Tests for expanded dispatch_service (Phase 2).

Run: docker exec archie_platform python -m pytest services/tests/test_phase2_dispatch.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from database import get_db_cursor


def _cleanup_test_jobs():
    """Remove test jobs."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM bridge_jobs WHERE module_source = 'test_phase2'")


def test_create_job_returns_id():
    """create_job should return an integer job_id."""
    from services.dispatch_service import get_dispatch_service
    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job_id = svc.create_job(
            job_type="test_job",
            module_source="test_phase2",
            description="Phase 2 test job",
            total_steps=5,
        )
        assert isinstance(job_id, int)
        assert job_id > 0
    finally:
        _cleanup_test_jobs()


def test_create_job_blocks_duplicate():
    """Duplicate job (same type+module, still running) should return None."""
    from services.dispatch_service import get_dispatch_service
    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job1 = svc.create_job("test_dup", "test_phase2", "first", 5)
        job2 = svc.create_job("test_dup", "test_phase2", "second", 5)
        assert job1 is not None
        assert job2 is None
    finally:
        _cleanup_test_jobs()


def test_update_job_progress():
    """update_job_progress should increment completed_steps."""
    from services.dispatch_service import get_dispatch_service
    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job_id = svc.create_job("test_progress", "test_phase2", "progress test", 10)
        svc.update_job_progress(job_id, completed_delta=3)
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT completed_steps FROM bridge_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            assert row["completed_steps"] == 3
    finally:
        _cleanup_test_jobs()


def test_complete_job_auto_status():
    """complete_job with status='auto' should determine from counters."""
    from services.dispatch_service import get_dispatch_service
    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job_id = svc.create_job("test_complete", "test_phase2", "complete test", 5)
        svc.update_job_progress(job_id, completed_delta=5)
        result = svc.complete_job(job_id)
        assert result is True
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM bridge_jobs WHERE id = %s", (job_id,))
            assert cur.fetchone()["status"] == "completed"
    finally:
        _cleanup_test_jobs()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase2_dispatch.py -v 2>&1 | tail -15
```

Expected: FAIL — `AttributeError: 'DispatchService' has no attribute 'create_job'`

- [ ] **Step 3: Add job lifecycle methods to DispatchService**

Add these methods to the `DispatchService` class in `dispatch_service.py`:

```python
    def _get_db(self):
        """Get a database connection."""
        from database import get_db_connection
        return get_db_connection()

    def create_job(
        self,
        job_type: str,
        module_source: str,
        description: str,
        total_steps: int,
        capability: Optional[str] = None,
        metadata: Optional[dict] = None,
        agent_name: Optional[str] = None,
        station_code: Optional[str] = None,
    ) -> Optional[int]:
        """Create a bridge job with duplicate prevention.

        Uses an advisory lock + duplicate check. Returns job_id or None.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            # Advisory lock on type+module to prevent races
            lock_key = hash(f"{job_type}:{module_source}") % (2**31)
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

            # Duplicate guard
            cur.execute(
                """SELECT id FROM bridge_jobs
                   WHERE job_type = %s AND module_source = %s AND status = 'running'
                   ORDER BY created_at DESC LIMIT 1""",
                (job_type, module_source),
            )
            existing = cur.fetchone()
            if existing:
                eid = existing[0] if isinstance(existing, (list, tuple)) else existing["id"]
                conn.rollback()
                logger.info("dispatch_service: duplicate blocked %s/%s (job #%s)", job_type, module_source, eid)
                return None

            import json as _json
            from psycopg2 import Json

            cur.execute(
                """INSERT INTO bridge_jobs
                   (job_type, module_source, description, total_steps,
                    status, agent_name, station_code, metadata, created_at)
                   VALUES (%s, %s, %s, %s, 'running', %s, %s, %s, NOW())
                   RETURNING id""",
                (
                    job_type, module_source, description, total_steps,
                    agent_name, station_code,
                    Json(metadata) if metadata else None,
                ),
            )
            job_id = cur.fetchone()[0]
            conn.commit()
            logger.info("dispatch_service: created job #%s (%s/%s)", job_id, job_type, module_source)
            return job_id

        except Exception as exc:
            logger.error("dispatch_service: create_job failed: %s", exc)
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def update_job_progress(
        self,
        job_id: int,
        completed_delta: int = 0,
        failed_delta: int = 0,
    ) -> bool:
        """Increment job progress counters."""
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """UPDATE bridge_jobs
                   SET completed_steps = COALESCE(completed_steps, 0) + %s,
                       failed_steps = COALESCE(failed_steps, 0) + %s
                   WHERE id = %s""",
                (completed_delta, failed_delta, job_id),
            )
            conn.commit()
            return True
        except Exception as exc:
            logger.error("dispatch_service: update_job_progress failed: %s", exc)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def complete_job(self, job_id: int, status: str = "auto") -> bool:
        """Mark a job as completed/failed/cancelled.

        If status='auto', determines from completed_steps and failed_steps.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            if status == "auto":
                cur.execute(
                    "SELECT completed_steps, failed_steps, total_steps FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row:
                    completed = (row[0] if isinstance(row, (list, tuple)) else row["completed_steps"]) or 0
                    failed = (row[1] if isinstance(row, (list, tuple)) else row["failed_steps"]) or 0
                    if completed == 0 and failed == 0:
                        status = "cancelled"
                    elif completed == 0 and failed > 0:
                        status = "failed"
                    else:
                        status = "completed"
                else:
                    status = "completed"

            cur.execute(
                "UPDATE bridge_jobs SET status = %s, completed_at = NOW() WHERE id = %s",
                (status, job_id),
            )
            conn.commit()
            logger.info("dispatch_service: job #%s → %s", job_id, status)
            return True
        except Exception as exc:
            logger.error("dispatch_service: complete_job failed: %s", exc)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
```

- [ ] **Step 4: Add get_db_connection to database.py if missing**

Check if `get_db_connection()` exists. If not, add a simple wrapper:

```bash
docker exec archie_platform grep -n 'def get_db_connection' database.py
```

If missing, add to `database.py`:

```python
def get_db_connection():
    """Return a raw psycopg2 connection (caller must close)."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=RealDictCursor,
    )
```

- [ ] **Step 5: Run tests**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase2_dispatch.py -v 2>&1 | tail -15
```

Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/dispatch_service.py platform_v2/services/tests/test_phase2_dispatch.py platform_v2/database.py
git commit -m "feat(dispatch-service): add job lifecycle — create, update, complete

Phase 2: DispatchService now has create_job() with advisory locks and
duplicate prevention, update_job_progress() for step tracking, and
complete_job() with auto-status detection. Core job CRUD extracted
from bridge_dispatcher's 400-line create_job method."
```

---

### Task 5: Wire bridge_dispatcher.py to call Department HQ services

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

This is the critical wiring task. The dispatcher keeps its public API but delegates internally to the three services.

- [ ] **Step 1: Add service imports**

Near the top of `bridge_dispatcher.py` (after existing Phase 1 imports at line ~34), add:

```python
# Phase 2: Service delegation
from services.model_service import get_model_service
from services.department_coordinator import get_coordinator
from services.dispatch_service import get_dispatch_service
```

- [ ] **Step 2: Wire ensure_model_ready**

At line ~6901, the dispatcher's `ensure_model_ready()` is called from 2 places (lines 1796, 2553). Add a delegation wrapper at the top of the method:

```python
    def ensure_model_ready(self, agent_name, model, target_host=None):
        """Ensure model is loaded — delegates to ModelService (Phase 2)."""
        svc = get_model_service()
        return svc.ensure_model_ready(agent_name, model, target_host)
```

Keep the old implementation commented or in a `_ensure_model_ready_legacy` method for rollback safety.

- [ ] **Step 3: Wire agent selection in create_job**

In `create_job()` at line ~5267, replace the agent selection block with coordinator calls:

```python
            # Phase 2: Delegate agent selection to coordinator
            coord = get_coordinator()
            cap_key = capability or job_type.split("_")[0]
            dept = coord.resolve_department(cap_key)
            agent = coord.select_agent(cap_key, dept)
            if not agent:
                agent = coord.find_cross_department_agent(cap_key, dept)
```

- [ ] **Step 4: Wire create_job delegation for simple cases**

The dispatcher's `create_job` has 400 lines of logic. We can't replace it all at once. Instead, add a helper that new callers can use directly:

In `bridge_dispatcher.py`, add after the imports:

```python
def create_job_via_service(job_type, module_source, description, total_steps,
                           capability=None, metadata=None):
    """Convenience function for new callers — routes through DispatchService."""
    svc = get_dispatch_service()
    coord = get_coordinator()

    # Resolve agent
    cap_key = capability or job_type.split("_")[0]
    dept = coord.resolve_department(cap_key)
    agent_info = coord.select_agent(cap_key, dept)

    agent_name = None
    if agent_info:
        agent_name = agent_info.get("name")
        # Ensure model is loaded
        model_svc = get_model_service()
        model_svc.ensure_model_ready(agent_name, agent_info.get("model", ""))

    return svc.create_job(
        job_type=job_type,
        module_source=module_source,
        description=description,
        total_steps=total_steps,
        capability=capability,
        metadata=metadata,
        agent_name=agent_name,
        station_code=dept,
    )
```

- [ ] **Step 5: Mark old methods as deprecated**

Add deprecation comments to these dispatcher methods (do NOT delete — backward compatibility):
- `_score_agent` (line 1149)
- `_select_agent_by_department` (line 1332)
- `_select_agent` (line 1501)
- `_find_cross_department_agent` (line 1415)
- `_resolve_department` (line 1315)
- The body of `ensure_model_ready` (line 6901, now a one-liner)

Format:

```python
    def _score_agent(self, ...):
        """DEPRECATED: Use services.department_coordinator.score_agent() instead.
        Kept during Phase 2 migration — will be removed in Phase 5.
        """
        # Original implementation stays for backward compatibility
```

- [ ] **Step 6: Run all Phase 1 + Phase 2 tests**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -30
```

Expected: All tests pass

- [ ] **Step 7: Restart and verify platform health**

```bash
docker compose restart archie_platform
sleep 15
docker logs --since=30s archie_platform 2>&1 | grep -iE 'error|traceback|lifecycle|model.?service|coordinator|dispatch.?service' | tail -20
```

Expected: No errors. Logs show service initialization.

- [ ] **Step 8: Verify consciousness loops still work**

```bash
docker logs --since=60s archie_platform 2>&1 | grep -iE 'embedding|analysis|translate|knowledge.?card' | tail -10
```

Expected: Embedding/analysis/translate processing continues.

- [ ] **Step 9: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "refactor(dispatcher): wire to Department HQ services

Phase 2: ensure_model_ready delegates to ModelService, agent selection
in create_job uses coordinator, create_job_via_service added for new
callers. Old methods marked deprecated. All callers unaffected."
```

---

### Task 6: Verify all existing callers still work

**Files:** Read-only verification, no edits.

External callers of the dispatcher's public API:
- `ai_bridge/agent_loop.py` → `create_job()`, `complete_job()`, `update_job_progress()`
- `ai_bridge/mission_manager.py` → `create_job()`, `complete_job()`
- `ai_bridge/translation_service.py` → `create_job()`, `update_job_progress()`, `complete_job()`
- Consciousness loops → `request_work()`

- [ ] **Step 1: Verify agent_loop creates a job successfully**

```bash
docker exec archie_platform python3 -c "
from bridge_dispatcher import get_dispatcher
d = get_dispatcher()
print('Dispatcher loaded:', type(d).__name__)
print('Has create_job:', hasattr(d, 'create_job'))
print('Has complete_job:', hasattr(d, 'complete_job'))
print('Has ensure_model_ready:', hasattr(d, 'ensure_model_ready'))
print('Has request_work:', hasattr(d, 'request_work'))
"
```

Expected: All `True`

- [ ] **Step 2: Verify model_service singleton works**

```bash
docker exec archie_platform python3 -c "
from services.model_service import get_model_service
svc = get_model_service()
models = svc.check_loaded_models()
print(f'Loaded models: {len(models)}')
for m in models[:5]:
    print(f'  {m[\"name\"]}: {m[\"size_gb\"]:.1f}GB')
print(f'Available RAM: {svc.get_available_ram():.1f}GB')
"
```

- [ ] **Step 3: Verify coordinator singleton works**

```bash
docker exec archie_platform python3 -c "
from services.department_coordinator import get_coordinator
coord = get_coordinator()
status = coord.get_status()
print(f'Reserved agents: {len(status[\"reserved_agents\"])}')
print(f'Loaded models: {len(status[\"loaded_models\"])}')
print(f'Available RAM: {status[\"available_ram_gb\"]:.1f}GB')

# Test scoring
result = coord.select_agent('general', 'Engineering & Technology')
if result:
    print(f'Selected agent: {result[\"display_name\"]} ({result[\"model\"]})')
else:
    print('No agent available (all may be reserved or offline)')
"
```

- [ ] **Step 4: Verify dispatch_service job creation**

```bash
docker exec archie_platform python3 -c "
from services.dispatch_service import get_dispatch_service
svc = get_dispatch_service()
# Create and immediately clean up a test job
job_id = svc.create_job('verification_test', 'phase2_verify', 'Phase 2 verification', 1)
if job_id:
    print(f'Created verification job #{job_id}')
    svc.complete_job(job_id, 'cancelled')
    print('Cleaned up')
else:
    print('Job creation returned None (possible duplicate)')
"
```

- [ ] **Step 5: Check embedding loop still uses dispatcher correctly**

```bash
docker logs --since=120s archie_platform 2>&1 | grep -iE 'embedding|arctic-embed|knowledge.?card|analysis' | tail -10
```

Expected: Active embedding/analysis output, no errors.

- [ ] **Step 6: Run full test suite one last time**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -30
```

Expected: All tests pass (Phase 1 lifecycle + Phase 2 model/coordinator/dispatch).

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Fix 3 broken agent models | DB only | 0 (DB change) |
| 2 | model_service: ensure_model_ready + estimate_model_size | model_service.py + tests | 1 |
| 3 | coordinator: score_agent + select_agent + cross-dept | coordinator.py + agent_service.py + tests | 1 |
| 4 | dispatch_service: create_job + complete_job + update | dispatch_service.py + tests | 1 |
| 5 | Wire dispatcher to call services | bridge_dispatcher.py | 1 |
| 6 | Verify all callers work | Read-only verification | 0 |

**Total: 4 commits, 3 new test files, 5 modified files, 3 DB fixes**

After Phase 2:
- `model_service.py` handles all model lifecycle (load, unload, ensure ready, estimate size, eviction)
- `department_coordinator.py` handles all agent selection (scoring, department routing, cross-dept fallback)
- `dispatch_service.py` handles all job CRUD (create, update, complete, duplicate prevention)
- `bridge_dispatcher.py` delegates to services — still works for all existing callers
- 3 broken agent models fixed (Maven, Sage, W.A.T.C.H.)
