# Node Onboarding & Provisioning System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fragmented node installer scripts with a unified, branded deployment system that installs Docker + full container stack on Windows (GUI) and Linux (terminal).

**Architecture:** Two installers (Windows tkinter GUI + Linux bash) follow the same 8-step flow: prerequisites, hardware detection, Docker install, hub registration, download stack, build containers, wait for approval, verify. Hub orchestration handles post-approval model push via existing OTA pipeline.

**Tech Stack:** Python 3 + tkinter (Windows GUI), bash + jq (Linux terminal), Docker Compose, Flask (hub endpoints), PostgreSQL (mesh_sync_log for OTA)

**Spec:** `docs/superpowers/specs/2026-03-20-node-onboarding-provisioning-design.md`
**Project:** Dev HQ #169 | **Tasks:** #1170-#1182

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `node_client/installer/archie_node_installer.py` | Windows tkinter LCARS GUI installer (rewrite of existing 686-line file) |
| `node_client/install-node.sh` | Linux branded terminal installer (~400 lines bash) |

### Modified Files
| File | Changes |
|------|---------|
| `node_client/docker-compose.node.yml` | Finalize as standard — healthchecks on all services |
| `node_client/Dockerfile.node` | Ensure migrations copy and pip deps are complete |
| `node_client/installer/build_installer.py` | Update PyInstaller config for new installer |
| `platform_v2/tools/starbase/node_routes.py` | Add `_on_node_approved()`, serve new files, duplicate cleanup |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Connect-a-Machine UI redesign |
| `platform_v2/tools/starship/static/js/starship.js` | Add node modal JS functions |
| `platform_v2/tools/starship/ota_routes.py` | Add upgrade-v3 endpoint |

---

## Task 1: Clean Up .245 Duplicate Registrations + Finalize Docker Compose
**Dev HQ:** #1170, #1178

**Files:**
- Modify: `node_client/docker-compose.node.yml`
- Modify: `node_client/Dockerfile.node`
- Modify: `node_client/config.example.json`

- [ ] **Step 1: Remove stale .245 node entries from DB**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
  DELETE FROM remote_nodes
  WHERE node_id IN ('starship_a93be85109cbd00d', 'node_966f13c825a61308');
"
```

Expected: DELETE 2

- [ ] **Step 2: Verify only valid nodes remain**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
  SELECT node_id, node_name, status, last_heartbeat FROM remote_nodes ORDER BY node_name;
"
```

Expected: archie-starbase (online) + KYTRAN-StarShip node_7e33... (online)

- [ ] **Step 3: Read and update docker-compose.node.yml**

Read `node_client/docker-compose.node.yml`. Add healthchecks to sync and node_api services. Ensure ComfyUI section is present (not commented out — controlled by GPU detection in installer).

- [ ] **Step 4: Update Dockerfile.node**

