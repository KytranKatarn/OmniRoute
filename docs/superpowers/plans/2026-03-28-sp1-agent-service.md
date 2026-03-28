# SP1: Agent Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a single authoritative agent service that owns ALL agent operations — CRUD, lifecycle, skills, welfare, model management, dispatch support, node deployment. No other file writes directly to agent tables.

**Architecture:** Three focused service files in platform_v2/services/. Build the service first, then incrementally refactor each consumer (Bridge, agent loop, Department HQ, Starbase, orchestration engine) to call the service instead of raw SQL. Each refactored consumer is independently deployable.

**Tech Stack:** Python, PostgreSQL, psycopg2 (via database.get_db_cursor), Flask, Ollama API

---

## File Structure

```
platform_v2/services/
├── agent_service.py      — Core CRUD, lifecycle, skills, welfare, performance (NEW)
├── agent_models.py       — Model management: load/unload/warmboot/VRAM state (NEW)
├── agent_dispatch.py     — Candidate selection, scoring, escalation support (NEW)
├── work_tracking_service.py  — Already exists (work sessions, dept metrics)
├── audit_pipeline.py         — Already exists (repair pipeline)
└── ...
```

## Consumers to refactor (in order)
1. Department HQ roster_routes.py — easiest, already thin
2. Starbase agent_routes.py — already redirected, just wire to service
3. Agent loop (welfare, training, shifts) — medium complexity
4. Bridge dispatcher (biggest — agent selection, shift transitions, model loading)
5. Orchestration engine (agent creation, department changes)
6. MCP tools (list_agents, assign_agent)

---

### Task 1: Create agent_service.py — Core CRUD + Lifecycle

**Files:**
- Create: `platform_v2/services/agent_service.py`

- [ ] **Step 1: Create agent_service.py with CRUD functions**

