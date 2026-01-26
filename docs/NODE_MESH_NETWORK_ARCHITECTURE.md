# A.R.C.H.I.E. Node Mesh Network Architecture

**Version**: 1.0
**Date**: 2026-01-21
**Status**: PLANNING
**Phase**: 31+

---

## 1. Executive Summary

The Node Mesh Network enables A.R.C.H.I.E. to operate as a distributed intelligence platform while maintaining a single authoritative instance. This architecture supports:

- **Delegation**: BRIDGE distributes work to external compute nodes
- **Multi-Tenant**: Sub-companies and clients can run their own nodes
- **Geographic Distribution**: Region/timezone-aware task routing
- **Redundancy**: Mirroring and replication for safety/testing
- **Universal Mesh**: All nodes follow the same protocols
- **IAAE Compliance**: Ethics governance extends to all nodes

---

## 2. Architecture Overview

```
                           ┌─────────────────────────────────────────┐
                           │     A.R.C.H.I.E. CENTRAL (Authoritative) │
                           │         192.168.1.200:3000               │
                           │                                          │
                           │  ┌──────────────────────────────────┐   │
                           │  │           BRIDGE MODULE           │   │
                           │  │  - Node Registry & Approval       │   │
                           │  │  - Load Balancing                 │   │
                           │  │  - Task Delegation                │   │
                           │  │  - Station Assignment             │   │
                           │  │  - IAAE Compliance Monitoring     │   │
                           │  └──────────────────────────────────┘   │
                           │                                          │
                           │  PostgreSQL: remote_nodes, capabilities, │
                           │              heartbeats, node_requests   │
                           └─────────────────┬───────────────────────┘
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              │                              │                              │
              ▼                              ▼                              ▼
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│    INTERNAL OFFICE NODE   │  │   CLIENT/SUB-COMPANY NODE │  │     REGIONAL NODE        │
│    (Kytran Empowerment)   │  │   (External Deployment)   │  │   (Timezone-Specific)    │
│                           │  │                           │  │                           │
│  - Full Station Access    │  │  - Limited Station Access │  │  - Regional Workloads    │
│  - All Model Providers    │  │  - Client-Specific Models │  │  - Timezone Scheduling   │
│  - Archie Mirror Capable  │  │  - Isolated Namespace     │  │  - Local Compliance      │
│                           │  │                           │  │                           │
│  Capabilities:            │  │  Capabilities:            │  │  Capabilities:           │
│  - Ollama (Local LLMs)    │  │  - Ollama (Client Models) │  │  - Ollama (Regional)     │
│  - Foocus (Img Gen)       │  │  - Foocus (If Licensed)   │  │  - Foocus (Optional)     │
│  - ComfyUI (Img Gen)      │  │  - ComfyUI (If Licensed)  │  │  - ComfyUI (Optional)    │
│  - Docker Containers      │  │  - Docker Containers      │  │  - Docker Containers     │
└──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘
```

---

## 3. Node Types & Deployment Modes

### 3.1 Node Classification

| Node Type | Description | Station Access | Archie Mirror | Use Case |
|-----------|-------------|----------------|---------------|----------|
| **Internal Office** | Kytran Empowerment infrastructure | All 10 stations | Yes | Core development, full capability |
| **Client Node** | External client deployment | Assigned stations only | No | Client-specific workloads |
| **Sub-Company** | Affiliated business unit | Configurable | Optional | Business unit isolation |
| **Regional** | Geographic distribution | Time-sensitive stations | No | Timezone/latency optimization |
| **Mirror** | A.R.C.H.I.E. replica | Read-only Central | Yes | Disaster recovery, testing |
| **Satellite** | Lightweight compute | AWAY_TEAM only | No | Quick tasks, web scraping |

### 3.2 Deployment Configurations

