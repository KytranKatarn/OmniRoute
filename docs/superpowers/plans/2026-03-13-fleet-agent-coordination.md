# Fleet Agent Coordination System — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build fleet-wide agent coordination where Bridge is the single source of truth, LLMs are unique per agent, and tasks flow through local triage -> Bridge dispatch -> tiered escalation.

**Architecture:** Smart Relay — nodes do lightweight triage (can I handle this?), Bridge does full fleet-wide scoring on escalation. Mesh sync (existing hub-push + node-poll) carries job requests and results. Station commands provide structured task triggers alongside natural language.

**Tech Stack:** Python/Flask, PostgreSQL, APScheduler, Ollama API, existing mesh_sync_log infrastructure

**Spec:** `docs/superpowers/specs/2026-03-13-fleet-agent-coordination-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `database/migrations/148_fleet_coordination.sql` | Create | Schema cleanup + station_commands table |
| `ai_bridge/fleet_triage.py` | Create | Triage logic — shared between hub and nodes |
| `ai_bridge/bridge_dispatcher.py` | Modify | Fleet-wide agent cache + scoring extension |
| `platform_v2/tools/bridge/mesh_routes.py` | Modify | Add broadcast endpoint + job result processing |
| `platform_v2/tools/bridge/routes.py` | Modify | Heartbeat handler — accept completed_jobs + welfare data |
| `platform_v2/tools/starship/routes.py` | Modify | Station commands CRUD + recommendation hardening |
| `node_client/node_sync.py` | Modify | Job request handler + result reporting in heartbeat |
| `node_client/node_api.py` | Modify | Job execution endpoint |
| `node_client/node_triage.py` | Create | Local triage — imports fleet_triage, checks Ollama |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Modify | Station command UI + job tracker |

---

## Task 1: Database Migration — Cleanup + Schema

**Files:**
- Create: `database/migrations/148_fleet_coordination.sql`

- [ ] **Step 1: Audit current data before migration**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT count(*) AS orphans FROM node_agents WHERE source_agent_id IS NULL;
  SELECT a.name, a.primary_model FROM agents a WHERE a.status = 'active' AND a.primary_model IS NOT NULL
    GROUP BY a.name, a.primary_model HAVING count(*) > 0 ORDER BY a.primary_model;
"
```

Check for: orphan count, any duplicate primary_models among active agents that need resolving before adding unique index.

- [ ] **Step 2: Write migration SQL**

Create `database/migrations/148_fleet_coordination.sql`:

```sql
-- Fleet Agent Coordination System
-- Spec: docs/superpowers/specs/2026-03-13-fleet-agent-coordination-design.md

BEGIN;

-- 1. Clean orphan node agents (any without Bridge parent)
DELETE FROM node_agents WHERE source_agent_id IS NULL;

-- 2. Enforce source_agent_id NOT NULL + ON DELETE RESTRICT
ALTER TABLE node_agents ALTER COLUMN source_agent_id SET NOT NULL;
ALTER TABLE node_agents DROP CONSTRAINT IF EXISTS node_agents_source_agent_id_fkey;
ALTER TABLE node_agents ADD CONSTRAINT node_agents_source_agent_id_fkey
    FOREIGN KEY (source_agent_id) REFERENCES agents(id) ON DELETE RESTRICT;

-- 3. Deprecate hub_agent_id — copy any non-null values to source_agent_id where source is null
UPDATE node_agents SET source_agent_id = hub_agent_id
    WHERE source_agent_id IS NULL AND hub_agent_id IS NOT NULL;

-- 4. Fleet-wide LLM uniqueness (active agents only)
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_unique_model_active
    ON agents (primary_model) WHERE status = 'active' AND primary_model IS NOT NULL;

-- 5. Station commands table
CREATE TABLE IF NOT EXISTS station_commands (
    id SERIAL PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES bridge_stations(id) ON DELETE CASCADE,
    command_name VARCHAR(100) NOT NULL,
    capability VARCHAR(100) NOT NULL,
    description TEXT,
    parameters_schema JSONB,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(station_id, command_name)
);

-- 6. Indexes for fleet dispatch
CREATE INDEX IF NOT EXISTS idx_node_agents_source ON node_agents(source_agent_id);
CREATE INDEX IF NOT EXISTS idx_node_agents_station ON node_agents USING GIN(station_codes);

COMMIT;
```

- [ ] **Step 3: Run migration**

```bash
docker cp database/migrations/148_fleet_coordination.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/148_fleet_coordination.sql
```