```python
"""Agent Service — THE single authority for all agent operations.

No other file should INSERT/UPDATE/DELETE on agents, agent_skills,
agent_emotional_state, agent_identity, or node_agents directly.
All mutations go through this service.

Import:
    from services.agent_service import (
        get_agent, list_agents, create_agent, update_agent, delete_agent,
        activate, barracks, deploy_to_node, return_from_node,
        get_org_chart, get_department_summary,
    )
"""

import json
import logging
import os
from database import get_db_cursor

logger = logging.getLogger(__name__)

DEPARTMENT_FLOOR_MAP = {
    "Executive Office": "BRIDGE",
    "Operations & Infrastructure": "OPERATIONS",
    "Logistics & Supply Chain": "OPERATIONS",
    "Finance & Accounting": "OPERATIONS",
    "Engineering & Technology": "ENGINEERING",
    "Security & Compliance": "ENGINEERING",
    "Research & Development": "ENGINEERING",
    "Creative & Design": "CREATIVE",
    "Marketing & Communications": "CREATIVE",
    "Documentation & Knowledge": "CREATIVE",
    "Customer Success & Support": "SERVICES",
    "Human Resources & Culture": "SERVICES",
    "Medical & Wellness": "SERVICES",
    "Legal & Regulatory": "SERVICES",
    "Diplomatic & External Relations": "SERVICES",
    "Analytics & Intelligence": "SERVICES",
}

VALID_SHIFT_STATES = ("active", "deployed", "barracked", "off_duty", "winding_down", "cooldown")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def get_agent(agent_id):
    """Get full agent profile by ID. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT a.*,
                      aes.stress_level, aes.energy_level, aes.mood, aes.mood_intensity
               FROM agents a
               LEFT JOIN agent_emotional_state aes ON aes.agent_id = a.id
               WHERE a.id = %s""",
            (agent_id,),
        )
        return dict(cur.fetchone()) if cur.rowcount else None


def get_agent_by_name(name):
    """Get agent by code name. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM agents WHERE name = %s", (name,))
        return dict(cur.fetchone()) if cur.rowcount else None


def list_agents(department=None, floor=None, shift_state=None, skill=None,
                search=None, is_department_ai=None, limit=200):
    """List agents with optional filters. Returns list of dicts."""
    conditions = []
    params = []

    if department:
        conditions.append("a.department = %s")
        params.append(department)
    if floor:
        conditions.append("a.floor = %s")
        params.append(floor)
    if shift_state:
        conditions.append("a.shift_state = %s")
        params.append(shift_state)
    if is_department_ai is not None:
        conditions.append("a.is_department_ai = %s")
        params.append(is_department_ai)
    if search:
        conditions.append("(a.name ILIKE %s OR a.display_name ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""SELECT a.id, a.name, a.display_name, a.department, a.floor,
                       a.model, a.status, a.shift_state, a.is_department_ai,
                       a.temperature, a.max_tokens, a.system_prompt,
                       a.capabilities, a.metadata
                FROM agents a {where}
                ORDER BY a.floor, a.department, a.is_department_ai DESC, a.name
                LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def create_agent(name, display_name, department, model, **kwargs):
    """Create a new agent. Returns agent_id.

    Required: name, display_name, department, model
    Optional kwargs: system_prompt, temperature, max_tokens, capabilities,
                     is_department_ai, shift_state, tier, worker_type
    """
    floor = DEPARTMENT_FLOOR_MAP.get(department, "SERVICES")
    shift_state = kwargs.get("shift_state", "barracked")

    if department not in DEPARTMENT_FLOOR_MAP:
        raise ValueError(f"Invalid department: {department}")
    if shift_state not in VALID_SHIFT_STATES:
        raise ValueError(f"Invalid shift_state: {shift_state}")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agents
               (name, display_name, department, floor, model, shift_state,
                system_prompt, temperature, max_tokens, capabilities,
                is_department_ai, tier, worker_type, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
               RETURNING id""",
            (
                name, display_name, department, floor, model, shift_state,
                kwargs.get("system_prompt", ""),
                kwargs.get("temperature", 0.7),
                kwargs.get("max_tokens", 2048),
                json.dumps(kwargs.get("capabilities", {})),
                kwargs.get("is_department_ai", False),
                kwargs.get("tier", 3),
                kwargs.get("worker_type", "internal"),
            ),
        )
        agent_id = cur.fetchone()["id"]

        # Create initial emotional state
        cur.execute(
            """INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level, mood, mood_intensity)
               VALUES (%s, 0.1, 0.9, 'neutral', 0.5)""",
            (agent_id,),
        )

    logger.info("Created agent #%d: %s (%s) in %s", agent_id, name, display_name, department)
    return agent_id


def update_agent(agent_id, **fields):
    """Update agent fields. Auto-derives floor if department changes.

    Returns True on success, False if agent not found.
    """
    if not fields:
        return True

    # Auto-derive floor when department changes
    if "department" in fields:
        dept = fields["department"]
        if dept not in DEPARTMENT_FLOOR_MAP:
            raise ValueError(f"Invalid department: {dept}")
        fields["floor"] = DEPARTMENT_FLOOR_MAP[dept]

    if "shift_state" in fields and fields["shift_state"] not in VALID_SHIFT_STATES:
        raise ValueError(f"Invalid shift_state: {fields['shift_state']}")

    # Build dynamic UPDATE
    set_clauses = []
    params = []
    for key, val in fields.items():
        if key in ("capabilities", "metadata") and isinstance(val, dict):
            set_clauses.append(f"{key} = %s::jsonb")
            params.append(json.dumps(val))
        else:
            set_clauses.append(f"{key} = %s")
            params.append(val)

    set_clauses.append("updated_at = NOW()")
    params.append(agent_id)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = %s RETURNING id",
            params,
        )
        updated = cur.fetchone() is not None

    if updated:
        logger.info("Updated agent #%d: %s", agent_id, list(fields.keys()))
    return updated


def delete_agent(agent_id, hard=False):
    """Delete agent. Soft-delete by default (status=inactive, shift_state=off_duty)."""
    if hard:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
        logger.warning("Hard-deleted agent #%d", agent_id)
    else:
        update_agent(agent_id, status="inactive", shift_state="off_duty")
        logger.info("Soft-deleted agent #%d", agent_id)


# ---------------------------------------------------------------------------
# Shift Lifecycle
# ---------------------------------------------------------------------------

def activate(agent_id):
    """Set agent to active duty."""
    return update_agent(agent_id, shift_state="active")


def barracks(agent_id):
    """Return agent to barracks (reserve)."""
    return update_agent(agent_id, shift_state="barracked")


def wind_down(agent_id):
    """Begin wind-down cycle."""
    return update_agent(agent_id, shift_state="winding_down")


def cooldown(agent_id):
    """Put agent in cooldown."""
    return update_agent(agent_id, shift_state="cooldown")


def deploy_to_node(agent_id, node_id):
    """Deploy agent to a remote node."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Get agent info
        cur.execute("SELECT name, department, model FROM agents WHERE id = %s", (agent_id,))
        agent = cur.fetchone()
        if not agent:
            return False

        # Update shift state
        cur.execute(
            "UPDATE agents SET shift_state = 'deployed' WHERE id = %s",
            (agent_id,),
        )

        # Create or reactivate node_agent
        cur.execute(
            """INSERT INTO node_agents (hub_agent_id, node_id, name, department, model, status)
               VALUES (%s, %s, %s, %s, %s, 'active')
               ON CONFLICT (hub_agent_id, node_id)
               DO UPDATE SET status = 'active', department = EXCLUDED.department""",
            (agent_id, node_id, agent["name"], agent["department"], agent["model"]),
        )

    logger.info("Deployed agent #%d to node #%d", agent_id, node_id)
    return True


def return_from_node(agent_id):
    """Return agent from node to barracks."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE agents SET shift_state = 'barracked' WHERE id = %s AND shift_state = 'deployed'",
            (agent_id,),
        )
        cur.execute(
            "UPDATE node_agents SET status = 'inactive' WHERE hub_agent_id = %s AND status = 'active'",
            (agent_id,),
        )
    logger.info("Returned agent #%d from node to barracks", agent_id)
    return True


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def get_skills(agent_id):
    """Get agent's skills with levels. Returns list of dicts."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT skill_name, category, level FROM agent_skills WHERE agent_id = %s ORDER BY level DESC",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def add_skill(agent_id, skill_name, level=1, category="general"):
    """Add or update a skill for an agent."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_skills (agent_id, skill_name, level, category)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_id, skill_name) DO UPDATE SET level = EXCLUDED.level""",
            (agent_id, skill_name, level, category),
        )
    logger.info("Agent #%d skill %s set to level %d", agent_id, skill_name, level)


def update_skill_from_benchmark(agent_id, skill_name, score):
    """Update skill level from benchmark score (0.0-1.0). Auto-levels 1-5."""
    level = max(1, min(5, int(score * 5) + 1))
    add_skill(agent_id, skill_name, level=level, category="benchmarked")


def match_capability(capability):
    """Find agents who have a matching skill, ranked by level. Returns list of (agent_id, level)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.model,
                      a.shift_state, s.level
               FROM agent_skills s
               JOIN agents a ON a.id = s.agent_id
               WHERE s.skill_name = %s AND a.status = 'active'
               ORDER BY s.level DESC, a.is_department_ai DESC""",
            (capability,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Welfare
# ---------------------------------------------------------------------------

def get_welfare(agent_id):
    """Get agent's current emotional state. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT stress_level, energy_level, mood, mood_intensity
               FROM agent_emotional_state WHERE agent_id = %s
               ORDER BY id DESC LIMIT 1""",
            (agent_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_welfare(agent_id, stress=None, energy=None, mood=None, mood_intensity=None):
    """Update agent welfare metrics."""
    updates = {}
    if stress is not None:
        updates["stress_level"] = max(0.0, min(1.0, stress))
    if energy is not None:
        updates["energy_level"] = max(0.0, min(1.0, energy))
    if mood is not None:
        updates["mood"] = mood
    if mood_intensity is not None:
        updates["mood_intensity"] = max(0.0, min(1.0, mood_intensity))

    if not updates:
        return

    set_clauses = [f"{k} = %s" for k in updates]
    params = list(updates.values()) + [agent_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE agent_emotional_state SET {', '.join(set_clauses)} WHERE agent_id = %s",
            params,
        )


def check_welfare_threshold(agent_id):
    """Check if agent is healthy enough to work. Returns (ok: bool, reason: str)."""
    welfare = get_welfare(agent_id)
    if not welfare:
        return True, "no welfare data"

    stress = float(welfare.get("stress_level", 0))
    energy = float(welfare.get("energy_level", 1))

    if stress >= 0.8:
        return False, f"stress too high ({stress:.2f})"
    if energy <= 0.2:
        return False, f"energy too low ({energy:.2f})"
    return True, "healthy"


def recover_idle(agent_id, energy_boost=0.2, stress_reduction=0.15):
    """Recover an idle agent's welfare."""
    welfare = get_welfare(agent_id)
    if not welfare:
        return

    new_energy = min(1.0, float(welfare.get("energy_level", 0.5)) + energy_boost)
    new_stress = max(0.0, float(welfare.get("stress_level", 0.5)) - stress_reduction)
    update_welfare(agent_id, stress=new_stress, energy=new_energy)


# ---------------------------------------------------------------------------
# Org Chart & Department Summary
# ---------------------------------------------------------------------------

def get_org_chart():
    """Get full org chart: floors -> departments -> agents."""
    agents = list_agents(limit=500)
    floors = {}

    for agent in agents:
        floor = agent["floor"]
        dept = agent["department"]
        if floor not in floors:
            floors[floor] = {}
        if dept not in floors[floor]:
            floors[floor][dept] = {"director": None, "staff": []}

        if agent.get("is_department_ai"):
            floors[floor][dept]["director"] = agent
        else:
            floors[floor][dept]["staff"].append(agent)

    return floors


def get_department_summary():
    """Get per-department agent counts and health."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT department, floor,
                      COUNT(*) as total,
                      COUNT(*) FILTER (WHERE shift_state = 'active') as active,
                      COUNT(*) FILTER (WHERE shift_state = 'deployed') as deployed,
                      COUNT(*) FILTER (WHERE shift_state = 'barracked') as barracked,
                      COUNT(*) FILTER (WHERE is_department_ai = true) as directors
               FROM agents
               WHERE status = 'active'
               GROUP BY department, floor
               ORDER BY floor, department"""
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def get_performance(agent_id, period_days=7):
    """Get agent performance metrics for a period."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT COUNT(*) FILTER (WHERE status = 'completed') as jobs_completed,
                      COUNT(*) FILTER (WHERE status = 'failed') as jobs_failed,
                      AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_seconds
               FROM bridge_jobs
               WHERE agent_name = (SELECT name FROM agents WHERE id = %s)
                 AND created_at > NOW() - INTERVAL '%s days'""",
            (agent_id, period_days),
        )
        row = cur.fetchone()
        if not row:
            return {"jobs_completed": 0, "jobs_failed": 0, "avg_response_ms": 0, "success_rate": 0}

        completed = row["jobs_completed"] or 0
        failed = row["jobs_failed"] or 0
        total = completed + failed
        return {
            "jobs_completed": completed,
            "jobs_failed": failed,
            "avg_response_ms": int((row["avg_seconds"] or 0) * 1000),
            "success_rate": round(completed / total * 100, 1) if total > 0 else 100,
        }


# ---------------------------------------------------------------------------
# Hardware-Aware Recommendations
# ---------------------------------------------------------------------------

def get_agents_for_hardware(gpu_vram_gb, ram_gb):
    """Return agents whose models fit the given hardware, ranked by benchmark score."""
    # Rough model size estimates (can be refined with actual data)
    agents = list_agents(shift_state="active")
    compatible = []

    for agent in agents:
        model = agent.get("model", "")
        # Estimate VRAM need from model name
        if "1.5b" in model or "3b" in model:
            vram_need = 2.0
        elif "7b" in model:
            vram_need = 5.0
        elif "12b" in model or "14b" in model:
            vram_need = 10.0
        elif "16b" in model:
            vram_need = 12.0
        elif ":cloud" in model:
            vram_need = 0  # cloud models don't need local VRAM
        else:
            vram_need = 5.0  # default estimate

        if vram_need <= gpu_vram_gb or vram_need <= ram_gb * 0.8:
            agent["estimated_vram_gb"] = vram_need
            compatible.append(agent)

    return sorted(compatible, key=lambda a: a.get("is_department_ai", False), reverse=True)


def recommend_node_deployment(node_id):
    """Recommend agents for a specific node based on its hardware."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT gpu_vram_gb, ram_gb, gpu_model FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        node = cur.fetchone()

    if not node:
        return []

    return get_agents_for_hardware(
        gpu_vram_gb=float(node.get("gpu_vram_gb") or 0),
        ram_gb=float(node.get("ram_gb") or 0),
    )
```

