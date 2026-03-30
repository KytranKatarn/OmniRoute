# Fleet Deployment System — Design Spec

**Date:** 2026-03-30
**Status:** Draft — Pending User Approval
**Supersedes:** Projects #114, #121, #160, #163, #169, #172, #173 (all cancelled via Decision #258)
**Decision:** #346 — Global Fleet Taxonomy (Outposts, Starships, Satellites)

---

## 1. Problem Statement

A.R.C.H.I.E. needs a distributed node system that has failed 7 times across 7 cancelled projects. Every attempt suffered from the same root causes: no unified architecture, one-size-fits-all deployment, untested claims, and incremental patching instead of proper design.

This spec defines a profile-based, adaptive deployment system that works for all three node types — from a $5 VPS in Frankfurt to a GPU workstation on the LAN to a phone in someone's pocket.

## 2. Node Taxonomy (Decision #346)

| Type | Hardware | Nature | Role | Example |
|------|----------|--------|------|---------|
| **Hub** | 192.168.1.200 | Stationary, powerful | Brain — AI, GPU, 128GB RAM, orchestration | Home server |
| **Outpost** | VPS worldwide | Stationary, lightweight | Regional proxy, data collector, relay | Hostinger KVM2 (76.13.107.109) |
| **Starship** | Laptops/Desktops | Stationary, powerful | Compute nodes, development, GPU inference | Node .245 (RTX 3070) |
| **Satellite** | Mobile phones | Mobile, orbiting user | Lightweight agent presence | Android phone |

### Scope for This Spec
- **In scope:** Linux/Docker deployment (Outpost + Starship)
- **Parked (Tier 2):** Windows deployment
- **Parked (Tier 3):** Android/iOS Satellite apps

## 3. Architecture Overview

### 3.1 One Installer, Adaptive Profiles

A single deployment system that adapts to what the node IS, not a monolithic stack forced onto everything.

```
fleet/
  installer/          # Phase 1: Bash bootstrap script
    install.sh        # Detects hardware, installs deps, mesh VPN, pulls wizard
  wizard/             # Phase 2: Go TUI (interactive hub-driven setup)
    main.go           # Bubble Tea TUI — profile selection, hub handshake
    hardware.go       # Hardware detection (CPU, RAM, GPU, disk)
    auth.go           # Token + approval queue auth
  profiles/           # Node type definitions (YAML)
    outpost.yml       # Lightweight: mesh + proxy + sync + API
    starship.yml      # Full: mesh + proxy + sync + API + Ollama + Postgres
    satellite.yml     # Minimal: mesh + sync + lite API
  hub/                # Hub-side registration & management
    registry.go       # Node registration, profile assignment
    provisioner.go    # Docker Compose generation from profiles
    manager.go        # Ongoing profile management, OTA, health
  templates/          # Docker Compose templates per service
    mesh-vpn.yml
    sync-daemon.yml
    node-api.yml
    reverse-proxy.yml
    smtp-relay.yml
    ollama.yml
    postgres.yml
    comfyui.yml
    monitoring-agent.yml
```

### 3.2 Install Flow

#### Phase 1 — Bootstrap (Bash script, standalone, no hub needed)

```
curl -sSL install.kytranempowerment.com/fleet | bash
```

1. Detect OS (Ubuntu/Debian/Alpine/etc.)
2. Install prerequisites: Docker, Docker Compose, curl, jq
3. Detect hardware: CPU cores, RAM, GPU (nvidia-smi), disk space
4. Suggest node type based on hardware:
   - No GPU + <16GB RAM → Outpost
   - GPU detected OR >16GB RAM → Starship
   - Mobile/Termux → Satellite
5. User confirms or overrides
6. Install Tailscale client → connect to Headscale mesh at mesh.kytranempowerment.com
7. Node is now on the mesh and can reach the hub
8. Download Go wizard binary from hub via mesh
9. Hand off to Phase 2

#### Phase 2 — Hub Handshake (Go TUI wizard, hub-driven)

1. Wizard launches with LCARS-themed Bubble Tea TUI
2. Authentication:
   - **Token mode** (headless/VPS): User pastes one-time token generated in Starbase
   - **Approval mode** (interactive): Node sends join request, user approves in Starbase
3. Hub assigns node ID, records hardware profile
4. Hub pushes profile config (which services to install)
5. Wizard shows optional services menu → user picks
6. Hub generates Docker Compose from profile + selections
7. Docker Compose pulled and started
8. Services boot, sync daemon connects, heartbeat begins
9. Hub confirms node healthy, adds to fleet roster in Starbase
10. Wizard shows success screen with node status

