# Node Docker-Only Deployment — Design Spec

**Date:** 2026-03-22
**Status:** Draft
**Decision:** ADR-258 (All previous node projects cancelled due to failed delivery)

---

## Problem

ARCHIE nodes cannot be deployed to Windows or Mac machines. The previous approach used PyInstaller GUI installers, Inno Setup, PowerShell script generators, bind mounts, local Python files, and OTA file manipulation on the host. All of it failed. Node .246 was corrupted when OTA overwrote docker-compose.yml with an empty file. 200GB of Docker debris left on the machine. Client relationship damaged.

The root cause: the docker-compose.node.yml uses `build:` (requires local Dockerfile + Python files) and bind mounts (requires host filesystem manipulation). This violates the "Docker only" promise.

## Solution

Publish the node as a Docker image to GitHub Container Registry. The compose file uses ONLY `image:` references. Zero local files beyond docker-compose.yml and .env. Zero build steps. Zero bind mounts for code.

## Architecture

### 3 Components

#### 1. Published Docker Image

**Image:** `ghcr.io/kytranempowerment/archie-node:latest`

Built automatically by GitHub Actions on every push to `main` that touches `node_client/`. Contains:
- Python 3.11 runtime
- node_sync.py (heartbeat, OTA polling, agent management)
- node_api.py (REST API, BEACON endpoints)
- node_triage.py (local task routing)
- requirements.txt dependencies (flask, psycopg2-binary, requests, psutil)
- Database migrations in /app/migrations/

The image is the SINGLE source of truth for node code. No code exists on the host machine.