Expected: no errors. If duplicate primary_model found, resolve manually first (deactivate or reassign duplicate agents).

- [ ] **Step 4: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT count(*) AS orphans FROM node_agents WHERE source_agent_id IS NULL;
  \d station_commands;
  \di idx_agents_unique_model_active;
"
```

Expected: 0 orphans, station_commands table exists, unique index exists.

- [ ] **Step 5: Seed station commands**

```bash
docker exec archie_database psql -U archie -d archie -c "
INSERT INTO station_commands (station_id, command_name, capability, description) VALUES
  -- ENGINEERING
  ((SELECT id FROM bridge_stations WHERE station_code='ENGINEERING'), 'code_review', 'code_review', 'Review code for quality and bugs'),
  ((SELECT id FROM bridge_stations WHERE station_code='ENGINEERING'), 'debug', 'debugging', 'Debug an issue in code'),
  ((SELECT id FROM bridge_stations WHERE station_code='ENGINEERING'), 'test', 'testing', 'Write or run tests'),
  ((SELECT id FROM bridge_stations WHERE station_code='ENGINEERING'), 'deploy', 'deployment', 'Deploy code changes'),
  -- ANALYTICS
  ((SELECT id FROM bridge_stations WHERE station_code='ANALYTICS'), 'classify', 'classify', 'Classify text or data'),
  ((SELECT id FROM bridge_stations WHERE station_code='ANALYTICS'), 'sentiment', 'sentiment', 'Analyze sentiment'),
  ((SELECT id FROM bridge_stations WHERE station_code='ANALYTICS'), 'translate', 'translate', 'Translate text between languages'),
  -- OPERATIONS
  ((SELECT id FROM bridge_stations WHERE station_code='OPERATIONS'), 'health_check', 'health_check', 'Run system health check'),
  ((SELECT id FROM bridge_stations WHERE station_code='OPERATIONS'), 'backup', 'backup', 'Trigger system backup'),
  ((SELECT id FROM bridge_stations WHERE station_code='OPERATIONS'), 'monitor', 'system_monitoring', 'Monitor system metrics'),
  -- RESEARCH
  ((SELECT id FROM bridge_stations WHERE station_code='RESEARCH'), 'summarize', 'summarize', 'Summarize a document or topic'),
  ((SELECT id FROM bridge_stations WHERE station_code='RESEARCH'), 'search', 'semantic_search', 'Search knowledge base'),
  ((SELECT id FROM bridge_stations WHERE station_code='RESEARCH'), 'analyze', 'knowledge_analysis', 'Deep analysis of a topic'),
  -- CREATIVE
  ((SELECT id FROM bridge_stations WHERE station_code='CREATIVE'), 'write', 'content_writing', 'Write content or copy'),
  ((SELECT id FROM bridge_stations WHERE station_code='CREATIVE'), 'image', 'image_generation', 'Generate an image'),
  -- COMMAND
  ((SELECT id FROM bridge_stations WHERE station_code='COMMAND'), 'dispatch', 'dispatch', 'Dispatch a task to the fleet'),
  ((SELECT id FROM bridge_stations WHERE station_code='COMMAND'), 'orchestrate', 'orchestration', 'Orchestrate a multi-step workflow')
ON CONFLICT (station_id, command_name) DO NOTHING;
"
```

- [ ] **Step 6: Commit**

```bash
git add database/migrations/148_fleet_coordination.sql
git commit -m "feat(fleet): migration 148 — cleanup orphans, LLM uniqueness, station_commands"
```

---

## Task 2: Fleet Triage Module

**Files:**
- Create: `ai_bridge/fleet_triage.py`

This module contains the lightweight triage logic shared between Bridge (for Starbase local dispatch) and nodes (via node_triage.py). It does NOT import Flask or any heavy dependencies.

- [ ] **Step 1: Create fleet_triage.py**

Create `ai_bridge/fleet_triage.py`:

```python
"""Fleet triage — lightweight agent capability check.

Used by both Bridge (Starbase) and remote nodes to determine
if a task can be handled locally before escalating to Bridge dispatch.

This module must stay dependency-light (no Flask, no DB imports).
Callers provide agent state as dicts.
"""