#### Phase 3 — Ongoing (Hub-managed)

- Heartbeat/sync continues (60s interval, existing OTA pipeline)
- Hub can push profile changes (upgrade Outpost → Starship if GPU added)
- OTA updates through mesh (code_update, model_pull, config_update, etc.)
- Agent assignments managed from Starbase/Department HQ
- Health monitoring via B.A.S.E. (Operations & Infrastructure director)

### 3.3 Profile Definitions

```yaml
# fleet/profiles/outpost.yml
name: outpost
description: Lightweight proxy and relay node for regional presence
min_requirements:
  cpu_cores: 1
  ram_gb: 2
  disk_gb: 20
services:
  required:
    - mesh-vpn        # Tailscale → Headscale
    - sync-daemon     # Heartbeat + OTA sync (existing node_sync.py)
    - node-api        # REST API (port 3001, existing node_api.py)
    - reverse-proxy   # Nginx/Caddy for routing
  optional:
    - smtp-relay      # Outbound mail relay (Stalwart/Postfix)
    - monitoring-agent # Prometheus node exporter
```

```yaml
# fleet/profiles/starship.yml
name: starship
description: Full compute node with AI inference and generation
min_requirements:
  cpu_cores: 4
  ram_gb: 16
  disk_gb: 100
  gpu: recommended
services:
  required:
    - mesh-vpn
    - sync-daemon
    - node-api
    - reverse-proxy
    - ollama          # LLM inference
    - postgres        # Local agent/job database
  optional:
    - comfyui         # Image generation (requires GPU)
    - smtp-relay
    - monitoring-agent
```

```yaml
# fleet/profiles/satellite.yml
name: satellite
description: Mobile lightweight agent presence
min_requirements:
  cpu_cores: 1
  ram_gb: 1
  disk_gb: 5
services:
  required:
    - mesh-vpn
    - sync-daemon
    - node-api-lite   # Stripped REST API
  optional:
    - monitoring-agent
```

### 3.4 Authentication

Two auth paths based on deployment context:

#### Token Auth (headless/VPS deployments)
1. Admin generates one-time token in Starbase: `POST /api/fleet/tokens`
2. Token has: expiry (24h default), allowed node type, optional name
3. Installer pastes token during Phase 2
4. Hub validates, registers node, invalidates token

#### Approval Queue (interactive deployments)
1. Node connects to mesh, sends join request with hardware profile
2. Request appears in Starbase fleet management panel
3. Admin reviews hardware specs, assigns node type, approves
4. Node receives approval, proceeds with profile installation
5. Denied requests are logged and the node is informed

### 3.5 Docker Compose Generation

The hub generates a Docker Compose file dynamically based on:
- Selected profile (outpost/starship/satellite)
- Enabled optional services
- Hardware capabilities (GPU flag for Ollama/ComfyUI)
- Node-specific config (node_id, hub_url, API key)

Template assembly:
```
base.yml + profile_services.yml + optional_services.yml → docker-compose.yml
```

Each service template is self-contained with its own volumes, ports, and environment. The generator merges them into a single valid Compose file.

## 4. Reusable Infrastructure (from cancelled projects)

These components exist and should be reused, not rewritten:

| Component | Location | Status | Reuse |
|-----------|----------|--------|-------|
| Headscale mesh VPN | `/mnt/archie_brain/headscale/config.yaml` | Configured | Direct — connect new nodes |
| OTA sync pipeline | `mesh_sync_log` table, 11 sync types | Working | Direct — same sync mechanism |
| Hub_url protection | `node_sync.py` | Working | Keep — hard-won safety |
| HTML rejection on code_update | `node_sync.py` | Working | Keep — prevents proxy corruption |
| Stale sync prevention | `node_sync.py` | Working | Keep |
| Node API (port 3001) | `node_client/node_api.py` | Basic | Extend for profiles |
| Fleet triage | `ai_bridge/fleet_triage.py` | Working | Direct — agent routing |
| Node router | `ai_bridge/node_router.py` | Working | Direct — task routing |
| Bridge dispatcher fleet support | `ai_bridge/bridge_dispatcher.py` | Working | Direct — cross-node dispatch |
| Starbase mesh routes | `platform_v2/tools/starbase/mesh_routes.py` | Working | Extend for new node types |
| Docker node stack | `node_client/docker-compose.node.yml` | 5 containers | Refactor into service templates |

