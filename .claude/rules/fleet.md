# Fleet Rules

**Authoritative fleet reference** — supercedes starbase.md for new code. Starbase.md kept for historical patterns.

## Architecture

Department HQ Fleet tab owns all fleet management (merged from Starbase Command 2026-04-08).
- 7 route files inside `tools/department_hq/`
- Hub = primary; nodes join via Headscale mesh (100.64.0.x)

## Mesh Node Map (ALWAYS use mesh IPs for inter-cluster calls)

Names below are the 2026-06-04 canonical set (display `node_name` + headscale `given_name`). `node_id` is unchanged (renames are display-only). Full roster + audit: KB #270521.

| Display name | mesh given_name | LAN/Public IP | Mesh IP | DB id | GPU / VRAM | RAM | Role |
|------|------|--------|---------|-----|-----|-----|------|
| Archie Starbase (hub) | archie-starbase | 192.168.1.200 | 100.64.0.4 | 68 | Quadro M4000 8GB | 128GB | Platform core / dispatch hub. `BRIDGE_URL=100.64.0.4:3000` |
| Outpost - United States | outpost-us | 76.13.107.109 | 100.64.0.2 | 93 | None | 8GB | CPU outpost (Ashburn). **SSH `kytran@`** |
| Starship - Defiant - USS-246 | starship-246 | 192.168.1.246 | 100.64.0.3 | 115 | RTX 3070 8GB (**Defiant**) | 32GB | LAN GPU, 7B. SSH `Famil@` |
| Starship - Runabout - USS-245 | starship-245 | 192.168.1.245 | 100.64.0.6 | 120 | RTX 3050 4GB (**Runabout**) | 12GB | LAN GPU, small. SSH `Famil@` |
| Outpost - Singapore | outpost-singapore | 156.67.217.86 | 100.64.0.5 | 125 | None | 8GB | CPU outpost |
| Outpost - Lithuania | outpost-lithuania | 72.62.112.210 | 100.64.0.7 | 126 | None | 8GB | CPU outpost |
| Outpost - United Kingdom | outpost-uk | 2.24.130.153 | 100.64.0.8 | 127 | None | 8GB | CPU outpost |
| Citadel - United States | citadel-us | 2.25.133.122 | 100.64.0.10 | 128 | None | 31GB | **DR warm-standby base** (boston-2): watch products + DR replica + ingress Caddy. SSH `root@` |
| Beacon | beacon | 2.25.170.252 | 100.64.0.11 | 129 | None | 4GB | Front-door ingress (Caddy). No Ollama/agents, `bridge_off` |

**NEVER** use public hostnames (`platform.kytranempowerment.com`) for inter-cluster traffic — Hostinger CDN caps at 60s, bypasses queue.

### Naming tiers & ship-class
- Tiers by role/scale: **Starbase** (hub) > **Citadel** (DR warm-standby base) > **Outpost** (CPU VPS, regional) > **Starship - `<class>` - USS-`<lan-octet>`** (LAN GPU) > **Beacon** (ingress satellite).
- GPU nodes auto-class from live `remote_nodes.gpu_vram_gb` via `ship_classes` table + `v_fleet_ship_class` view (migration 398). Ladder by VRAM: Runabout ≤4 / Nova 6 / Defiant 8 / Intrepid 12 / Constitution 16 / Galaxy 24 / Sovereign 48 / Dreadnought 80 / Armada (multi-GPU). Re-tune via `UPDATE ship_classes` (no deploy). Hub + CPU outposts = NULL class.

### Hub has THREE tailscale presences (don't confuse — KB #270520)
- `.4 archie-starbase` = host headscale tailscaled (`/var/lib/tailscale-hs`, `--tun=tailscale1`) — THE platform/dispatch hub (`BRIDGE_URL`, :3000, direct via public IP).
- `.1 archie-starbase-subnet` = the `archie_tailscale` Docker container (docker-compose.yml ~L714) — hub-LAN subnet router (`--advertise-routes=192.168.1.0/24 --ssh`). Route currently **Enabled=false** (dormant; platform reaches hub via `.4`). Do NOT delete — re-registers via authkey.
- `100.79.11.3` = host's Tailscale.com client — a SEPARATE tailnet, not the mesh.
- `.9 shuttle-kytran` = Kytran personal device (not a fleet node).

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