# Mirror of CAPABILITY_STATION_MAP from bridge_dispatcher.py
# Synced to nodes via capability_map config sync
CAPABILITY_STATION_MAP = {
    "COMMAND": [
        "conversation", "dispatch", "governance", "orchestration",
    ],
    "ANALYTICS": [
        "classify", "sentiment", "tagging", "anomaly_detection",
        "pattern_recognition", "embedding", "vision", "translate",
        "detect_language",
    ],
    "ENGINEERING": [
        "code", "code_analysis", "code_review", "testing", "debugging",
        "schema_design", "api_design", "deployment",
    ],
    "OPERATIONS": [
        "operations", "system_monitoring", "backup", "health_check",
        "security_analysis", "telegram", "email", "notification",
        "webhook", "ha_integration", "automation",
    ],
    "CREATIVE": [
        "content_writing", "email_composition", "chat_styling", "voice",
        "ux_writing", "social_media", "image_generation",
        "video_generation",
    ],
    "RESEARCH": [
        "knowledge_analysis", "summarize", "document_analysis",
        "fact_checking", "semantic_search", "context_retrieval",
    ],
}

# Reverse map: capability -> station
_CAPABILITY_TO_STATION = {}
for station, caps in CAPABILITY_STATION_MAP.items():
    for cap in caps:
        _CAPABILITY_TO_STATION[cap] = station


def capability_to_station(capability):
    """Map a capability string to its home station code."""
    return _CAPABILITY_TO_STATION.get(capability)


def can_agent_handle(agent):
    """Check if an agent passes triage hard-block conditions.

    Mirrors Bridge dispatcher hard-blocks from _score_agent().
    Agent dict must have: status, shift_state, stress, energy, task_count, task_limit.
    """
    if agent.get("status") != "active":
        return False

    shift = agent.get("shift_state", "active")
    if shift in ("cooldown", "off_duty"):
        return False

    stress = agent.get("stress", 0.0)
    energy = agent.get("energy", 1.0)

    # Critical welfare block — mirrors dispatcher exactly
    if stress >= 0.9 and energy <= 0.15:
        return False

    task_count = agent.get("task_count", 0)
    task_limit = agent.get("task_limit", 10)
    if task_count >= task_limit:
        return False

    return True


def triage_local(capability, local_agents):
    """Find the best local agent for a capability.

    Args:
        capability: The task capability (e.g., 'code_review')
        local_agents: List of agent dicts with keys:
            name, station_codes, status, shift_state, stress, energy,
            task_count, task_limit, model_loaded (bool)

    Returns:
        Best agent dict, or None if escalation needed.
    """
    station = capability_to_station(capability)
    if not station:
        return None  # Unknown capability — escalate

    candidates = []
    for agent in local_agents:
        # Must serve the right station
        if station not in agent.get("station_codes", []):
            continue

        # Must pass hard-block checks
        if not can_agent_handle(agent):
            continue

        # Must have model loaded locally
        if not agent.get("model_loaded", False):
            continue

        candidates.append(agent)

    if not candidates:
        return None  # Escalate to Bridge

    # Pick agent with lowest current task count
    candidates.sort(key=lambda a: a.get("task_count", 0))
    return candidates[0]
```

- [ ] **Step 2: Commit**

```bash
git add ai_bridge/fleet_triage.py
git commit -m "feat(fleet): add fleet_triage module — shared triage logic for nodes and hub"
```

---

## Task 3: Bridge Dispatcher — Fleet-Wide Agent Cache

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (lines ~214, ~253, ~1053, ~1215, ~2831)

Extend the agent cache to include remote node agents, and extend scoring to factor in network cost and model readiness.

- [ ] **Step 1: Read current _refresh_agent_cache**

Read lines 250-330 of bridge_dispatcher.py to understand cache population.

- [ ] **Step 2: Add fleet agent cache population**

In `_refresh_agent_cache()` (~line 253), after the existing agent cache population from `agents` + `station_assignments`, add a second query that pulls remote node agents:

```python
# --- Fleet extension: add remote node agents to cache ---
try:
    cur.execute("""
        SELECT na.id AS node_agent_id, na.name, na.node_id,
               na.source_agent_id, na.model AS local_model,
               na.station_codes, na.status,
               rn.node_id AS node_str_id, rn.hostname,
               rn.last_heartbeat, rn.status AS node_status,
               rn.gpu_vram_mb, rn.ram_total_mb, rn.ram_available_mb
        FROM node_agents na
        JOIN remote_nodes rn ON rn.id = na.node_id
        WHERE na.status = 'active'
          AND rn.status = 'online'
          AND rn.last_heartbeat > NOW() - INTERVAL '90 seconds'
    """)
    for row in cur.fetchall():
        cache_key = f"fleet:{row['node_str_id']}:{row['name']}"
        self._agent_cache[cache_key] = {
            "id": row["node_agent_id"],
            "source_agent_id": row["source_agent_id"],
            "name": row["name"],
            "model": row["local_model"],
            "station_codes": row["station_codes"] or [],
            "status": row["status"],
            "node_id": row["node_str_id"],
            "node_db_id": row["node_id"],
            "hostname": row["hostname"],
            "is_remote": True,
            "gpu_vram_mb": row["gpu_vram_mb"],
            "ram_total_mb": row["ram_total_mb"],
            "ram_available_mb": row["ram_available_mb"],
            # Welfare defaults — updated from heartbeat data
            "stress": 0.0,
            "energy": 1.0,
            "shift_state": "active",
            "task_count": 0,
            "task_limit": 10,
        }