- [ ] **Step 2: Verify file parses**

```bash
python3 -c "import ast; ast.parse(open('platform_v2/services/agent_service.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/agent_service.py
git commit -m "feat(agents): create centralized agent_service.py — CRUD, lifecycle, skills, welfare, performance"
```

---

### Task 2: Create agent_models.py — Model Management

**Files:**
- Create: `platform_v2/services/agent_models.py`

- [ ] **Step 1: Create agent_models.py**

```python
"""Agent Model Service — model loading, unloading, warmboot, VRAM state tracking.

Owns the relationship between agents and their Ollama models.
Bridge dispatcher calls these instead of managing models directly.

Import:
    from services.agent_models import (
        get_model_state, load_model, unload_model, warmboot,
        get_loaded_models, check_vram_budget,
    )
"""

import json
import logging
import urllib.request
from database import get_db_cursor

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://192.168.1.200:11434"


def get_model_state(agent_id):
    """Get the load state of an agent's model. Returns dict with tier (gpu/cpu/cold), model name."""
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent:
        return {"ready": False, "tier": "unknown", "model": None}

    model_name = agent.get("model", "")
    if not model_name:
        return {"ready": False, "tier": "no_model", "model": None}

    # Check if model is loaded in Ollama
    loaded = get_loaded_models()
    for m in loaded:
        if m["name"] == model_name or m["name"].startswith(model_name.split(":")[0]):
            return {
                "ready": True,
                "tier": "gpu" if m.get("size_vram", 0) > 0 else "cpu",
                "model": model_name,
                "size_vram": m.get("size_vram", 0),
                "size": m.get("size", 0),
            }

    return {"ready": False, "tier": "cold", "model": model_name}


def get_loaded_models(ollama_url=None):
    """Get currently loaded models from Ollama. Returns list of model dicts."""
    url = (ollama_url or OLLAMA_URL) + "/api/ps"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("models", [])
    except Exception as e:
        logger.warning("Failed to get loaded models: %s", e)
        return []


def load_model(agent_id, ollama_url=None):
    """Load an agent's model into Ollama. Returns True on success."""
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent or not agent.get("model"):
        return False

    model_name = agent["model"]
    if ":cloud" in model_name:
        return True  # Cloud models don't need local loading

    url = (ollama_url or OLLAMA_URL) + "/api/generate"
    try:
        payload = json.dumps({"model": model_name, "prompt": "", "keep_alive": "24h"}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
        logger.info("Loaded model %s for agent #%d", model_name, agent_id)
        return True
    except Exception as e:
        logger.warning("Failed to load model %s for agent #%d: %s", model_name, agent_id, e)
        return False


def unload_model(agent_id, ollama_url=None):
    """Unload an agent's model from Ollama. Returns True on success."""
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent or not agent.get("model"):
        return False

    model_name = agent["model"]
    url = (ollama_url or OLLAMA_URL) + "/api/generate"
    try:
        payload = json.dumps({"model": model_name, "keep_alive": 0}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        logger.info("Unloaded model %s for agent #%d", model_name, agent_id)
        return True
    except Exception as e:
        logger.warning("Failed to unload model %s: %s", model_name, e)
        return False


def warmboot(agent_id, ollama_url=None):
    """Ensure an agent's model is ready for dispatch. Load if cold."""
    state = get_model_state(agent_id)
    if state.get("ready"):
        return True
    return load_model(agent_id, ollama_url=ollama_url)


def check_vram_budget(ollama_url=None):
    """Check current VRAM usage across all loaded models. Returns dict."""
    loaded = get_loaded_models(ollama_url)
    total_vram = sum(m.get("size_vram", 0) for m in loaded)
    total_ram = sum(m.get("size", 0) for m in loaded)
    return {
        "models_loaded": len(loaded),
        "total_vram_bytes": total_vram,
        "total_vram_gb": round(total_vram / (1024**3), 2),
        "total_ram_bytes": total_ram,
        "total_ram_gb": round(total_ram / (1024**3), 2),
        "models": [{"name": m["name"], "vram_gb": round(m.get("size_vram", 0) / (1024**3), 2)} for m in loaded],
    }
```