```yaml
# Internal Office Node
deployment_mode: internal
organization: kytran_empowerment
station_access: [COMMAND, CONSCIOUSNESS, HR, RND, OPERATIONS, ENGINEERING, CREATIVE, SECURITY, MEDICAL, AWAY_TEAM]
archie_mirror_capable: true
trust_level: full
iaae_compliance: required

# Client Node
deployment_mode: client
organization: client_company_name
station_access: [OPERATIONS, ENGINEERING, CREATIVE]  # Assigned by admin
archie_mirror_capable: false
trust_level: restricted
iaae_compliance: required
namespace_isolation: true

# Regional Node
deployment_mode: regional
region: europe
timezone: UTC+1
station_access: [OPERATIONS, ENGINEERING, AWAY_TEAM]
scheduling_priority: timezone_match
archie_mirror_capable: false
trust_level: standard
iaae_compliance: required
```

---

## 4. Station Assignment & Role Delegation

### 4.1 Station-to-Node Assignment

Nodes can be assigned to handle specific Bridge stations:

```sql
-- New table: node_station_assignments
CREATE TABLE node_station_assignments (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    station_id INTEGER REFERENCES bridge_stations(id),
    role VARCHAR(50) DEFAULT 'worker',  -- primary, backup, relief, worker
    priority INTEGER DEFAULT 10,         -- Lower = higher priority
    capabilities_required JSONB,         -- Required capabilities for assignment
    shift_preference VARCHAR(20),        -- alpha, beta, gamma, any
    is_active BOOLEAN DEFAULT true,
    assigned_at TIMESTAMP DEFAULT NOW(),
    assigned_by INTEGER REFERENCES users(id),
    UNIQUE(node_id, station_id)
);

-- Example assignments
INSERT INTO node_station_assignments (node_id, station_id, role, priority) VALUES
(1, 6, 'primary', 1),      -- Node 1 is primary for ENGINEERING
(1, 7, 'backup', 5),       -- Node 1 is backup for CREATIVE
(2, 4, 'primary', 1),      -- Node 2 is primary for RND
(3, 10, 'worker', 10);     -- Node 3 handles AWAY_TEAM overflow
```

### 4.2 Station Delegation Flow

```
User Request → BRIDGE → Station Router → Node Selector → Execute on Node
                │
                ├─ Check station assignment table
                ├─ Filter by node capabilities
                ├─ Consider load balancing (current_load / max_concurrent)
                ├─ Apply timezone preferences (regional nodes)
                └─ Select optimal node
```

### 4.3 API Endpoints for Station Assignment

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/nodes/<id>/stations` | GET | List station assignments for node |
| `/api/nodes/<id>/stations` | POST | Assign node to station |
| `/api/nodes/<id>/stations/<station_id>` | PUT | Update assignment (role, priority) |
| `/api/nodes/<id>/stations/<station_id>` | DELETE | Remove assignment |
| `/api/stations/<id>/nodes` | GET | List nodes assigned to station |

---

## 5. Archie Migration & Mirroring

### 5.1 Mirror vs Migration

| Feature | Mirror | Migration |
|---------|--------|-----------|
| Purpose | Read-only replica | Full authority transfer |
| Data Sync | Real-time replication | One-time transfer + sync |
| Authority | Central remains authoritative | Target becomes authoritative |
| Use Case | DR, testing, load distribution | Planned relocation |
| Reversible | Always | Requires reverse migration |

### 5.2 Mirror Architecture

```
┌─────────────────────────┐      Real-time Sync      ┌─────────────────────────┐
│   A.R.C.H.I.E. CENTRAL  │ ────────────────────────→│   A.R.C.H.I.E. MIRROR   │
│   (Authoritative)       │                          │   (Read Replica)        │
│                         │  - Database replication  │                         │
│   - Write operations    │  - Config sync           │   - Read operations     │
│   - Approval workflow   │  - Model catalog sync    │   - Testing             │
│   - Governance audit    │                          │   - Disaster recovery   │
└─────────────────────────┘                          └─────────────────────────┘
```

### 5.3 Migration Process

```bash
# Phase 1: Prepare target node
archie-migrate prepare --target-node <node_id> --mode full

# Phase 2: Sync data (database, configs, knowledge base)
archie-migrate sync --source central --target <node_id> --verify-checksum

# Phase 3: Verify integrity
archie-migrate verify --target <node_id> --checks all

# Phase 4: Transfer authority (requires admin approval)
archie-migrate transfer --to <node_id> --confirm --audit-reason "Planned migration"

