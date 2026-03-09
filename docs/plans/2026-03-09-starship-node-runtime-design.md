# Starship Node Runtime — Phase 1 Design

**Date:** 2026-03-09
**Project:** ARCHIE Starship Node Runtime
**Status:** Approved

---

## Overview

Transform Starship nodes from passive heartbeat senders into fully functional ARCHIE nodes with local agent runtime, database, and bidirectional mesh sharing. Phase 1 focuses on KYTRAN-StarShip (local Windows machine) with a deployment package that works for external nodes (Toronto friend test).

## Architecture

### Node Stack (4 containers)

```
+---------------------------------------------+
|           ARCHIE Starship Node              |
+-------------+-----------+-------------------+
|  node_api   |  ollama   |  postgres         |
|  (Flask)    |  (LLM)    |  (local DB)       |
|  port 3001  |  port 11434|  port 5432       |
+-------------+-----------+-------------------+
|              sync_service                    |
|  (heartbeat + sync polling + job exec)      |
+---------------------------------------------+
         | outbound HTTPS only |
         v                     v
    archie.kytranempowerment.com
         (Hub / Starbase)
```

- **node_api** — Lightweight Flask app. Receives agent configs, queues jobs, serves local status. Future: SaaS module endpoints.
- **ollama** — LLM inference engine (exists).
- **postgres** — Local node database. Same dialect as hub. Migrations on container startup.
- **sync_service** — Enhanced node_sync.py. Polls hub for pending syncs, processes agent_config and job_request, reports results. Heartbeat 30s, sync poll 60s.

All communication is outbound HTTPS polling. No inbound ports needed. Works behind NAT/firewalls.

## Onboarding Flow

### Hub Side (Starship Command)

1. Admin clicks "+ ADD NODE" button
2. Fills in: node name, owner name (optional), stations to enable
3. Hub generates: unique node_id, one-time setup token (24h expiry), pre-filled .env
4. Shows setup page with:
   - One-liner install commands for Windows and Linux
   - QR code linking to setup page
   - Download button for .env
   - Live status: "Waiting for node to connect..."
5. First heartbeat flips status to "Connected", auto-redirects to node detail

### Install Commands

Windows (PowerShell):
```
irm https://archie.kytranempowerment.com/starship/install?token=abc123 | iex
```

Linux/Mac (bash):
```
curl -fsSL https://archie.kytranempowerment.com/starship/install?token=abc123 | bash
```

### What the Install Script Does

1. Checks Docker installed; if not, opens Docker Desktop download (Windows) or runs get.docker.com (Linux)
2. Creates ~/archie-node/ directory
3. Downloads docker-compose.yml + .env (pre-configured with token)
4. Runs docker compose up -d
5. Prints: "Your node is connecting to ARCHIE..."

### Security

- Setup token is one-time use, 24h expiry
- Once node registers, token consumed and replaced with permanent API key
- API key stored in node's local Postgres

## Agent Runtime

### Job Execution Flow

```
Hub (Bridge Dispatcher)                    Node (sync_service)
        |                                         |
        |  1. Push agent config                    |
        |  --> mesh_sync_log (agent_config) -->    |
        |                                    saves crew manifest
        |                                    to local Postgres
        |                                         |
        |  2. Dispatch job                         |
        |  --> mesh_sync_log (job_request) -->     |
        |                                    picks up job
        |                                    loads agent config
        |                                    calls local Ollama
        |                                    streams response
        |                                         |
        |  3. Report results                       |
        |  <-- POST /api/mesh/sync/{id}/ack --     |
        |       with output in payload             |
        |                                         |
        |  4. Hub updates bridge_jobs              |
        |       marks complete/failed              |
```

### Agent Config Format (pushed to node)