- [ ] **Step 2: Verify and commit**

```bash
python3 -c "import ast; ast.parse(open('platform_v2/services/agent_models.py').read()); print('OK')"
git add platform_v2/services/agent_models.py
git commit -m "feat(agents): create agent_models.py — model load/unload/warmboot/VRAM tracking"
```

---

### Task 3: Create agent_dispatch.py — Dispatch Support

**Files:**
- Create: `platform_v2/services/agent_dispatch.py`

- [ ] **Step 1: Create agent_dispatch.py**

```python
"""Agent Dispatch Service — candidate selection, scoring, escalation support.

Bridge dispatcher calls these to find the best agent for a task.
Selection logic is centralized here instead of scattered through the dispatcher.

Import:
    from services.agent_dispatch import (
        get_candidates, score_agent, get_best_agent, get_fleet_roster,
    )
"""

import logging
from database import get_db_cursor
from services.agent_service import (
    list_agents, get_skills, get_welfare, check_welfare_threshold,
    DEPARTMENT_FLOOR_MAP,
)

logger = logging.getLogger(__name__)

# Scoring weights (from bridge_dispatcher SELECTION_WEIGHTS)
WEIGHTS = {
    "skills": 0.30,
    "specialization": 0.25,
    "welfare": 0.15,
    "availability": 0.15,
    "budget": 0.05,
    "tier_match": 0.10,
}

FLOOR_DEPARTMENTS = {}
for _dept, _flr in DEPARTMENT_FLOOR_MAP.items():
    FLOOR_DEPARTMENTS.setdefault(_flr, []).append(_dept)


def score_agent(agent, capability):
    """Score an agent for a capability. Returns float 0.0-1.0."""
    score = 0.0
    agent_id = agent.get("id")

    # Skills score (0.30 weight)
    skills = get_skills(agent_id)
    skill_match = next((s for s in skills if s["skill_name"] == capability), None)
    skill_score = (skill_match["level"] / 5.0) if skill_match else 0.3
    score += skill_score * WEIGHTS["skills"]

    # Welfare score (0.15 weight)
    welfare = get_welfare(agent_id)
    if welfare:
        stress = float(welfare.get("stress_level", 0))
        energy = float(welfare.get("energy_level", 1))
        welfare_score = (1.0 - stress) * energy
    else:
        welfare_score = 0.7
    score += welfare_score * WEIGHTS["welfare"]

    # Availability (0.15 weight) — active agents score higher
    shift = agent.get("shift_state", "barracked")
    avail_score = 1.0 if shift == "active" else 0.5 if shift == "deployed" else 0.0
    score += avail_score * WEIGHTS["availability"]

    # Director bonus (0.25 weight for specialization)
    is_director = agent.get("is_department_ai", False)
    spec_score = 0.8 if is_director else 0.5
    score += spec_score * WEIGHTS["specialization"]

    # Budget (0.05 weight) — placeholder
    score += 0.8 * WEIGHTS["budget"]

    # Tier match (0.10 weight) — placeholder
    score += 0.5 * WEIGHTS["tier_match"]

    return round(score, 4)


def get_candidates(capability, department, include_cross_department=False):
    """Get scored candidate agents for a capability+department.

    Returns list of (agent_dict, score) sorted by score descending.
    """
    # Primary: agents in the target department
    agents = list_agents(department=department, shift_state="active")

    # Cross-department: same floor first, then all floors
    if include_cross_department and not agents:
        floor = DEPARTMENT_FLOOR_MAP.get(department)
        if floor:
            for sibling in FLOOR_DEPARTMENTS.get(floor, []):
                if sibling != department:
                    agents.extend(list_agents(department=sibling, shift_state="active"))
        if not agents:
            # All departments
            agents = list_agents(shift_state="active")

    # Filter out welfare-blocked agents
    healthy = []
    for agent in agents:
        ok, reason = check_welfare_threshold(agent["id"])
        if ok:
            healthy.append(agent)

    # Score and rank
    scored = [(agent, score_agent(agent, capability)) for agent in healthy]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def get_best_agent(capability, department):
    """Get the single best agent for a capability. Returns (agent_dict, score) or (None, 0)."""
    candidates = get_candidates(capability, department, include_cross_department=True)
    if candidates:
        return candidates[0]
    return None, 0.0


def get_fleet_roster():
    """Get full fleet view: hub agents + node-deployed agents."""
    with get_db_cursor() as (conn, cur):
        # Hub agents
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.floor,
                      a.model, a.shift_state, a.is_department_ai
               FROM agents a
               WHERE a.status = 'active' AND a.shift_state != 'deployed'
               ORDER BY a.floor, a.department"""
        )
        hub_agents = [dict(r) for r in cur.fetchall()]

        # Node-deployed agents
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.floor,
                      a.model, a.shift_state, na.node_id,
                      rn.node_name, rn.hostname
               FROM agents a
               JOIN node_agents na ON na.hub_agent_id = a.id AND na.status = 'active'
               JOIN remote_nodes rn ON rn.id = na.node_id
               WHERE a.shift_state = 'deployed'
               ORDER BY rn.node_name, a.department"""
        )
        node_agents = [dict(r) for r in cur.fetchall()]

    return {"hub": hub_agents, "nodes": node_agents}
```

