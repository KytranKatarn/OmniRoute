# A.R.C.H.I.E. Node Management Guide

**Phase**: 29+ Enhancement - Bridge Node Network Interface
**Last Updated**: 2026-01-21

## Overview

The Node Management system allows ARCHIE to distribute workloads across multiple compute nodes, creating a scalable AI infrastructure. Remote nodes can be deployed on any Linux machine and will connect back to the central ARCHIE server for coordinated AI processing.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CENTRAL ARCHIE (192.168.1.200)               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Bridge Module (/tools/bridge)                          │    │
│  │  - Node Registration API                                │    │
│  │  - Node Management UI                                   │    │
│  │  - Load Balancing                                       │    │
│  │  - Health Monitoring                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                            │                                    │
│                     PostgreSQL Database                         │
│                   (remote_nodes, node_capabilities,             │
│                    node_heartbeats, node_requests)              │
└─────────────────────────────────────────────────────────────────┘
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │  Remote Node  │ │  Remote Node  │ │  Remote Node  │
    │ (192.168.1.200)│ │ (10.8.0.x)   │ │ (VPN Client) │
    │               │ │               │ │               │
    │ - Ollama      │ │ - Ollama      │ │ - Ollama      │
    │ - Heartbeat   │ │ - Heartbeat   │ │ - Heartbeat   │
    │ - Capabilities│ │ - Capabilities│ │ - Capabilities│
    └───────────────┘ └───────────────┘ └───────────────┘
```

## Deployment Methods

### 1. Linux/macOS One-Liner Install (Recommended)

On the target Linux/macOS machine, run:

```bash
curl -sSL http://192.168.1.200:3000/tools/bridge/api/nodes/install.sh | sudo bash
```

### 2. Windows PowerShell Install

On Windows, open PowerShell **as Administrator** and run:

```powershell
iwr -useb http://192.168.1.200:3000/tools/bridge/api/nodes/install.ps1 | iex
```

Or download and run with parameters:
```powershell
# Download the script
Invoke-WebRequest -Uri "http://192.168.1.200:3000/tools/bridge/api/nodes/install.ps1" -OutFile "install.ps1"

# Run with custom name
.\install.ps1 -NodeName "my-windows-node" -CentralUrl "http://192.168.1.200:3000"
```

**Windows Requirements:**
- Windows 10/11 or Windows Server 2016+
- Python 3.9+ installed (from python.org, check "Add to PATH")
- PowerShell 5.1+ (built-in)
- Administrator privileges

Both installers will:
1. Install dependencies (Python3, pip, curl, jq)
2. Create `/opt/archie-node` directory
3. Download the node client package
4. Collect hardware info (CPU, RAM, GPU, Disk, Ollama models)
5. Register with central ARCHIE
6. Wait for admin approval (if required)
7. Create and start the systemd service

### 2. Manual Installation

```bash
# Clone or download the node client
git clone https://github.com/your-org/archie-node /opt/archie-node

# Install dependencies
cd /opt/archie-node
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
NODE_ID=your-node-id
API_KEY=your-api-key
NODE_NAME=my-node
CENTRAL_URL=http://192.168.1.200:3000
OLLAMA_HOST=http://localhost:11434
HEARTBEAT_INTERVAL=30
CAPABILITY_INTERVAL=300
EOF

# Run the node
python archie_node.py run
```

## Node Approval Workflow

New nodes register with `approval_status = 'pending'` by default. An admin must approve the node in the Bridge UI before it becomes active.

### States

| Status | Description |
|--------|-------------|
| `pending` | Node registered, awaiting admin approval |
| `approved` | Node approved and active in the network |
| `rejected` | Node rejected by admin |

### Approval Process

1. Node runs install.sh and registers with central
2. Install.sh polls for approval (5 minute timeout)
3. Admin sees pending node in Bridge UI
4. Admin clicks APPROVE or REJECT
5. Node receives approval and starts heartbeat service

## Bridge UI Features

Access the Node Network interface at: `http://192.168.1.200:3000/tools/bridge`

### Node Stats Bar
- Online count (green)
- Offline count (gray)
- Pending count (blue)
- "+ Add Node" button

### Pending Approval Section
- Shows nodes awaiting approval
- APPROVE / REJECT buttons
- Hardware specs display

### Active Nodes Grid
- Node cards with status indicator
- Hardware specs (CPU, RAM, GPU)
- Load bar (current/max concurrent)
- TEST button (checks Ollama connectivity)
- DETAIL button (node details modal)

## API Endpoints

