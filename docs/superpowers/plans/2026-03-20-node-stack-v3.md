# ARCHIE Node Stack v3.0 — Implementation Plan

**Created:** 2026-03-20 | **Status:** Planning | **Priority:** HIGH
**Current:** v2.2.0 (5 containers, 11 sync types, OTA operational)
**Target:** v3.0 (full remote observability, ComfyUI management, VPN/SSH, auto-start)

---

## Phase 1: Observability (HIGHEST PRIORITY — Week 1-2)

**Goal:** See what's happening on nodes without SSH/RDP.

### Task 1.1: Self-Diagnostics Endpoint
- **File:** `node_client/node_api.py`
- **Complexity:** Low (2-3h)
- **What:** `GET /diagnostics` → disk space, GPU health, container states, Ollama models, uptime, sync timestamps

### Task 1.2: Hub Proxy for Diagnostics
- **File:** `platform_v2/tools/starship/node_routes.py`
- **Complexity:** Low (1-2h)
- **Depends:** 1.1
- **What:** `GET /api/nodes/<id>/diagnostics` proxies to node API

### Task 1.3: Container Health Dashboard
- **Files:** `starship.js`, `starship.html`
- **Complexity:** Medium (3-4h)
- **Depends:** 1.2
- **What:** LCARS panel in node modal — 5 containers with green/red/yellow, disk/VRAM/RAM bars

### Task 1.4: Live Log Streaming
- **Files:** `node_sync.py`, `node_api.py`, `ota_routes.py`, `node_routes.py`
- **Complexity:** High (6-8h)
- **Depends:** 1.1
- **What:** New `log_request` sync type. Hub requests logs → node sends back via ACK payload. UI button to fetch and display logs in LCARS pre-formatted block.

### Task 1.5: Download Progress Reporting
- **File:** `node_client/node_sync.py`
- **Complexity:** Medium (3-4h)
- **What:** Stream Ollama/ComfyUI downloads, write progress to local `download_progress` table. `GET /downloads` on node API. Hub proxy endpoint.

### Task 1.6: Non-Blocking Heartbeat Thread (DO FIRST)
- **File:** `node_client/node_sync.py`
- **Complexity:** Medium (2-3h)
- **What:** Extract heartbeat into `threading.Thread`. Heartbeat runs every 30s regardless of sync handler state. Fixes the "node appears offline during model downloads" problem.

---

## Phase 2: ComfyUI Integration (Week 3-4)

**Goal:** Full model management from Starship UI, cross-node image generation.

### Task 2.1: ComfyUI Model Inventory
- **Files:** `node_api.py`, `node_routes.py`
- **Complexity:** Medium (4-5h)
- **What:** `GET /comfyui/models` scans checkpoints/, loras/, vae/, controlnet/. Hub proxy at `/api/nodes/<id>/comfyui-models`.

### Task 2.2: ComfyUI Model Management UI
- **Files:** `starship.js`, `starship.html`
- **Complexity:** High (6-8h)
- **Depends:** 2.1, 2.3
- **What:** Grid showing models across hub + all nodes. Download/delete buttons per model per node. Type filter (checkpoint, LoRA, VAE, ControlNet).

### Task 2.3: New Sync Types for ComfyUI
- **Files:** `node_sync.py`, `ota_routes.py`
- **Complexity:** Medium (3-4h)
- **Depends:** 2.1
- **What:** `comfyui_model_download` (with progress), `comfyui_model_delete`. Hub trigger endpoints.