- [ ] **Step 2: Verify and commit**

```bash
python3 -c "import ast; ast.parse(open('platform_v2/services/agent_dispatch.py').read()); print('OK')"
git add platform_v2/services/agent_dispatch.py
git commit -m "feat(agents): create agent_dispatch.py — candidate selection, scoring, fleet roster"
```

---

### Task 4: Refactor Department HQ to use agent_service

**Files:**
- Modify: `platform_v2/tools/department_hq/roster_routes.py`
- Modify: `platform_v2/tools/department_hq/routes.py`

- [ ] **Step 1: Update roster_routes.py to import from agent_service**

Replace raw SQL queries with agent_service calls:
- `GET /api/roster` → `agent_service.list_agents(filters)`
- `POST /api/roster/assign` → `agent_service.update_agent(agent_id, department=dept)`
- `POST /api/roster/shift` → `agent_service.update_agent(agent_id, shift_state=state)`

- [ ] **Step 2: Update routes.py overview/org-chart to use agent_service**

- `GET /api/overview` → `agent_service.get_department_summary()`
- `GET /api/org-chart` → `agent_service.get_org_chart()`

- [ ] **Step 3: Verify and commit**

```bash
docker compose restart archie_platform
git commit -m "refactor(dept-hq): use agent_service for roster and org chart"
```

