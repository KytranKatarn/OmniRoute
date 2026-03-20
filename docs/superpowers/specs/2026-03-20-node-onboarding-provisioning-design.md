# Node Onboarding & Provisioning System — Design Spec

**Date**: 2026-03-20
**Status**: Draft
**Project**: Fleet Node Deployment
**Replaces**: Fragmented install.ps1 / deploy-node.ps1 / heartbeat.sh approach

---

## Problem

The current "Connect a Machine" flow in Starship serves `install.ps1` which only installs a lightweight `node_sync.py` as a Windows Scheduled Task — no Docker, no containers, no local database. The full Docker deployment (`deploy-node.ps1`) exists separately but isn't wired into the UI. Result: new nodes (.245) only get heartbeat, not the full stack.

Meanwhile, KYTRAN-StarShip (.246) was set up manually with the Docker path and works perfectly — proving the architecture is sound, just not accessible.

## Vision

A turnkey node onboarding system where any machine (Windows or Linux, local or external) runs one installer and gets a fully provisioned ARCHIE fleet node with Docker containers, Ollama, sync service, local database, and OTA management — all branded and consistent.

Long-term: Android satellites (APKs) running single-agent nodes, external contributors providing their own hardware, forming a distributed compute cluster orchestrated by the hub.

## Architecture

Three layers:

### 1. Installer Layer (runs on the new node)

