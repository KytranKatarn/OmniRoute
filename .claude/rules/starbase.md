---
globs: ["platform_v2/tools/department_hq/fleet_*.py", "platform_v2/tools/department_hq/templates/department_hq.html"]
---

# Fleet Management — Department HQ Fleet Tab (Updated 2026-04-15)

## History
Starbase Command + Starship + A.R.M.A.D.A. fully merged into Department HQ (2026-04-08).
Old Starbase/Starship modules are commented out in `module_registry.py`.
Old URLs redirect via `app.py` `starship_compat_redirect`.

## Department HQ — 14 Tabs
Overview, Org Chart, Roster, K.I.N., C.R.E.E.D., S.I.G.N.A.L., S.C.O.U.T., Autonomy, **A.R.M.A.D.A.** (Fleet lives here), Contractors, COMs, Online Presence, V.I.G.I.L., Approvals

## Fleet Tab File Structure (inside `tools/department_hq/`)
- `fleet_dashboard_routes.py` — fleet overview, stats, map
- `fleet_node_routes.py` — node status, settings, setup/onboarding, disconnect
- `fleet_crew_routes.py` — crew manifest, agent profiles, node stations
- `fleet_mesh_routes.py` — node lending, sync, cluster (Headscale mesh)
- `fleet_provider_routes.py` — cloud providers, routing, ComfyUI
- `fleet_dispatch_routes.py` — cross-node dispatch, activity, analytics
- `fleet_mission_routes.py` — SSE, command, profiles, flows
- `fleet_ota_routes.py` — OTA push, sync, model pull
- `fleet_helpers.py` — shared constants + node lookup functions

## Fleet Node Management
- `check_fleet_health()` — agent loop job #45, every 30s
- Node offline (heartbeat stale >2min): agents return to barracks, node_agents inactive
- Node online: agents restored if still in barracks, new assigned if not
- `_save_model_state()` / `_restore_model_state()` — persists loaded models for restart recovery
- Agent loop job #46 saves model state every 5m for hub + all online nodes
- `model_load_state` table tracks which models were loaded on which host
- Node heartbeat sends: cpu_model, gpu_model, gpu_vram_gb, ram_gb, ollama_models
- Node disconnect: DELETE endpoint returns agents to barracks, LCARS red alert confirm

## Cross-Node Dispatch
- `_find_fleet_agent()` + `_dispatch_to_node()` for cross-node dispatch
- Fleet agents (fleet:node_xxx:Name) excluded from hub manifest
- `model-control` endpoint accepts `node_id` — routes to node Ollama when provided
- ComfyUI VRAM swap: `_vram_swap_for_comfyui(node_db_id)` / `_vram_restore_after_comfyui()`
- Escalation reaches fleet tier via Department HQ dispatcher (home dept → capability → cross-dept → **fleet node** → cloud)

## Station Panels (Legacy UI)
- StationOps shared component (station-ops.js/css) still renders in Fleet tab
- 10 station colors remain for backward-compatible UI rendering
- Department HQ is the source of truth for agent assignments — station panels are display only

## UI Patterns
- LCARS tablet modals: `bm-overlay` + `bm-shell` + `bm-frame` + `bm-content`
- Live data glow: `sc-live` (pulsing teal) vs `sc-static` (dim)
- Single status badge: ON DUTY / DEPLOYED / WORKING / BARRACKED / OFF DUTY
- Model load/unload: LCARS confirm modal (cyan load, red unload)
- Node disconnect: LCARS red alert modal

## DB Tables (Fleet-specific)
- `node_agents`: FK `hub_agent_id` → `agents.id`, `source_agent_id` → `agents.id`
- `remote_nodes`: `hostname` must be IP (not hostname), `deployment_mode` = 'starbase'|'starship'
- `model_load_state`: tracks loaded models per host for restart recovery
- Node RAM budget: 80% agents, 5% swap, 15% host, 0% security (managed from hub)
