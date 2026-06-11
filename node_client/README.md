# A.R.C.H.I.E. Node Client

Deploy compute nodes to the A.R.C.H.I.E. starship mesh. Each node contributes Ollama LLM inference capacity to the platform, with optional full-stack deployment including a local Postgres database, sync service, and node API.

## Prerequisites

- **Linux** (Ubuntu 20.04+ recommended) or **Windows** (PowerShell scripts provided)
- **Python 3.8+** (for full-stack mode)
- **curl**, **jq** (installed automatically if missing)
- **Ollama** (installed automatically by the installer)
- **NVIDIA GPU** (optional, for GPU-accelerated inference)
- Network access to the A.R.C.H.I.E. hub at `192.168.1.200:3000`

## Quick Install (Linux)

One-liner that downloads and runs the installer:

```bash
curl -fsSL http://192.168.1.200:3000/tools/starbase/api/nodes/install.sh | sudo bash
```

This will:
1. Detect your hardware (CPU, RAM, GPU, disk)
2. Install Ollama (if not present) and configure it to listen on `0.0.0.0`
3. Pull starter models (`qwen2.5:7b`, `llama3.2:3b`)
4. Register the node with the A.R.C.H.I.E. platform
5. Install and start a systemd heartbeat service
6. Wait for admin approval
7. Optionally deploy the full Docker stack (Ollama + Postgres + sync + node API)

## Quick Install (Windows)

```powershell
irm http://192.168.1.200:3000/tools/starbase/api/nodes/install.ps1 | iex
```

### Windows reboot self-heal (#3956)

`install.ps1` already runs `node_sync.py` at startup as a **SYSTEM** scheduled task (`ARCHIE-Node-Sync`,
no login required) and every container is `restart: unless-stopped`. The only thing missing after an
unattended Patch-Tuesday reboot is starting the Docker **engine** — Docker Desktop is a per-user GUI
app, so with nobody signed in there is no engine and the node stays offline.

Run **once per Windows Starship**, as Administrator, signed in as the node user:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-node-autostart.ps1
```

It configures Docker Desktop "start at sign-in" + Windows auto-login (Sysinternals Autologon —
password stored as an LSA secret, never plaintext) and verifies the container restart policy. Reboot
chain afterwards: power on → auto-login → Docker Desktop → engine → `unless-stopped` containers →
`ARCHIE-Node-Sync` reconnects, hands-free. Tradeoff: the box auto-unlocks on boot (fine for a
dedicated LAN GPU node). Use `-SkipAutologon` for the Docker-autostart part only.

## Manual Install

1. **Clone or download** the `node_client/` directory to the target machine.

2. **Install Ollama** from https://ollama.com and ensure it listens on `0.0.0.0:11434`:
   ```bash
   # Linux: systemd override
   sudo mkdir -p /etc/systemd/system/ollama.service.d
   echo -e '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"' | sudo tee /etc/systemd/system/ollama.service.d/override.conf
   sudo systemctl daemon-reload && sudo systemctl restart ollama
   ```

3. **Pull starter models**:
   ```bash
   ollama pull qwen2.5:7b
   ollama pull llama3.2:3b
   ```

4. **Run the installer**:
   ```bash
   sudo bash install.sh
   ```

5. **Or configure manually** — copy `config.example.json` to `/etc/archie-node/config.json` and fill in the values from your node registration.

## Configuration

The node reads configuration from `/etc/archie-node/config.json` (created automatically by the installer). For manual setup, copy `config.example.json`:

```bash
sudo mkdir -p /etc/archie-node
sudo cp config.example.json /etc/archie-node/config.json
sudo chmod 600 /etc/archie-node/config.json
# Edit with your node_id and api_key from registration
```

### Config Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `node_id` | Yes | — | Assigned during registration (e.g., `starship_abc123`) |
| `api_key` | Yes | — | API key returned from registration |
| `server_url` | Yes | — | Hub URL (e.g., `http://192.168.1.200:3000`) |
| `heartbeat_interval` | No | `30` | Seconds between heartbeat pings |
| `sync_interval` | No | `60` | Seconds between sync command polls |
| `deployment_mode` | No | `starship` | Deployment type (`starship` or `starbase`) |
| `ollama_port` | No | `11434` | Local Ollama API port |
| `log_level` | No | `INFO` | Logging verbosity |

### Environment Variables (Full-Stack Mode)

When running in Docker (full-stack mode), these are set in `/opt/archie-node/.env`:

| Variable | Description |
|----------|-------------|
| `NODE_ID` | Node identifier |
| `HUB_URL` | Hub platform URL |
| `HUB_API_KEY` | Authentication key |
| `DB_PASSWORD` | Local Postgres password (auto-generated) |
| `OLLAMA_HOST` | Ollama endpoint (default: `http://ollama:11434`) |
| `DEPLOYMENT_MODE` | `starship` or `business_node` |
| `NODE_TIMEZONE` | Timezone (default: `America/Toronto`) |

