# Fleet Deployment System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the first Outpost node on a US VPS, establish the fleet directory structure, and create the reusable installer bootstrap.

**Architecture:** Profile-based adaptive deployment. Bash bootstrap detects hardware and connects to mesh VPN, then hub manages the node's Docker stack via OTA. Existing node_sync.py, node_api.py, and Headscale mesh are reused — not rewritten.

**Tech Stack:** Bash (installer), Docker Compose (services), Tailscale/Headscale (mesh VPN), Python (sync/API), Go (future TUI wizard), PostgreSQL (hub fleet DB)

**Spec:** `docs/superpowers/specs/2026-03-30-fleet-deployment-system-design.md`

---

## File Structure

### New Files
```
fleet/
  profiles/
    outpost.yml              # Outpost service profile definition
    starship.yml             # Starship service profile definition
  installer/
    install.sh               # Phase 1 bootstrap script
  templates/
    docker-compose.outpost.yml   # Compose for outpost nodes
    docker-compose.starship.yml  # Compose for starship nodes (refactored from node_client)
    .env.template                # Environment template for nodes
```

### Modified Files
```
platform_v2/tools/starbase/node_routes.py   # Add fleet token generation + node type support
platform_v2/tools/starbase/mesh_routes.py   # Add outpost registration endpoint
```

### Existing (Reused As-Is)
```
node_client/node_sync.py        # Sync daemon — works for all node types
node_client/node_api.py         # Node REST API — works for all node types
headscale/config.yaml           # Mesh VPN coordination server
```

---

## Task 1: Harden the VPS

**Target:** 76.13.107.109 (Hostinger KVM2, Ubuntu)
**Files:** None (remote server configuration)

- [ ] **Step 1: SSH in and change the root password**

```bash
ssh root@76.13.107.109
passwd
# Enter new strong password — store in password manager, NOT in chat
```

- [ ] **Step 2: Create a non-root user**

```bash
adduser kytran
usermod -aG sudo kytran
```

- [ ] **Step 3: Copy SSH key for key-based auth**

From local machine:
```bash
ssh-copy-id kytran@76.13.107.109
```

- [ ] **Step 4: Disable password auth and root login**

```bash
ssh kytran@76.13.107.109
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

- [ ] **Step 5: Set up firewall (UFW)**

```bash
sudo apt update && sudo apt install -y ufw fail2ban
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 41641/udp # Tailscale
sudo ufw enable
sudo ufw status
```

Expected: Status active with rules listed.

- [ ] **Step 6: Install fail2ban**

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
sudo fail2ban-client status
```

Expected: `Status: Number of jail: 1` (sshd jail active)

- [ ] **Step 7: Set hostname**

```bash
sudo hostnamectl set-hostname outpost-us
```

Or via Hostinger API:
```
MCP tool: VPS_setHostnameV1
hostname: outpost-us.kytranempowerment.com
```

- [ ] **Step 8: Commit — note VPS is hardened**

```bash
# No local code changes — just a progress note
# Log in Dev HQ that VPS hardening is complete
```

---

## Task 2: Install Docker on VPS

**Target:** 76.13.107.109

- [ ] **Step 1: Install Docker Engine**

```bash
ssh kytran@76.13.107.109
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

- [ ] **Step 2: Add user to docker group**

```bash
sudo usermod -aG docker kytran
# Log out and back in for group to take effect
exit
ssh kytran@76.13.107.109
```

- [ ] **Step 3: Verify Docker works**

```bash
docker run hello-world
docker compose version
```

Expected: Hello from Docker message + Compose version output.

---

## Task 3: Connect VPS to Mesh VPN

**Target:** 76.13.107.109 → mesh.kytranempowerment.com

- [ ] **Step 1: Generate a Headscale pre-auth key on hub**

```bash
# On hub (192.168.1.200), inside headscale container
docker exec headscale headscale preauthkeys create --user default --expiration 24h --reusable=false
```

Save the output key — needed for next step.

- [ ] **Step 2: Install Tailscale on VPS**

```bash
ssh kytran@76.13.107.109
curl -fsSL https://tailscale.com/install.sh | sh
```

- [ ] **Step 3: Connect to Headscale mesh**

```bash
sudo tailscale up --login-server https://mesh.kytranempowerment.com --authkey <PREAUTH_KEY_FROM_STEP1>
```

- [ ] **Step 4: Verify mesh connectivity**

```bash
# On VPS
tailscale status
ping 100.64.0.1   # Hub's mesh IP (verify actual IP from headscale)

