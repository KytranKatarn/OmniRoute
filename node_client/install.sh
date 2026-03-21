#!/usr/bin/env bash
###############################################################################
# A.R.C.H.I.E. Fleet Node Installer v4.0
# ============================================================================
# One-command installer for ARCHIE Starship nodes.
#
# Usage:
#   curl -fsSL https://HUB/tools/starbase/api/nodes/install.sh | \
#     HUB_URL=http://192.168.1.200:3000 NODE_TOKEN=xxx sudo bash
#
# Or with options:
#   curl ... | HUB_URL=... NODE_TOKEN=... NODE_NAME=my-node \
#     SKIP_GPU=1 SKIP_COMFYUI=1 sudo bash
#
# Environment variables:
#   HUB_URL       (required) Hub platform URL
#   NODE_TOKEN    (required) One-time registration token from hub
#   NODE_NAME     (optional) Human-readable node name (default: hostname)
#   SKIP_GPU      (optional) Set to 1 to skip NVIDIA setup
#   SKIP_COMFYUI  (optional) Set to 1 to skip ComfyUI service
#   INSTALL_DIR   (optional) Installation directory (default: /opt/archie-node)
###############################################################################

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
INSTALL_DIR="${INSTALL_DIR:-/opt/archie-node}"
NODE_NAME="${NODE_NAME:-$(hostname -s)}"
SKIP_GPU="${SKIP_GPU:-0}"
SKIP_COMFYUI="${SKIP_COMFYUI:-0}"
VERSION="4.0.0"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# ============================================================================
# Helpers
# ============================================================================
log()   { echo -e "${CYAN}[ARCHIE]${NC} $*"; }
ok()    { echo -e "${GREEN}  [OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}  [WARN]${NC} $*"; }
fail()  { echo -e "${RED}  [FAIL]${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}${CYAN}=== Step $1: $2 ===${NC}"; }

banner() {
    echo -e "${CYAN}"
    echo "    _    ____   ____ _   _ ___ _____"
    echo "   / \\  |  _ \\ / ___| | | |_ _| ____|"
    echo "  / _ \\ | |_) | |   | |_| || ||  _|"
    echo " / ___ \\|  _ <| |___|  _  || || |___"
    echo "/_/   \\_\\_| \\_\\\\____|_| |_|___|_____|"
    echo ""
    echo -e "${BOLD}  Fleet Node Installer v${VERSION}${NC}"
    echo -e "${CYAN}  Kytran Empowerment Technologies${NC}"
    echo -e "${NC}"
}

# ============================================================================
# Step 0: Prerequisites
# ============================================================================
banner

step 0 "Prerequisites"

# Must be root
[[ $EUID -eq 0 ]] || fail "Must run as root (use sudo)"

# Required env vars
[[ -n "${HUB_URL:-}" ]] || fail "HUB_URL is required"
[[ -n "${NODE_TOKEN:-}" ]] || fail "NODE_TOKEN is required"

# Required tools
for cmd in curl jq; do
    if ! command -v "$cmd" &>/dev/null; then
        log "Installing $cmd..."
        if command -v apt-get &>/dev/null; then
            apt-get update -qq && apt-get install -y -qq "$cmd"
        elif command -v yum &>/dev/null; then
            yum install -y -q "$cmd"
        elif command -v dnf &>/dev/null; then
            dnf install -y -q "$cmd"
        else
            fail "Cannot install $cmd — unsupported package manager"
        fi
    fi
done
ok "Prerequisites satisfied (root, curl, jq)"

# ============================================================================
# Step 1: OS & Hardware Detection
# ============================================================================
step 1 "Hardware Detection"

OS_ID=$(. /etc/os-release 2>/dev/null && echo "$ID" || echo "unknown")
OS_VERSION=$(. /etc/os-release 2>/dev/null && echo "$VERSION_ID" || echo "unknown")
CPU_MODEL=$(lscpu 2>/dev/null | grep "Model name" | head -1 | sed 's/.*: *//' || echo "unknown")
CPU_CORES=$(nproc 2>/dev/null || echo "1")
RAM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1048576}' /proc/meminfo 2>/dev/null || echo "0")
DISK_GB=$(df -BG / 2>/dev/null | awk 'NR==2{print $4}' | tr -d 'G' || echo "0")