**Dockerfile** (existing `node_client/Dockerfile.node`, unchanged):
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl jq && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask psycopg2-binary requests psutil
WORKDIR /app
COPY node_sync.py node_api.py node_triage.py ./
COPY migrations/ ./migrations/
CMD ["python3", "-u", "node_sync.py"]
```

**GitHub Actions workflow** (`.github/workflows/build-node-image.yml`):
- Trigger: push to main touching `node_client/**`
- Runner: ubuntu-latest (Linux — no Windows needed!)
- Steps: checkout, docker login to ghcr.io, docker build, docker push
- Tags: `latest` + git SHA for rollback

#### 2. Docker Compose (pull-only, zero build)

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: archie_node_ollama
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - OLLAMA_KEEP_ALIVE=24h
      - OLLAMA_NUM_PARALLEL=4
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "${OLLAMA_PORT:-11434}:11434"
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - archie_net

  postgres:
    image: postgres:16-alpine
    container_name: archie_node_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: archie_node
      POSTGRES_PASSWORD: ${DB_PASSWORD:-archie_node_default}
      POSTGRES_DB: archie_node
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U archie_node"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - archie_net

  sync:
    image: ghcr.io/kytranempowerment/archie-node:latest
    container_name: archie_node_sync
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      NODE_ID: ${NODE_ID}
      HUB_URL: ${HUB_URL}
      HUB_API_KEY: ${HUB_API_KEY}
      OLLAMA_HOST: http://ollama:11434
      DATABASE_URL: postgresql://archie_node:${DB_PASSWORD:-archie_node_default}@postgres:5432/archie_node
      HEARTBEAT_INTERVAL: "30"
      SYNC_POLL_INTERVAL: "60"
      DEPLOYMENT_MODE: "starship"
      COMFYUI_PORT: "${COMFYUI_PORT:-8188}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: ["python3", "-u", "node_sync.py"]
    healthcheck:
      test: ["CMD-SHELL", "pgrep -f node_sync.py || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - archie_net

  node_api:
    image: ghcr.io/kytranempowerment/archie-node:latest
    container_name: archie_node_api
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://archie_node:${DB_PASSWORD:-archie_node_default}@postgres:5432/archie_node
      OLLAMA_HOST: http://ollama:11434
      NODE_ID: ${NODE_ID}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: ["python3", "-u", "node_api.py"]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:3001/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    ports:
      - "${NODE_API_PORT:-3001}:3001"
    networks:
      - archie_net

  comfyui:
    image: comfyui/base:latest
    container_name: archie_node_comfyui
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    volumes:
      - comfyui_data:/comfyui/models
    ports:
      - "${COMFYUI_PORT:-8188}:8188"
    networks:
      - archie_net

volumes:
  ollama_data:
  pg_data:
  comfyui_data:

networks:
  archie_net:
    driver: bridge
```

**Key differences from old compose:**
- `sync` and `node_api` use `image:` not `build:`
- NO bind mounts for Python files (code is IN the image)
- NO Dockerfile.node needed on client
- NO node_sync.py/node_api.py needed on client
- Docker socket still mounted (needed for container management OTA commands)
- Migrations baked into image (run on first boot via node_sync.py init)
- Tailscale removed (simplify — add back later if needed)
- Container names simplified: `archie_node_*` instead of `archie_starship_*`

#### 3. One-Click Install via Starship UI

**Flow:**
1. Admin opens Starship, clicks "+Add Node"
2. Hub generates `node_id` and `api_key`, creates pending record in `remote_nodes`
3. Hub serves a downloadable ZIP file containing:
   - `docker-compose.yml` (the pull-only compose above)
   - `.env` (pre-filled with NODE_ID, HUB_URL, HUB_API_KEY)
   - `start.bat` (Windows: `docker compose up -d & pause`)
   - `start.command` (Mac: `#!/bin/bash\ndocker compose up -d`)
   - `stop.bat` / `stop.command` (graceful shutdown)
   - `update.bat` / `update.command` (`docker compose pull && docker compose up -d`)
   - `README.txt` (plain English: "Install Docker Desktop, extract this folder, double-click start")
4. User downloads ZIP to any folder on their machine
5. User double-clicks `start.bat` (Windows) or `start.command` (Mac)
6. Docker pulls all images from registry, starts containers
7. Node auto-registers with hub via heartbeat
8. Admin approves in Starship UI (or auto-approve for LAN nodes)

**Hub endpoint:** `GET /tools/starship/api/nodes/<node_id>/download`
Returns ZIP with all files pre-configured for that specific node.

## Update Flow (replaces broken OTA file manipulation)

**Code updates (new node_sync.py, node_api.py, etc.):**
1. Developer pushes to main
2. GitHub Actions builds new `archie-node:latest` image
3. Admin clicks "Push Update" in Starship OTA tab
4. Hub sends OTA sync: `{"sync_type": "container_restart", "payload": {"action": "pull_and_restart"}}`
5. Node's sync poller receives it, runs: `docker compose pull && docker compose up -d`
6. New containers start with new code baked in
7. Zero files touched on the host. Ever.

**Model updates (Ollama models, ComfyUI checkpoints):**
Same as before — OTA `model_pull` and `comfyui_setup` commands work unchanged because they operate inside containers, not on the host.

**Cleanup (new OTA sync type: `docker_cleanup`):**
Cleans up Docker debris — dangling images, unused volumes, build cache. Prevents the 200GB disaster from happening again.
1. Admin clicks "Cleanup Node" in Starship
2. Hub sends OTA: `{"sync_type": "docker_cleanup", "payload": {"action": "prune_all"}}`
3. Node runs: `docker system prune -af --volumes` (removes ALL unused images, containers, volumes, build cache)
4. Node reports freed space back to hub
5. Hub displays result in Starship UI

This should be a SCHEDULED job too — weekly auto-cleanup via agent loop, reports disk usage in heartbeat so hub can trigger cleanup proactively when free space drops below 20%.

## What This Eliminates

| Old Approach | Status | New Approach |
|---|---|---|
| PyInstaller .exe builder | ELIMINATED | Not needed — no local Python |
| Inno Setup installer | ELIMINATED | Not needed — ZIP + double-click |
| NSSM Windows service | ELIMINATED | Docker Desktop auto-starts |
| PowerShell script generators | ELIMINATED | Simple .bat in ZIP |
| Bash script generators | ELIMINATED | Simple .command in ZIP |
| Bind mounts for .py files | ELIMINATED | Code baked in image |
| OTA file downloads to host | ELIMINATED | Image pull from registry |
| Dockerfile.node on client | ELIMINATED | Build happens in CI |
| Local Python on client | ELIMINATED | Python is in the image |
| Tailscale VPN container | DEFERRED | Add back when needed |
| 1,363-line tkinter installer | ELIMINATED | ZIP with 4 files |

## What Stays

- node_sync.py (2,146 lines) — unchanged, runs inside container
- node_api.py (1,415 lines) — unchanged, runs inside container
- node_triage.py (99 lines) — unchanged, runs inside container
- OTA pipeline (mesh_sync_log) — unchanged, same 11 sync types
- Hub registration flow — unchanged
- Starship UI — enhanced with download button
- Heartbeat/sync polling — unchanged

## Prerequisites for the User

1. **Docker Desktop** installed (download from docker.com — GUI installer for Windows/Mac)
2. **NVIDIA drivers** installed (if GPU node — already installed on gaming/workstation PCs)
3. That's it.

## Files to Create/Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/build-node-image.yml` | CREATE | GitHub Actions to build + push image |
| `node_client/docker-compose.node.yml` | MODIFY | Replace `build:` with `image:`, remove bind mounts |
| `platform_v2/tools/starship/node_routes.py` | MODIFY | Add ZIP download endpoint |
| `node_client/start.bat` | CREATE | Windows one-click start (1 line) |
| `node_client/start.command` | CREATE | Mac one-click start (2 lines) |
| `node_client/stop.bat` | CREATE | Windows graceful stop (1 line) |
| `node_client/stop.command` | CREATE | Mac graceful stop (2 lines) |
| `node_client/update.bat` | CREATE | Windows pull + restart (1 line) |
| `node_client/update.command` | CREATE | Mac pull + restart (2 lines) |

## Rollback Plan

If the new image doesn't work:
- Images are tagged by git SHA: `ghcr.io/kytranempowerment/archie-node:abc123`
- Change compose to pin a known-good SHA instead of `latest`
- `docker compose pull && docker compose up -d`
- Node rolls back in 30 seconds

## Success Criteria

1. Fresh Windows machine: download ZIP, double-click start.bat, node appears in Starship within 2 minutes
2. Fresh Mac machine: same flow with start.command
3. OTA code update: push to main, GitHub Actions builds image, hub sends update command, node pulls and restarts with new code
4. No files on host except docker-compose.yml, .env, and .bat/.command scripts
5. Uninstall: `docker compose down -v` removes everything

## Estimated Scope

- GitHub Actions workflow: ~30 lines YAML
- Compose rewrite: ~80 lines (smaller than current 178)
- ZIP download endpoint: ~50 lines Python
- .bat/.command files: 1-2 lines each
- Total new code: ~170 lines
- Total eliminated code: ~2,500+ lines (installer, build script, PowerShell generators, bash generators)
