---
globs: ["platform_v2/tools/starbase/**", "ai_bridge/bridge_dispatcher.py", "platform_v2/tools/starship/**"]
---

# Starbase Command + Starship Rules (Updated 2026-03-19)

## Starbase File Structure
- `routes.py` — core routes (dashboard, stats, traffic, LLM monitor)
- `helpers.py` — shared caches (_get_cached_ollama_tags/ps/hw_capacity)
- `node_routes.py` — nodes, approval, assignments
- `station_routes.py` — stations, actions, benchmarks, agent profiles
- `agent_routes.py` — CRUD, skills, workload compliance max 3 jobs
- `crew_routes.py` — manifest, lounge, training, IAAE, model-control, node capacity
- `provider_routes.py` — ComfyUI, routing, providers
- `dispatch_routes.py` — activity, jobs, analytics
- `mission_routes.py` — SSE, command, profiles, flows
- `mesh_routes.py` — node lending, sync, cluster
- Pattern: `register_*_routes(bp, admin_required)` in `__init__.py` (ADR-045)

## Starship File Structure (reworked 2026-03-18)
- `routes.py` — 115 lines (fleet overview + starbase stats only)
- `helpers.py` — shared constants + node lookup functions
- `crew_routes.py` — crew manifest, agent profiles via dispatcher, node stations endpoint
- `node_routes.py` — node status, settings, setup/onboarding, station commands, disconnect
- `ota_routes.py` — OTA push, sync, model pull
- `__init__.py` — ADR-045 register_*_routes with login_required
- `starship.html` — ~500 lines pure HTML, 2 tabs (FLEET + OPERATIONS)
- `starship.css` — extracted styles + live glow indicators
- `starship.js` — extracted JS + hero stats, docked fleet, StationOps, unified cards

## Roster Rules (Decision #228, #229)
- `agents` table is single source of truth — 50 agents
- 1 agent = 1 station (DB constraint `idx_station_assignments_one_per_agent`)
- Shift states: active (hub), deployed (on node), barracked (reserve), off_duty, winding_down, cooldown
- ARCHIE = primary on COMMAND, Vigil = secondary (always)
- Starship COMMAND = solo captain (maxPrimary=1, maxAux=0)
- Deployed agents excluded from hub hardware groups — show only in node section
- Advisory notification when barracked ≤ 5 (no auto-creation — Decision #229)
- Agent creation is collaborative review, not automatic

## Dispatch & Orchestration
- `get_dispatcher()` singleton — NEVER instantiate `BridgeDispatcher()` directly
- `get_crew_manifest()` for all roster data (includes display_name, shift_state, station_codes, node info)
- Fleet agents (fleet:node_xxx:Name) excluded from hub manifest
- `ensure_model_ready()` auto warm-boots before dispatch (3-tier: GPU > CPU > cold)
- Escalation chain: home station → capability → cross-station → fleet node → cloud
- `_find_fleet_agent()` + `_dispatch_to_node()` for cross-node dispatch
- `model-control` endpoint accepts `node_id` — routes to node Ollama when provided
- ComfyUI VRAM swap: `_vram_swap_for_comfyui(node_db_id)` / `_vram_restore_after_comfyui()`

## Fleet Management
- `check_fleet_health()` — agent loop job #45, every 30s
- Node offline (heartbeat stale >2min): agents return to barracks, node_agents inactive
- Node online: agents restored if still in barracks, new assigned if not
- `_save_model_state()` / `_restore_model_state()` — persists loaded models for restart recovery
- Agent loop job #46 saves model state every 5m for hub + all online nodes
- `model_load_state` table tracks which models were loaded on which host
- Node heartbeat sends: cpu_model, gpu_model, gpu_vram_gb, ram_gb, ollama_models
- Node disconnect: DELETE endpoint returns agents to barracks, LCARS red alert confirm

## 10 Canonical Stations
COMMAND (#00e5ff), ANALYTICS (#8b5cf6), CREATIVE (#f472b6), ENGINEERING (#fbbf24), COMMUNICATIONS (#22d3ee), RESEARCH (#10b981), SECURITY (#ef4444), LOGISTICS (#f97316), DIPLOMATIC (#818cf8), OPERATIONS (#a3e635)

## UI Patterns
- StationOps shared component for all station panels (station-ops.js/css)
- StationOps accepts `dataUrl` for node-specific data, `maxPrimary`/`maxAux` overrides
- LCARS tablet modals: `bm-overlay` + `bm-shell` + `bm-frame` + `bm-content`
- Live data glow: `sc-live` (pulsing teal) vs `sc-static` (dim)
- Single status badge: ON DUTY / DEPLOYED / WORKING / BARRACKED / OFF DUTY
- Collapsible roster: purple (hub), baby blue (node), gray (barracks)
- `_renderUnifiedAgentCard()` — one card renderer for hub + node
- `openAgentProfileFromBridge(hubAgentId)` — always fetch from Starbase profile endpoint
- Model load/unload: LCARS confirm modal (cyan load, red unload)
- Node disconnect: LCARS red alert modal

## DB Gotchas
- `bridge_jobs`: uses `agent_name` (varchar, not agent_id), `completed_steps`/`total_steps`
- `agents`: `display_name` for UI, `name` for code. `shift_state` constraint includes 'deployed'
- `station_assignments`: unique index `idx_station_assignments_one_per_agent` (1 active per agent)
- `node_agents`: FK `hub_agent_id` → `agents.id`, `source_agent_id` → `agents.id`
- `remote_nodes`: `hostname` must be IP (not hostname), `deployment_mode` = 'starbase'|'starship'
- `model_load_state`: tracks loaded models per host for restart recovery
- Node RAM budget: 80% agents, 5% swap, 15% host, 0% security (managed from hub)
