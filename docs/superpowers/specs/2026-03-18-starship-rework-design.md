# Starship Module Rework — Design Spec

**Date:** 2026-03-18
**Task:** #1023 — Starship module rework — pull agents/stations from Bridge, stop generating fake crew
**Status:** Foundation build (Approach B — Surgical Refactor)

---

## 1. Problem Statement

The Starship module (72KB monolith, 1,900-line `routes.py`, 2,334-line inline template) generates fake crew data via `_generate_node_crew()` with 96 hardcoded names and random assignment. It duplicates Bridge logic (`MODULE_STATION_MAP`, `MODEL_SIZE_HINTS`, `get_agent_recommendations()`) instead of consuming Bridge as the single source of truth.

Bridge rules state: "Starship module = remote view of Bridge (should NOT generate own agents)."

## 2. Three-Layer Vision

The long-term architecture has three layers:

1. **Starbase (Archie hub)** — the mothership. Unique active roster system, full agent management, global delegation.
2. **Fleet nodes (Starships)** — remote machines on the network. Each runs locally with private data and local modules.
3. **Node operator view** — each person controls their own node's stations and agents. Simplified/compressed roster compared to Archie's full system.

Nodes are autonomous (local mode, private data, own modules) but stay connected to the hub so Archie can manage the global roster — assign agents cross-node, share vs. keep local.

**This rework builds Layer 1 + 2. Layer 3 (node operator control panel) is designed for but implemented later.**

## 3. Architecture & Data Flow

### Data Sources (single source of truth)

| Data | Source | Access Method |
|------|--------|---------------|
| Node registration, status, hardware | `remote_nodes` table | Direct DB query |
| Real agent roster, wellness, jobs | `agents` + `station_assignments` | `BridgeDispatcher.get_crew_manifest()` |
| Node-specific agent deployments | `node_agents` table (FK to `agents` via `hub_agent_id`) | Direct DB query + enrichment from manifest |
| Node agent configs, sync state | `node_agents.config_version`, `fleet_nodes` | Direct DB query |

### Data Flow

```
BridgeDispatcher.get_crew_manifest()
        │
        ▼
Starship routes import dispatcher
        │
        ├─► FLEET tab: hero Starbase stats + node cards
        │     └─► Click node → LCARS tablet modal
        │           └─► Real crew from node_agents JOIN agents
        │           └─► Real stations from station_assignments
        │
        └─► OPERATIONS tab: OTA push, sync, installers
              └─► Uses existing fleet_nodes/remote_nodes queries (kept as-is)
```

### Dispatcher Import Pattern

```python
from ai_bridge.bridge_dispatcher import BridgeDispatcher

dispatcher = BridgeDispatcher()
hub_manifest = dispatcher.get_crew_manifest()

# For a specific node's agents:
# SELECT na.*, a.display_name, a.model, a.shift_state, a.status
# FROM node_agents na
# JOIN agents a ON na.hub_agent_id = a.id
# WHERE na.node_id = %s
# Enriched with wellness/job data from hub_manifest
```

This matches how `crew_routes.py` already works (line 836: `manifest = dispatcher.get_crew_manifest()`).

## 4. File Structure

### New Layout

```
tools/starship/
├── __init__.py              — register_*_routes pattern (ADR-045)
├── routes.py                — main page + fleet overview API (~150 lines)
├── node_routes.py           — node status, settings, setup/onboarding (~300 lines)
├── crew_routes.py           — crew manifest, agent profiles via dispatcher (~200 lines)
├── ota_routes.py            — OTA push, sync, installers (~350 lines)
├── helpers.py               — shared utils (_compute_node_status, node lookups) (~100 lines)
└── templates/tools/starship/
    └── starship.html        — pure HTML (~500 lines, down from 2,334)

platform_v2/static/
├── css/starship.css         — extracted styles (~600 lines)
└── js/starship.js           — extracted JS (~800 lines)
```

### `__init__.py` Pattern

```python
from .routes import starship_bp
from .node_routes import register_node_routes
from .crew_routes import register_crew_routes
from .ota_routes import register_ota_routes

register_node_routes(starship_bp, login_required)
register_crew_routes(starship_bp, login_required)
register_ota_routes(starship_bp, login_required)

__all__ = ["starship_bp"]
```

Access control: `login_required` (not `admin_required`). Node ownership enforced per-request via `_get_node_for_user()`.

## 5. UI Design — Two Tabs

### Tab 1: FLEET

**Hero Starbase Section (top):**
- Archie Starbase banner with distinct visual treatment (teal accent, larger card)
- Live stats from dispatcher: total active agents, loaded models, VRAM/RAM usage, active jobs
- Count of connected nodes + online/offline indicators
- Visually separated from fleet grid — this is the mothership