---

### Task 5: Refactor Starbase to use agent_service

**Files:**
- Modify: `platform_v2/tools/starbase/agent_routes.py`
- Modify: `platform_v2/tools/starbase/crew_routes.py`

- [ ] **Step 1: Update agent_routes.py redirects to call agent_service where needed**

Most are already redirects. Any remaining agent queries should go through agent_service.

- [ ] **Step 2: Update crew_routes.py model management to use agent_models**

- Model load/unload → `agent_models.load_model()`, `agent_models.unload_model()`
- VRAM check → `agent_models.check_vram_budget()`
- Crew manifest → `agent_dispatch.get_fleet_roster()`

- [ ] **Step 3: Verify and commit**

```bash
docker compose restart archie_platform
git commit -m "refactor(starbase): use agent_service + agent_models for crew and model management"
```

---

### Task 6: Refactor agent_loop.py to use agent_service

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Replace welfare direct SQL with agent_service calls**

- `_recover_idle_welfare()` → use `agent_service.recover_idle()`
- `_process_training_tick()` → use `agent_service.get_skills()`, `agent_service.add_skill()`
- Shift management → use `agent_service.activate()`, `agent_service.barracks()`, etc.

- [ ] **Step 2: Replace agent queries with agent_service**

Find all `SELECT ... FROM agents` in agent_loop.py and replace with agent_service calls where the query is doing management (not just logging/reporting).