# GPU detection
GPU_MODEL="none"
GPU_VRAM_GB="0"
HAS_GPU=false
if [[ "$SKIP_GPU" != "1" ]] && command -v nvidia-smi &>/dev/null; then
    GPU_MODEL=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "none")
    GPU_VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    GPU_VRAM_GB=$(awk "BEGIN {printf \"%.0f\", ${GPU_VRAM_MB}/1024}")
    [[ "$GPU_MODEL" != "none" && "$GPU_MODEL" != "" ]] && HAS_GPU=true
fi

log "OS:   $OS_ID $OS_VERSION"
log "CPU:  $CPU_MODEL ($CPU_CORES cores)"
log "RAM:  ${RAM_GB}GB"
log "Disk: ${DISK_GB}GB free"
log "GPU:  $GPU_MODEL (${GPU_VRAM_GB}GB VRAM)"
ok "Hardware detected"

# ============================================================================
# Step 2: Docker Setup
# ============================================================================
step 2 "Docker Setup"

if command -v docker &>/dev/null; then
    DOCKER_VERSION=$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',')
    ok "Docker already installed ($DOCKER_VERSION)"
else
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | bash || fail "Docker install failed"
    systemctl enable --now docker
    ok "Docker installed"
fi

# Docker Compose plugin
if docker compose version &>/dev/null; then
    ok "Docker Compose plugin available"
else
    log "Installing Docker Compose plugin..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    else
        fail "Docker Compose plugin install failed — install manually"
    fi
    ok "Docker Compose plugin installed"
fi

# NVIDIA Container Toolkit (if GPU detected and not skipped)
if [[ "$HAS_GPU" == "true" ]]; then
    if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        ok "NVIDIA Container Toolkit working"
    else
        log "Installing NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
            gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > \
            /etc/apt/sources.list.d/nvidia-container-toolkit.list
        apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker
        ok "NVIDIA Container Toolkit installed"
    fi
fi

# ============================================================================
# Step 3: Pre-register with Hub
# ============================================================================
step 3 "Hub Registration"

log "Registering with hub at ${HUB_URL}..."

REGISTER_PAYLOAD=$(jq -n \
    --arg token "$NODE_TOKEN" \
    --arg name "$NODE_NAME" \
    --arg cpu_model "$CPU_MODEL" \
    --arg cpu_cores "$CPU_CORES" \
    --arg ram_gb "$RAM_GB" \
    --arg gpu_model "$GPU_MODEL" \
    --arg gpu_vram_gb "$GPU_VRAM_GB" \
    --arg os_info "$OS_ID $OS_VERSION" \
    --argjson has_gpu "$HAS_GPU" \
    '{
        token: $token,
        node_name: $name,
        cpu_model: $cpu_model,
        cpu_cores: ($cpu_cores | tonumber),
        ram_gb: ($ram_gb | tonumber),
        gpu_model: $gpu_model,
        gpu_vram_gb: ($gpu_vram_gb | tonumber),
        gpu_available: $has_gpu,
        os_info: $os_info
    }')

REGISTER_RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST \
    "${HUB_URL}/tools/starbase/api/nodes/register" \
    -H "Content-Type: application/json" \
    -d "$REGISTER_PAYLOAD" 2>&1)

HTTP_CODE=$(echo "$REGISTER_RESPONSE" | tail -1)
RESPONSE_BODY=$(echo "$REGISTER_RESPONSE" | sed '$d')

[[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "201" ]] || \
    fail "Hub registration failed (HTTP $HTTP_CODE): $RESPONSE_BODY"

# Parse response
NODE_ID=$(echo "$RESPONSE_BODY" | jq -r '.node_id // empty')
HUB_API_KEY=$(echo "$RESPONSE_BODY" | jq -r '.api_key // empty')
HEADSCALE_AUTHKEY=$(echo "$RESPONSE_BODY" | jq -r '.headscale_authkey // empty')
HEADSCALE_URL=$(echo "$RESPONSE_BODY" | jq -r '.headscale_url // empty')

