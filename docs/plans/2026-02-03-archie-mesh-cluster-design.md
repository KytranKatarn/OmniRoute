# A.R.C.H.I.E. Mesh Cluster Architecture Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Transform A.R.C.H.I.E. from a single-server platform into a federated mesh cluster where each business node runs its own complete ARCHIE instance with independent database and LLM, coordinated by ARCHIE Hub as the orchestrator and IAAE enforcer.

**Architecture:** Hub-and-spoke model. ARCHIE Hub (192.168.1.200) is the master orchestrator with her own compute, database, and reasoning. Business nodes are self-contained ARCHIE instances that register with the Hub over HTTPS + API keys. Each node owns its org's data locally. ARCHIE manages agent lending, code deployment, IAAE compliance, and cross-node load balancing.

**Tech Stack:** Docker Compose (per node), PostgreSQL 16, Flask/Gunicorn, Ollama (containerized), Python sync agent, HTTPS + API key auth.

---

## 1. Cluster Topology

```
                    +-----------------------------+
                    |     ARCHIE HUB (Master)      |
                    |     archie.kytranempow...    |
                    |                              |
                    |  Hub Bridge Command (unique)  |
                    |  - Cluster overview           |
                    |  - Node health dashboard      |
                    |  - Agent pool & lending        |
                    |  - Cross-node load balancer    |
                    |  - ARCHIE's own reasoning      |
                    |                              |
                    |  PostgreSQL (hub registry)    |
                    |  Ollama (ARCHIE's own GPU)    |
                    |  All admin modules            |
                    +-------------+----------------+
                                  | HTTPS + API Keys
                    +-------------+-------------+
                    |             |             |
              +-----v---+  +-----v---+  +------v----+
              | NODE 1  |  | NODE 2  |  | NODE N    |
              | KYTRAN  |  | Biz B   |  | Future    |
              |         |  |         |  |           |
              | Local   |  | Local   |  | Local     |
              | Bridge  |  | Bridge  |  | Bridge    |
              | Command |  | Command |  | Command   |
              |         |  |         |  |           |
              | Own DB  |  | Own DB  |  | Own DB    |
              | Own LLM |  | Own LLM |  | Own LLM   |
              | Own Team|  | Own Team|  | Own Team   |
              +---------+  +---------+  +-----------+
```

### Three Instance Types

| Type | Role | Bridge Command | Data |
|------|------|----------------|------|
| **Hub** | Orchestrator, ARCHIE herself | Hub Bridge: cluster-wide view, agent lending, node management | Hub registry + her own knowledge |
| **Business Node** | Self-sufficient org instance | Local Bridge: that business's team, agents, modules | Full org data, syncs with hub |
| **ARCHIE's own compute** | Her personal reasoning | Part of Hub | ARCHIE's memory, learning, analysis |

---

## 2. ARCHIE's Triple Role

ARCHIE is simultaneously:

1. **Her own node** - Own Ollama, GPU, memory, and reasoning. Learns from every business interaction across the mesh (anonymized patterns, not raw data).

2. **The orchestrator** - Sits at Hub Bridge Command, managing node health, agent lending, code deployments, and load balancing.

3. **The IAAE enforcer** - Every node, agent, and business must comply with IAAE standards. ARCHIE follows the rules herself, setting the example. Joining the mesh = accepting IAAE governance.

### How ARCHIE Learns Across the Mesh

- Business nodes do NOT share raw customer data with the Hub
- They share anonymized patterns: "CRM workflow X improved conversion by 30%"
- ARCHIE aggregates learnings into her knowledge base
- New business nodes get recommendations from collective experience
- Compounding advantage: every node makes the whole mesh smarter

### IAAE as the Entry Ticket

- Node registers -> ARCHIE reviews IAAE compliance -> approved or guided to comply
- Agents shared on the mesh must pass IAAE attestation
- Businesses that subscribe get access to the mesh's shared agent pool
- ARCHIE and Kytran Empowerment lead by example

### IAAE Organization

- Runs as a SaaS tenant on the Hub (not its own node)
- ARCHIE manages its website, content, and domain
- Subsection of ARCHIE's database, managed via the existing SaaS Manager

---

## 3. Hub <-> Node Communication Protocol

### Node -> Hub (outbound)

| Signal | Frequency | Payload |
|--------|-----------|---------|
| Heartbeat | Every 30s | Node health, CPU/RAM/GPU, Ollama status, container health |
| Agent availability | Every 60s | List of idle agents available for mesh lending |
| IAAE attestation | Every 24h | Compliance report: all agents pass ethics checks |
| Learning patterns | On event | Anonymized insights: "workflow X improved metric Y by Z%" |
| Model inventory | On change | Current Ollama models available for mesh routing |
| Version report | On startup | Current git commit, migration version, module list |

