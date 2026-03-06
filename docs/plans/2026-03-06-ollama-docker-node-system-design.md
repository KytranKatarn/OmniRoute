# Ollama Containerization & Node System Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Ollama moved from systemd to Docker, fleet hierarchy for multi-node deployment

---

## Fleet Hierarchy

| deployment_mode | Role | Priority | Example |
|----------------|------|----------|---------|
| `starbase` | Main Archie server, hosts platform, DB, all modules | 100 | 192.168.1.200 |
| `starship` | Compute donor node, shares resources to fleet | 50 | Windows/Linux desktop on LAN |
| `shuttle` | Mobile/thin client, observe only (future) | 10 | Android, tablet |

UI views map to roles:
- **Bridge Command** — Starbase operator (admin, full control)
- **Starship Command** — Node operator (sees contribution, read-only config)
- **Shuttle Command** — Mobile view (future, lightest interface)

---

## Part 1: Archie Ollama Container (Starbase)

### docker-compose.yml addition

New `archie_ollama` service:
- Image: `ollama/ollama:latest`
- Network: `archie_internal` (archie_network)
- GPU: nvidia, count: 1, capabilities: [gpu] (shared with ComfyUI)
- Volume: `/mnt/llm_drive/ollama:/root/.ollama` (Samsung 840 SSD, 110GB)
- Ports: `11434:11434` (LAN access for starship nodes + backward compat)
- Environment: `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_MAX_LOADED_MODELS=13`, `OLLAMA_NUM_PARALLEL=4`
- Restart: always

### Environment changes

| Variable | Old value | New value |
|----------|-----------|-----------|
| OLLAMA_HOST | `http://host.docker.internal:11434` | `http://archie_ollama:11434` |
| OLLAMA_PRIMARY | `host.docker.internal:11434` | `archie_ollama:11434` |

All 8+ AI bridge integration points read from env vars — no code changes needed.

### Migration steps

1. Add `archie_ollama` to `docker-compose.yml`
2. Update both `.env` files (root + platform_v2)
3. Stop + disable systemd Ollama service
4. `docker compose up archie_ollama`
5. Verify 18 models visible via `/api/tags`
6. Restart `archie_platform` to pick up new env
7. Verify Bridge dispatch, embeddings, warmup all work
8. Register Archie as starbase node in `remote_nodes` table

### Archie as Node Zero

Insert into `remote_nodes`:
- node_name: `archie-starbase`
- hostname: `192.168.1.200`
- deployment_mode: `starbase`
- approval_status: `approved`
- bridge_enabled: `true`
- bridge_priority: `100`
- ollama_available: `true`
- gpu_model: `Quadro M4000`
- gpu_vram_gb: `8`
- docker_available: `true`
- nvidia_docker: `true`

---

## Part 2: Starship Docker Package

### Deployment: `docker-compose.starship.yml`

Two containers:

| Container | Purpose |
|-----------|---------|
| `archie_ollama` | Ollama server, GPU passthrough if available |
| `archie_starship` | Python sidecar (~200 lines) — heartbeat, hardware scanner, dispatch receiver |

### First Boot Flow

1. User runs `docker compose up`
2. Starship-agent scans hardware (CPU, RAM, GPU via nvidia-smi, disk)
3. Calls Archie's `POST /api/nodes` with hardware profile + generated node token
4. Node appears as `pending` in Bridge Network tab
5. Admin approves in Network tab
6. Archie responds with: assigned models to pull, agent config, RAM budget rules
7. Starship-agent tells local Ollama to pull assigned models
8. Node goes `active`, starts heartbeat loop (30s interval)

### Heartbeat Payload

```json
{
  "node_id": "starship-xyz",
  "status": "active",
  "hardware": {
    "cpu_percent": 45.2,
    "ram_used_gb": 12.3,
    "ram_total_gb": 32.0,
    "gpu_usage_percent": 0,
    "gpu_vram_used_gb": 0,
    "disk_free_gb": 89.4
  },
  "ollama": {
    "loaded_models": ["mistral:7b"],
    "available_models": ["mistral:7b", "phi3.5:latest"]
  },
  "uptime_seconds": 3600
}
```