except Exception as e:
    logger.warning(f"Fleet cache population failed: {e}")
```

- [ ] **Step 3: Extend _score_agent for remote agents**

In `_score_agent()` (~line 1053), add network cost penalty for remote agents before the return:

```python
# Network cost penalty for remote fleet agents
if agent_info.get("is_remote"):
    score *= 0.85  # 15% penalty for remote dispatch latency
    if not agent_info.get("model_loaded", True):
        score *= 0.7  # Additional 30% penalty if model not loaded on node
```

- [ ] **Step 4: Extend _select_agent to consider fleet agents**

In `_select_agent()` (~line 1215), when checking station match, handle both formats:

```python
# Handle both local agents (station_code string) and fleet agents (station_codes array)
agent_station = info.get("station_code", "")
agent_stations = info.get("station_codes", [])
if station_code != agent_station and station_code not in agent_stations:
    continue
```

- [ ] **Step 5: Add remote dispatch method**

After agent selection in `request_work()` (~line 2831), add remote dispatch path:

```python
if selected_agent.get("is_remote"):
    return self._dispatch_to_remote_node(
        selected_agent, capability, prompt, module_id, system_prompt
    )
```

Add new method `_dispatch_to_remote_node`:

```python
def _dispatch_to_remote_node(self, agent_info, capability, prompt,
                              module_id, system_prompt):
    """Dispatch a job to a remote node via mesh_sync_log."""
    import json as _json
    node_id = agent_info["node_id"]
    payload = {
        "capability": capability,
        "prompt": prompt,
        "module_id": module_id,
        "system_prompt": system_prompt,
        "target_agent": agent_info["name"],
        "target_model": agent_info["model"],
        "station_codes": agent_info.get("station_codes", []),
    }

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            INSERT INTO mesh_sync_log
                (node_id, sync_type, payload, status, sent_at)
            VALUES (%s, 'job_request', %s, 'sent', NOW())
            RETURNING id
        """, (node_id, _json.dumps(payload)))
        sync_id = cur.fetchone()["id"]

    logger.info(
        f"Fleet dispatch: job_request #{sync_id} "
        f"to {node_id} agent {agent_info['name']}"
    )
    return {
        "status": "dispatched_remote",
        "sync_id": sync_id,
        "node_id": node_id,
        "agent": agent_info["name"],
    }
```

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(fleet): extend dispatcher — fleet agent cache, remote scoring, mesh dispatch"
```

---

## Task 4: Mesh Routes — Broadcast + Job Result Processing

**Files:**
- Modify: `platform_v2/tools/bridge/mesh_routes.py`

The pending and ack endpoints already exist. Add broadcast and job result processing.

- [ ] **Step 1: Read current mesh_routes.py**

Understand existing patterns for route registration, auth decorators, and imports.

- [ ] **Step 2: Add fleet broadcast endpoint**

```python
@mesh_bp.route("/api/mesh/broadcast", methods=["POST"])
@admin_required
def api_mesh_broadcast():
    """Broadcast a sync entry to all active online nodes."""
    data = request.get_json()
    sync_type = data.get("sync_type")
    payload = data.get("payload", {})

    if not sync_type:
        return jsonify({"error": "sync_type required"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            SELECT node_id FROM remote_nodes
            WHERE status = 'online'
              AND last_heartbeat > NOW() - INTERVAL '90 seconds'
        """)
        nodes = cur.fetchall()

        created = 0
        for node in nodes:
            cur.execute("""
                INSERT INTO mesh_sync_log
                    (node_id, sync_type, payload, status, sent_at)
                VALUES (%s, %s, %s, 'sent', NOW())
            """, (node["node_id"], sync_type, json.dumps(payload)))
            created += 1

    return jsonify({
        "broadcast": True,
        "nodes_targeted": created,
        "sync_type": sync_type,
    })