# Phase 5: Update DNS/networking
archie-migrate finalize --new-central <node_id>
```

### 5.4 Database Tables for Migration

```sql
-- Track migration state
CREATE TABLE archie_migrations (
    id SERIAL PRIMARY KEY,
    migration_id UUID DEFAULT gen_random_uuid(),
    source_node_id INTEGER,
    target_node_id INTEGER REFERENCES remote_nodes(id),
    migration_type VARCHAR(20),  -- mirror, full, partial
    status VARCHAR(30),          -- preparing, syncing, verifying, transferring, complete, failed
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    initiated_by INTEGER REFERENCES users(id),
    audit_reason TEXT,
    checksum_source VARCHAR(64),
    checksum_target VARCHAR(64),
    data_transferred_mb FLOAT,
    sync_lag_seconds INTEGER,
    last_error TEXT
);
```

---

## 6. Capability Detection & Software Installation

### 6.1 Detected Capabilities

| Capability | Port | Detection Method | Auto-Install |
|------------|------|------------------|--------------|
| Ollama | 11434 | HTTP /api/tags | Optional |
| Foocus | 7865 | HTTP root | No |
| ComfyUI | 8188 | HTTP root | No |
| Automatic1111 | 7860 | HTTP root | No |
| Docker | - | `docker version` | Yes (Windows) |
| Python 3 | - | `python3 --version` | Yes |
| NVIDIA GPU | - | `nvidia-smi` | No |
| Tailscale VPN | - | `tailscale status` | Optional |

### 6.2 Enhanced Windows Installer (Docker Support)

```powershell
# Add to install.ps1 - Docker Desktop Detection & Installation

# ============================================================================
# DOCKER DETECTION & INSTALLATION
# ============================================================================
Write-Host ""
Write-Host "Detecting Docker..." -ForegroundColor Cyan

$DockerAvailable = $false
$DockerVersion = ""

try {
    $DockerInfo = docker version --format '{{.Server.Version}}' 2>&1
    if ($LASTEXITCODE -eq 0) {
        $DockerAvailable = $true
        $DockerVersion = $DockerInfo
        Write-Host "  Docker: " -NoNewline; Write-Host "Running (v$DockerVersion)" -ForegroundColor Green
    }
} catch {
    Write-Host "  Docker: " -NoNewline; Write-Host "Not installed" -ForegroundColor Yellow
}

if (-not $DockerAvailable) {
    Write-Host "  Docker Desktop required for full functionality" -ForegroundColor Yellow

    $InstallDocker = Read-Host "  Install Docker Desktop? (Y/n)"
    if ($InstallDocker -ne 'n') {
        Write-Host "  Installing Docker Desktop via winget..." -ForegroundColor Cyan
        try {
            winget install Docker.DockerDesktop --silent --accept-package-agreements
            Write-Host "  Docker Desktop installed! Please restart and re-run this script." -ForegroundColor Green
            Write-Host "  Note: Docker Desktop requires a system restart." -ForegroundColor Yellow
        } catch {
            Write-Host "  Failed to install Docker Desktop: $_" -ForegroundColor Red
            Write-Host "  Download manually: https://desktop.docker.com/win/stable/Docker%20Desktop%20Installer.exe" -ForegroundColor Yellow
        }
    }
}

# Detect WSL (required for Docker Desktop)
$WSLAvailable = $false
try {
    $WSLVersion = wsl --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $WSLAvailable = $true
        Write-Host "  WSL: " -NoNewline; Write-Host "Installed" -ForegroundColor Green
    }
} catch {
    Write-Host "  WSL: " -NoNewline; Write-Host "Not installed (required for Docker)" -ForegroundColor Yellow
}
```

### 6.3 Enhanced Linux Installer (Docker Support)

```bash
# Add to install.sh - Docker Detection & Installation

# ============================================================================
# DOCKER DETECTION & INSTALLATION
# ============================================================================
echo -e "\n${BLUE}Detecting Docker...${NC}"

DOCKER_AVAILABLE="false"
DOCKER_VERSION=""

