# Fleet Agent Coordination System — Design Spec

**Date:** 2026-03-13
**Status:** Draft
**Author:** Claude + Kytran

## Goal

Build a fleet-wide agent coordination system where Bridge Command is the single source of truth for all agents. Agents are unique individuals with unique LLMs, nodes receive crew from Bridge via recommendations, and Bridge coordinates task delegation across the fleet using a Smart Relay architecture (local triage → Bridge dispatch → tiered escalation).

## Architecture Overview

Bridge Command owns the master agent roster (`agents` table). Every node agent must trace back to a Bridge agent via `source_agent_id`. LLMs are unique fleet-wide — each model is assigned to exactly one active agent, enabling per-model performance tracking. Nodes handle tasks locally when capable, escalating to Bridge when capacity or capability is insufficient. Bridge dispatches fleet-wide using the existing scoring algorithm, extended to consider all nodes.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Task handling | Hybrid — local first, escalate to Bridge | Fast local execution, full fleet optimization on escalation |
| Agent identity | Unique clones with lineage | Node agents are distinct individuals, `source_agent_id` is lineage not identity |
| LLM uniqueness | Fleet-wide unique | Enables tracking each LLM's skills/weaknesses as a distinct "brain" |
| Task trigger | Station commands + natural language | Structured commands for common ops, NL for everything else |
| Escalation target | Tiered: local → mesh nodes → hub Starbase → cloud | Consistent with existing 5-step escalation pattern |
| Orphan agents | Delete, strict enforcement | No local-only agents. Every node agent must have Bridge parent |
| Dispatch architecture | Smart Relay (Approach C) | Single scoring algorithm on Bridge, lightweight triage on nodes |

---

## Section 1: Data Model & Uniqueness

### Bridge `agents` Table — Single Source of Truth

Every agent in the fleet has a row in `agents`. This table is owned by Bridge Command.

**Changes:**
- No schema changes to `agents` itself
- Add **unique partial index** on `primary_model WHERE status = 'active'` — enforces fleet-wide LLM uniqueness at DB level
- Existing columns cover all needs: name, display_name, primary_model, station assignments, status, worker_type, budget, performance

### Node Agents — Strict Linkage

**`node_agents.source_agent_id`** becomes NOT NULL with FK constraint to `agents.id`.

- No orphan node agents allowed
- `source_agent_id` = which Bridge agent this clone derives from (lineage) — NOT NULL, ON DELETE RESTRICT
- `hub_agent_id` = deprecated, redundant with `source_agent_id`. Both reference the same Bridge agent. Will be consolidated to just `source_agent_id` in this migration.
- Node agents have their own unique names (from `_STARSHIP_FIRST_NAMES`/`_STARSHIP_LAST_NAMES` pools)
- Node agents inherit station_codes from their source agent's station assignments

### Performance Tracking

`agent_performance_rankings` table (already exists) tracks per-agent, per-capability scores:
- `agent_id`, `capability`, `rank_score`, `sample_size`
- Extended so node-executed tasks also feed this table via heartbeat result reporting
- Bridge dispatcher's scoring (skills 35%, specialization 25%, welfare 20%, availability 15%, budget 5%) uses these rankings fleet-wide

### Starbase as Node

`remote_nodes` row for Starbase (node 68) already exists. Bridge treats it identically to any other node for dispatch purposes. The only difference is Starbase has direct access to Bridge's scoring algorithm (no network hop for escalation).

---

## Section 2: Smart Relay — Local Triage & Escalation

### Task Flow

```
User Request (on any node)
    │
    ▼
[Local Triage] ── Can I handle this?
    │               Checklist: capable agent + model loaded + not stressed + under task limit
    │
    ├─ YES ──► Execute locally, report result to Bridge (async via heartbeat)
    │
    └─ NO ───► Send to Bridge
                    │
                    ▼
              [Bridge Dispatch] ── Full scoring algorithm, fleet-wide
                    │
                    ├─ Other node has best agent ──► Push job via mesh_sync_log (job_request)
                    │
                    ├─ Hub/Starbase agent is best ──► Execute on Starbase directly
                    │
                    └─ No fleet agent available ──► Cloud escalation (existing chain)
```

### Local Triage (on node)

Intentionally simple — NOT a copy of the scoring algorithm. Just a checklist:

1. Map request capability → station using `CAPABILITY_STATION_MAP` (synced from Bridge as config)
2. Find local agents with that station in their `station_codes`
3. Check each agent passes ALL (mirrors Bridge hard-block conditions exactly):
   - Status = active
   - Shift state not cooldown/off_duty
   - NOT (stress >= 0.9 AND energy <= 0.15) — critical welfare block
   - Stress < 0.9 OR energy > 0.15 — at least one must be healthy
   - Task count < queue limit
4. Check agent's model is loaded locally in Ollama (`/api/ps`)
5. If any pass → pick lowest current task count → execute
6. If none pass → escalate to Bridge with full request payload

> **Note:** Local triage mirrors Bridge dispatcher hard-block conditions from `_score_agent()` to avoid dispatching locally to agents Bridge would have rejected.

### Bridge Fleet-Wide Dispatch

Uses existing `_select_agent()` and `_score_agent()` from `bridge_dispatcher.py`. Extended to:

1. Query agents across ALL nodes (not just local station_assignments)
2. Factor in node hardware availability (model loaded? VRAM available?)
3. Factor in network cost (prefer local/Starbase over remote nodes, prefer remote nodes over cloud)
4. Write dispatch decision to `mesh_sync_log` with `sync_type='job_request'` for remote execution

### Fleet Agent Cache Population

Bridge maintains a fleet-wide agent cache (extension of existing `_agent_cache`):

1. **Source:** Node heartbeats (every 30s) report idle agents with station_codes, model name, loaded status
2. **Enrichment:** Bridge joins heartbeat data with `node_agents` + `agents` tables to get welfare state, shift state, performance rankings
3. **Cache TTL:** 60s (matches sync poll interval) — stale entries from offline nodes are excluded from scoring
4. **Scoring:** Remote node agents scored alongside Starbase agents using same `_score_agent()`, with an additional network-cost penalty for remote dispatch
5. **Welfare for node agents:** Nodes report stress/energy in heartbeat payload (node_sync.py already tracks local agent state)

### Job Request Timeout & Retry

- Job requests have a 5-minute TTL. If not acknowledged within 5 minutes, Bridge marks the job as `failed` and re-dispatches to the next best agent.
- If target node's heartbeat is stale (>90s), Bridge skips that node's agents during scoring.
- Failed jobs increment the agent's failure count in `agent_performance_rankings` to inform future scoring.

### Result Reporting

After local execution, node includes completed jobs in next heartbeat:
```json
{
  "completed_jobs": [
    {"agent_id": 12, "capability": "code_review", "success": true, "duration_ms": 4500, "job_id": "uuid"}
  ]
}
```
Bridge writes these to `task_execution_log` and updates `agent_performance_rankings`.

---

## Section 3: Station Commands & Task Delegation

### Two Paths, Unified Pipeline

**Path 1: Station Commands (structured)**
- Each station defines a command catalog
- New `station_commands` table:
  - `id` SERIAL PRIMARY KEY
  - `station_code` VARCHAR(50) NOT NULL
  - `command_name` VARCHAR(100) NOT NULL
  - `capability` VARCHAR(100) NOT NULL (maps to CAPABILITY_STATION_MAP)
  - `description` TEXT
  - `parameters_schema` JSONB (optional, defines expected input fields)
  - UNIQUE on (station_code, command_name)
- User picks station → command → fills params → submits
- Command maps directly to capability — skips intent parsing

**Path 2: Natural Language (flexible)**
- Free-form text input on Starship UI
- Routes to Bridge orchestration engine (`orchestration_engine.py`)
- Orchestration parses intent → capability → enters same triage/dispatch flow
- Falls back to COMMAND station if intent ambiguous

**Convergence point:** Both paths produce a `(capability, prompt, parameters)` tuple that enters the Smart Relay flow.

### Module Execution

Bridge dispatches via existing `request_work()` in `bridge_dispatcher.py`. The `module_source` identifies which Flask Blueprint handles the work. Results return through mesh sync.

### Starship UI Integration

- STATIONS tab: each station card shows command catalog as clickable buttons
- Agent availability indicators (green/amber/red) per station
- Job tracker with progress (reuses `bridge_jobs` progress tracking)
- NL input field at top for free-form requests
- Job history per station showing recent completions/failures

---

## Section 4: Fleet Sync & Mesh Communication

### Existing Infrastructure (kept as-is)

- `mesh_sync_log` table — hub-push + node-poll (60s interval)
- Node heartbeat (30s) — metrics + idle agent list
- Agent config auto-sync with 5s debounce on hub changes
- Node sync handlers for: code_update, container_restart, agent_config, model_pull, model_recommend