```

- [ ] **Step 3: Add job result processor to ack handler**

In the existing `POST /api/mesh/sync/<sync_id>/ack` handler, after updating mesh_sync_log status, add:

```python
# Process job_request results
if sync_entry["sync_type"] == "job_request" and ack_payload:
    _process_job_result(cur, sync_entry, ack_payload)


def _process_job_result(cur, sync_entry, result):
    """Process completed job result from a remote node."""
    original = sync_entry.get("payload", {})
    station_codes = original.get("station_codes", [])

    cur.execute("""
        INSERT INTO task_execution_log
            (agent_name, station_code, capability, module_source,
             success, duration_ms, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (
        result.get("agent_name", original.get("target_agent")),
        station_codes[0] if station_codes else "UNKNOWN",
        original.get("capability"),
        original.get("module_id", "remote"),
        result.get("success", False),
        result.get("duration_ms", 0),
    ))
```

- [ ] **Step 4: Add config version endpoint**

```python
@mesh_bp.route("/api/mesh/version", methods=["GET"])
def api_mesh_version():
    """Return current config versions for sync checks."""
    return jsonify({
        "capability_map_version": 1,
        "station_commands_version": 1,
        "agent_config_version": 1,
    })
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/bridge/mesh_routes.py
git commit -m "feat(fleet): mesh broadcast, job result processing, config version endpoint"
```

---

## Task 5: Heartbeat Extension — Welfare + Completed Jobs

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (heartbeat handler, ~line 4296)

- [ ] **Step 1: Read current heartbeat handler**

Find the heartbeat endpoint in bridge/routes.py and understand the current payload processing.

- [ ] **Step 2: Extend heartbeat to accept completed_jobs**

In the heartbeat handler, after existing metric processing:

```python
# Process completed jobs from node
completed_jobs = data.get("completed_jobs", [])
if completed_jobs:
    for job in completed_jobs:
        try:
            cur.execute("""
                INSERT INTO task_execution_log
                    (agent_name, station_code, capability,
                     module_source, success, duration_ms, created_at)
                VALUES (%s, %s, %s, 'remote', %s, %s, NOW())
            """, (
                job.get("agent_name"),
                job.get("station_code", "UNKNOWN"),
                job.get("capability"),
                job.get("success", False),
                job.get("duration_ms", 0),
            ))
        except Exception as e:
            logger.warning(f"Failed to log completed job: {e}")
```

- [ ] **Step 3: Extend heartbeat to accept node agent welfare**

```python
# Update fleet agent cache with node welfare data
agent_welfare = data.get("agent_welfare", {})
if agent_welfare:
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher
        dispatcher = get_dispatcher()
        for agent_name, welfare in agent_welfare.items():
            cache_key = f"fleet:{node_id}:{agent_name}"
            if cache_key in dispatcher._agent_cache:
                dispatcher._agent_cache[cache_key].update({
                    "stress": welfare.get("stress", 0.0),
                    "energy": welfare.get("energy", 1.0),
                    "shift_state": welfare.get("shift_state", "active"),
                    "task_count": welfare.get("task_count", 0),
                    "model_loaded": welfare.get("model_loaded", False),
                })
    except Exception as e:
        logger.warning(f"Failed to update fleet welfare cache: {e}")
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(fleet): extend heartbeat — completed jobs + agent welfare reporting"
```

---

## Task 6: Node Triage + Job Execution

**Files:**
- Create: `node_client/node_triage.py`
- Modify: `node_client/node_api.py`
- Modify: `node_client/node_sync.py`

- [ ] **Step 1: Create node_triage.py**

```python
"""Node-side triage — determines if a task can be handled locally.

Imports shared triage logic concepts and adds Ollama model checks.
"""

import requests
import logging

logger = logging.getLogger(__name__)

# Local copy of capability map — synced from Bridge
_capability_station_map = {}


def update_capability_map(new_map):
    """Update local capability map from Bridge sync."""
    global _capability_station_map
    _capability_station_map = new_map


def capability_to_station(capability):
    """Map capability to station using local map."""
    for station, caps in _capability_station_map.items():
        if capability in caps:
            return station
    return None


def get_loaded_models(ollama_host="http://localhost:11434"):
    """Query local Ollama for loaded models."""
    try:
        resp = requests.get(f"{ollama_host}/api/ps", timeout=5)
        if resp.ok:
            return {
                m["name"].split(":")[0]
                for m in resp.json().get("models", [])
            }
    except Exception as e:
        logger.warning(f"Ollama ps check failed: {e}")
    return set()


def can_handle_locally(capability, local_agents,
                       ollama_host="http://localhost:11434"):
    """Check if any local agent can handle this capability.

    Returns best agent dict or None (meaning escalate to Bridge).
    """
    station = capability_to_station(capability)
    if not station:
        return None

    loaded_models = get_loaded_models(ollama_host)

    candidates = []
    for agent in local_agents:
        if station not in agent.get("station_codes", []):
            continue
        if agent.get("status") != "active":
            continue
        shift = agent.get("shift_state", "active")
        if shift in ("cooldown", "off_duty"):
            continue
        stress = agent.get("stress", 0.0)
        energy = agent.get("energy", 1.0)
        if stress >= 0.9 and energy <= 0.15:
            continue
        if agent.get("task_count", 0) >= agent.get("task_limit", 10):
            continue

        # Check model is loaded in Ollama
        model_name = agent.get("model", "").split(":")[0]
        if model_name not in loaded_models:
            continue

        candidates.append(agent)

    if not candidates:
        return None

    candidates.sort(key=lambda a: a.get("task_count", 0))
    return candidates[0]
```

- [ ] **Step 2: Add job execution endpoint to node_api.py**

In `node_client/node_api.py`, add:

```python
@app.route("/api/jobs/execute", methods=["POST"])
def execute_job():
    """Execute a job request from Bridge dispatch."""
    import time

    data = request.get_json()
    capability = data.get("capability")
    prompt = data.get("prompt")
    target_agent = data.get("target_agent")
    target_model = data.get("target_model")

    if not all([capability, prompt, target_agent]):
        return jsonify({"error": "capability, prompt, target_agent required"}), 400

    start = time.time()
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": target_model, "prompt": prompt, "stream": False},
            timeout=300,
        )
        duration_ms = int((time.time() - start) * 1000)

        if resp.ok:
            result = resp.json()
            return jsonify({
                "success": True,
                "agent_name": target_agent,
                "capability": capability,
                "duration_ms": duration_ms,
                "response": result.get("response", ""),
            })
        else:
            return jsonify({
                "success": False,
                "agent_name": target_agent,
                "capability": capability,
                "duration_ms": int((time.time() - start) * 1000),
                "error": resp.text,
            }), 500

    except Exception as e:
        return jsonify({
            "success": False,
            "agent_name": target_agent,
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000),
        }), 500
```

- [ ] **Step 3: Add job_request handler to node_sync.py**

In `node_client/node_sync.py`, in the sync type dispatcher (after `_handle_agent_config`):

```python
def _handle_job_request(self, sync_entry):
    """Handle a job request dispatched from Bridge."""
    payload = sync_entry.get("payload", {})
    capability = payload.get("capability")
    prompt = payload.get("prompt")
    target_agent = payload.get("target_agent")
    target_model = payload.get("target_model")

    logger.info(
        f"Job request: {capability} -> {target_agent} ({target_model})"
    )

    try:
        resp = requests.post(
            f"http://localhost:{self.api_port}/api/jobs/execute",
            json={
                "capability": capability,
                "prompt": prompt,
                "target_agent": target_agent,
                "target_model": target_model,
            },
            timeout=300,
        )

        result = resp.json()
        station_codes = payload.get("station_codes", [])
        self._completed_jobs.append({
            "agent_name": target_agent,
            "capability": capability,
            "success": result.get("success", False),
            "duration_ms": result.get("duration_ms", 0),
            "station_code": station_codes[0] if station_codes else "UNKNOWN",
        })

        return {
            "status": "completed" if result.get("success") else "failed",
            "result": result,
        }

    except Exception as e:
        logger.error(f"Job execution failed: {e}")
        return {"status": "failed", "error": str(e)}
```

- [ ] **Step 4: Add completed_jobs + welfare to heartbeat payload**

In node_sync.py, in the heartbeat function, extend the payload:

```python
# Initialize _completed_jobs list in __init__
self._completed_jobs = []

# In heartbeat payload construction:
payload["completed_jobs"] = self._completed_jobs
self._completed_jobs = []  # Clear after sending

payload["agent_welfare"] = self._get_agent_welfare()

def _get_agent_welfare(self):
    """Get local agent welfare state for heartbeat."""
    welfare = {}
    for agent in self._get_idle_agents():
        welfare[agent["name"]] = {
            "stress": agent.get("stress", 0.0),
            "energy": agent.get("energy", 1.0),
            "shift_state": agent.get("shift_state", "active"),
            "task_count": agent.get("task_count", 0),
            "model_loaded": agent.get("model_loaded", False),
        }
    return welfare
```

- [ ] **Step 5: Commit**

```bash
git add node_client/node_triage.py node_client/node_api.py node_client/node_sync.py
git commit -m "feat(fleet): node triage, job execution endpoint, heartbeat welfare reporting"
```

---

## Task 7: Station Commands API

**Files:**
- Modify: `platform_v2/tools/starship/routes.py`

- [ ] **Step 1: Add station commands CRUD endpoints**

```python
@starship_bp.route("/api/station-commands", methods=["GET"])
@admin_required
def api_get_station_commands():
    """Get all station commands, optionally filtered by station."""
    station_code = request.args.get("station_code")

    with get_db_cursor() as (conn, cur):
        if station_code:
            cur.execute("""
                SELECT sc.*, bs.station_code
                FROM station_commands sc
                JOIN bridge_stations bs ON bs.id = sc.station_id
                WHERE bs.station_code = %s AND sc.is_active = true
                ORDER BY sc.command_name
            """, (station_code,))
        else:
            cur.execute("""
                SELECT sc.*, bs.station_code
                FROM station_commands sc
                JOIN bridge_stations bs ON bs.id = sc.station_id
                WHERE sc.is_active = true
                ORDER BY bs.station_code, sc.command_name
            """)
        commands = cur.fetchall()

    return jsonify({"commands": [dict(c) for c in commands]})


@starship_bp.route("/api/station-commands/execute", methods=["POST"])
@admin_required
def api_execute_station_command():
    """Execute a station command via Smart Relay triage flow."""
    data = request.get_json()
    command_id = data.get("command_id")
    prompt = data.get("prompt", "")

    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT sc.*, bs.station_code
            FROM station_commands sc
            JOIN bridge_stations bs ON bs.id = sc.station_id
            WHERE sc.id = %s AND sc.is_active = true
        """, (command_id,))
        command = cur.fetchone()

    if not command:
        return jsonify({"error": "Command not found"}), 404

    from ai_bridge.bridge_dispatcher import get_dispatcher
    dispatcher = get_dispatcher()

    result = dispatcher.request_work(
        capability=command["capability"],
        prompt=prompt or command["description"],
        module_id="station_command",
    )

    return jsonify({
        "command": command["command_name"],
        "station": command["station_code"],
        "result": result,
    })
