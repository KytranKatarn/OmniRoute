# Fleet Installer + KSO App Catalog — Design Spec

**Date:** 2026-03-30
**Project:** #208 — Fleet Deployment System
**Tasks:** #1494 (Fleet Installer), #1496 (KSO App Catalog)
**Status:** Design approved

---

## Overview

Two interconnected systems that turn KSO into the fleet's universal node operating system:

1. **Fleet Installer** (`fleet/installer/install.sh`) — bootstrap script that gets KSO running on any Linux machine
2. **KSO App Catalog** — registry-driven UI in KSO for one-click deploy/manage of standalone products
3. **Satellite PWA** — mobile fleet presence app for Android/iOS via Tailscale mesh
4. **Hub Fleet API** — registration, approval, catalog, and heartbeat endpoints

## Node Types

| Type | Target Hardware | Installer | Management |
|------|----------------|-----------|------------|
| **Outpost** | VPS (1 CPU, 2GB RAM) | `install.sh` | KSO + App Catalog |
| **Starship** | Desktop/server (4+ cores, GPU) | `install.sh` | KSO + App Catalog |
| **Satellite** | Android/iOS phone | Tailscale app + PWA | PWA only (no Docker) |

## Architecture

```
┌─────────────────────────────────────────────┐
│  ARCHIE Hub (192.168.1.200)                 │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │Starbase │  │Fleet API │  │ App       │  │
│  │   UI    │  │(register,│  │ Registry  │  │
│  │         │  │ approve, │  │(catalog   │  │
│  │         │  │ heartbeat│  │ manifest) │  │
│  └─────────┘  └──────────┘  └───────────┘  │
└──────────────────┬──────────────────────────┘
                   │ mesh (Headscale 100.64.x.x)
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   ┌─────────┐ ┌────────┐ ┌──────────┐
   │ Outpost │ │Starship│ │Satellite │
   │  (KSO)  │ │ (KSO)  │ │  (PWA)   │
   │  Docker  │ │ Docker │ │ browser  │
   │  Catalog │ │ Catalog│ │ only     │
   └─────────┘ └────────┘ └──────────┘
```

## Component 1: Fleet Installer (`fleet/installer/install.sh`)

Thin idempotent bash script. Five steps:

### Step 1: Detect OS
- Require Ubuntu 22.04+ or Debian 12+
- Warn and exit on unsupported OS
- Check arch (amd64/arm64)

### Step 2: Install Dependencies
- Docker Engine + Docker Compose plugin (official Docker repo)
- Tailscale client (for Headscale mesh join)
- `curl`, `jq` (if missing)

### Step 3: Ask Node Type
- Interactive prompt: `outpost` or `starship`
- Loads corresponding profile from embedded YAML (resource limits, required services)
- Non-interactive mode: `--type outpost` flag

### Step 4: Fleet Registration
- Ask for registration token OR request approval
- Token mode: `--token <token>` — validated by hub, instant approval
- Approval mode: registers as pending, waits for admin approval (polls every 10s, timeout 10min)
- Hub returns `node_id` + mesh auth key on success

### Step 5: Join Mesh + Start KSO
- `tailscale up --login-server https://mesh.kytranempowerment.com --authkey <mesh_key>`
- Generate `.env` from profile (node_id, hub_url, node_type, mesh_ip)
- `docker compose pull && docker compose up -d`
- KSO starts, pulls catalog, reports healthy to hub

### Installer Flags
```bash
install.sh                          # interactive mode
install.sh --type outpost --token abc123  # non-interactive
install.sh --uninstall              # tear down (stops containers, removes data)
```

### Idempotency
- Each step checks if already done (Docker installed? Tailscale running? KSO up?)
- Re-running skips completed steps
- `--force` flag to redo everything

## Component 2: App Registry (`fleet/catalog/`)

### Catalog Entry Format
```yaml
# fleet/catalog/apps/gov-watch.yml
name: Kytran Gov Watch
id: gov-watch
description: Government procurement tender monitoring
image: ghcr.io/kytrankatarn/gov-watch:latest
version: "1.0.0"
port: 8097
env:
  - name: FLASK_SECRET_KEY
    required: true
    generate: true          # auto-generate if not set
  - name: DATABASE_URL
    required: false
    default: "sqlite:///data/gov-watch.db"
volumes:
  - name: data
    path: /app/data
resources:
  min_ram_mb: 256
  min_disk_mb: 500
  gpu: false
compatible_nodes: [outpost, starship]
category: products
health_endpoint: /api/health
depends_on: []               # other catalog app IDs
```

### Shipped Products in Catalog (v1)

| App ID | Name | Port | Compatible |
|--------|------|------|------------|
| `kso` | Kytran System Operations | 8085 | outpost, starship |
| `gov-watch` | Kytran Gov Watch | 8097 | outpost, starship |
| `news` | Kytran News | 8098 | outpost, starship |
| `business-suite` | Kytran Business Suite | 8091 | starship |
| `market-watch` | Kytran Market Watch | 8101 | starship |
| `smtp-relay` | SMTP Relay | 587 | outpost, starship |
| `monitoring` | Nagios Monitoring | 8080 | outpost, starship |

