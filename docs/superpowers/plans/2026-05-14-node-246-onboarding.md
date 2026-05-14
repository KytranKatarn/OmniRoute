# Node .246 Starship — Onboarding Guide

**Date:** 2026-05-14
**Node:** 192.168.1.246 (Windows 11 + Docker Desktop + RTX 3070 + 32GB RAM)
**Tier:** Starship — mid-GPU 7B models
**Deployment mode:** starship

---

## Two Ongoing Deploy Paths

### Path A: SSH Docker Management (same as VPS outpost — primary)

Enable Windows OpenSSH once. Hub manages containers exactly like the VPS.

```powershell
# On .246 — PowerShell as Administrator (one-time setup)
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# Add hub SSH public key (~/.ssh/id_ed25519.pub from hub)
$keyPath = "$env:ProgramData\ssh\administrators_authorized_keys"
Add-Content $keyPath "ssh-ed25519 AAAA..."
icacls $keyPath /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
```

From hub after key is added:
```bash
# Test
ssh kytran@192.168.1.246 "docker ps"

# Deploy updated sync container
scp /mnt/archie_brain/node_client/node_sync.py kytran@192.168.1.246:C:/archie-node/
ssh kytran@192.168.1.246 "cd C:/archie-node && docker compose up -d --build --no-deps archie_node_sync"

# Manage containers remotely
ssh kytran@192.168.1.246 "docker ps --format table"
ssh kytran@192.168.1.246 "docker logs archie_node_sync --tail 20"
ssh kytran@192.168.1.246 "docker restart archie_node_api"
```

### Path B: OTA via Heartbeat (model and config updates)

Hub queues changes in mesh_sync_log. The node_sync container applies them automatically.

```bash
# Queue a model pull on .246
curl -X POST http://192.168.1.200:3000/api/nodes/starship_<hex>/pull-model \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen2.5:7b"}'
```

---

## KSO (System Operations) on .246 — Docker Dashboard

Deploy KSO alongside the node agent. This gives a browser-based Docker/system management UI for .246, identical to server.kytranempowerment.com.

KSO source: /mnt/archie_brain/kytran-server-manager/

```bash
# From hub — deploy KSO to .246 via SSH
scp -r /mnt/archie_brain/kytran-server-manager/ kytran@192.168.1.246:C:/archie-246-kso/

ssh kytran@192.168.1.246 "cd C:/archie-246-kso && docker compose up -d --build"
```

KSO provides on .246:
- Live CPU / GPU / RAM / disk metrics
- Docker container list + start/stop/restart from browser
- Compliance scanning (STIG/CIS)
- Host log viewer
- A.R.C.H.I.E. chat overlay (routes to hub Bridge via mesh)

Access at: http://192.168.1.246:8085 (once deployed)

---

## Phase 1: WSL2 + Docker Desktop + GPU

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
cd C:\archie-node
.\setup-node.ps1
```

Verify in Docker Desktop:
- Settings > General > Use WSL2 based engine: ON
- Settings > Resources > GPU > NVIDIA: Enabled

---

## Phase 2: Register Node (from hub)

```bash
curl -s -X POST http://192.168.1.200:3000/api/nodes/register \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "Starship-246",
    "hostname": "192.168.1.246",
    "port": 11434,
    "gpu_available": true,
    "gpu_model": "RTX 3070",
    "gpu_vram_gb": 8,
    "ram_gb": 32,
    "os_info": "Windows 11 / Docker Desktop WSL2",
    "docker_available": true
  }' | python3 -m json.tool
```

**SAVE the response — api_key returned once:**
```json
{
  "node_id": "starship_XXXX",
  "api_key": "SAVE_THIS",
  "headscale_authkey": "expires in 1h",
  "approval_status": "pending"
}
```

---

## Phase 3: Deploy on .246

```powershell
cd C:\archie-node
.\deploy-node.ps1 -Fresh -NodeId "starship_XXXX" -HubUrl "http://192.168.1.200:3000" -HubApiKey "SAVE_THIS"
```

**.env written automatically:**
```
NODE_ID=starship_XXXX
HUB_URL=http://192.168.1.200:3000
HUB_API_KEY=SAVE_THIS
DEPLOYMENT_MODE=starship
GPU_ENABLED=true
```

---

## Phase 4: Headscale Mesh

```powershell
winget install tailscale.tailscale
tailscale login --login-server http://mesh.kytranempowerment.com:80 --auth-key <headscale_authkey>
tailscale ip -4   # note the assigned IP e.g. 100.64.0.3
```

Register mesh IP back to hub:
```bash
curl -X POST http://192.168.1.200:3000/api/nodes/starship_XXXX/mesh-ip \
  -H "X-Node-API-Key: SAVE_THIS" \
  -H "Content-Type: application/json" \
  -d '{"mesh_ip": "100.64.0.X"}'
```

---

## Phase 5: Admin Approval

DHQ > Fleet tab > .246 node > Approve
OR tap the Telegram button from A.R.C.H.I.E. notification.

---

## Container Stack

| Container | Port | Purpose |
|-----------|------|---------|
| archie_node_ollama | internal | GPU LLM inference |
| archie_node_db | internal | Local job store |
| archie_node_sync | none | Heartbeat 30s + OTA |
| archie_node_api | 3001 | Health endpoint |
| kytran_system_ops | 8085 | KSO Docker dashboard |

---

## Verification

- curl http://192.168.1.246:3001/health returns status ok
- ssh kytran@192.168.1.246 "docker ps" shows all containers
- DHQ Fleet tab: node green, heartbeat < 30s
- KSO dashboard at http://192.168.1.246:8085 shows GPU + containers

---

## Recommended Models (RTX 3070, 8GB VRAM)

- qwen2.5:7b — general work (5GB VRAM)
- llama3.1:8b — balanced (6GB)
- phi3.5:3.8b — fast/lightweight (3GB)

Hub-only (too large): 70B+ models stay on hub Quadro M4000.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Heartbeat timeout | Windows Firewall: allow TCP 3001 from 192.168.1.200 |
| Mesh join fails | Auth key 1h TTL, re-register if expired |
| Cannot reach hub | HUB_URL must be http://192.168.1.200:3000 not CDN |
| SSH denied | Re-run icacls fix on administrators_authorized_keys |