# On hub
docker exec headscale headscale nodes list
```

Expected: VPS shows as connected node. Ping succeeds between VPS and hub via mesh.

- [ ] **Step 5: Test hub reachability from VPS**

```bash
# On VPS — test that hub platform is reachable via mesh
curl -s http://100.64.0.1:3000/api/health | head -5
```

Expected: JSON health response from A.R.C.H.I.E. platform.

---

## Task 4: Set PTR Record for Mail

**Files:** None (API call)

- [ ] **Step 1: Find the VPS ID via Hostinger API**

```
MCP tool: VPS_getVirtualMachinesV1
```

Note the VPS ID for 76.13.107.109.

- [ ] **Step 2: Set PTR record**

```
MCP tool: VPS_createPTRRecordV1
vps_id: <ID from step 1>
ip_address: 76.13.107.109
ptr_record: mail.kytranempowerment.com
```

- [ ] **Step 3: Verify PTR**

```bash
# Wait a few minutes for DNS propagation, then:
dig -x 76.13.107.109 +short
```

Expected: `mail.kytranempowerment.com.`

- [ ] **Step 4: Set forward DNS A record**

```
MCP tool: DNS_updateDNSRecordsV1
domain: kytranempowerment.com
records: [{ type: "A", name: "mail", value: "76.13.107.109", ttl: 3600 }]
```

- [ ] **Step 5: Verify forward + reverse match**

```bash
dig mail.kytranempowerment.com +short      # Should return 76.13.107.109
dig -x 76.13.107.109 +short               # Should return mail.kytranempowerment.com
```

Expected: Both match — forward and reverse DNS aligned.

---

## Task 5: Create Fleet Directory Structure

**Files:**
- Create: `fleet/profiles/outpost.yml`
- Create: `fleet/profiles/starship.yml`
- Create: `fleet/templates/docker-compose.outpost.yml`
- Create: `fleet/templates/.env.template`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/fleet/{profiles,installer,templates,hub}
```

- [ ] **Step 2: Create outpost profile**

Create `fleet/profiles/outpost.yml`:
```yaml
name: outpost
description: Lightweight proxy and relay node for regional presence
min_requirements:
  cpu_cores: 1
  ram_gb: 2
  disk_gb: 20
services:
  required:
    - sync-daemon
    - node-api
    - reverse-proxy
  optional:
    - smtp-relay
    - monitoring-agent
network:
  mesh_vpn: required
  ports:
    - 80
    - 443
    - 3001
```

- [ ] **Step 3: Create starship profile**

Create `fleet/profiles/starship.yml`:
```yaml
name: starship
description: Full compute node with AI inference and generation
min_requirements:
  cpu_cores: 4
  ram_gb: 16
  disk_gb: 100
  gpu: recommended
services:
  required:
    - sync-daemon
    - node-api
    - reverse-proxy
    - ollama
    - postgres
  optional:
    - comfyui
    - smtp-relay
    - monitoring-agent
network:
  mesh_vpn: required
  ports:
    - 80
    - 443
    - 3001
    - 11434
```

- [ ] **Step 4: Create outpost Docker Compose**