### Hub Serves Catalog
- `GET /api/fleet/catalog` — returns all catalog entries
- `GET /api/fleet/catalog?node_type=outpost` — filtered by compatibility
- KSO on each node caches the catalog locally, refreshes every 30min

## Component 3: KSO App Catalog UI + Backend

### New Routes in KSO

```
GET  /apps                    — catalog browser page
GET  /api/apps/catalog        — list available apps (from hub cache)
GET  /api/apps/installed      — list deployed apps on this node
POST /api/apps/<id>/deploy    — pull image + create compose + start
POST /api/apps/<id>/stop      — stop container
POST /api/apps/<id>/start     — start stopped container
POST /api/apps/<id>/remove    — stop + remove container + optionally data
POST /api/apps/<id>/update    — pull latest image + recreate container
GET  /api/apps/<id>/logs      — stream container logs
GET  /api/apps/<id>/health    — check health endpoint
```

### Catalog UI (New Tab in KSO)

Grid layout showing each app as a card:
- App name, description, icon
- Status badge: **Available** / **Running** / **Stopped** / **Update Available**
- Resource requirements (RAM, disk, GPU)
- One-click actions: Deploy / Stop / Start / Remove / Update / Logs
- LCARS styling consistent with KSO theme

### Deploy Flow (Backend)
1. Pull image (`docker pull <image>`)
2. Create app directory (`/opt/archie-fleet/apps/<id>/`)
3. Generate `docker-compose.yml` from catalog entry
4. Generate `.env` (auto-generate secrets, apply defaults)
5. `docker compose up -d`
6. Wait for health endpoint (30s timeout)
7. Report status to hub via heartbeat

### App Data Storage
- Each app gets `/opt/archie-fleet/apps/<id>/` directory
- Contains: `docker-compose.yml`, `.env`, `data/` volume mount
- Remove with `--keep-data` option to preserve volumes

## Component 4: Satellite PWA

### Tech Stack
- Vanilla HTML/CSS/JS (no framework — keep it tiny)
- Service Worker for offline support + background sync
- `manifest.json` for installability
- LCARS theme (dark background, teal accents)

### PWA Structure
```
platform_v2/static/fleet/satellite/
  index.html          — single-page app
  manifest.json       — PWA manifest
  sw.js               — service worker
  satellite.js        — main app logic
  satellite.css       — LCARS mobile styles
  icons/              — app icons (192x192, 512x512)
```

### Served From Hub
- Route: `GET /fleet/satellite/` → serves PWA static files
- Accessible via mesh IP (100.64.0.2) or public outpost proxy

### Registration Flow
1. User opens PWA URL
2. PWA checks `localStorage` for existing registration
3. If new: prompt for a name, call `POST /api/fleet/register` with `type=satellite`
4. Hub queues for admin approval
5. PWA polls `GET /api/fleet/status/<node_id>` every 10s
6. On approval: stores `node_id` + `auth_token` in `localStorage`
7. Starts heartbeat loop

### Heartbeat
- Every 60s via `fetch()` to `POST /api/fleet/heartbeat`
- Payload: `{ node_id, battery_level, network_type, online: true, timestamp }`
- Uses `navigator.getBattery()` API (where available)
- Uses `navigator.connection.effectiveType` for network info
- Falls back gracefully if APIs unavailable

### v1 UI Screens
1. **Registration** — name input + "Join Fleet" button + approval waiting screen
2. **Dashboard** — this satellite's status, fleet overview (how many nodes online)
3. **Fleet Map** — simple list of fleet nodes with status indicators
4. **Settings** — hub URL, notification preferences, disconnect

### Future Hooks (Designed But Not Implemented in v1)
- `satellite.js` exports a `TaskRunner` class with `register()` and `execute()` methods
- Tasks received via heartbeat response: `{ tasks: [{ id, type, payload }] }`
- Task types stubbed: `url_check`, `speed_test`, `relay_data`
- Results sent back via next heartbeat

## Component 5: Hub Fleet API Extensions

### New Endpoints (in Starbase or new `fleet_routes.py`)

```
POST /api/fleet/register        — register new node
  body: { name, type, token?, device_info }
  returns: { node_id, status: "approved"|"pending", mesh_auth_key? }

POST /api/fleet/heartbeat       — node heartbeat
  body: { node_id, auth_token, apps_running[], battery?, network_type? }
  returns: { ack: true, catalog_updated?: bool, tasks?: [] }

GET  /api/fleet/catalog         — app catalog
  query: ?node_type=outpost
  returns: { apps: [...catalog entries] }

POST /api/fleet/approve/<id>    — approve pending node
  returns: { status: "approved", mesh_auth_key }

POST /api/fleet/deny/<id>       — deny pending node

POST /api/fleet/token/generate  — generate registration token
  body: { node_type, expires_in_hours: 24 }
  returns: { token, expires_at }

GET  /api/fleet/status/<id>     — node status (used by satellites polling for approval)
  returns: { status: "pending"|"approved"|"denied" }
```