```json
{
  "agents": [
    {
      "name": "OpsMaster",
      "display_name": "Ember Theron (OpsMaster)",
      "model": "mistral:latest",
      "system_prompt": "You are an operations specialist...",
      "station_codes": ["OPERATIONS"],
      "capabilities": ["analysis", "monitoring"]
    }
  ]
}
```

### Job Request Format (sent to node)

```json
{
  "job_id": 2701,
  "agent_name": "OpsMaster",
  "job_type": "analysis",
  "description": "Analyze system logs",
  "prompt": "Review these logs and identify issues...",
  "timeout_seconds": 300
}
```

### Execution

1. Sync service picks up job_request from pending syncs
2. Looks up agent config in local DB (model + system prompt)
3. Calls local Ollama: POST http://ollama:11434/api/generate
4. Captures full output
5. ACKs back to hub with status + output
6. Hub updates bridge_jobs with result

### Failure Handling

If Ollama down or model not pulled: ACK with status "failed" + error. Hub retries or escalates.

## Bidirectional Mesh Sharing

### Node Shares Agents to Hub

1. **Heartbeat advertises availability** — Every 30s, node includes idle agents + models + capabilities
2. **Hub dispatcher considers node agents** — When no hub agent available (or node has better model), dispatcher checks available_agents from heartbeats
3. **Creates mesh_agent_loan** — Queues job_request sync to node
4. **Node executes** — Returns result via ACK

### Privacy Controls (Starship Privacy tab)

- "Share idle agents with fleet" — on/off toggle
- "Max concurrent shared jobs" — limit hub jobs on node GPU
- "Priority: local first" — node's own jobs always take priority

## Starship Agents Tab Redesign

Replace simple agent list with Bridge Command manifest-style card grid.

### Each Agent Card Shows

- Agent name (display_name) + callsign subtitle
- Status badge (idle/working)
- MODEL READY / OFFLINE badge (fuzzy model match)
- Station tags (colored by station)
- Model name (Ollama model assigned)
- Sharing badge (SHARED / LOCAL ONLY)
- Active job progress bar (if running)

### Skipped for Now (future)

- Wellness/stress dots
- GPU/CPU/Cloud hardware tiers
- Load/Unload toggle
- Capacity bars (RAM/VRAM)

### Layout

Reuse crew-manifest-grid CSS and crew-agent-card styling from Bridge Command.

## Files

### New

- `node_client/node_api.py` — Flask app for local agent runtime
- `node_client/migrations/` — Schema for local node DB
- `node_client/Dockerfile.node` — Node API + sync image
- `platform_v2/tools/starship/templates/tools/starship/install.html` — Setup instructions page
- `platform_v2/tools/starship/install_routes.py` — Install script endpoints

### Modified

- `node_client/docker-compose.node.yml` — Add postgres + node_api containers
- `node_client/node_sync.py` — Add agent_config + job_request handlers, advertise idle agents
- `platform_v2/tools/bridge/routes.py` — Heartbeat includes pending syncs, dispatcher considers node agents
- `platform_v2/tools/starship/routes.py` — Onboarding endpoints, install script generation
- `platform_v2/tools/starship/templates/tools/starship/starship.html` — Manifest-style agents tab, + ADD NODE flow

## Future Phases (Dev HQ projects)

### Phase 2: SaaS Modules on Node

- Knowledge base, projects, CRM with local data
- Node serves its own SaaS features via node_api
- Data stays on node, only metadata syncs to hub

### Phase 3: Full Hub Orchestration

- Intelligent job routing across mesh
- Performance benchmarking across models/nodes
- Auto-scaling: spin up/down node agents based on demand
- Cross-node data federation (opt-in)

## Research References

- Kubernetes kubeadm join: token-based onboarding pattern
- Hive (HiveCore/HiveNode): outbound-only Ollama distributed inference
- Docker Compose: cross-platform deployment (Windows + Linux)
- dbmate: lightweight migration tool for both SQLite and Postgres
- Salt Bootstrap: curl-pipe-bash + PowerShell cross-platform installer pattern