Create `fleet/templates/docker-compose.outpost.yml`:
```yaml
version: "3.8"

services:
  archie_sync:
    image: python:3.11-slim
    container_name: archie_outpost_sync
    restart: unless-stopped
    working_dir: /app
    command: python3 node_sync.py
    environment:
      - NODE_ID=${NODE_ID}
      - HUB_URL=${HUB_URL}
      - HUB_API_KEY=${HUB_API_KEY}
      - NODE_TYPE=outpost
      - HEARTBEAT_INTERVAL=60
      - SYNC_POLL_INTERVAL=60
    volumes:
      - ./node_sync.py:/app/node_sync.py:ro
      - ./config.json:/etc/archie-node/config.json
    networks:
      - archie_net
    deploy:
      resources:
        limits:
          memory: 128M
          cpus: "0.25"

  archie_api:
    image: python:3.11-slim
    container_name: archie_outpost_api
    restart: unless-stopped
    working_dir: /app
    command: python3 node_api.py
    ports:
      - "3001:3001"
    environment:
      - NODE_ID=${NODE_ID}
      - HUB_URL=${HUB_URL}
      - HUB_API_KEY=${HUB_API_KEY}
      - NODE_TYPE=outpost
    volumes:
      - ./node_api.py:/app/node_api.py:ro
    networks:
      - archie_net
    deploy:
      resources:
        limits:
          memory: 128M
          cpus: "0.25"

  archie_proxy:
    image: caddy:2-alpine
    container_name: archie_outpost_proxy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - archie_net
    deploy:
      resources:
        limits:
          memory: 128M
          cpus: "0.25"

volumes:
  caddy_data:
  caddy_config:

networks:
  archie_net:
    driver: bridge
```

- [ ] **Step 5: Create environment template**

Create `fleet/templates/.env.template`:
```bash
# A.R.C.H.I.E. Fleet Node Configuration
# Generated by fleet installer — do not edit manually

# Node Identity (set during registration)
NODE_ID=
NODE_TYPE=outpost
NODE_NAME=

# Hub Connection
HUB_URL=http://100.64.0.1:3000
HUB_API_KEY=

# Mesh VPN
MESH_SERVER=https://mesh.kytranempowerment.com

# Optional: SMTP Relay
SMTP_RELAY_ENABLED=false
SMTP_RELAY_HOST=
SMTP_RELAY_PORT=587
```

- [ ] **Step 6: Commit fleet directory structure**

```bash
git add fleet/
git commit -m "feat(fleet): create directory structure with outpost/starship profiles and compose templates"
```

---

## Task 6: Deploy Outpost Stack on VPS

**Target:** 76.13.107.109

- [ ] **Step 1: Create deployment directory on VPS**

```bash
ssh kytran@76.13.107.109
sudo mkdir -p /opt/archie-outpost
sudo chown kytran:kytran /opt/archie-outpost
```

- [ ] **Step 2: Copy node files to VPS**

From hub:
```bash
scp /mnt/archie_brain/node_client/node_sync.py kytran@76.13.107.109:/opt/archie-outpost/
scp /mnt/archie_brain/node_client/node_api.py kytran@76.13.107.109:/opt/archie-outpost/
scp /mnt/archie_brain/fleet/templates/docker-compose.outpost.yml kytran@76.13.107.109:/opt/archie-outpost/docker-compose.yml
```

- [ ] **Step 3: Generate node credentials on hub**

```bash
# On hub — generate a node_id and API key
docker exec archie_database psql -U archie -d archie -c "
INSERT INTO remote_nodes (hostname, node_name, deployment_mode, status, created_at)
VALUES ('76.13.107.109', 'outpost-us', 'outpost', 'pending', NOW())
RETURNING id, node_id;
"
```

Note the node_id. Generate an API key:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

- [ ] **Step 4: Create .env on VPS**

```bash
ssh kytran@76.13.107.109
cat > /opt/archie-outpost/.env << 'EOF'
NODE_ID=<node_id_from_step3>
NODE_TYPE=outpost
NODE_NAME=outpost-us
HUB_URL=http://100.64.0.1:3000
HUB_API_KEY=<api_key_from_step3>
EOF
```

