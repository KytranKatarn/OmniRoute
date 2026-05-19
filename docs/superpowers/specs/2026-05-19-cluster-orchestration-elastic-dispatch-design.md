# Cluster Orchestration & Elastic Agent Dispatch
**Project #352 | Date: 2026-05-19 | Status: Design Approved**

---

## Overview

Universal agent elasticity across the A.R.C.H.I.E. cluster. Every agent in every department becomes eligible for overflow work when idle. Every capability can generate queue pressure that activates dormant capacity. Every node participates automatically.

V.E.R.I.F.Y. backlog pool (hub + Starship-245 + Starship-246) is the proof of concept. This system generalises that pattern platform-wide — no hardcoded agent lists, no capability restrictions.

---

## Unified Agent Identity Rule

**One agent = one DB row, one stats record, one character, one welfare profile. Always.**

Overflow work is the SAME agent picking up secondary capability dispatches on additional nodes — not a new agent. There are no `-B` variants, no clones, no split identities.

- V.E.R.I.F.Y. handles both `fact_check` AND `fact_check_backlog` — same agent_id, all stats unified
- B.I.A.S. handles both `bias_analysis` AND `bias_backlog` — same agent
- L.O.C.A.L. handles both `geo_extraction` AND `geo_backlog` — same agent
- Any agent in any department that picks up overflow work still shows as itself in work history, welfare tracking, and the roster

In the Fleet tab UI, overflow shows as a mode label on the existing agent card: `V.E.R.I.F.Y. [⟳ backlog]` — not a separate card. Stats, dispatch counts, performance metrics all aggregate under the one agent_id.

**V.E.R.I.F.Y.-B (id=370) has been deactivated (2026-05-19).** V.E.R.I.F.Y. (id=116) now runs on Hub + Starship-245 + Starship-246 via `node_agents`. Migration #385 is superseded — do not create new -B agents.

---

## What Gets Built

Three components, no changes to the hot dispatch path:

1. **`cluster_orchestration_worker`** — new DHQ APScheduler job (60s)
2. **Two new DB tables** — config + live state
3. **Fleet tab panel** — "CLUSTER ORCHESTRATION" with full read/write/control UI

---

## Data Layer

### `cluster_orchestration_config`
Stores thresholds and manual controls. Scoped hierarchy: node > agent > capability > global. Manual pause always wins over computed score.

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `scope` | varchar | `global` | `global`, `agent`, `capability`, `node` |
| `agent_id` | int FK | NULL | NULL = applies to all agents |
| `capability` | varchar | NULL | NULL = applies to all capabilities |
| `node_id` | int FK | NULL | NULL = applies to all nodes |
| `idle_threshold_minutes` | int | 5 | Agent idle > N min → eligible |
| `utilization_threshold_pct` | float | 60 | Node < X% utilized → eligible |
| `queue_pressure_threshold` | int | 10 | Pending queue > N → activate |
| `idle_weight` | float | 0.3 | Signal weight (sum to 1.0) |
| `utilization_weight` | float | 0.3 | Signal weight |
| `queue_pressure_weight` | float | 0.4 | Signal weight |
| `overflow_enabled` | bool | true | Master switch for this scope |
| `overflow_paused` | bool | false | Manual pause from Fleet tab |
| `priority_boost` | int | 0 | Manual queue priority bump |
| `max_overflow_concurrent` | int | 3 | Max simultaneous overflow dispatches per agent |

### `agent_overflow_state`
Live computed state. Written every 60s by the worker. Read by the dispatcher's scoring formula.

| Column | Type | Purpose |
|--------|------|---------|
| `agent_id` | int FK | Which agent |
| `capability` | varchar | Which overflow capability is active |
| `overflow_score` | float | 0.0–1.0 computed from all three signals |
| `is_active` | bool | True when score ≥ 0.5 and not paused |
| `activated_at` | timestamptz | When it last flipped active |
| `expires_at` | timestamptz | TTL = NOW() + 90s (cleared if worker stops) |
| `dispatches_sent` | int | Count this overflow session |
| `node_id` | int FK | Which node this agent runs on |
| `reason` | jsonb | `{idle_mins, util_pct, queue_depth, manual_boost}` |

Unique constraint: `(agent_id, capability)`.

---

## Orchestration Worker

**Job:** `cluster_orchestration_worker`
**Schedule:** Every 60s
**Constraints:** `max_instances=1`, `coalesce=True`
**Location:** `platform_v2/tools/department_hq/jobs.py`

### Five passes per cycle

**Pass 1 — Node signals**
For each online fleet node (`remote_nodes` WHERE `last_heartbeat > NOW()-2min`):
- `node_util = fleet_resource_router.utilization_pct(node)` ← existing function

**Pass 2 — Agent idle signals**
For each active agent (`agents` WHERE `shift_state IN ('active','deployed')`):
- `recent_dispatches = COUNT(*) FROM task_execution_log WHERE agent_name=X AND started > NOW()-5min`
- `idle_minutes = EXTRACT(EPOCH FROM NOW()-MAX(started))/60 FROM task_execution_log WHERE agent_name=X`

**Pass 3 — Queue pressure signals**
For each capability with pending work:
- `queue_depth = COUNT(*) FROM dispatch_pending_queue WHERE status='pending' AND capability=X`
- Extended: pluggable backlog registry (wtf.articles unverified, future products)

**Pass 4 — Compute and write**
For each `(agent, node, capability)` where `agent_skills` has that capability:

```
idle_score    = min(1.0, idle_minutes / idle_threshold)
util_score    = max(0.0, 1.0 - node_util / util_threshold)
queue_score   = min(1.0, queue_depth / queue_threshold)

overflow_score = (idle_weight × idle_score) +
                 (util_weight × util_score) +
                 (queue_weight × queue_score)

is_active = overflow_score ≥ 0.5
            AND NOT paused (from config hierarchy)
            AND dispatches_sent < max_overflow_concurrent
```

UPSERT `agent_overflow_state`. Delete rows WHERE `expires_at < NOW()`.

**Pass 5 — Alerts**
If `newly_activated_count ≥ 5` in one cycle: Telegram ping to A.R.C.H.I.E.:
`"Cluster overflow activated: N agents across M capabilities (top queue: fact_check_backlog=83)"`

### Dispatcher integration

In `department_coordinator.select_agent()`, after computing the existing scoring formula, add overflow bonus from a module-level cache (refreshed every 60s, zero per-dispatch DB queries):

```python
if overflow_cache.get((agent.id, capability), {}).get("is_active"):
    score += 0.4  # enough to beat a busy home agent, not a fresh one
```

This is the only change to the hot dispatch path. One dict lookup per agent per dispatch.

---

## Fleet Tab Panel — "CLUSTER ORCHESTRATION"

Added to the existing Fleet tab below WTF AGENT STATUS. LCARS teal accent. Auto-refreshes every 30s.

### Layout

**Status bar**
```
● ORCHESTRATION ACTIVE   Last scan: 14s ago   [▶ Trigger Now]   [⏸ Global Pause]
```

**Queue Pressure grid**
One bar per capability with pending work. Green → amber → red as depth approaches threshold. Click opens config drawer.
```
fact_check_backlog  ████████░░  83/100   [⬆ Boost]
bias_backlog        ███░░░░░░░  31/100   [⬆ Boost]
research            █░░░░░░░░░   4/100   [⬆ Boost]
```

**Agent Overflow grid**
One card per agent in the overflow system — every agent, every department. Shows: node, overflow_score gauge, active capability, idle time, node utilization, dispatches sent, pause button.

Cards are grouped by department. Inactive agents (score < threshold) shown dimmed. Any agent from any department can appear here.

**Activation log**
Last 20 events with timestamp, agent, capability, score, reason.

### Config drawer (slides in from right)
Per-scope (global / agent / capability / node). Controls:
- Enable/disable toggle
- Threshold sliders: idle minutes, utilization %, queue depth
- Weight knobs (idle / utilization / queue pressure)
- Max concurrent overflow dispatches
- Manual pause

### API endpoints

```
GET  /tools/department-hq/api/orchestration/status
     → {agents: [{id, name, dept, node, score, is_active, capability, reason}],
        queues: [{capability, depth, threshold}],
        last_scan, global_paused}

GET  /tools/department-hq/api/orchestration/config
     → {global: {...}, overrides: [{scope, agent_id, capability, ...}]}

POST /tools/department-hq/api/orchestration/config
     body: {scope, agent_id?, capability?, node_id?, ...thresholds}

POST /tools/department-hq/api/orchestration/pause
     body: {agent_id?, capability?}   ← NULL = global pause

POST /tools/department-hq/api/orchestration/boost
     body: {capability, duration_minutes}  ← temporary priority_boost

POST /tools/department-hq/api/orchestration/trigger
     → runs one worker cycle synchronously, returns summary
```

---

## Implementation Files

| File | Change |
|------|--------|
| `database/migrations/NNN_cluster_orchestration.sql` | New tables: `cluster_orchestration_config`, `agent_overflow_state` |
| `platform_v2/services/cluster_orchestration_service.py` | Score computation, config hierarchy resolution, cache management |
| `platform_v2/tools/department_hq/jobs.py` | New `cluster_orchestration_worker` job (5 passes) |
| `platform_v2/tools/department_hq/fleet_orchestration_routes.py` | 6 new endpoints |
| `platform_v2/services/department_coordinator.py` | +3 lines: overflow cache lookup + score bonus |
| `platform_v2/templates/tools/department_hq.html` | Fleet tab: new CLUSTER ORCHESTRATION panel |
| `platform_v2/static/js/department-hq-fleet.js` | Panel rendering, config drawer, 30s refresh |

---

## Build Sequence

1. Migration — tables
2. `cluster_orchestration_service.py` — score engine + config hierarchy
3. `jobs.py` — worker (5 passes, writes to state table)
4. `department_coordinator.py` — overflow cache + score bonus (+3 lines)
5. `fleet_orchestration_routes.py` — 6 endpoints
6. Fleet tab panel — read-only first (status + queues + agent cards)
7. Config drawer + controls (pause, boost, trigger, threshold sliders)
8. Telegram alert integration

---

## What This Enables

Every agent across all 17 departments and all fleet nodes participates in cluster-wide load balancing. When Engineering is busy and Research is idle, D.A.R.W.I.N. absorbs `code_review` overflow. When Creative is quiet, M.U.S.E. picks up `summarization` backlog. The cluster self-optimises continuously.

The V.E.R.I.F.Y. backlog pool (fact_check_backlog across hub + Starship-245 + Starship-246) was built manually. This system makes that automatic for every capability, every agent, every node — forever.

---

*ADR-610 logged. Project #352 in Dev HQ.*
