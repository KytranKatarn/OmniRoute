# Agent Lifecycle Coordination Architecture

**Date:** 2026-03-31
**Status:** Approved (brainstorm complete)
**Scope:** AI Bridge, Department HQ, Starbase Command, Autonomy module refactor
**Triggered by:** Embedding pipeline stall — agents stuck in cooldown with no budget reset job

---

## Problem Statement

Agent lifecycle management is fragmented across 4 systems that don't coordinate:

- **bridge_dispatcher.py** — owns shift transitions, budget tracking, welfare updates, replacement finding (should only route)
- **agent_loop.py** — 6,700-line monolith with all 58 scheduled jobs (should be distributed)
- **Department HQ** — has agent UI but doesn't own lifecycle logic
- **Autonomy** — supposed to be job command center but is read-only
- **Starbase Command** — has fleet/node management mixed with internal agent management

No daily budget reset job exists. Agents hit task limits, enter cooldown, and stay there forever. This blocked the consciousness embedding pipeline (2,373 github_file entries without embeddings).

---

## Design Principles

1. **Department HQ = "who"** — owns internal agents, their skills, welfare, budgets, shifts
2. **Autonomy = "what"** — owns all scheduled jobs, their lifecycle, execution, monitoring
3. **Starbase Command = "where"** — owns fleet visualization, nodes, cloud providers, external resources
4. **AI Bridge = "how"** — pure routing engine, reads from agent_service + fleet_service, never writes agent state directly
5. **Services are the mutation layer** — modules are UI shells over services

---

## Architecture

### Three Services

#### `agent_service.py` (expanded from existing 673 lines)

Current: agent CRUD, basic welfare
Absorbs from bridge_dispatcher.py:

| Function | Source | Description |
|----------|--------|-------------|
| `transition_shift_state(agent_id, new_state, reason)` | `_transition_shift_state()` | Shift lifecycle: active -> winding_down -> cooldown -> active |
| `increment_budget(agent_id, tokens_used)` | `_increment_agent_budget()` | Task count + token tracking in agent_budgets |
| `reset_budgets()` | NEW | Daily zero-out of current_task_count, reset shift states |
| `find_replacement(agent_id, department)` | `_find_replacement()` | When agent enters cooldown, activate barracked agent in same dept |
| `update_welfare_after_task(agent_id, success)` | `_update_agent_welfare()` | Stress/energy adjustment after task completion |
| `check_shift_transitions()` | `_check_shift_transitions()` | Budget/stress threshold checks for auto-transitions |
| `deploy_to_node(agent_id, node_id)` | Starbase crew_routes | Move agent from hub to node |
| `recall_from_node(agent_id)` | Starbase crew_routes | Return agent from node to hub (barracks) |
| `get_scored_candidates(capability, department)` | NEW | Fast query returning ranked candidates for dispatcher |

Shift transition thresholds (from bridge_dispatcher.py):
- 80% budget used -> winding_down
- 95% budget used -> cooldown
- stress >= 0.70 -> winding_down
- stress >= 0.85 -> cooldown

#### `fleet_service.py` (new)

Owns everything external to the hub:

| Function | Description |
|----------|-------------|
| `register_node(hostname, specs)` | Node connects to fleet |
| `disconnect_node(node_id)` | Node goes offline, agents recalled via agent_service |
| `get_node_status(node_id)` | Hardware specs, loaded models, deployed agents |
| `list_nodes()` | All nodes with health/location data |
| `register_provider(name, config)` | Add cloud provider profile |
| `get_provider_status(provider_id)` | Tier, usage, budget, health |
| `list_providers()` | All cloud providers with status |
| `record_cloud_usage(provider_id, tokens, cost)` | Track per-call usage |
| `get_usage_summary(provider_id, period)` | Usage/budget burn rate |
| `get_fleet_map_data()` | All pins (hub + nodes + providers) with coordinates |

#### `job_service.py` (new, replaces agent_loop.py monolith)

The runner engine:

| Function | Description |
|----------|-------------|
| `register_job(name, func, schedule, department, enabled)` | Module registers a recurring job |
| `run_job(job_id)` | Execute with logging, error handling |
| `list_jobs()` | All registered jobs with status |
| `get_job_status(job_id)` | Last run, next run, health |
| `enable_job(job_id)` / `disable_job(job_id)` | Toggle jobs |
| `reschedule_job(job_id, new_schedule)` | Change interval |

Jobs register at startup via owning module:

```python
# consciousness/__init__.py
def register_jobs(job_service):
    job_service.register("embedding_batch", _run_embedding, hours=4)
    job_service.register("skill_sync", _run_skill_sync, hours=12)
    job_service.register("skill_analyzer", _run_skill_analyzer, hours=6)

# app.py startup
job_service = JobService(scheduler)
consciousness.register_jobs(job_service)
starbase.register_jobs(job_service)
autonomy.register_jobs(job_service)
```