- [ ] **Step 3: Verify and commit**

```bash
python3 -c "import ast; ast.parse(open('ai_bridge/agent_loop.py').read()); print('OK')"
docker compose restart archie_platform
git commit -m "refactor(agent-loop): use agent_service for welfare, skills, shifts"
```

---

### Task 7: Wire Bridge dispatcher to agent_dispatch

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

- [ ] **Step 1: Import agent_dispatch in Bridge**

Add at relevant locations:
```python
from services.agent_dispatch import get_best_agent, get_candidates, score_agent
from services.agent_models import warmboot, get_model_state
```

- [ ] **Step 2: Replace _select_agent internals**

Bridge's `_select_agent` and `_select_agent_by_department` should delegate scoring to `agent_dispatch.get_candidates()`. Keep Bridge's method as the entry point but the scoring logic lives in agent_dispatch.

- [ ] **Step 3: Replace model management**

Bridge's `ensure_model_ready` should delegate to `agent_models.warmboot()`.

- [ ] **Step 4: Verify and commit**

```bash
docker compose restart archie_platform
# Test dispatch works
git commit -m "refactor(dispatch): delegate agent selection to agent_dispatch, model loading to agent_models"
```

---

### Task 8: Deprecate agent_management_api.py + add Code Health check

**Files:**
- Modify: `ai_bridge/agent_management_api.py`
- Modify: `platform_v2/services/code_metrics_service.py`