```

- [ ] **Step 2: Harden recommendation engine with is_cloneable filter**

In `get_agent_recommendations()` (~line 1485), after the agent query, add:

```python
# Exclude non-cloneable agents (ARCHIE, Vigil, Kytran)
agents = [a for a in agents if a.get("is_cloneable", True)]
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "feat(fleet): station commands API + recommendation is_cloneable filter"
```

---

## Task 8: Starship UI — Station Commands + Job Tracker

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`

- [ ] **Step 1: Add station command loading function**

```javascript
async function loadStationCommands(stationCode) {
    const resp = await fetch(
        '/tools/starship/api/station-commands?station_code='
        + encodeURIComponent(stationCode)
    );
    const data = await resp.json();
    return data.commands || [];
}
```

- [ ] **Step 2: Render station commands as buttons in station cards**

```javascript
function renderStationCommands(commands, containerEl) {
    if (!commands.length) {
        containerEl.textContent = 'No commands configured';
        return;
    }

    // Clear container safely
    while (containerEl.firstChild) containerEl.removeChild(containerEl.firstChild);

    commands.forEach(function(cmd) {
        var btn = document.createElement('button');
        btn.className = 'sc-station-cmd-btn';
        btn.dataset.cmdId = cmd.id;
        btn.title = cmd.description || cmd.command_name;

        var nameSpan = document.createElement('span');
        nameSpan.className = 'cmd-name';
        nameSpan.textContent = cmd.command_name;
        btn.appendChild(nameSpan);

        var capSpan = document.createElement('span');
        capSpan.className = 'cmd-capability';
        capSpan.textContent = cmd.capability;
        btn.appendChild(capSpan);

        btn.addEventListener('click', function() {
            executeStationCommand(cmd.id);
        });
        containerEl.appendChild(btn);
    });
}
```