## 5. Constraints (Lessons from 7 Failed Projects)

These are non-negotiable rules derived from real failures documented in the knowledge base.

### 5.1 Verification Rules
- **Nothing is "done" until tested end-to-end on a real node** — the US outpost VPS is the first test target
- **Never claim the installer works without running it on a clean machine**
- **OTA commands must show output** — fire-and-forget commands are invisible failures (KB #243448)
- **Sync poller must survive errors** — one bad response cannot crash the daemon (KB #241091)

### 5.2 Remote Safety Rules
- **NEVER overwrite remote files without backup** — node .246 was bricked by a bad OTA push (KB #243665)
- **NEVER assume bind mount paths** — verify with `docker inspect` first
- **NEVER assume Docker behavior matches across OS** — Windows != Linux
- **After 2 failed remote operations → STOP and escalate to user**
- **hub_url is PROTECTED** — OTA cannot override it (hard-won lesson)

### 5.3 UX Rules
- **Non-technical users must never need a terminal** — everything one-click from web UI
- **The installer script is the ONLY exception** — after that, all management is GUI
- **Downloaded scripts run everything automatically** — no manual steps
- **Self-healing on failure** — node fixes itself before asking for help

### 5.4 Architecture Rules
- **Profile-based, not one-size-fits-all** — the root cause of every previous failure
- **No incremental patching** — design first, build second, test third
- **Docker Compose generated from templates** — not hand-edited per node
- **Mesh VPN before anything else** — can't manage what you can't reach

## 6. Strategic Vision — Global Mesh

The fleet deployment system is the foundation for a global distributed network:

- **Outposts on every continent** — regional proxies for data collection, social media presence, latency reduction
- **Agents route through outposts** — appearing geographically local to each region
- **Products become multi-clustered** — News, Gov Watch, Market Watch collect data from local sources per region
- **Social media presence** — posts, clicks, engagement counted from regional IPs
- **Cross-continent data analysis** — compare perspectives from different regions
- **Free/cheap VPS expansion** — slower is fine, they're connected via the mesh

### Priority Continents
1. North America — DONE (US outpost, Hostinger KVM2)
2. Europe — next (Frankfurt or Amsterdam)
3. Asia-Pacific — follow
4. South America, Africa, Oceania — as growth demands

## 7. This Week's Deliverables

Focus: Get the US outpost (76.13.107.109) online as the first working node.

1. **Harden VPS** — SSH keys, firewall, fail2ban, Docker install
2. **Connect to mesh** — Tailscale → Headscale, verify connectivity to hub
3. **Set PTR record** — via Hostinger API for mail.kytranempowerment.com
4. **Deploy outpost profile** — reverse proxy + sync daemon + node API
5. **Configure Stalwart relay** — outbound mail through VPS
6. **Verify end-to-end** — hub can see node, send OTA, node responds
7. **Write installer bootstrap** — `fleet/installer/install.sh` (Phase 1 only)
8. **Create fleet/ repo structure** — profiles, templates, hub registration stubs

## 8. Future Work (Not This Week)

- Go TUI wizard (Phase 2 installer)
- Token + approval queue auth system
- Dynamic Docker Compose generator
- Starbase fleet UI for new node types
- Windows Starship deployment
- Android Satellite app
- AI fleet manager agent (when 3-4+ nodes exist)
- Additional outposts (EU, APAC)

## 9. Related Projects & Tasks

### Cancelled Projects (absorbed by this spec)
- #114: Ollama Docker & Node Fleet System
- #121: Starship Node Runtime Phase 1
- #160: Starship Node Overhaul
- #163: Fleet Command Integration
- #169: Node Onboarding & Provisioning System
- #172: Fleet Mesh VPN — Headscale + Branded Installer
- #173: B.E.A.C.O.N. — Fleet Node Dashboard

### Active Tasks to Fold In
- #1444 [P9]: Standalone Node Product — extract & ship
- #1216 [P6]: Test installer on WAN node (Hostinger VM)
- #1189 [P7]: Fix Node Onboarding — re-verify code from #169
- #1381 [P6]: Migrate fleet dispatch from station_code to department routing

### Parked
- #1180 [P8]: Test OTA upgrade on .246 (Windows) — Tier 2
- #1182 [P6]: Android Satellite App Design Spec — Tier 3