### Dispatch Flow (Archie to Starship)

1. Smart router selects starship node (has capacity + needed model)
2. Archie calls `http://<starship-ip>:11434/api/generate` directly
3. Response flows back through dispatcher
4. Job logged in `bridge_jobs` with `node_id` reference
5. Starship heartbeat confirms model state

### Hardware Validation

Archie scans the starship's hardware report and applies:
- RAM budget rules (ADR-078): 80/20 split, same as starbase
- Model sizing: only assigns models that fit the node's RAM/VRAM
- Agent allocation: assigns agents appropriate to the node's capabilities
- IAAE governance: same ethics/welfare rules apply fleet-wide

User CANNOT change these assignments. Archie decides.

---

## Part 3: Smart Router Integration

### New escalation tier

| Tier | Source |
|------|--------|
| 1-5 | Local models (loaded, swap, barracked) |
| **6** | **Starship nodes (bridge_enabled=true, active, has model)** |
| 7-11 | Cloud escalation (existing) |

### Routing logic for Tier 6

Query `node_ollama_models` + `remote_nodes` where:
- `is_active = true`
- `bridge_enabled = true`
- `approval_status = 'approved'`
- Last heartbeat < 90s ago
- Node has the requested model available

Pick node by: highest `bridge_priority`, then lowest current load, then lowest `avg_response_ms`.

### Failure handling

- Heartbeat timeout (90s) — mark `is_active=false`, skip in routing
- In-flight request timeout — retry on local or another starship
- Node comes back — heartbeat resumes, Archie re-validates, back to active

---

## Part 4: Starship Command UI

### Role detection

- `remote_nodes` table gets `user_id` column linking to user account
- When user hits `/tools/bridge`, route checks role
- Starship operator -> Starship Command layout
- Otherwise -> Bridge Command (Starbase)

### Starship Command tabs

| Tab | Content | Editable? |
|-----|---------|-----------|
| Status | Connection to Archie, uptime, last heartbeat, approval status | No |
| Hardware | CPU/RAM/GPU bars, disk usage, Archie's allocation vs total | No |
| Models | Models Archie assigned, load status, pull progress | No |
| Agents | Agents Archie assigned, activity, job count | No |
| Profile | Name, display name, avatar. Archie's recommendations | Yes (name/profile only) |

### What starship users CANNOT do

- Change model or agent assignments
- Access admin modules (Dev HQ, Dev Pipeline, Consciousness admin)
- Approve/deny other nodes
- Change RAM budget or IAAE rules

### What they CAN see

- Their contribution stats (jobs processed, uptime)
- Fleet-wide public stats (total nodes, total models)
- Their node's job history
- Archie's recommendations for their hardware

### LCARS theme

- Distinct accent color (teal/green vs Bridge's gold/amber)
- Header: "STARSHIP COMMAND" with node name
- Simpler layout than Bridge Command

---

## Part 5: Network Tab Enhancements

### Existing endpoints (enhance)

- `GET /api/nodes` — already returns node list with hardware
- `POST /api/nodes` — registration (used by starship first boot)
- `POST /api/nodes/{id}/approve` — admin approval
- `PUT /api/nodes/{id}` — update node config

### New endpoints

- `GET /api/nodes/{id}/models` — live model list from node's Ollama
- `GET /api/nodes/{id}/health` — real-time hardware from last heartbeat
- `POST /api/nodes/{id}/dispatch-test` — send test prompt to verify connectivity

### Database

Existing tables sufficient:
- `remote_nodes` — node registry + hardware + approval
- `node_ollama_models` — per-node model inventory
- `node_station_assignments` — agent/station mapping per node
- `node_regional_preferences` — latency, preferred hours

New column: `remote_nodes.user_id` (link to user account for Starship Command)

---

## Implementation Order

1. **Containerize Archie's Ollama** — fixes current 500 error, docker-compose addition
2. **Register Archie as starbase node** — insert into remote_nodes
3. **Build starship Docker package** — docker-compose.starship.yml + sidecar
4. **Update smart router** — add Tier 6 shuttle node routing
5. **Build Starship Command UI** — role-based view in Bridge module
6. **Test with Windows machine on LAN**