- [ ] **Step 3: Add command execution function**

```javascript
async function executeStationCommand(cmdId) {
    var prompt = window.prompt('Enter task details (or leave blank for default):');
    if (prompt === null) return;

    var resp = await fetch('/tools/starship/api/station-commands/execute', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({command_id: parseInt(cmdId), prompt: prompt}),
    });
    var result = await resp.json();
    if (result.result) {
        showToast('Command dispatched to ' + result.station, 'success');
    } else {
        showToast('Command failed', 'error');
    }
}
```

- [ ] **Step 4: Add CSS for station command buttons**

```css
.sc-station-cmd-btn {
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    padding: 8px 14px;
    margin: 4px;
    background: rgba(0, 229, 255, 0.08);
    border: 1px solid rgba(0, 229, 255, 0.25);
    border-radius: 6px;
    color: #e0e0e0;
    cursor: pointer;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    transition: all 0.2s;
}
.sc-station-cmd-btn:hover {
    background: rgba(0, 229, 255, 0.18);
    border-color: #00e5ff;
}
.sc-station-cmd-btn .cmd-name {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.sc-station-cmd-btn .cmd-capability {
    font-size: 9px;
    opacity: 0.6;
    margin-top: 2px;
}
```

- [ ] **Step 5: Integrate commands into station card rendering**