Ensure it installs curl + jq, copies migrations, and has all pip deps:

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl jq && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask psycopg2-binary requests
WORKDIR /app
COPY node_sync.py node_api.py node_triage.py ./
COPY migrations/ ./migrations/
CMD ["python3", "-u", "node_sync.py"]
```

- [ ] **Step 5: Update config.example.json with Docker-mode fields**

Add `deployment_mode`, `client_version`, and Docker-aware `ollama_host` default.

- [ ] **Step 6: Commit**

```bash
git add node_client/docker-compose.node.yml node_client/Dockerfile.node node_client/config.example.json
git commit -m "feat(node): finalize docker-compose stack with healthchecks, updated Dockerfile"
```

---

## Task 2: Hub — Post-Approval Orchestration + Endpoints
**Dev HQ:** #1174, #1176

**Files:**
- Modify: `platform_v2/tools/starbase/node_routes.py`

- [ ] **Step 1: Read node_routes.py**

Read `platform_v2/tools/starbase/node_routes.py` — find register_node() (~line 470), the approval endpoint, and file-serving endpoints. Note exact line numbers.

- [ ] **Step 2: Add duplicate cleanup to registration endpoint**

In `register_node()`, before inserting new node, delete stale pending/offline duplicates with same hostname where last_heartbeat is NULL or older than 24h.

- [ ] **Step 3: Add `_on_node_approved()` function**

New function that runs after admin approves a node:
1. Sets `deployment_mode = 'starship'`
2. Gets node hardware specs (GPU VRAM, RAM)
3. Pushes starter models (`llama3.2:3b`, `qwen2.5:7b`) via `mesh_sync_log` entries with status `'sent'`
4. If GPU >= 8GB VRAM, also pushes `llama3.1:8b`
5. If GPU >= 6GB VRAM, queues `comfyui_setup` sync

- [ ] **Step 4: Wire `_on_node_approved()` into approval endpoint**

Call `_on_node_approved(node_id)` after the status update to 'approved'.

- [ ] **Step 5: Add new file-serving endpoints**

Add GET endpoints for `/api/nodes/install-node.sh` and `/api/nodes/installer.exe` (using `send_file`).

- [ ] **Step 6: Test registration with duplicate cleanup**

Register a test node twice with same hostname, verify first stale entry gets cleaned up.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/starbase/node_routes.py
git commit -m "feat(starbase): post-approval orchestration, duplicate cleanup, new installer endpoints"
```

---

## Task 3: Windows GUI Installer (tkinter LCARS)
**Dev HQ:** #1171

**Files:**
- Rewrite: `node_client/installer/archie_node_installer.py`

- [ ] **Step 1: Read existing archie_node_installer.py**

Read the current file (686 lines). Understand structure — what to preserve, what to replace.

- [ ] **Step 2: Write the new installer**

Full rewrite with LCARS theme and 8-step Docker deployment flow.