- [ ] **Step 1: Deprecate agent_management_api.py**

Add deprecation notice and redirect functions to agent_service:
```python
"""DEPRECATED: Use services.agent_service instead.
This file is kept for backward compatibility. All functions delegate to agent_service.
"""
from services.agent_service import create_agent, update_agent, delete_agent, get_agent, list_agents
```

- [ ] **Step 2: Add Code Health check for direct agent table writes**

In `audit_single_module`, add a new check that flags direct INSERT/UPDATE/DELETE on agent tables outside of agent_service.py:

```python
# Check 9: Direct agent table mutations (should go through agent_service)
if "agent_service" not in fname:
    agent_tables = ["INSERT INTO agents", "UPDATE agents SET", "DELETE FROM agents",
                     "INSERT INTO agent_skills", "UPDATE agent_emotional_state"]
    for pattern in agent_tables:
        if pattern in content:
            _add_issue("DIRECT_AGENT_WRITE", fname, f"found '{pattern}' — use agent_service")
```

- [ ] **Step 3: Verify and commit**

```bash
git commit -m "refactor(agents): deprecate agent_management_api, add direct-write audit check"
```

---

### Task 9: Verify full system + deploy

- [ ] **Step 1: Restart platform and check for errors**

```bash
docker compose restart archie_platform
sleep 10
docker logs archie_platform --since 8s 2>&1 | grep -i error | head -10
```

- [ ] **Step 2: Test agent_service functions**

```python
from services.agent_service import list_agents, get_org_chart, get_department_summary
from services.agent_dispatch import get_best_agent
from services.agent_models import check_vram_budget

agents = list_agents(department="Engineering & Technology")
chart = get_org_chart()
summary = get_department_summary()
best, score = get_best_agent("code_review", "Engineering & Technology")
vram = check_vram_budget()
```

- [ ] **Step 3: Log decision and complete task**

```python
mcp__archie__log_decision(title="SP1 Complete — Centralized Agent Service")
mcp__archie__complete_task(task_id=1264)
```