In the function that renders Starbase station cards, after rendering agents, add a commands section:

```javascript
// In renderStarbaseStations or equivalent, for each station card:
var cmdContainer = document.createElement('div');
cmdContainer.className = 'sc-station-commands';
stationCard.appendChild(cmdContainer);
loadStationCommands(station.station_code).then(function(cmds) {
    renderStationCommands(cmds, cmdContainer);
});
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(fleet): station command UI buttons in Starship STATIONS tab"
```

---

## Task 9: Integration Test + Deploy

- [ ] **Step 1: Test migration**

```bash
docker exec archie_database psql -U archie -d archie -c "
  SELECT count(*) FROM station_commands;
  SELECT count(*) FROM node_agents WHERE source_agent_id IS NULL;
"
```

Expected: 17 commands seeded, 0 orphans.

- [ ] **Step 2: Test station commands API**

```bash
curl -s http://192.168.1.200:3000/tools/starship/api/station-commands | python3 -m json.tool | head -30
```

- [ ] **Step 3: Test fleet agent cache**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.bridge_dispatcher import get_dispatcher
d = get_dispatcher()
d._refresh_agent_cache()
fleet = {k: v for k, v in d._agent_cache.items() if v.get('is_remote')}
print(f'Fleet agents in cache: {len(fleet)}')
for k, v in fleet.items():
    print(f'  {k}: {v[\"name\"]} ({v[\"model\"]}) on {v[\"hostname\"]}')
"
```

- [ ] **Step 4: Test triage logic**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.fleet_triage import triage_local
agents = [
    {'name': 'Nexus', 'station_codes': ['ENGINEERING'], 'status': 'active',
     'shift_state': 'active', 'stress': 0.2, 'energy': 0.8,
     'task_count': 1, 'task_limit': 10, 'model_loaded': True},
    {'name': 'Scholar', 'station_codes': ['RESEARCH'], 'status': 'active',
     'shift_state': 'active', 'stress': 0.1, 'energy': 0.9,
     'task_count': 0, 'task_limit': 10, 'model_loaded': True},
]
r = triage_local('code_review', agents)
print(f'code_review -> {r[\"name\"] if r else \"ESCALATE\"}')
r = triage_local('summarize', agents)
print(f'summarize -> {r[\"name\"] if r else \"ESCALATE\"}')
"
```

Expected: code_review -> Nexus, summarize -> Scholar

- [ ] **Step 5: Restart platform and smoke test**

```bash
docker compose restart archie_platform
sleep 5
curl -s http://192.168.1.200:3000/tools/starship/api/station-commands | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'{len(d[\"commands\"])} commands loaded')
"
```

- [ ] **Step 6: Push**

```bash
git push origin main
```

---

## Task 10: Dev HQ Updates

- [ ] **Step 1: Update Dev HQ project**

Use MCP tools:
- `mcp create_task` — "Fleet Agent Coordination System — implementation complete"
- `mcp log_decision` — "Smart Relay architecture: local triage on nodes, Bridge dispatch fleet-wide, tiered escalation"
- `mcp store_memory` — vault_note documenting the fleet coordination system
- `mcp update_project_understanding` — for Starship Command project

- [ ] **Step 2: Create ADRs**

Log architectural decisions via MCP:
- ADR: "Fleet-wide LLM uniqueness — each active agent has a unique primary_model"
- ADR: "Smart Relay dispatch — nodes triage locally, Bridge scores fleet-wide on escalation"
- ADR: "Station commands — structured task triggers alongside natural language"