- [ ] **Step 5: Create Caddyfile for reverse proxy**

```bash
cat > /opt/archie-outpost/Caddyfile << 'EOF'
:80 {
    respond /health "OK" 200
    reverse_proxy /api/* archie_outpost_api:3001
}
EOF
```

- [ ] **Step 6: Start the outpost stack**

```bash
cd /opt/archie-outpost
docker compose up -d
docker compose ps
```

Expected: 3 containers running (sync, api, proxy).

- [ ] **Step 7: Verify sync daemon connects to hub**

```bash
# On VPS — check sync logs
docker logs archie_outpost_sync --tail 20

# On hub — check for heartbeat
docker exec archie_database psql -U archie -d archie -c "
SELECT node_name, status, last_heartbeat FROM remote_nodes WHERE hostname = '76.13.107.109';
"
```

Expected: Sync logs show heartbeat sent. Hub shows recent heartbeat timestamp.

- [ ] **Step 8: Verify API responds**

```bash
# From hub via mesh
curl http://100.64.0.x:3001/health

# From VPS directly
curl http://localhost:3001/health
```

Expected: Health check JSON response.

- [ ] **Step 9: Verify proxy responds**

```bash
curl http://76.13.107.109/health
```

Expected: "OK"

---

## Task 7: Configure Stalwart Mail Relay

**Target:** Hub Stalwart → VPS outbound relay

- [ ] **Step 1: Install Postfix as relay on VPS**

```bash
ssh kytran@76.13.107.109
sudo apt install -y postfix
# During install, select "Internet Site"
# System mail name: mail.kytranempowerment.com
```

- [ ] **Step 2: Configure Postfix as relay-only**

```bash
sudo tee /etc/postfix/main.cf << 'EOF'
myhostname = mail.kytranempowerment.com
mydomain = kytranempowerment.com
myorigin = $mydomain
inet_interfaces = all
inet_protocols = ipv4

# Relay configuration — accept mail from hub mesh IP only
mynetworks = 127.0.0.0/8 100.64.0.0/10
relay_domains =
smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination

# TLS
smtpd_tls_cert_file = /etc/ssl/certs/ssl-cert-snakeoil.pem
smtpd_tls_key_file = /etc/ssl/private/ssl-cert-snakeoil.key
smtpd_tls_security_level = may
smtp_tls_security_level = may
EOF

sudo systemctl restart postfix
sudo systemctl enable postfix
```

- [ ] **Step 3: Open SMTP port in firewall (mesh only)**

```bash
# Only allow SMTP from mesh network — NOT public
sudo ufw allow from 100.64.0.0/10 to any port 25 proto tcp
sudo ufw reload
```

- [ ] **Step 4: Configure Stalwart on hub to relay through VPS**

Update Stalwart config to use VPS as relay host:
- Relay host: `100.64.0.x` (VPS mesh IP) port 25
- This routes outbound mail through the VPS IP which has proper PTR

(Exact Stalwart config depends on current setup — check `/mnt/archie_brain/mail_server/` config)

- [ ] **Step 5: Send test email and verify**

```bash
# Send test from hub through relay
echo "Test from ARCHIE via outpost relay" | mail -s "PTR Test" test@mail-tester.com
```

Check mail-tester.com score — PTR should now resolve correctly.

- [ ] **Step 6: Commit relay configuration notes**

```bash
# Document the relay setup in Dev HQ
# MCP: complete_task for #1467 (PTR record)
```

---

## Task 8: Write Installer Bootstrap Script

**Files:**
- Create: `fleet/installer/install.sh`

- [ ] **Step 1: Write the installer script**