### Task 2.4: Cross-Node ComfyUI Dispatch
- **Files:** `bridge_dispatcher.py`, `node_api.py`
- **Complexity:** High (8-10h)
- **Depends:** 2.1, Bridge recovery (#170)
- **What:** `POST /comfyui/generate` on node API. Bridge dispatcher routes image gen to node with best available GPU. VRAM swap logic for node-side.

---

## Phase 3: Network & Security (Week 5-6)

**Goal:** External nodes, SSH management, API security.

### Task 3.1: WireGuard VPN Auto-Config
- **Files:** New `vpn_setup.py`, `node_routes.py`
- **Complexity:** High (8-10h)
- **What:** Hub as WireGuard server, nodes as peers. New `vpn_config` sync type. Auto-detect LAN vs external. DB columns: `vpn_public_key`, `vpn_assigned_ip`.

### Task 3.2: SSH Key Management UI
- **Files:** `node_routes.py`, `starship.js`
- **Complexity:** Medium (4-5h)
- **What:** New sync types `ssh_key_add`, `ssh_key_remove`. LCARS modal with key list, add/revoke buttons.

### Task 3.3: API Key Rotation
- **Files:** `node_sync.py`, `node_routes.py`
- **Complexity:** Medium (3-4h)
- **What:** Two-phase rotation — push new key, old key invalidated only after ACK.

### Task 3.4: TLS for Node API
- **Files:** `node_api.py`, `docker-compose.node.yml`
- **Complexity:** Medium (3-4h)
- **What:** Self-signed certs, HTTPS on port 3001. Hub stores cert fingerprint.

---

## Phase 4: Reliability & Auto-Start (Week 4-5, parallel with 2/3)

**Goal:** Nodes survive reboots, recover from crashes.

### Task 4.1: Windows Service Installer
- **Files:** New `windows_service.py`, installer
- **Complexity:** Medium (4-5h)
- **What:** Scheduled Task that ensures Docker Desktop + `docker compose up -d` on boot.

### Task 4.2: Linux systemd Unit File
- **Files:** New `archie-node.service`, `install-node.sh`
- **Complexity:** Low (1-2h)
- **What:** systemd unit: `After=docker.service`, `ExecStart=docker compose up -d`.

### Task 4.3: Graceful Shutdown
- **File:** `node_sync.py`
- **Complexity:** Low (2-3h)
- **Depends:** 1.6
- **What:** SIGTERM/SIGINT handlers, finish current sync, send "shutting_down" heartbeat.

### Task 4.4: Health Check Watchdog
- **File:** `node_sync.py`
- **Complexity:** Medium (3-4h)
- **Depends:** 1.6
- **What:** Watchdog thread checks each container every 60s, auto-restarts unhealthy ones. Max 3 restarts/hour circuit breaker.

---

## Phase 5: Deployment & Scaling (Week 7-8)

**Goal:** One-click provisioning, cluster-aware dispatch.

### Task 5.1: Fix Node Provisioning (#169)
- **Complexity:** High (6-8h)
- **Depends:** Phase 1
- **What:** Fix documented bugs, re-verify all code, build .exe, test on .245.

### Task 5.2: Pre-Built Docker Images
- **Complexity:** Medium (4-5h)
- **What:** Push `archie-node-sync:3.0` and `archie-node-api:3.0` to registry. No build step on nodes.

### Task 5.3: Node Templates
- **Complexity:** Medium (3-4h)
- **Depends:** 5.1
- **What:** GPU Full Stack / CPU-Only / ComfyUI-Only templates during provisioning.

### Task 5.4: Cluster-Aware Load Balancing
- **Files:** `bridge_dispatcher.py`, `smart_router.py`
- **Complexity:** High (8-10h)
- **Depends:** Phase 1, Bridge recovery
- **What:** Score = `priority * 0.3 + vram_free * 0.3 + ram_free * 0.2 + (1 - job_load) * 0.2`. Prefer node with model already loaded.

---

## New Sync Types (6 new → 17 total)

| Type | Phase | Purpose |
|------|-------|---------|
| `log_request` | 1 | Request container logs |
| `comfyui_model_download` | 2 | Download model from URL |
| `comfyui_model_delete` | 2 | Delete a model file |
| `vpn_config` | 3 | Push WireGuard config |
| `ssh_key_add` | 3 | Distribute SSH key |
| `ssh_key_remove` | 3 | Revoke SSH key |

## New Node API Endpoints (4 new)

| Endpoint | Phase | Purpose |
|----------|-------|---------|
| `GET /diagnostics` | 1 | Full node health snapshot |
| `GET /downloads` | 1 | Active download progress |
| `GET /comfyui/models` | 2 | ComfyUI model inventory |
| `POST /comfyui/generate` | 2 | Proxy image gen to local ComfyUI |

## DB Schema Changes

```sql
-- Hub: VPN support
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS vpn_public_key VARCHAR(64);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS vpn_assigned_ip INET;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS vpn_endpoint VARCHAR(100);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS shutdown_requested BOOLEAN DEFAULT FALSE;

-- Node: Progress + watchdog tracking
CREATE TABLE IF NOT EXISTS download_progress (
  id SERIAL PRIMARY KEY,
  download_type VARCHAR(20) NOT NULL,
  item_name VARCHAR(200) NOT NULL,
  total_bytes BIGINT,
  completed_bytes BIGINT DEFAULT 0,
  status VARCHAR(20) DEFAULT 'downloading',
  started_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS container_restarts (
  id SERIAL PRIMARY KEY,
  container_name VARCHAR(50) NOT NULL,
  reason TEXT,
  restarted_at TIMESTAMP DEFAULT NOW()
);
```

## Total Effort: 22 tasks, ~88-115 hours

| Phase | Hours |
|-------|-------|
| 1: Observability | 18-24 |
| 2: ComfyUI | 21-27 |
| 3: Network & Security | 18-23 |
| 4: Reliability | 10-14 |
| 5: Deployment | 21-27 |

## Implementation Order

```
Phase 1 (FIRST — everything depends on seeing what's happening)
  ├── 1.6 heartbeat thread (FIRST — unblocks everything)
  ├── 1.1 diagnostics endpoint
  ├── 1.2 hub proxy
  ├── 1.3 container health UI
  ├── 1.5 download progress (parallel)
  └── 1.4 log streaming (last)

Phase 2 + 4 (parallel)
  ├── 2.1 → 2.3 → 2.2 → 2.4
  └── 4.1, 4.2, 4.3, 4.4

Phase 3 (after observability)
  ├── 3.3 API key rotation (quick win)
  ├── 3.2 SSH keys
  ├── 3.4 TLS
  └── 3.1 VPN (most complex, last)

Phase 5 (after everything else)
  └── 5.1 → 5.2 → 5.3 → 5.4
```