**Windows GUI Installer** — tkinter LCARS-themed application
- Dark background (#0a0a12), cyan (#00e5ff) headers, orange (#f97316) warnings, green (#10b981) success
- Consolas monospace font for sci-fi feel
- ~700x500 window, non-resizable
- ARCHIE banner at top
- Hardware readout panel, progress bar, scrolling log panel
- Install / Cancel buttons
- Packaged as single `.exe` via PyInstaller (~15-25MB, stdlib only)
- Hub serves at `/api/nodes/installer.exe`

**Linux Terminal Installer** — branded bash script
- Colored ASCII art ARCHIE banner (cyan)
- Step indicators: `[OK]` green, `[WARN]` yellow, `[FAIL]` red, `[...]` gray
- Pure bash — no Python dependency (Docker handles Python inside containers)
- Single `install-node.sh` file (~400 lines)
- Hub serves at `/api/nodes/install-node.sh`
- One-liner: `curl -fsSL https://archie.kytranempowerment.com/tools/starbase/api/nodes/install-node.sh | sudo bash`

**Both installers follow the same 8-step flow:**

#### Step 1: Prerequisites
- Check admin/root privileges
- Check internet connectivity to hub URL
- Detect OS version
- Check if this is a re-provision (existing ARCHIE install detected)
  - If yes: offer "Upgrade" (keep config, rebuild containers) or "Fresh Install" (wipe and redo)

#### Step 2: Hardware Detection
- CPU model + core count
- RAM total (GB)
- GPU model + VRAM via nvidia-smi (if available)
- Disk space available
- Display branded hardware readout

#### Step 3: Docker Setup
- Detect if Docker is installed and running
- **Windows**: Install Docker Desktop if missing (silent install)
  - **Restart handling**: Docker Desktop requires a system restart after first install (WSL2/Hyper-V). Installer saves state to `resume_after_reboot.json` (node_id, api_key, install step), prompts user to restart, and registers a Run-once registry key to auto-resume after reboot. On relaunch, installer detects the resume file and picks up from Step 4.
- **Linux**: Install Docker Engine via `https://get.docker.com` if missing (no restart needed)
- Enable Docker Compose v2
- Detect native Ollama on port 11434
  - If found: warn about port conflict, offer to stop/disable it
  - Rationale: Docker Ollama is standard — enables OTA model management, consistent versioning, auto-restart
- Verify Docker is responding

#### Step 4: Register with Hub
- POST hardware specs to `/tools/starbase/api/nodes/register`
- Payload: node_name, IP, CPU, RAM, GPU, VRAM, disk, OS, client_version
- Receive `node_id` + `api_key` from hub
- Node created with status "pending"
- Display: "Waiting for admin approval..."

#### Step 5: Download Stack Files
- Pull from hub endpoints:
  - `docker-compose.yml` (from `docker-compose.node.yml`)
  - `node_sync.py`
  - `node_api.py`
  - `Dockerfile.node`
  - `migrations/001_node_schema.sql`
  - `migrations/002_knowledge_projects.sql`
- Strip GPU config from compose if no NVIDIA GPU detected
- Auto-enable ComfyUI service if GPU detected AND 50GB+ free disk (skip with warning if disk too low)

#### Step 6: Build & Start Containers
- `docker compose build`
- `docker compose up -d`
- Services started:
  - **ollama** — GPU-accelerated (or CPU-only), port 11434
  - **postgres** — local node DB, auto-runs migrations
  - **sync** — node_sync.py (heartbeats + 11 sync types + OTA)
  - **node_api** — Flask API port 3001 (local job execution)
  - **comfyui** — (GPU nodes only) image/video generation, port 8188

#### Step 7: Wait for Approval + Model Provisioning
- Sync service starts heartbeating immediately (hub sees node is alive)
- Installer polls hub for approval status
- GUI: shows animated "waiting" state. Terminal: spinner with status updates
- Once approved by admin:
  - Hub auto-pushes **starter pack** (small utility models: `llama3.2:3b`, `qwen2.5:7b`)
  - Hub then runs **smart assessment**: evaluates VRAM, RAM, station needs, agent availability
  - Pushes appropriate models for the node's hardware profile via `model_pull` OTA
  - ComfyUI nodes get image generation models (SDXL checkpoint, etc.)
- Installer shows download progress as models arrive

#### Step 8: Verify & Summary
- All containers healthy (docker compose ps)
- Heartbeat reaching hub confirmed
- Display node info: ID, name, IP, hub URL, services, GPU status
- Display management commands
- Windows GUI: "Close" button
- Linux: return to shell with summary

### 2. Hub Orchestration Layer (Starbase/Starship)

**Registration Endpoint** (`/api/nodes/register`)
- Receives hardware specs from installer
- Creates node in `remote_nodes` with status "pending"
- Generates unique `node_id` + `api_key`
- Returns credentials to installer
- Cleans up duplicate registrations (same hostname/IP)

**"Connect a Machine" UI** (Starship Command)
- Behind login (login IS the access gate)
- Shows two options:
  - **One-liner command** — copy/paste into PowerShell or terminal
  - **Download button** — `.exe` for Windows, `.sh` for Linux
- Displays hub URL pre-filled
- Shows list of pending/online nodes below

**Admin Approval Flow**
- Pending nodes appear in Starship UI with hardware specs
- Admin clicks "Approve" or "Deny"
- On approval, hub triggers `_on_node_approved(node_id)` — **NEW function** to be added to `node_routes.py`:
  1. Status update to "online" in `remote_nodes`
  2. Set `deployment_mode = 'starship'` if not already set
  3. Starter model push — insert `model_pull` entries into `mesh_sync_log` with status `'sent'`
  4. Smart model assessment (based on GPU VRAM, RAM, station coverage gaps)
  5. Agent assignment if stations need coverage

**Smart Model Push Logic**
- Input: node hardware specs (GPU VRAM, RAM, disk), current fleet model coverage, station staffing gaps
- Rules:
  - GPU node with 8GB+ VRAM → inference-capable models (7B-13B range)
  - GPU node with ComfyUI → SDXL checkpoint + LoRAs for image gen
  - CPU-only node → lightweight models (1B-3B) for utility tasks
  - Always include starter pack regardless of hardware
- Executed via existing `model_pull` OTA sync type
- Coordinated with crew roster — Bridge dispatcher knows what models each station needs

### 3. OTA Upgrade Layer (for existing nodes)

**Purpose**: Bring legacy nodes (.246) to the new standard without reinstalling.

**Upgrade Flow** (triggered from Starship UI or automated):
1. Push new `docker-compose.yml` via `code_update` sync
2. Push updated `node_sync.py`, `node_api.py` via `code_update` sync
3. Push new migrations via `code_update` sync
4. `container_restart` sync to rebuild and restart the stack
5. Verify via heartbeat that new version is running

**Existing OTA Sync Types** (all remain as-is):
1. `code_update` — download + extract new files, restart containers
2. `config_update` — update config.json / .env from payload
3. `container_restart` — restart Docker containers
4. `model_pull` — pull model into Docker Ollama
5. `shell_exec` — run arbitrary shell command
6. `ssh_toggle` — enable/disable SSH
7. `comfyui_setup` — configure ComfyUI service
8. `agent_config` — push crew manifest + system prompts
9. `job_request` — execute job locally
10. `iaae_policy` — update governance policies
11. `model_recommend` — suggest model loads

## Security

- **Login required** to access "Connect a Machine" page
- **Admin approval required** before node receives any work or models
- **API key** generated per-node, used for all hub communication (X-Node-API-Key header)
- **HTTPS** — external nodes connect via `archie.kytranempowerment.com` (SSL via NPM)
- **Local network** nodes can use `http://192.168.1.200:3000` directly
- **File download endpoints are public** — the install scripts and stack files (`/api/nodes/*`) are unauthenticated GETs. This is acceptable: the scripts contain no secrets, and a downloaded node cannot do anything without admin approval. The `api_key` is only issued at registration time.
- **Duplicate registration cleanup** — only removes `pending` or `offline` duplicates with same hostname/IP. Never removes `approved` or `online` nodes.
- Future: invite codes for public registration campaigns (not needed now — login gates access)

## Failure Handling & Cleanup

**Installer failure at any step:**
- Steps 1-3 (pre-registration): clean exit, no hub state to clean up
- Step 4 (registration failed): display error, suggest checking hub URL / network
- Steps 5-6 (download/build failed): remove downloaded files, node stays "pending" in hub. Hub auto-cleans stale pending nodes after 24h with no heartbeat.
- Step 7 (waiting for approval): if user cancels, containers stop, node stays pending. Admin can deny/delete later.
- **Windows restart edge case**: if Docker install requires restart, state saved to `resume_after_reboot.json`. If user never reboots or re-runs, hub cleans up the stale pending entry after 24h.

**Linux installer dependency**: uses `jq` for JSON parsing (installed automatically if missing via apt/dnf/yum). No Python dependency — pure bash.

## File Changes

### New Files
- `node_client/installer/archie_node_installer.py` — **rewrite** existing file for full Docker deployment + LCARS GUI
- `node_client/install-node.sh` — new branded Linux terminal installer (replaces `install.sh`)
- `node_client/installer/build_installer.py` — update for new installer

### Modified Files
- `platform_v2/tools/starship/` — "Connect a Machine" UI updates (download buttons, one-liner display)
- `platform_v2/tools/starbase/node_routes.py` — serve new installer files, clean up duplicate registration logic, add `_on_node_approved()` post-approval orchestration function, stale pending node cleanup (24h TTL)
- `platform_v2/tools/starbase/mesh_routes.py` — smart model push on approval
- `platform_v2/tools/starship/ota_routes.py` — upgrade-existing-node endpoint
- `node_client/docker-compose.node.yml` — review and finalize as the standard compose file

### Deprecated Files (to remove after migration)
- `node_client/install.ps1` — replaced by GUI installer
- `node_client/install.sh` — replaced by `install-node.sh`
- `node_client/heartbeat.sh` — replaced by Docker sync service
- `node_client/heartbeat.ps1` — replaced by Docker sync service
- `node_client/deploy-node.ps1` — merged into GUI installer
- `node_client/update.ps1` — replaced by OTA

## Testing Plan

1. **Fresh install on .245 (Windows)** — Run new `.exe` installer from scratch, verify full Docker stack comes up
2. **OTA upgrade on .246 (Windows)** — Push upgrade via Starship OTA, verify containers rebuild to new standard
3. **Linux fresh install** — Test `install-node.sh` on a Linux VM or machine
4. **Re-provision test** — Run installer on a machine that already has ARCHIE containers, verify "Upgrade" path works
5. **External node test** — Connect from outside local network via `archie.kytranempowerment.com`
6. **No-GPU test** — Install on a CPU-only machine, verify GPU config stripped, CPU models pushed
7. **Approval flow test** — Verify node stays in pending until admin approves, then models auto-push

## Success Criteria

- Any Windows or Linux machine can go from bare metal to fully provisioned ARCHIE node in one installer run
- Existing nodes (.246) can be upgraded via OTA without reinstalling
- Admin has full control: approval gate, model selection, OTA management
- All nodes end up with identical Docker stack (Ollama, Postgres, sync, node_api, optional ComfyUI)
- "Connect a Machine" UI is the single entry point — no separate scripts to hunt down
- Branded, consistent experience on both platforms

## Phase 2: Android Satellite App (Future — Planned)

**Vision**: ARCHIE as a personal AI assistant on your phone. Not just a compute node — an AI agent that integrates with your daily life through Google services and phone features.

**Core Concept**:
- Lightweight Android APK — single ARCHIE agent running on your phone/tablet
- Connects to hub via `archie.kytranempowerment.com` (same registration + approval flow)
- Same "Connect a Machine" UI in Starship shows Android as a third download option (QR code + APK download)
- Contributes device resources to the cluster (CPU inference with small models)

**Personal AI Agent Features**:
- **Google Calendar** — manage schedule, create events, remind you, suggest optimal meeting times
- **Gmail** — read/summarize emails, draft replies, flag important messages, auto-respond to routine ones
- **Messages** — answer people on your behalf with your tone/style, summarize conversation threads
- **Phone management** — battery optimization, storage cleanup suggestions, app usage insights
- **Notifications** — intelligent filtering, priority surfacing, "do not disturb" awareness
- **Voice** — talk to your ARCHIE agent hands-free (Google Assistant integration or custom wake word)

**Technical Approach** (to be fully designed in a separate spec):
- Native Android (Kotlin) or cross-platform (React Native / Flutter)
- Google OAuth for Calendar/Gmail/Contacts access
- Lightweight local model (TinyLlama or similar) for offline basic responses
- Hub connection for complex tasks — agent escalates to fleet when needed
- Push notifications via Firebase for hub-initiated communication
- Background service for heartbeat + sync (battery-optimized)
- On-device privacy: personal data stays on phone, only task results sent to hub

**Registration Flow**:
- Download APK from Starship "Connect a Machine" page (or future Play Store)
- Open app → enter hub URL or scan QR code from Starship UI
- App registers with hub (sends device specs: model, OS version, RAM, storage)
- Admin approves in Starship
- Agent assigned + small model pushed (or cloud-only mode for low-spec devices)

**Deployment Modes**:
- **Full satellite** — local model + hub connection (high-spec phones, 8GB+ RAM)
- **Cloud relay** — no local model, all inference via hub/fleet (low-spec devices)
- **Personal assistant only** — Google services integration, no compute contribution

**Dependencies / Prerequisites**:
- Google Cloud project for OAuth credentials (Calendar, Gmail, Contacts APIs)
- Firebase project for push notifications
- APK signing key + distribution method (direct download initially, Play Store later)
- Android development environment (Android Studio, Kotlin)
- Privacy policy + terms of service (required for Google API access)

**This is a separate project** — will get its own spec, plan, and implementation cycle after Phase 1 (desktop/server nodes) is proven and stable.

## Future Considerations (beyond Phase 2)

- **iOS Satellite** — same concept as Android, for iPhone users
- **External contributor onboarding** — public registration page, resource contribution tracking
- **Cluster auto-scaling** — hub automatically suggests new nodes when workload exceeds capacity
- **Node reputation/trust scoring** — track reliability, uptime, task success rate per node
- **Satellite mesh** — phones relay tasks to each other when hub is unreachable
- **Wearable integration** — smartwatch companion for quick ARCHIE interactions
