# Fleet Rules

**Authoritative fleet reference** — supercedes starbase.md for new code. Starbase.md kept for historical patterns.

## Architecture

Department HQ Fleet tab owns all fleet management (merged from Starbase Command 2026-04-08).
- 7 route files inside `tools/department_hq/`
- Hub = primary; nodes join via Headscale mesh (100.64.0.x)

## Mesh Node Map (ALWAYS use mesh IPs for inter-cluster calls)

| Node | LAN IP | Mesh IP | GPU | RAM | Role |
|------|--------|---------|-----|-----|------|
| Hub | 192.168.1.200 | 100.64.0.4 | Quadro M4000 8GB | 128GB | Platform core, large models |
| Outpost-us | 76.13.107.109 | 100.64.0.2 | None | 8GB | VPS standalones, small CPU agents |
| Starship-246 | 192.168.1.246 | 100.64.0.3 | RTX 3070 8GB | 32GB | Mid-tier 7B GPU agents |
| Starship-245 | 192.168.1.245 | 100.64.0.6 | RTX 3050 Laptop 4GB | 12GB | Light GPU, small models |

**NEVER** use public hostnames (`platform.kytranempowerment.com`) for inter-cluster traffic — Hostinger CDN caps at 60s, bypasses queue.

## Fleet Route Files (`tools/department_hq/`)

| File | Purpose |
|------|---------|
| `fleet_dashboard_routes.py` | Overview, stats, map |
| `fleet_node_routes.py` | Node status, settings, onboarding, disconnect |
| `fleet_crew_routes.py` | Crew manifest, agent profiles, node stations |
| `fleet_mesh_routes.py` | Node lending, sync, Headscale mesh |
| `fleet_provider_routes.py` | Cloud providers, routing, ComfyUI |
| `fleet_dispatch_routes.py` | Cross-node dispatch, activity, analytics |
| `fleet_mission_routes.py` | SSE, command, profiles, flows |
| `fleet_ota_routes.py` | OTA push, sync, model pull |
| `fleet_helpers.py` | Shared constants + node lookup functions |

## Model Tiers by Node

| Tier | Nodes | Models |
|------|-------|--------|
| GPU small | Hub + Starship-246 + Starship-245 | `qwen2.5:1.5b`, `llama3.2:3b` |
| GPU mid | Starship-246 | `qwen2.5:7b`, `mistral:7b` |
| GPU large | Hub | `gemma3:12b`, `dolphin3:latest` + ComfyUI SDXL |
| CPU only | Outpost-us (VPS) | `qwen2.5:1.5b` (no GPU) |

## Cross-Node Dispatch

- `_find_fleet_agent()` + `_dispatch_to_node()` — cross-node dispatch in `fleet_dispatch_routes.py`
- Fleet agents keyed as `fleet:node_xxx:Name` — excluded from hub manifest
- `model-control` endpoint accepts `node_id` — routes to node Ollama when provided
- Escalation tier order: hub home dept → capability → cross-dept → **fleet node** → cloud

## Node Health + Lifecycle

- `check_fleet_health()` — job #45, every 30s
- Node offline (heartbeat stale >2min): agents → barracks, `node_agents` inactive
- Node online: agents restored from barracks; `_restore_model_state()` reloads models
- Heartbeat payload: `cpu_model, gpu_model, gpu_vram_gb, ram_gb, ollama_models`
- `model_load_state` table: tracks loaded models per host for restart recovery

## DB Tables (Fleet-specific)

| Table | Key columns |
|-------|-------------|
| `remote_nodes` | `hostname` (MUST be IP, not hostname), `deployment_mode`, `mesh_ip` |
| `node_agents` | `hub_agent_id`, `source_agent_id`, `node_id` |
| `model_load_state` | `node_host`, `model_name`, `loaded_at` |

## Headscale Mesh Admin

- Headscale UI: `http://192.168.1.200:8095` (or mesh.kytranempowerment.com)
- Enroll new node: `headscale nodes register --user default --key <machinekey>`
- Mesh IP assignment: auto from `100.64.0.0/10` range

## Key Gotchas

- `remote_nodes.hostname` MUST be IP (e.g. `192.168.1.246`) — NOT `starship-246.local`
- OTA URL bug: CORRECT path is `/tools/department-hq/api/fleet/checkpoints/<file>`. WRONG: `/api/fleet/checkpoints/<file>` returns 200 + HTML login page (KB #266408)
- ComfyUI VRAM swap: unload Ollama GPU models before SDXL, restore after
- K.I.N. auto-rest at >80% capacity (task_queue_limit=500, trigger at 400)
- After OTA model pull: manually update `extra_capabilities.comfyui_models` JSONB for the node
- Starship-246 SSH: `Famil@192.168.1.246` (different username than hub)
- FLEET_RESOURCE_ROUTING_ENABLED env gates fleet resource routing enforcement