### Node Registration & Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/bridge/api/nodes` | GET | List all nodes |
| `/tools/bridge/api/nodes/register` | POST | Register new node |
| `/tools/bridge/api/nodes/<id>` | GET | Get node details |
| `/tools/bridge/api/nodes/<id>` | PUT | Update node config |
| `/tools/bridge/api/nodes/<id>` | DELETE | Remove node |

### Node Status & Actions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/bridge/api/nodes/<id>/status` | GET | Get approval status (polling) |
| `/tools/bridge/api/nodes/<id>/approve` | POST | Approve pending node |
| `/tools/bridge/api/nodes/<id>/reject` | POST | Reject pending node |
| `/tools/bridge/api/nodes/<id>/test` | POST | Test node connectivity |
| `/tools/bridge/api/nodes/<id>/health-history` | GET | Get health metrics |

### Node Heartbeat & Capabilities

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/bridge/api/nodes/<id>/heartbeat` | POST | Node heartbeat (every 30s) |
| `/tools/bridge/api/nodes/<id>/capabilities` | POST | Update Ollama models |

## Database Schema

### remote_nodes Table

```sql
id SERIAL PRIMARY KEY
node_id VARCHAR(64) UNIQUE
node_name VARCHAR(100)
description TEXT
vpn_ip VARCHAR(45)
hostname VARCHAR(255)
port INTEGER DEFAULT 11434
api_key_hash VARCHAR(256)
status VARCHAR(20) DEFAULT 'offline'
approval_status VARCHAR(20) DEFAULT 'pending'
approved_by INTEGER REFERENCES users(id)
approved_at TIMESTAMP
cpu_cores INTEGER
cpu_model VARCHAR(200)
ram_gb FLOAT
disk_gb FLOAT
os_info VARCHAR(200)
gpu_available BOOLEAN
gpu_model VARCHAR(100)
gpu_vram_gb FLOAT
ollama_available BOOLEAN
priority INTEGER DEFAULT 10
weight INTEGER DEFAULT 100
max_concurrent INTEGER DEFAULT 5
current_load INTEGER DEFAULT 0
```

### node_capabilities Table

```sql
id SERIAL PRIMARY KEY
node_id INTEGER REFERENCES remote_nodes(id)
provider VARCHAR(50) -- 'ollama', 'openai', etc.
model_name VARCHAR(100)
is_available BOOLEAN
avg_tokens_per_sec FLOAT
priority INTEGER DEFAULT 10
```

### node_heartbeats Table

```sql
id SERIAL PRIMARY KEY
node_id INTEGER REFERENCES remote_nodes(id)
status VARCHAR(20)
latency_ms INTEGER
cpu_usage FLOAT
memory_usage FLOAT
gpu_usage FLOAT
current_load INTEGER
created_at TIMESTAMP
```

## Node Client Files

Located in `/mnt/archie_brain/node_client/`:

| File | Description |
|------|-------------|
| `archie_node.py` | Main daemon script |
| `health_monitor.py` | System metrics collection |
| `config.py` | Configuration management |
| `install.sh` | Network installer script |
| `deploy-node.sh` | Self-contained deployment script |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container build file |

## Troubleshooting

### Node won't register

1. Check network connectivity: `curl http://192.168.1.200:3000/health`
2. Verify jq is installed: `apt install jq`
3. Check the registration response: Look at install.sh output

### Node shows as offline

1. Check systemd service: `systemctl status archie-node`
2. View logs: `journalctl -fu archie-node`
3. Verify credentials: `cat /opt/archie-node/.env`
4. Check heartbeat URL: `/tools/bridge/api/nodes/<id>/heartbeat`

### Approval polling timeout

If the installer times out waiting for approval:
1. The service will start anyway
2. Approve the node in the Bridge UI
3. The node will sync on next heartbeat

### Can't connect to Ollama

1. Verify Ollama is running: `curl http://localhost:11434/api/tags`
2. Check Ollama service: `systemctl status ollama`
3. Ensure Ollama listens on all interfaces (if remote)

## Security Considerations

1. **API Keys**: Hashed with SHA256, never stored in plaintext
2. **Approval Workflow**: Prevents unauthorized nodes from joining
3. **Network Access**: Restrict database access to internal network
4. **VPN Recommended**: Use WireGuard/OpenVPN for external nodes

## Related Documentation

- `/docs/ARCHIE_BRIDGE_MODULE.md` - Full Bridge module documentation
- `/docs/DATABASE_SCHEMA_DOCUMENTATION.md` - Complete schema reference
- `/docs/MASTER_STATUS_AND_ROADMAP_2026.md` - Project roadmap