### New: Mesh Sync Endpoints in Bridge Routes

The `node_sync.py` client already calls these, but the routes don't exist yet in `bridge/routes.py`:

1. `GET /tools/bridge/api/mesh/sync/<node_id>/pending` — Returns all pending sync entries for a node
2. `POST /tools/bridge/api/mesh/sync/<sync_id>/ack` — Node acknowledges a sync entry with status + result payload
3. `GET /tools/bridge/api/mesh/version` — Returns current config versions (capability_map, station_commands, agent_configs)

### New: Job Request Sync Type

When Bridge dispatches to a remote node:
1. Bridge writes to `mesh_sync_log`: `sync_type='job_request'`, payload contains capability, prompt, parameters, target_agent_id
2. Node picks up on next poll (≤60s)
3. Node executes via local agent
4. Node acks with `status='completed'` and result in payload (or `status='failed'` with error)
5. Bridge receives ack, writes to `task_execution_log`, updates job status

### New: Fleet Broadcast

`POST /tools/bridge/api/mesh/broadcast` — Writes the same sync entry to all active nodes.

Used for:
- Agent config changes (when a Bridge agent is modified)
- Station command catalog updates
- Capability map version bumps
- IAAE policy updates

### New: Result Reporting via Heartbeat

Node heartbeat payload extended with `completed_jobs` array. Bridge processes into `task_execution_log` + `agent_performance_rankings`.

### Capability Map Sync

`CAPABILITY_STATION_MAP` pushed to nodes as config sync:
- Versioned — Bridge bumps version on any change
- Nodes check version on heartbeat response
- If stale, Bridge pushes update via `sync_type='capability_map'`
- Ensures local triage uses same mappings as Bridge

---

## Section 5: Recommendation Engine & Fleet Growth

### New Node Onboarding Flow

1. Node registers via `/api/nodes/register` — reports hardware profile
2. Bridge activates default stations based on hardware:
   - GPU node → CREATIVE, ANALYTICS (vision/image tasks)
   - High RAM → can handle large swap models
   - CPU-only → ENGINEERING, OPERATIONS, RESEARCH
3. Recommendation engine scores available agents (existing 4-factor + new hardware fit)
4. Admin reviews in Starship UI → approves → Bridge creates `node_agents` → pushes config

### Scoring Factors (recommendation weights — distinct from dispatch scoring)

| Factor | Weight | Description |
|--------|--------|-------------|
| Station match | 35% | Agent's stations overlap with node's enabled stations |
| Job volume | 25% | How frequently this agent gets dispatched (popularity) |
| Success rate | 20% | Agent's task success rate from performance rankings |
| Model efficiency | 10% | Inverse of model size (smaller = better for resource-constrained nodes) |
| Hardware fit | 10% | Model size vs node VRAM/RAM — penalize models that won't fit |

### Fleet-Wide LLM Uniqueness

- Recommendations exclude models already assigned to active agents fleet-wide
- Recommendations exclude agents where `is_cloneable = false` (ARCHIE, Vigil, Kytran)
- Model catalog (50+ LLMs) is the diversity pool
- Each agent = 1 unique LLM = trackable performance profile
- Catalog browsable in Starship UI for manual assignment

### Fleet Gap Analysis

Recommendation engine can identify:
- "No agent in fleet handles capability X" — suggest adding agent with appropriate model
- "Station Y has only 1 agent — recommend adding agent Z to node N"
- "Node N has spare capacity — recommend these agents"
- Feeds into existing `reassignment-recommendations` endpoint, extended fleet-wide

---

## Section 6: Resource-Aware Dispatch

### Problem

Large RAM models (e.g., qwen3-coder at 55GB) can only run on Starbase via RAM swap. While loaded, they consume capacity that limits other agents. Bridge must factor this in.

### VRAM/RAM Budget Tracking (Fleet-Wide)

- Bridge already has `_get_cached_hw_capacity()` for Starbase (30s TTL cache)
- Extend fleet-wide: nodes report RAM/VRAM usage in heartbeat (already do)
- Bridge maintains a fleet capacity map: per-node free VRAM, free RAM, loaded models

### Model Loading Cost

When scoring an agent whose model isn't loaded:
- Calculate load cost: will loading this model force other models to unload?
- How many agents does that sideline?
- Factor into dispatch scoring as a penalty

### Three-Tier Readiness as Fleet Signal

Existing ADR-078 readiness tiers become fleet-wide dispatch signals:

| Tier | Meaning | Dispatch Impact |
|------|---------|-----------------|
| **Loaded** (VRAM) | Model in GPU memory, instant inference | No penalty |
| **Swap** (RAM) | Model in RAM, ~2-5s load to VRAM | Small penalty in scoring |
| **Barracked** (disk) | Model on disk, cold load required | Large penalty, prefer other nodes |
| **Cloud** | External provider | Last resort, cost penalty |

### Capacity Reservation

When a large model is loading on Starbase:
1. Bridge marks affected agents as "reduced capacity"
2. Routes their pending work to other nodes (KYTRAN, etc.)
3. Once large model finishes and unloads, capacity restores
4. This is automatic — Bridge's scoring naturally prefers available agents

---

## Section 7: Data Cleanup & Migration

### Immediate Cleanup

1. Delete 9 orphan Theron agents from `node_agents` on KYTRAN (node_id=67) where `source_agent_id IS NULL`
2. Verify all remaining `node_agents` have valid `source_agent_id` referencing `agents.id`
3. Audit LLM assignments — check for duplicate `primary_model` across active agents, resolve conflicts

### Schema Migrations

```sql
-- Migration: 148_fleet_coordination.sql

-- 1. Clean orphan node agents (any without Bridge parent)
DELETE FROM node_agents WHERE source_agent_id IS NULL;

-- 2. Enforce source_agent_id NOT NULL + change ON DELETE to RESTRICT
-- (prevents deleting Bridge agents that have node clones — must remove clones first)
ALTER TABLE node_agents ALTER COLUMN source_agent_id SET NOT NULL;
ALTER TABLE node_agents DROP CONSTRAINT IF EXISTS node_agents_source_agent_id_fkey;
ALTER TABLE node_agents ADD CONSTRAINT node_agents_source_agent_id_fkey
    FOREIGN KEY (source_agent_id) REFERENCES agents(id) ON DELETE RESTRICT;

-- 3. Fleet-wide LLM uniqueness (active agents only)
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_unique_model_active
ON agents (primary_model) WHERE status = 'active' AND primary_model IS NOT NULL;

-- 4. Station commands table (uses station_id FK like rest of codebase)
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

-- 5. Index for fleet dispatch queries
CREATE INDEX IF NOT EXISTS idx_node_agents_source ON node_agents(source_agent_id);
CREATE INDEX IF NOT EXISTS idx_node_agents_station ON node_agents USING GIN(station_codes);
```

### No Breaking Changes

- All existing endpoints continue working
- Mesh sync endpoints are new additions
- Local triage is new node-side code
- Dispatcher fleet-wide extension is additive to existing scoring
- Fleet dispatch flows through the existing orchestration pipeline including IAAE governance checks

### Known Limitations (Initial Implementation)

- **Job dispatch latency:** Node poll interval is 60s, so remote-dispatched jobs may wait up to 60s to start. Acceptable for v1. Future optimization: add a lightweight webhook endpoint on nodes for priority dispatch, or WebSocket/SSE push.
- **Offline nodes:** If a node goes offline, pending job_requests timeout after 5 minutes and re-dispatch. No real-time push notification of node loss.

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `database/migrations/148_fleet_coordination.sql` | Create | Schema cleanup + new tables |
| `ai_bridge/bridge_dispatcher.py` | Modify | Extend `_select_agent` for fleet-wide scoring, fleet agent cache |
| `ai_bridge/fleet_triage.py` | Create | Lightweight triage logic (shared with nodes) |
| `platform_v2/tools/bridge/mesh_routes.py` | Modify | Add mesh sync endpoints (pending, ack, broadcast) — existing file |
| `platform_v2/tools/starship/routes.py` | Modify | Station commands UI endpoints, recommendation updates |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Modify | Station command UI, job tracker |
| `node_client/node_sync.py` | Modify | Add local triage, job execution, result reporting |
| `node_client/node_triage.py` | Create | Local triage checklist (imports fleet_triage logic) |

---

## Success Criteria

1. Every `node_agent` has a valid `source_agent_id` — no orphans
2. No two active agents share the same LLM fleet-wide
3. A task submitted on KYTRAN can execute locally OR escalate to Bridge → Starbase/cloud
4. Bridge can dispatch a job to KYTRAN via mesh sync and receive results
5. Station commands work from Starship UI → Bridge → module execution
6. Performance rankings are fleet-wide (local + remote executions feed same table)
7. New node onboarding produces hardware-appropriate agent recommendations with unique LLMs
8. Large model loading on Starbase automatically shifts dispatch to other nodes