Create `fleet/installer/install.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

# A.R.C.H.I.E. Fleet Node Installer — Phase 1 Bootstrap
# Usage: curl -sSL install.kytranempowerment.com/fleet | bash

MESH_SERVER="https://mesh.kytranempowerment.com"
HUB_MESH_IP="100.64.0.1"
INSTALL_DIR="/opt/archie-outpost"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

banner() {
    echo -e "${CYAN}"
    echo "  =========================="
    echo "  A.R.C.H.I.E. Fleet Node"
    echo "  Phase 1 Bootstrap"
    echo "  =========================="
    echo -e "${NC}"
}

log() { echo -e "${GREEN}[FLEET]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Hardware Detection ---
detect_hardware() {
    log "Detecting hardware..."
    CPU_CORES=$(nproc 2>/dev/null || echo "1")
    RAM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo "1")
    DISK_GB=$(df -BG / | awk 'NR==2 {print $2}' | tr -d 'G' 2>/dev/null || echo "10")

    GPU="none"
    if command -v nvidia-smi &>/dev/null; then
        GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "none")
    fi

    log "  CPU: ${CPU_CORES} cores"
    log "  RAM: ${RAM_GB} GB"
    log "  Disk: ${DISK_GB} GB"
    log "  GPU: ${GPU}"
}

# --- Suggest Node Type ---
suggest_node_type() {
    if [ "$GPU" != "none" ] || [ "$RAM_GB" -ge 16 ]; then
        SUGGESTED="starship"
    else
        SUGGESTED="outpost"
    fi
    log "Suggested node type: ${CYAN}${SUGGESTED}${NC}"
}

# --- Prompt for Node Type ---
choose_node_type() {
    echo ""
    echo -e "  1) ${CYAN}Outpost${NC}  — Lightweight proxy & relay (VPS, low-spec machines)"
    echo -e "  2) ${CYAN}Starship${NC} — Full compute node with AI (GPU workstations)"
    echo ""
    read -rp "  Choose node type [1-2] (default: $([ "$SUGGESTED" = "outpost" ] && echo 1 || echo 2)): " choice

    case "${choice:-}" in
        1) NODE_TYPE="outpost" ;;
        2) NODE_TYPE="starship" ;;
        "") NODE_TYPE="$SUGGESTED" ;;
        *) NODE_TYPE="$SUGGESTED" ;;
    esac
    log "Selected: ${CYAN}${NODE_TYPE}${NC}"
}

# --- Install Prerequisites ---
install_prerequisites() {
    log "Installing prerequisites..."
    if command -v apt &>/dev/null; then
        sudo apt update -qq
        sudo apt install -y -qq curl jq ca-certificates gnupg
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y -q curl jq ca-certificates
    elif command -v apk &>/dev/null; then
        sudo apk add --no-cache curl jq ca-certificates
    else
        err "Unsupported package manager. Install curl and jq manually."
    fi
}

# --- Install Docker ---
install_docker() {
    if command -v docker &>/dev/null; then
        log "Docker already installed: $(docker --version)"
        return
    fi
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    log "Docker installed. You may need to log out and back in for group membership."
}

# --- Install Tailscale ---
install_tailscale() {
    if command -v tailscale &>/dev/null; then
        log "Tailscale already installed: $(tailscale version)"
        return
    fi
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
}

# --- Connect to Mesh ---
connect_mesh() {
    log "Connecting to A.R.C.H.I.E. mesh network..."
    echo ""
    echo -e "  Enter your Headscale pre-auth key (generate in Starbase):"
    read -rp "  Auth key: " AUTH_KEY
    [ -z "$AUTH_KEY" ] && err "Auth key is required"

    sudo tailscale up --login-server "$MESH_SERVER" --authkey "$AUTH_KEY"

    # Verify connectivity
    log "Verifying mesh connectivity..."
    sleep 3
    if tailscale status | grep -q "100.64"; then
        log "Connected to mesh!"
        MESH_IP=$(tailscale ip -4)
        log "  Mesh IP: ${MESH_IP}"
    else
        err "Failed to connect to mesh. Check your auth key and network."
    fi
}

# --- Main ---
main() {
    banner
    detect_hardware
    suggest_node_type
    choose_node_type
    install_prerequisites
    install_docker
    install_tailscale
    connect_mesh

    echo ""
    log "Phase 1 complete!"
    log "  Node type: ${NODE_TYPE}"
    log "  Mesh IP: ${MESH_IP}"
    echo ""
    log "Next steps:"
    log "  1. Go to Starbase and approve this node"
    log "  2. The hub will push your ${NODE_TYPE} profile"
    log "  3. Docker services will start automatically"
    echo ""
    log "Or run with a token for headless setup:"
    log "  export ARCHIE_TOKEN=<your-token>"
    log "  curl -sSL install.kytranempowerment.com/fleet | bash"
}

main "$@"
```