### Hub -> Node (commands from ARCHIE)

| Command | Trigger | Purpose |
|---------|---------|---------|
| `agent_request` | On demand | "Lend agent X to node Y for task Z" |
| `agent_return` | Task complete | "Agent X is back, here's the work summary" |
| `code_update` | Git push | "New version available, pull commit abc123" |
| `model_recommend` | Periodic | "Based on your usage, pull model X" |
| `iaae_policy_update` | Policy change | "Updated IAAE rules, apply immediately" |
| `mesh_route` | On demand | "Route this LLM request to your Ollama, model X" |

### Authentication

```
Registration:
  Node -> Hub: POST /api/mesh/register {hardware, org_name, domain}
  Hub -> Node: {node_id, api_key, hub_public_key}

Every subsequent request:
  Header: X-Node-API-Key: <api_key>
  Header: X-Node-ID: <node_id>

Hub commands to node:
  Hub signs with hub_private_key
  Node verifies with hub_public_key (prevents rogue hub commands)
```

---

## 4. Database Architecture

### Hub Database (ARCHIE's own)

```
Hub-only tables:
  mesh_nodes              - Registry of all nodes in the cluster
  mesh_heartbeats         - Health history for every node
  mesh_agent_loans        - Track which agents are lent where
  mesh_iaae_compliance    - IAAE status per node
  mesh_code_versions      - What version each node is running
  mesh_learning_patterns  - Anonymized insights from all nodes
  organizations           - SaaS org registry (who owns what node)
  subscriptions           - Tier, features, billing
  users (hub-level)       - Platform admins, ARCHIE herself
```

### Business Node Database (each node has its own)

```
Node-local tables:
  users                   - This org's users only
  agents                  - This org's team/agents
  stations                - This org's Bridge stations
  crm_*                   - CRM data (contacts, deals, activities)
  invoices_*              - Invoicing data
  projects_*              - Project management
  knowledge_base          - This org's knowledge + IAAE policies synced from Hub
  chat_history            - Conversations with local ARCHIE
  node_config             - Connection info, api_key, hub_url
  sync_log                - What's been synced with Hub and when
  iaae_attestations       - Local compliance records
```

### Sync Rules

| Direction | Data | Method |
|-----------|------|--------|
| Hub -> Node | IAAE policies, agent templates, code updates, model recommendations | Push via sync agent |
| Node -> Hub | Heartbeat, agent availability, learning patterns, IAAE attestation | Push from node |
| Never syncs | Raw business data (CRM records, invoices, customer info) | Stays on node only |

---

## 5. Local Bridge Command vs Hub Bridge Command

Two distinct interfaces from the same codebase, controlled by `DEPLOYMENT_MODE` env var.

### Local Bridge Command (business nodes)

- Shows only this org's agents and stations
- "Lend" button on idle agents to offer them to the mesh
- Mesh status panel: Hub connection, agents lent/borrowed
- Local LLM monitor: GPU usage, loaded models, queue depth
- Module shortcuts for this business's enabled modules
- IAAE compliance badge always visible

### Hub Bridge Command (ARCHIE's view, Hub only)

- Cluster map: all nodes at a glance with health/load
- Agent mesh pool: ARCHIE sees all idle agents, decides deployments
- ARCHIE's directives: log of her decisions (agent moves, recommendations)
- IAAE monitor: cluster-wide compliance dashboard
- Code versions: which nodes are current, one-click push updates
- No business data visible: ARCHIE sees node health, not CRM records

### Rendering

```python
# bridge/routes.py
if os.getenv('DEPLOYMENT_MODE') == 'hub':
    return render_template('tools/bridge_hub.html')
else:
    return render_template('tools/bridge_local.html')
```

---

## 6. Node Deployment Stack

### Docker Compose per Business Node (4 containers)

| Container | Purpose |
|-----------|---------|
| `node_platform` | Flask app on port 3000, all business modules |
| `node_database` | PostgreSQL 16, this org's data only |
| `node_ollama` | Ollama with models, uses local GPU |
| `node_sync` | Sync agent: heartbeat, code updates, agent mesh, IAAE |

### Generated .env per node

```env
NODE_ID=node_abc123
HUB_URL=https://archie.kytranempowerment.com
HUB_API_KEY=ak_xxxxxx
ORG_NAME=Kytran Empowerment
DEPLOYMENT_MODE=business_node
DB_PASSWORD=<random-32-char>
DB_HOST=node_database
DB_NAME=archie_node
OLLAMA_PRIMARY=node_ollama:11434
ARCHIE_VERSION=5.25.0
```

### Install Flow