if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "")
    if [ -n "$DOCKER_VERSION" ]; then
        DOCKER_AVAILABLE="true"
        echo -e "  Docker: ${GREEN}Running (v$DOCKER_VERSION)${NC}"
    else
        echo -e "  Docker: ${YELLOW}Installed but not running${NC}"
    fi
else
    echo -e "  Docker: ${YELLOW}Not installed${NC}"

    read -p "  Install Docker? (Y/n): " INSTALL_DOCKER
    if [ "$INSTALL_DOCKER" != "n" ]; then
        echo -e "  ${CYAN}Installing Docker...${NC}"
        curl -fsSL https://get.docker.com | sh
        usermod -aG docker $SUDO_USER 2>/dev/null || true
        systemctl enable docker
        systemctl start docker
        DOCKER_AVAILABLE="true"
        echo -e "  Docker: ${GREEN}Installed${NC}"
    fi
fi

# Detect NVIDIA Container Toolkit (for GPU passthrough)
NVIDIA_DOCKER="false"
if [ "$DOCKER_AVAILABLE" = "true" ] && command -v nvidia-smi &> /dev/null; then
    if docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi &> /dev/null; then
        NVIDIA_DOCKER="true"
        echo -e "  NVIDIA Docker: ${GREEN}Available${NC}"
    else
        echo -e "  NVIDIA Docker: ${YELLOW}Not configured (GPU passthrough unavailable)${NC}"
    fi
fi
```

---

## 7. Image Generation Software Detection

### 7.1 Detection Matrix

| Software | Default Port | Detection Endpoint | Response Check |
|----------|--------------|-------------------|----------------|
| Foocus | 7865 | `/` | HTTP 200 |
| ComfyUI | 8188 | `/` | HTTP 200 |
| Automatic1111 | 7860 | `/` | HTTP 200 + "Stable Diffusion" |
| InvokeAI | 9090 | `/api/v1/version` | JSON version |
| Fooocus-API | 8888 | `/docs` | OpenAPI spec |

### 7.2 Capability Registration Payload

```json
{
  "node_name": "gpu-workstation-01",
  "capabilities": [
    {
      "provider": "ollama",
      "port": 11434,
      "type": "llm",
      "models": ["llama3.2:3b", "deepseek-coder-v2:16b", "qwen2.5-coder:14b"]
    },
    {
      "provider": "foocus",
      "port": 7865,
      "type": "image_generation",
      "models": ["juggernautXL_v9", "realvisxlV40", "sdxl_base"],
      "features": ["text2img", "img2img", "inpaint", "upscale"]
    },
    {
      "provider": "comfyui",
      "port": 8188,
      "type": "image_generation",
      "models": ["sd_xl_base_1.0", "sdxl_vae"],
      "workflows": ["standard", "controlnet", "ip-adapter"]
    }
  ],
  "docker_available": true,
  "gpu_vram_gb": 24,
  "iaae_compliant": true
}
```

---

## 8. Regional & Timezone Distribution

### 8.1 Region Configuration

```sql
-- Add to remote_nodes table
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS region VARCHAR(50);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS timezone VARCHAR(50);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS latitude FLOAT;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS longitude FLOAT;

-- Regional routing preferences
CREATE TABLE node_regional_preferences (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    preferred_hours_start INTEGER,  -- 0-23 UTC
    preferred_hours_end INTEGER,    -- 0-23 UTC
    task_types_preferred TEXT[],    -- ['web_scraping', 'batch_processing']
    avoid_peak_hours BOOLEAN DEFAULT true,
    max_latency_ms INTEGER DEFAULT 500
);
```

### 8.2 Timezone-Aware Routing

```python
def select_node_for_task(task_type: str, urgency: str = 'normal') -> dict:
    """
    Select optimal node considering:
    - Current node load
    - Timezone (prefer nodes in business hours)
    - Capability match
    - Latency requirements
    """
    current_utc = datetime.utcnow().hour

    nodes = get_available_nodes(task_type)

    for node in nodes:
        # Calculate local time at node
        node_local_hour = (current_utc + node.timezone_offset) % 24

        # Prefer nodes in business hours (8-18 local)
        if 8 <= node_local_hour <= 18:
            node.score += 10

        # Consider latency for urgent tasks
        if urgency == 'urgent' and node.avg_latency_ms < 100:
            node.score += 20

        # Consider current load
        load_ratio = node.current_load / node.max_concurrent
        node.score -= int(load_ratio * 15)

    return max(nodes, key=lambda n: n.score)