**Fleet Node Grid (below hero):**
- One card per connected node from `remote_nodes WHERE is_active = true`
- Each card compact summary:
  - Node name + status badge (online/offline/degraded)
  - Agent count + active jobs count
  - Hardware one-liner (GPU, RAM)
  - Last heartbeat timestamp
- **Click card → LCARS tablet modal** with sub-tabs:
  - **STATUS** — full hardware specs, loaded models, resource usage
  - **CREW** — real agents from `node_agents JOIN agents`, station assignments, model, shift state, wellness
  - **STATIONS** — active stations on this node, who's assigned

### Tab 2: OPERATIONS

Three sections:

1. **OTA Push Panel**
   - Push agent config to node (`push-config` — kept)
   - Push code updates (`push-update` — kept)
   - Trigger model pull on node (`pull-model` — kept)

2. **Sync Status Panel**
   - Sync log per node (`sync-log` + `sync-status` — kept)
   - Config version tracking (`node_agents.config_version`)
   - Last successful sync timestamp

3. **Node Setup / Onboarding Panel**
   - Request new node (`request-node` — kept)
   - Setup instructions with install scripts (bash/powershell generators — kept)
   - Node package download (`download-node-package` — kept)
   - Version tracking (`client_version` vs `latest_node_version`)

## 6. Code Deletion vs. Preservation

### Deleted (~2,350 lines)

| Code | Lines | Reason |
|------|-------|--------|
| `_STARSHIP_FIRST_NAMES` + `_STARSHIP_LAST_NAMES` | ~96 | Fake name pools |
| `_generate_node_crew()` | ~130 | Random crew generation |
| `MODULE_STATION_MAP` | ~17 | Duplicates Bridge |
| `MODEL_SIZE_HINTS` | ~35 | Duplicates Bridge/dispatcher |
| `get_agent_recommendations()` | ~150 | Replaced by dispatcher data |
| `_add_single_agent_to_node()` fake logic | ~120 | Replaced by real node_agents queries |
| Inline CSS/JS in template | ~1,800 | Extracted to static files |

### Kept (relocated)

| Code | Destination | Lines |
|------|-------------|-------|
| OTA push endpoints (3) | `ota_routes.py` | ~200 |
| Sync log/status endpoints | `ota_routes.py` | ~100 |
| Node setup/onboarding (3) | `node_routes.py` | ~150 |
| Install script generators | `node_routes.py` | ~100 |
| Node status + settings | `node_routes.py` | ~150 |
| `_compute_node_status()` | `helpers.py` | ~30 |
| `_get_node_for_user()` variants | `helpers.py` | ~50 |

### New Code

| Code | File | Lines (est.) |
|------|------|-------------|
| Hero Starbase + fleet API | `routes.py` | ~150 |
| Crew manifest via dispatcher | `crew_routes.py` | ~200 |
| Extracted CSS | `starship.css` | ~600 |
| Extracted JS | `starship.js` | ~800 |
| Restructured HTML template | `starship.html` | ~500 |

### Net Result

- `routes.py`: 1,900 lines → ~1,100 lines across 6 focused Python files
- `starship.html`: 2,334 lines → ~500 lines + ~1,400 lines cacheable static assets
- Zero fake data. All crew/agent data from real DB + dispatcher.

## 7. DB Tables Used (No Schema Changes)

No migrations needed. All tables already exist:

- `remote_nodes` — node registration, heartbeats, hardware (existing)
- `node_agents` — agent deployments per node, FK to `agents` (existing)
- `agents` — the real roster (existing, read via dispatcher)
- `station_assignments` — station mapping (existing, read via dispatcher)
- `fleet_nodes` — legacy table, referenced by some OTA code (kept for compatibility)

## 8. Boundaries & Future Work

### In Scope (this rework)
- Delete all fake crew generation
- Import dispatcher for real crew data
- Split routes into 4 files + helpers
- Extract CSS/JS from template
- Restructure to 2 tabs (FLEET + OPERATIONS)
- Hero Starbase section with real stats
- Node cards with click-to-expand LCARS tablet modal
- Preserve all OTA/sync/onboarding functionality

### Out of Scope (future)
- Node operator control panel (Layer 3 — control your own node's stations/agents)
- Shared vs. local agent model (Archie delegates globally, nodes keep private)
- Simplified roster UI for nodes running in local mode
- Cross-node agent lending UI (mesh_routes.py exists but no Starship UI yet)

## 9. Success Criteria

1. Zero fake data — all agent/crew info comes from `agents` table via dispatcher or `node_agents` join
2. Hero Starbase shows real live stats from the hub
3. Node cards show real connected nodes with accurate status
4. Click-to-expand modal shows real crew with station assignments
5. All OTA push/sync/onboarding endpoints work unchanged
6. Template is pure HTML with extracted cacheable CSS/JS
7. Route files follow `register_*_routes(bp, decorator)` pattern
8. No regressions — existing node operators can still access and manage their nodes