## File Descriptions

### Core Scripts

| File | Description |
|------|-------------|
| `install.sh` | Linux installer — hardware detection, Ollama setup, registration, heartbeat service, optional Docker stack |
| `install.ps1` | Windows PowerShell installer — same workflow as `install.sh` |
| `heartbeat.sh` | Linux heartbeat daemon — sends system metrics (CPU, RAM, GPU, Ollama models) every 30s via systemd |
| `heartbeat.ps1` | Windows heartbeat daemon — same metrics collection for Windows nodes |

### Full-Stack Components

| File | Description |
|------|-------------|
| `node_sync.py` | Sync service — heartbeats, version reporting, processes sync commands (code updates, model pulls, job execution, agent configs) |
| `node_api.py` | Flask API (port 3001) — local agent management, job execution endpoint for Bridge dispatch |
| `node_triage.py` | Local triage logic — determines if a task can be handled locally or needs escalation to Bridge |
| `docker-compose.node.yml` | 4-service Docker stack: Ollama, Postgres, sync, node_api (optional ComfyUI for GPU nodes) |
| `Dockerfile.node` | Container image for sync and node_api services |

### Deployment & Updates

| File | Description |
|------|-------------|
| `deploy-node.ps1` | Windows deployment script — advanced setup and management |
| `update.ps1` | Windows self-update script — downloads and applies node client updates |
| `config.example.json` | Template configuration file |
| `requirements.txt` | Python dependencies for full-stack mode |

### Database

| File | Description |
|------|-------------|
| `migrations/001_node_schema.sql` | Base schema — `node_agent_configs`, `node_jobs` tables |
| `migrations/002_knowledge_projects.sql` | Extended schema for knowledge and project sync |

## Deployment Modes

### Ollama-Only (Default)
- Installs Ollama + heartbeat service
- Node serves as a pure LLM compute resource
- Hub dispatches inference requests directly to Ollama
- Minimal footprint, no Docker required

### Full-Stack (Docker)
- 4 containers: Ollama, Postgres, sync service, node API
- Local agent configuration storage
- Job queue with local execution tracking
- Sync commands from hub (code updates, model pulls, agent configs)
- Self-updating via OTA push from hub

## Heartbeat Data

Each heartbeat sends:
- **System metrics**: CPU usage, memory usage, GPU utilization
- **Hardware specs**: CPU model/cores, RAM GB, GPU model/VRAM
- **Ollama status**: online/offline, list of available models with sizes
- **Agent welfare**: stress, energy, task count per agent (full-stack mode)
- **Idle agents**: available agents for mesh job sharing
- **Client version**: for OTA update detection

## Sync Commands (Full-Stack Mode)

The sync service polls the hub for pending commands:

| Command | Description |
|---------|-------------|
| `code_update` | Download updated Python files and migrations, apply, restart |
| `model_pull` | Pull a new Ollama model (up to 30min timeout) |
| `agent_config` | Save crew manifest to local Postgres |
| `job_request` | Execute an inference job via local Ollama |
| `container_restart` | Restart specified Docker containers |
| `iaae_policy` | Receive governance policy updates (stub) |
| `model_recommend` | Receive model recommendations (stub) |

## Troubleshooting

### Node not appearing in dashboard
- Verify the hub is reachable: `curl http://192.168.1.200:3000/tools/starbase/api/nodes`
- Check heartbeat service: `sudo systemctl status archie-node-heartbeat`
- Check heartbeat logs: `sudo journalctl -u archie-node-heartbeat -f`
- Verify config: `sudo cat /etc/archie-node/config.json`

### Heartbeat failing
- Ensure Ollama is running: `curl http://localhost:11434/api/tags`
- Check network connectivity to hub
- Verify `api_key` in config matches registration
- Log file: `/var/log/archie-node/heartbeat.log`

### Ollama not responding
- Check service: `sudo systemctl status ollama`
- Restart: `sudo systemctl restart ollama`
- Verify listening on all interfaces: `ss -tlnp | grep 11434`

### Docker stack issues (full-stack mode)
- Check containers: `cd /opt/archie-node && docker compose ps`
- View logs: `docker compose logs -f sync` or `docker compose logs -f node_api`
- Restart stack: `docker compose restart`
- Check Postgres: `docker exec archie_starship_db pg_isready -U archie_node`

### Registration failed
- Ensure the hub platform is running
- Check if the registration endpoint is accessible
- Look for firewall rules blocking port 3000

### Self-update failed
- Check heartbeat logs for update errors
- Manually download: `curl -fsSL http://192.168.1.200:3000/tools/starbase/api/nodes/heartbeat.sh -o /opt/archie-node/heartbeat.sh`
- Restart heartbeat: `sudo systemctl restart archie-node-heartbeat`