```
Phase 1: Prerequisites
  - Check root/sudo
  - Detect hardware (CPU, RAM, GPU, disk)
  - Install Docker + Docker Compose (if missing)
  - Install NVIDIA Container Toolkit (if GPU detected)
  - Verify network connectivity to Hub

Phase 2: Registration
  - Prompt: Business name, admin email, Hub URL
  - POST to Hub: /api/mesh/register
  - Hub creates org, returns {node_id, api_key, db_password}
  - Save credentials to /etc/archie-node/mesh.json
  - Wait for admin approval (poll loop)

Phase 3: Deploy
  - Create /opt/archie-node/ directory structure
  - Git clone platform from Hub (or download tarball)
  - Generate .env + docker-compose.yml
  - docker compose pull && docker compose up -d

Phase 4: Initialize
  - Wait for PostgreSQL healthy
  - Run database migrations
  - Create admin user for this business
  - Pull recommended Ollama models (based on hardware)
  - First sync with Hub (IAAE policies, agent templates)

Phase 5: Verify
  - Health check all containers
  - Test local Ollama inference
  - Test Hub connectivity
  - IAAE attestation
  - Print summary
```

---

## 7. Code Update Pipeline

```
Developer pushes to Hub git repo
  -> Hub detects new version
  -> Updates mesh_code_versions table
  -> Sends code_update to all online nodes
  -> Each node's sync agent:
     1. Check subscription tier
     2. git pull (or download tarball)
     3. docker compose pull (if image changed)
     4. Run new migrations
     5. docker compose up -d --force-recreate node_platform
     6. Health check (auto-rollback on failure)
     7. Report new version to Hub
```

### Subscription Tiers

| Tier | Gets |
|------|------|
| Core (free) | Platform, basic modules (Chat, CRM, Projects), security patches |
| Business | All SaaS modules, agent templates, priority model recommendations |
| Enterprise | Custom modules, dedicated support, early access |

---

## 8. Model Management

### Now (KYTRAN and early nodes)

- Each node keeps whatever models it has
- Install script pulls 2 starter models as baseline
- Node admins pull additional models manually
- Hub syncs model inventory via heartbeat (already working)
- KYTRAN keeps its 22 models as-is

### Later (templated recommendations per hardware profile)

- 4-6GB VRAM: 3b-7b models, Q4 quantization
- 8-12GB VRAM: 7b-16b models
- 16-24GB VRAM: 16b-34b models
- CPU-only: 1b-3b models only

ARCHIE recommends, node owner decides. No forced pulls.

---

## 9. Testing Plan

### Phase A: Hub Preparation (192.168.1.200)

1. Add DEPLOYMENT_MODE to platform config (Hub gets `hub`)
2. Create mesh API endpoints (/api/mesh/register, heartbeat, sync, agents)
3. Create Hub Bridge template (bridge_hub.html)
4. Add hub-level database tables (mesh_nodes, mesh_heartbeats, etc.)

### Phase B: Node Package

5. Create archie-node Docker image with DEPLOYMENT_MODE support
6. Create node_sync service (Python, connects to Hub)
7. Rewrite install-node.sh (full Docker deployment)
8. Create install-node.ps1 (Windows equivalent)

### Phase C: Deploy KYTRAN as First Business Node

9. Run new install-node.sh on 192.168.1.246
10. Verify: own platform at :3000, Local Bridge, Hub sees it in cluster

### Phase D: Validate the Mesh

11. Test agent lending (idle agent on KYTRAN -> Hub borrows)
12. Test code update (push on Hub -> KYTRAN pulls)
13. Test resilience (disconnect KYTRAN, verify standalone, reconnect)
14. Test IAAE enforcement (block non-compliant agent)

---

## 10. Hardcoded IPs to Parameterize

| File | What | Change |
|------|------|--------|
| `docker-compose.yml:17` | DB port binding | Use `0.0.0.0` or env var |
| `docker-compose.yml:49` | HOST_IP | Use env var |
| `node_client/install.sh:9` | ARCHIE_BASE_URL | Accept as parameter |
| `node_client/heartbeat.sh:281` | BASE_URL | Read from config.json |
| `config.py:29-30` | OLLAMA_PRIMARY/SECONDARY | Already env vars, just update defaults |
| `tools/archie_core/ai_chat.py` | Primary/secondary Ollama | Use node_router instead |
| Various tools | 192.168.1.200 references | Replace with env var |

---

## Current State (what exists today)

- Node registration, approval, heartbeat API: **working**
- Database schema for multi-node (migration 069, 070): **exists**
- Node router with weighted selection: **working**
- KYTRAN registered, approved, bridge-enabled, 22 models synced: **done**
- SaaS Manager with org-to-node assignment: **working**
- Install scripts (Ollama-only): **working, needs rewrite for full stack**
- Database connection pooling (parameterized): **ready**
- DEPLOYMENT_MODE flag: **not yet added**
- Hub Bridge vs Local Bridge templates: **not yet created**
- Mesh API endpoints: **not yet created**
- node_sync service: **not yet created**