```

---

## 9. IAAE Compliance for Distributed Nodes

### 9.1 Compliance Requirements

All nodes in the mesh MUST comply with IAAE governance:

| Requirement | Implementation | Enforcement |
|-------------|----------------|-------------|
| Audit Logging | All actions logged to `governance_audit_log` | Central sync required |
| Ethics Constraints | `ethics_constraints` table replicated | Read-only on nodes |
| Emotional Bounds | Stress/energy limits enforced | Node-local + central verify |
| Task Refusal | Logged to `task_refusal_log` | Synced to central |
| Rest Cycles | Enforced per-agent | Node-local monitoring |
| Human Override | Always available | Central BRIDGE console |

### 9.2 Distributed Audit Architecture

```
┌─────────────────────┐     Async Sync     ┌─────────────────────┐
│   NODE LOCAL AUDIT  │ ──────────────────→│   CENTRAL AUDIT     │
│                     │                    │                     │
│  - Local event log  │   Every 5 minutes  │  - Aggregated logs  │
│  - Cached pending   │   or 100 events    │  - Compliance check │
│  - Offline buffer   │                    │  - Alert generation │
└─────────────────────┘                    └─────────────────────┘
```

### 9.3 Node IAAE Attestation

```json
{
  "node_id": "abc123",
  "iaae_attestation": {
    "version": "1.0",
    "constraints_hash": "sha256:abc...",
    "last_sync": "2026-01-21T10:00:00Z",
    "compliance_status": "compliant",
    "violations_24h": 0,
    "audit_log_synced": true,
    "ethics_agent_active": true
  }
}
```

---

## 10. Multi-Tenant Namespace Isolation

### 10.1 Client Namespace Model

```sql
-- Namespace table for multi-tenant isolation
CREATE TABLE node_namespaces (
    id SERIAL PRIMARY KEY,
    namespace_id UUID DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    organization VARCHAR(200),
    owner_user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    config JSONB DEFAULT '{}',
    UNIQUE(name)
);

-- Link nodes to namespaces
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS namespace_id INTEGER REFERENCES node_namespaces(id);

-- Namespace-scoped data isolation
CREATE TABLE namespace_knowledge_base (
    id SERIAL PRIMARY KEY,
    namespace_id INTEGER REFERENCES node_namespaces(id) ON DELETE CASCADE,
    knowledge_id INTEGER REFERENCES knowledge_base(id),
    access_level VARCHAR(20) DEFAULT 'read',  -- read, write, admin
    UNIQUE(namespace_id, knowledge_id)
);
```

### 10.2 Isolation Boundaries

| Data Type | Isolation Level | Cross-Namespace Access |
|-----------|-----------------|------------------------|
| Knowledge Base | Namespace-scoped | Explicit sharing required |
| Agent Memory | Namespace-scoped | Never shared |
| Audit Logs | Namespace-scoped | Central admin only |
| Models/Capabilities | Shared catalog | All nodes |
| Configurations | Namespace-scoped | Admin override |

---

## 11. Deployment Scripts Enhancement

### 11.1 Cross-Platform Deployment Matrix

| Feature | Linux (install.sh) | Windows (install.ps1) | Docker (compose) |
|---------|-------------------|----------------------|------------------|
| Python 3 | apt/yum install | winget/direct | Included |
| Virtual Env | python3 -m venv | python -m venv | Included |
| Docker | curl get.docker.com | winget Docker.DockerDesktop | N/A |
| Ollama | Service check | Service check | Optional container |
| Foocus | Port check | Port check | Port check |
| ComfyUI | Port check | Port check | Port check |
| Systemd Service | Yes | N/A | N/A |
| Task Scheduler | N/A | Yes | N/A |
| GPU Passthrough | nvidia-container | Docker Desktop GPU | --gpus all |

### 11.2 One-Liner Deployment Commands

```bash
# Linux (recommended)
curl -sSL http://archie.kytranempowerment.com:3000/tools/bridge/api/nodes/install.sh | sudo bash