### Token Storage
- `fleet_registration_tokens` table: `id, token, node_type, created_by, expires_at, used_at, used_by_node_id`
- Tokens are single-use, expire after 24h by default

### Node Registration Table Extension
- Existing `remote_nodes` table gets new columns:
  - `registration_method` ENUM('token', 'approval')
  - `device_info` JSONB (battery, network, OS for satellites)
  - `apps_running` JSONB (list of deployed catalog app IDs)

## Data Flow

### Installer Flow
```
User runs install.sh on fresh VPS/machine
  → detects Ubuntu, installs Docker + Tailscale
  → joins Headscale mesh (gets 100.64.x.x IP)
  → asks: outpost or starship?
  → asks: paste registration token (or skip for approval)
  → pulls KSO image, writes .env with node type + hub URL + token
  → starts KSO container
  → KSO boots, registers with hub via Fleet API
  → hub validates token (instant approve) or queues for approval
  → KSO pulls app catalog, shows available apps
```

### App Deploy Flow
```
User opens KSO → Apps tab
  → sees catalog grid (filtered by node compatibility)
  → clicks "Deploy" on Gov Watch
  → KSO pulls image, generates docker-compose fragment
  → writes .env from catalog defaults + user overrides
  → docker compose up -d
  → monitors health endpoint, updates status
  → reports deployed app to hub heartbeat
```

### Satellite Flow
```
User installs Tailscale on phone → joins mesh
  → opens https://hub-or-outpost/fleet/satellite/
  → PWA prompts: "Add to home screen"
  → PWA calls POST /api/fleet/register (type=satellite)
  → hub queues for admin approval
  → admin approves in Starbase UI
  → PWA starts heartbeating every 60s
  → hub shows satellite in fleet dashboard
```

## Error Handling

- **Installer fails mid-way** — each step is idempotent, re-running picks up where it left off
- **Hub unreachable during registration** — KSO retries every 60s, shows "pending connection" in UI
- **App deploy fails** — KSO shows container logs, offers retry or rollback (remove failed container)
- **Satellite loses connectivity** — hub marks offline after 2min stale heartbeat (existing node logic)
- **App health check fails** — KSO shows unhealthy badge, hub alerted via heartbeat data
- **Catalog fetch fails** — KSO uses last cached catalog, shows "catalog stale" warning
- **Token expired** — hub returns 401, installer prompts for new token or switches to approval mode

## Testing Strategy

| Test | Method | Verification |
|------|--------|-------------|
| Installer on fresh VPS | Run on Hostinger VPS | KSO comes up, registers with hub |
| Installer idempotency | Run twice | Second run skips completed steps, no errors |
| Token registration | Generate token on hub, use in installer | Instant approval, node appears in Starbase |
| Approval registration | Register without token | Pending in Starbase, approve → node goes active |
| App Catalog UI | Open KSO on US outpost | Grid shows compatible apps with correct status |
| App deploy | Deploy Gov Watch via catalog | Container runs, health endpoint green |
| App update | Push new image tag, click update | Container recreated with new image |
| App remove | Remove deployed app | Container stopped, compose removed |
| Satellite PWA | Open on phone via mesh | Registration, approval, heartbeats in Starbase |
| Satellite offline | Turn off phone wifi | Hub marks satellite offline after 2min |
| Satellite PWA install | Add to home screen on Android | Opens as standalone app |

## File Structure (New/Modified)

```
fleet/
  installer/
    install.sh                  — bootstrap script
    profiles/                   — embedded node profiles (copied from fleet/profiles/)
  catalog/
    apps/
      gov-watch.yml
      news.yml
      business-suite.yml
      market-watch.yml
      smtp-relay.yml
      monitoring.yml
    catalog-schema.yml          — JSON schema for catalog entries

kytran-server-manager/
  kytran_server_manager/
    routes/
      app_catalog_routes.py     — NEW: catalog browse, deploy, manage
    services/
      app_catalog_service.py    — NEW: docker compose generation, deploy logic
    templates/
      apps.html                 — NEW: catalog browser UI

platform_v2/
  static/fleet/satellite/
    index.html                  — PWA entry point
    manifest.json
    sw.js
    satellite.js
    satellite.css
    icons/
  tools/starbase/
    fleet_routes.py             — NEW: fleet registration, catalog, tokens
```

## Out of Scope (Future)

- Satellite task execution (phases B + C)
- Auto-scaling (deploy apps based on load)
- App marketplace (third-party apps)
- App-to-app networking within a node
- Multi-hub federation
- iOS-specific optimizations