- [ ] **Step 2: Make executable and test locally**

```bash
chmod +x /mnt/archie_brain/fleet/installer/install.sh
# Review the script — do NOT run on hub
shellcheck /mnt/archie_brain/fleet/installer/install.sh || true
```

- [ ] **Step 3: Commit installer**

```bash
git add fleet/
git commit -m "feat(fleet): add bootstrap installer script with hardware detection and mesh connection"
```

---

## Task 9: End-to-End Verification

- [ ] **Step 1: Verify VPS is on mesh**

```bash
# From hub
docker exec headscale headscale nodes list
```

Expected: outpost-us visible with mesh IP.

- [ ] **Step 2: Verify hub can reach VPS services**

```bash
# API via mesh
curl http://<VPS_MESH_IP>:3001/health

# Proxy via public IP
curl http://76.13.107.109/health
```

Expected: Both return healthy responses.

- [ ] **Step 3: Verify sync daemon heartbeats**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT node_name, status, last_heartbeat,
       NOW() - last_heartbeat as age
FROM remote_nodes
WHERE hostname = '76.13.107.109';
"
```

Expected: last_heartbeat within last 2 minutes.

- [ ] **Step 4: Test OTA command to outpost**

```bash
docker exec archie_database psql -U archie -d archie -c "
INSERT INTO mesh_sync_log (node_id, sync_type, payload, status, sent_at)
VALUES ('<outpost_node_id>', 'shell_exec', '{\"command\": \"hostname && uptime\", \"timeout\": 30}'::jsonb, 'sent', NOW());
"
```

Wait 60s for sync poll, then check result:
```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT status, result FROM mesh_sync_log
WHERE node_id = '<outpost_node_id>'
ORDER BY sent_at DESC LIMIT 1;
"
```

Expected: status = 'completed', result contains hostname and uptime.

- [ ] **Step 5: Verify PTR record**

```bash
dig -x 76.13.107.109 +short
dig mail.kytranempowerment.com +short
```

Expected: Forward and reverse DNS match.

- [ ] **Step 6: Send test email through relay**

Send email to mail-tester.com and check score.
Expected: PTR check passes, score improved from previous tests.

- [ ] **Step 7: Update Dev HQ**

```
MCP: complete_task #1467 (PTR record — resolved via VPS relay)
MCP: complete_task #1216 (Test installer on WAN node)
MCP: log_decision "First outpost deployed — US VPS via Hostinger KVM2, mesh connected, relay active"
MCP: update_project_understanding for fleet project
```

---

## Summary

| Task | What | Time Est |
|------|------|----------|
| 1 | Harden VPS | 15 min |
| 2 | Install Docker | 10 min |
| 3 | Connect to mesh VPN | 15 min |
| 4 | Set PTR record | 10 min |
| 5 | Create fleet directory + profiles | 15 min |
| 6 | Deploy outpost stack | 20 min |
| 7 | Configure mail relay | 20 min |
| 8 | Write installer script | 15 min |
| 9 | End-to-end verification | 15 min |