**UI Layout:** Dark bg (#0a0a12), cyan headers (#00e5ff), orange warnings (#f97316), green success (#10b981). Hub URL input, hardware readout panel, progress bar, scrolling log, Install/Cancel buttons. ~700x500 window, Consolas font.

**Key classes/functions:**
- `ArchieInstaller(tk.Tk)` — main window class
- `_step_prerequisites()` — admin check, connectivity, re-provision detection
- `_step_hardware()` — WMI queries for CPU, RAM, GPU, disk
- `_step_docker()` — check/install Docker Desktop, restart handling with `resume_after_reboot.json`
- `_step_register()` — POST to hub `/api/nodes/register`
- `_step_download()` — pull stack files from hub, strip GPU if needed, enable ComfyUI if GPU + 50GB free
- `_step_build()` — `docker compose build` + `docker compose up -d`
- `_step_approval()` — poll hub for approval, show model download progress
- `_step_verify()` — `docker compose ps`, verify heartbeat, show summary

**Re-provision detection:** Check for existing `C:\archie-node\.env` and running containers. Offer "Upgrade" or "Fresh Install".

**Docker restart handling:** Save state to `resume_after_reboot.json`, add Windows Run-once registry key via `winreg`, prompt restart. On relaunch, detect resume file and continue from saved step.

**All steps run in background threads** to keep GUI responsive. Use `self.after()` for thread-safe GUI updates.

**stdlib only** — no pip dependencies (tkinter, subprocess, json, os, socket, urllib.request, winreg, threading, shutil).

- [ ] **Step 3: Test GUI launches correctly**

Run on Windows: `python installer/archie_node_installer.py`
Expected: LCARS window appears with hub URL input and Install button.

- [ ] **Step 4: Commit**

```bash
git add node_client/installer/archie_node_installer.py
git commit -m "feat(installer): LCARS tkinter GUI with full Docker deployment flow"
```

---

## Task 4: Linux Terminal Installer (branded bash)
**Dev HQ:** #1172

**Files:**
- Create: `node_client/install-node.sh`

- [ ] **Step 1: Write install-node.sh**

Create ~400 line branded bash installer with:

**Branding:** ASCII art banner, colored step indicators ([OK] green, [WARN] yellow, [FAIL] red, [...] blue).

**8-step flow:**
1. Prerequisites — root check, curl, jq (install if missing), re-provision detection
2. Hardware — CPU (from /proc/cpuinfo), RAM (from /proc/meminfo or free), GPU (nvidia-smi), disk (df)
3. Docker — install via `get.docker.com` if missing, detect and stop native Ollama
4. Register — POST JSON via curl, parse response with jq
5. Download — pull stack files from hub, strip GPU config with sed if no nvidia-smi, enable ComfyUI if GPU + 50GB free
6. Build — `docker compose build && docker compose up -d`
7. Approval — poll loop with spinner, display model pull progress
8. Verify — `docker compose ps`, heartbeat check, summary with management commands

**Re-provision detection:** Check for existing `/opt/archie-node/.env` and running `archie_starship_*` containers. Offer upgrade or fresh.

**Failure cleanup:** `cleanup_on_failure()` trap removes downloaded files if failed after step 5, warns user.

- [ ] **Step 2: Syntax check**

```bash
chmod +x node_client/install-node.sh
bash -n node_client/install-node.sh
```

- [ ] **Step 3: Commit**

```bash
git add node_client/install-node.sh
git commit -m "feat(installer): branded Linux terminal installer with Docker deployment"
```

---

## Task 5: PyInstaller .exe Build
**Dev HQ:** #1173

**Files:**
- Modify: `node_client/installer/build_installer.py`

- [ ] **Step 1: Read current build_installer.py**

Read the file. Understand current PyInstaller config.

- [ ] **Step 2: Update for new installer**

Update to target the rewritten `archie_node_installer.py`, output as `ARCHIE-Node-Setup.exe`, single file, windowed mode.

- [ ] **Step 3: Build on Windows**

```powershell
cd node_client\installer
pip install pyinstaller
python build_installer.py
```

Expected: `dist/ARCHIE-Node-Setup.exe` (~15-25MB)

- [ ] **Step 4: Test standalone (no Python needed)**

Copy .exe to a machine without Python. Run it. Expected: LCARS GUI window appears.

- [ ] **Step 5: Commit**

```bash
git add node_client/installer/build_installer.py
git commit -m "feat(installer): update PyInstaller build script for v3.0 GUI"
```

---

## Task 6: Starship UI — Connect a Machine Redesign
**Dev HQ:** #1175

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`
- Modify: `platform_v2/tools/starship/static/js/starship.js`
- Modify: `platform_v2/tools/starship/static/css/starship.css`
- Modify: `platform_v2/tools/starship/routes.py`

- [ ] **Step 1: Read current starship.html**

Find the existing ADD NODE button and modal. Note line numbers.

- [ ] **Step 2: Read starship.js**

Find current `openAddNodeModal()` function.

- [ ] **Step 3: Redesign the Connect a Machine modal**

Replace with LCARS modal (using `bm-overlay`/`bm-shell`/`bm-frame`/`bm-content` pattern) containing:
- Platform tabs: WINDOWS / LINUX
- Windows tab: download button for .exe + PowerShell one-liner with copy button
- Linux tab: curl one-liner with copy button + download button for .sh
- Pending nodes list with Approve/Deny buttons
- Use `textContent` for all dynamic text (no innerHTML with user data — XSS safe)
- Use `escHtml()` from consciousness.js for any node names displayed

- [ ] **Step 4: Add JS functions**

`showConnectTab(platform)`, `copyCmd(elementId)`, `loadPendingNodes()`, `approveNode(nodeId)`, `denyNode(nodeId)`

All DOM manipulation uses safe methods: `textContent`, `createElement`, `appendChild`, `escHtml()`.

- [ ] **Step 5: Add CSS for connect modal**

Styles for `.connect-tabs`, `.connect-tab`, `.connect-cmd`, `.copy-btn`, `.download-btn`, `.pending-node-card` — all LCARS themed.

- [ ] **Step 6: Pass hub_url to template**

In `starship/routes.py` `starship_dashboard()`, add `hub_url=request.host_url.rstrip("/")` to template context.

- [ ] **Step 7: Test the modal**

Navigate to Starship, click Connect a Machine. Verify: tabs switch, copy buttons work, download links resolve, pending nodes load.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html \
        platform_v2/tools/starship/static/js/starship.js \
        platform_v2/tools/starship/static/css/starship.css \
        platform_v2/tools/starship/routes.py
git commit -m "feat(starship): redesigned Connect a Machine modal with Windows/Linux tabs"
```

---

## Task 7: OTA Upgrade Path for Existing Nodes
**Dev HQ:** #1177

**Files:**
- Modify: `platform_v2/tools/starship/ota_routes.py`
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`
- Modify: `platform_v2/tools/starship/static/js/starship.js`

- [ ] **Step 1: Read ota_routes.py**

Read the file. Find the push-update endpoint. Note structure and patterns.

- [ ] **Step 2: Add upgrade-v3 endpoint**

New POST endpoint `/api/nodes/<node_id>/upgrade-v3` that:
1. Looks up numeric node ID from `remote_nodes`
2. Queues `code_update` sync (files: docker-compose.yml, node_sync.py, node_api.py, Dockerfile.node, migrations)
3. Queues `container_restart` sync (action: rebuild)
4. Both entries in `mesh_sync_log` with status `'sent'`
5. Returns success with sync count

- [ ] **Step 3: Add upgrade button to Starship UI**

In the node details section, add "Upgrade to v3.0" button for each online node. Uses confirm dialog before sending. Uses safe DOM methods.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/ota_routes.py \
        platform_v2/tools/starship/templates/tools/starship/starship.html \
        platform_v2/tools/starship/static/js/starship.js
git commit -m "feat(starship): OTA v3.0 upgrade path for existing nodes"
```

---

## Task 8: Testing — Fresh Install .245 + OTA Upgrade .246
**Dev HQ:** #1179, #1180

- [ ] **Step 1: Build the .exe on Windows**

Run `build_installer.py`, copy `dist/ARCHIE-Node-Setup.exe` to hub.

- [ ] **Step 2: Test fresh install on .245 (Windows)**

1. Download ARCHIE-Node-Setup.exe from Starship "Connect a Machine"
2. Run as Administrator on .245
3. Enter hub URL
4. Verify: Docker installs, containers come up, heartbeat reaches hub
5. Approve node in Starship UI
6. Verify: starter models push, node status becomes online

- [ ] **Step 3: Verify .245 fully operational**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
  SELECT node_id, node_name, status, last_heartbeat, gpu_model FROM remote_nodes WHERE status = 'online';
"
```

- [ ] **Step 4: Test OTA upgrade on .246**

Click "Upgrade to v3.0" for KYTRAN-StarShip in Starship UI. Verify: syncs picked up, containers rebuild, heartbeats resume with v3.0.

- [ ] **Step 5: Deprecate old scripts**

After both tests pass:
```bash
git rm node_client/install.ps1 node_client/install.sh node_client/heartbeat.ps1 \
       node_client/deploy-node.ps1 node_client/update.ps1
git commit -m "chore(node): remove deprecated installer scripts replaced by v3.0 unified installers"
```

Keep `heartbeat.sh` as emergency fallback.

---

## Build Order

```
Task 1 (cleanup + compose)
  └→ Task 2 (hub orchestration)
       └→ Task 3 + Task 4 (Windows GUI + Linux bash — parallel)
            └→ Task 5 (PyInstaller .exe)
                 └→ Task 6 (Starship UI)
                      └→ Task 7 (OTA upgrade)
                           └→ Task 8 (testing)
```