[[ -n "$NODE_ID" ]] || fail "No node_id in registration response"
[[ -n "$HUB_API_KEY" ]] || fail "No api_key in registration response"

ok "Registered as node: $NODE_ID"
[[ -n "$HEADSCALE_AUTHKEY" ]] && ok "Mesh auth key received" || warn "No mesh auth key — LAN-only mode"

# ============================================================================
# Step 4: Directory Structure
# ============================================================================
step 4 "Directory Setup"

mkdir -p "$INSTALL_DIR"/{data,logs,migrations}
cd "$INSTALL_DIR"

ok "Created $INSTALL_DIR/"
ok "  data/       — persistent data"
ok "  logs/       — service logs"
ok "  migrations/ — database migrations"

# ============================================================================
# Step 5: Download Stack Files
# ============================================================================
step 5 "Download Stack"

# Download docker-compose from hub
log "Downloading docker-compose.yml..."
curl -fsSL "${HUB_URL}/tools/starbase/api/nodes/docker-compose" \
    -H "X-Node-API-Key: ${HUB_API_KEY}" \
    -o docker-compose.yml 2>/dev/null || {
    warn "Compose endpoint not available, using bundled version"
    # Try direct file path
    curl -fsSL "${HUB_URL}/static/node_client/docker-compose.node.yml" \
        -o docker-compose.yml 2>/dev/null || fail "Cannot download docker-compose.yml"
}

# Download node scripts
for file in node_sync.py node_api.py Dockerfile.node; do
    log "Downloading $file..."
    curl -fsSL "${HUB_URL}/static/node_client/${file}" \
        -o "$file" 2>/dev/null || warn "Could not download $file (may need manual copy)"
done

# Download migrations
curl -fsSL "${HUB_URL}/static/node_client/migrations/001_init.sql" \
    -o migrations/001_init.sql 2>/dev/null || true

ok "Stack files downloaded to $INSTALL_DIR"

# ============================================================================
# Step 6: Create Environment File
# ============================================================================
step 6 "Environment Configuration"

DB_PASSWORD=$(openssl rand -hex 16 2>/dev/null || echo "archie_node_$(date +%s)")

cat > .env <<ENVEOF
# A.R.C.H.I.E. Starship Node Configuration
# Generated by installer v${VERSION} on $(date -Iseconds)

# Node identity
NODE_ID=${NODE_ID}
NODE_NAME=${NODE_NAME}

# Hub connection
HUB_URL=${HUB_URL}
HUB_API_KEY=${HUB_API_KEY}

# Database
DB_PASSWORD=${DB_PASSWORD}