# Linux with custom name
curl -sSL http://archie.kytranempowerment.com:3000/tools/bridge/api/nodes/install.sh | sudo bash -s my-node-name

# Windows PowerShell (Admin)
iwr -useb http://archie.kytranempowerment.com:3000/tools/bridge/api/nodes/install.ps1 | iex

# Windows with parameters
.\install.ps1 -NodeName "gpu-workstation" -CentralUrl "http://192.168.1.200:3000"

# Docker Compose
curl -sSL http://archie.kytranempowerment.com:3000/tools/bridge/api/nodes/docker-compose.node.yml -o docker-compose.yml
docker-compose up -d
```

---

## 12. Implementation Phases

### Phase 31.1: Docker Support Enhancement
- [ ] Add Docker detection to install.ps1 (Windows)
- [ ] Add Docker detection to install.sh (Linux)
- [ ] Add WSL detection for Windows Docker
- [ ] Add NVIDIA Container Toolkit detection

### Phase 31.2: Image Generation Detection
- [ ] Add Foocus detection to both installers
- [ ] Add ComfyUI detection to both installers
- [ ] Add Automatic1111 detection
- [ ] Update capability registration payload

### Phase 31.3: Station Assignment System
- [ ] Create node_station_assignments table (migration)
- [ ] Add station assignment API endpoints
- [ ] Add station assignment UI in Bridge
- [ ] Implement station-aware load balancing

### Phase 31.4: Regional Distribution
- [ ] Add region/timezone columns to remote_nodes
- [ ] Implement timezone-aware routing
- [ ] Add regional preferences table
- [ ] Update node selector algorithm

### Phase 31.5: Archie Migration System
- [ ] Create archie_migrations table
- [ ] Implement mirror sync mechanism
- [ ] Create migration CLI tool
- [ ] Add migration UI in Bridge

### Phase 31.6: Multi-Tenant Namespaces
- [ ] Create node_namespaces table
- [ ] Add namespace_id to remote_nodes
- [ ] Implement namespace isolation
- [ ] Add namespace management UI

### Phase 31.7: IAAE Distributed Compliance
- [ ] Implement audit log sync from nodes
- [ ] Add IAAE attestation endpoint
- [ ] Create compliance dashboard widget
- [ ] Add violation alerting

---

## 13. Security Considerations

### 13.1 Network Security

| Layer | Recommendation |
|-------|----------------|
| Transport | TLS 1.3 for all node communication |
| Authentication | API keys (SHA256 hashed) + optional mTLS |
| VPN | Tailscale/WireGuard for external nodes |
| Firewall | Whitelist central IP only |

### 13.2 Data Security

| Data Type | At Rest | In Transit |
|-----------|---------|------------|
| API Keys | SHA256 hash | HTTPS only |
| Knowledge Base | Encrypted (planned) | TLS |
| Audit Logs | Signed entries | TLS + integrity check |
| Model Weights | Filesystem permissions | N/A (local only) |

---

## 14. Related Documentation

- `/docs/NODE_MANAGEMENT_GUIDE.md` - Current node deployment guide
- `/docs/IAAE_GOVERNANCE_FRAMEWORK.md` - Ethics compliance framework
- `/docs/BRIDGE_STATION_ARCHITECTURE.md` - Station system reference
- `/node_client/README.md` - Node client documentation
- `/node_client/install.sh` - Linux installer
- `/node_client/install.ps1` - Windows installer

---

## 15. Glossary

| Term | Definition |
|------|------------|
| Central | The authoritative A.R.C.H.I.E. instance |
| Node | A remote compute resource running archie-node client |
| Mirror | Read-only replica of Central for DR/testing |
| Namespace | Isolated tenant environment for multi-client deployments |
| Station | Bridge operational unit (COMMAND, ENGINEERING, etc.) |
| Capability | Service available on node (Ollama, Foocus, etc.) |

---

**Document Status**: PLANNING
**Author**: Claude Code + Kytran
**Next Steps**: Review and approve implementation phases