All execution logged to `autonomy_loop_log` table.

---

### Bridge Dispatcher Refactor

**Keeps:**
- `dispatch()` / `dispatch_json()` — core routing entry point
- `_select_agent_by_department()` — scoring and candidate selection
- `_score_agent()` — multi-factor scoring (reads from agent_service, doesn't write)
- Escalation chain: home dept -> cross-dept -> fleet node -> cloud
- `CAPABILITY_DEPARTMENT_MAP` — routing table
- `ensure_model_ready()` — model readiness checks

**Loses (moves to agent_service):**
- `_check_shift_transitions()` -> `agent_service.check_shift_transitions()`
- `_transition_shift_state()` -> `agent_service.transition_shift_state()`
- `_find_replacement()` -> `agent_service.find_replacement()`
- `_update_agent_welfare()` -> `agent_service.update_welfare_after_task()`
- `_increment_agent_budget()` -> `agent_service.increment_budget()`
- Welfare cache management -> agent_service maintains, dispatcher reads

**New dispatch flow:**
1. Request arrives (capability + optional department)
2. Dispatcher calls `agent_service.get_scored_candidates(capability, department)`
3. agent_service returns ranked candidates (filtered by shift/budget/welfare)
4. If no internal candidates -> dispatcher calls `fleet_service.get_available_nodes(capability)`
5. If no fleet -> dispatcher calls `fleet_service.get_available_providers(capability)`
6. Dispatcher picks best candidate, executes
7. After execution -> `agent_service.record_task_completion(agent_id, success, tokens_used)`
8. agent_service handles budget increment, welfare update, shift transition if needed

**Module recurring work pattern (e.g. Market Watch):**
```
Autonomy (job_service) -> "time to run market_analysis"
    |
AI Bridge (dispatcher) -> "who can do this?" asks agent_service + fleet_service
    |
agent_service -> "M.A.R.K.E.T. agent is active, budget OK"
    |
Bridge dispatches to M.A.R.K.E.T. -> executes Market Watch cycle
    |
agent_service.record_task_completion() -> tracks the work done
```

Every module follows the same pattern. No special plumbing per module.

---

### Module UI Responsibilities

#### Department HQ — "who" (internal workforce)

**Keeps:** Roster, org chart, agent detail, skills, identity, social, work tracking, knowledge, auth, models
**Gains from Starbase:**
- Agent profile modal popups (LCARS tablet frames: `bm-overlay > bm-shell > bm-frame`)
- Crew manifest (internal agents only)
- Agent welfare/C.R.E.E.D. reporting UI

**Tabs:** Overview | Departments | Agents | Training | Welfare | Models

All reads/writes via `agent_service.py`.

#### Starbase Command — "where" (fleet visualization + external resources)

**Keeps:** Node management, model control across fleet
**Loses:** Crew manifest, agent profiles (move to Department HQ)
**Gains:**
- Fleet Map (replaces deprecated Stations tab)
- Cloud provider management UI (was partially there before)
- Provider usage/tier dashboard

**Tabs:** Fleet Map | Nodes | Cloud Providers | Models | Usage

All reads/writes via `fleet_service.py`. Agent data shown on node detail panels links to Department HQ.

#### Autonomy — "what" (job command center)

**Keeps:** Approval queue, Telegram integration, browser automation
**Gains from agent_loop.py:**
- Full job registry (all jobs as manageable entries)
- Job enable/disable/reschedule from UI (currently read-only, becomes read-write)
- Budget reset job
- Execution history and health monitoring

**Tabs:** Dashboard | Jobs | Approvals | History | Telegram

All reads/writes via `job_service.py`.

---

### Fleet Map Design

World map with real-time pins showing the full compute footprint:

| Pin Type | Icon | Data Source | Click Action |
|----------|------|-------------|-------------|
| Hub | Starbase icon (pulsing) | Hardcoded home location (Kitchener) | Show hub stats |
| Node/Outpost | Ship icon | `fleet_nodes` table | Slide-out: specs, deployed agents, models |
| Cloud Provider | Company logo | `cloud_providers` table | Slide-out: tier, usage, budget, models |

Replaces the deprecated Stations tab in Starbase Command.

---

### Data Model Changes

#### `cloud_providers` table (new)

```sql
CREATE TABLE cloud_providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    logo_url TEXT,
    headquarters_city VARCHAR(100),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    provider_type VARCHAR(20) DEFAULT 'cloud',  -- cloud, edge, partner
    api_endpoint TEXT,
    api_key_env_var VARCHAR(100),  -- e.g. 'OPENAI_API_KEY' (never store actual key)
    tier VARCHAR(30) DEFAULT 'free',  -- free, pay-as-you-go, enterprise
    capabilities JSONB DEFAULT '[]',  -- ["chat","embedding","image_gen"]
    models_available JSONB DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'active',  -- active, inactive, degraded
    monthly_budget DECIMAL(10,2) DEFAULT 0,
    monthly_usage DECIMAL(10,2) DEFAULT 0,
    usage_reset_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### `remote_nodes` table (add columns)

```sql
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS latitude DECIMAL(9,6);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS longitude DECIMAL(9,6);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS location_label VARCHAR(100);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS node_type VARCHAR(20) DEFAULT 'starship';
-- node_type: outpost, starship, edge
```

#### `cloud_usage_log` table (new)

```sql
CREATE TABLE cloud_usage_log (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES cloud_providers(id),
    agent_id INTEGER REFERENCES agents(id),
    model_name VARCHAR(100),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    estimated_cost DECIMAL(10,6) DEFAULT 0,
    capability VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### LCARS Design Standards (from Starbase)

The Starbase modal popup system becomes a platform-wide standard:

```
bm-overlay > bm-shell > bm-frame + bm-content > bm-header + bm-body + bm-footer
```

- Set `--bm-accent` CSS variable for theming per module
- Reference implementation: Starbase `bridge.html` lines 9209-9249
- Department HQ agent profiles adopt this pattern
- Document in a shared `lcars-modals.md` design standard file

---

## Migration Phases

### Phase 1: Foundation (unblocks embedding pipeline)
- Create `job_service.py` with `register_job()`, `run_job()`, `reset_all_budgets()`
- Add budget reset job: daily zero-out of `current_task_count` at 04:00 UTC, reset cooldown agents whose budgets are now clear back to active
- Add `token_reset_at` enforcement: if past reset time, auto-zero on read
- Wire job_service into app.py startup alongside existing agent_loop (both run, no breakage)
- **Deliverable:** Embedding pipeline unblocked, budgets auto-reset daily

### Phase 2: agent_service expansion
- Move shift transition logic from bridge_dispatcher -> agent_service
- Move budget increment from bridge_dispatcher -> agent_service
- Move welfare updates from bridge_dispatcher -> agent_service
- Move replacement finding from bridge_dispatcher -> agent_service
- Add `get_scored_candidates()` for dispatcher to call
- Bridge dispatcher calls agent_service instead of doing SQL directly
- **Deliverable:** Single mutation layer established

### Phase 3: fleet_service + data model
- Create `fleet_service.py`
- Create `cloud_providers` table migration
- Create `cloud_usage_log` table migration
- Add lat/long columns to `remote_nodes`
- Move node management logic from Starbase routes into fleet_service
- Bridge dispatcher reads fleet_service for escalation candidates
- **Deliverable:** Fleet data model ready for map

### Phase 4: Starbase UI transformation
- Fleet Map tab (replaces Stations) — world map with pins for hub, nodes, cloud providers
- Cloud provider management UI (add/edit/configure providers)
- Provider usage + tier dashboard
- Node detail panels with deployed agents
- Move agent profile modals (LCARS tablet frames) to Department HQ
- Move crew manifest to Department HQ
- **Deliverable:** Starbase becomes visual fleet command center

### Phase 5: agent_loop.py decomposition
- Extract job implementations to owning modules (`register_jobs()` pattern)
- Each module registers its jobs with job_service at startup
- agent_loop.py shrinks to thin compatibility shim, then removed
- Autonomy UI becomes read-write (enable/disable/reschedule jobs)
- **Deliverable:** Monolith eliminated, Autonomy is true job command center

### Phase 6: Polish
- LCARS modal system documented as platform design standard
- Cloud provider logos on fleet map
- Fleet map click-through to Department HQ profiles
- Autonomy job health monitoring + alerting
- Budget burn rate visualization in Starbase
- **Deliverable:** Full coordination architecture complete

---

## Key Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Module relationship | Dept HQ = "who", Autonomy = "what", Starbase = "where" | Clean separation of concerns |
| Dispatcher role | Pure router, delegates all mutations | Prevents state management fragmentation |
| Module recurring work | Autonomy schedules -> Bridge dispatches -> agent executes | Uniform pattern, escalation works automatically |
| Starbase future | Fleet visualization hub with world map | Leverages existing visual design strengths |
| agent_loop.py | Decompose into job_service + module registrations | Eliminates 6,700-line monolith |
| Cloud providers | First-class entities with location, logo, tier | Enables fleet map visualization of full compute footprint |
| LCARS modals | Starbase pattern becomes platform standard | Best modal implementation, Department HQ adopts it |

---

## Risk Mitigation

- **Phase 1 runs alongside existing agent_loop** — no breaking changes until validated
- **Bridge dispatcher changes are internal refactors** — external API unchanged
- **Each phase is independently shippable** — can pause between phases
- **2 other Claude sessions active** — Phase 1 can proceed without conflicts (new files only)
- **Fleet map is Phase 4** — backend plumbing proven before building visual layer