# Mesh VPN (Headscale)
HEADSCALE_URL=${HEADSCALE_URL:-http://192.168.1.200:8095}
HEADSCALE_AUTHKEY=${HEADSCALE_AUTHKEY:-}

# Service ports
OLLAMA_PORT=11434
NODE_API_PORT=3001
COMFYUI_PORT=8188

# Timezone
NODE_TIMEZONE=America/Toronto
ENVEOF

chmod 600 .env
ok "Environment file created (.env)"

# ============================================================================
# Step 7: Start Stack
# ============================================================================
step 7 "Start Services"

# Determine which services to start
SERVICES="ollama postgres sync node_api"
[[ -n "${HEADSCALE_AUTHKEY:-}" ]] && SERVICES="$SERVICES tailscale"
[[ "$SKIP_COMFYUI" != "1" ]] && [[ "$HAS_GPU" == "true" ]] && SERVICES="$SERVICES comfyui"

log "Starting: $SERVICES"
docker compose pull 2>&1 | tail -3
docker compose up -d $SERVICES 2>&1 | tail -5

# Wait for Ollama health
log "Waiting for Ollama..."
for i in $(seq 1 30); do
    if docker exec archie_starship_ollama ollama list &>/dev/null 2>&1; then
        ok "Ollama is healthy"
        break
    fi
    [[ $i -eq 30 ]] && warn "Ollama still starting (may need more time)"
    sleep 2
done

ok "Services started"

# ============================================================================
# Step 8: Post-Deploy Validation
# ============================================================================
step 8 "Validation"

PASS=0
TOTAL=0

# Ollama
TOTAL=$((TOTAL + 1))
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama responding on :11434"; PASS=$((PASS + 1))
else
    warn "Ollama not responding yet"
fi

# Node API
TOTAL=$((TOTAL + 1))
if curl -sf http://localhost:3001/health &>/dev/null; then
    ok "Node API responding on :3001"; PASS=$((PASS + 1))
else
    warn "Node API not responding yet"
fi

# Sync service
TOTAL=$((TOTAL + 1))
if docker ps --filter name=archie_starship_sync --format '{{.Status}}' | grep -q "Up"; then
    ok "Sync service running"; PASS=$((PASS + 1))
else
    warn "Sync service not running"
fi

# Mesh VPN
MESH_IP=""
if [[ -n "${HEADSCALE_AUTHKEY:-}" ]]; then
    TOTAL=$((TOTAL + 1))
    sleep 5
    MESH_IP=$(docker exec archie_starship_tailscale tailscale ip -4 2>/dev/null || echo "")
    if [[ -n "$MESH_IP" ]]; then
        ok "Mesh VPN connected ($MESH_IP)"; PASS=$((PASS + 1))
        # Report mesh IP to hub
        curl -sS -X POST "${HUB_URL}/tools/starbase/api/nodes/${NODE_ID}/mesh-ip" \
            -H "Content-Type: application/json" \
            -H "X-Node-API-Key: ${HUB_API_KEY}" \
            -d "{\"mesh_ip\": \"$MESH_IP\"}" &>/dev/null || true
    else
        warn "Mesh VPN not connected yet (will retry in background)"
    fi
fi

# ComfyUI
if [[ "$SKIP_COMFYUI" != "1" ]] && [[ "$HAS_GPU" == "true" ]]; then
    TOTAL=$((TOTAL + 1))
    if curl -sf http://localhost:8188/system_stats &>/dev/null; then
        ok "ComfyUI responding on :8188"; PASS=$((PASS + 1))
    else
        warn "ComfyUI not responding (may still be loading)"
    fi
fi

echo ""
log "Validation: $PASS/$TOTAL checks passed"

# ============================================================================
# Step 9: Summary
# ============================================================================
step 9 "Complete"

echo ""
echo -e "${GREEN}${BOLD}"
echo "  ============================================"
echo "   A.R.C.H.I.E. Node Successfully Deployed!"
echo "  ============================================"
echo -e "${NC}"
echo -e "  ${BOLD}Node ID:${NC}      $NODE_ID"
echo -e "  ${BOLD}Node Name:${NC}    $NODE_NAME"
echo -e "  ${BOLD}Install Dir:${NC}  $INSTALL_DIR"
echo -e "  ${BOLD}Hub:${NC}          $HUB_URL"
[[ -n "$MESH_IP" ]] && \
echo -e "  ${BOLD}Mesh IP:${NC}      $MESH_IP"
echo ""
echo -e "  ${BOLD}Services:${NC}"
echo "    Ollama:     http://localhost:11434"
echo "    Node API:   http://localhost:3001"
[[ "$SKIP_COMFYUI" != "1" ]] && [[ "$HAS_GPU" == "true" ]] && \
echo "    ComfyUI:    http://localhost:8188"
[[ -n "$MESH_IP" ]] && \
echo "    Mesh VPN:   $MESH_IP"
echo ""
echo -e "  ${BOLD}Commands:${NC}"
echo "    cd $INSTALL_DIR"
echo "    docker compose logs -f    # View logs"
echo "    docker compose restart    # Restart all"
echo "    docker compose down       # Stop all"
echo ""
echo -e "  ${CYAN}Node will appear in Starbase Command > Network tab${NC}"
echo -e "  ${CYAN}for approval once the first heartbeat is received.${NC}"
echo ""
