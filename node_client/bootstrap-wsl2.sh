#!/usr/bin/env bash
# A.R.C.H.I.E. Fleet — WSL2 Node Bootstrap
# Run inside WSL2 on a Windows machine with Docker Desktop + NVIDIA GPU
# Usage: bash bootstrap-wsl2.sh
#   or:  bash <(curl -fsSL http://192.168.1.200:3000/tools/starbase/api/nodes/bootstrap-wsl2.sh)
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
INSTALL_DIR="$HOME/archie-node"
LAN_HUB="http://192.168.1.200:3000"
MESH_HUB="http://100.64.0.4:3000"
HUB_API_BASE="/tools/starbase/api"
NODE_FILES="docker-compose.node.yml Dockerfile.node node_sync.py node_api.py node_triage.py"

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; exit 1; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "  ${CYAN}[..]${NC} $1"; }

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║   A.R.C.H.I.E. Fleet — WSL2 Node Bootstrap             ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Environment Checks ─────────────────────────────────────
echo -e "\n${CYAN}Step 1: Environment Checks${NC}"

# WSL2 detection
if grep -qi microsoft /proc/version 2>/dev/null; then
    ok "Running inside WSL2"
else
    warn "Not WSL2 — this script is designed for WSL2 + Docker Desktop"
    read -rp "  Continue anyway? (y/N): " CONT
    [[ "$CONT" =~ ^[Yy]$ ]] || exit 0
fi

# Docker Desktop
if docker info >/dev/null 2>&1; then
    ok "Docker Desktop accessible"
else
    fail "Docker not available. Ensure Docker Desktop is running with WSL2 integration enabled."
fi

# NVIDIA GPU in Docker
info "Testing GPU passthrough (this may pull an image on first run)..."
if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
    GPU_NAME=$(docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_VRAM=$(docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    ok "GPU detected: ${GPU_NAME} (${GPU_VRAM} MB VRAM)"
else
    fail "GPU passthrough failed. Check: NVIDIA driver on Windows, NVIDIA Container Toolkit in WSL2, Docker Desktop GPU support enabled."
fi

# ── Step 2: Hub Connectivity ───────────────────────────────────────
echo -e "\n${CYAN}Step 2: Hub Connectivity${NC}"

HUB_URL=""
if curl -sf "${LAN_HUB}/health" >/dev/null 2>&1; then
    HUB_URL="$LAN_HUB"
    ok "Hub reachable via LAN (${LAN_HUB})"
elif curl -sf "${MESH_HUB}/health" >/dev/null 2>&1; then
    HUB_URL="$MESH_HUB"
    ok "Hub reachable via mesh (${MESH_HUB})"
else
    fail "Cannot reach hub on LAN (${LAN_HUB}) or mesh (${MESH_HUB}). Check network."
fi

# ── Step 3: Node Registration ─────────────────────────────────────
echo -e "\n${CYAN}Step 3: Node Registration${NC}"

read -rp "  Node name (e.g., desktop-245): " NODE_NAME
[[ -n "$NODE_NAME" ]] || fail "Node name required"

# Accept token from env var (set by +Node modal) or prompt
NODE_TOKEN="${TOKEN:-}"
if [[ -z "$NODE_TOKEN" ]]; then
    read -rp "  Registration token (or Enter for manual approval): " NODE_TOKEN
else
    ok "Using pre-generated token (auto-approved)"
fi

info "Registering with hub..."
REG_PAYLOAD=$(cat <<EOJSON
{"name": "${NODE_NAME}", "type": "starship", "token": "${NODE_TOKEN:-null}", "device_info": {"gpu_model": "${GPU_NAME}", "gpu_vram_mb": ${GPU_VRAM:-0}, "os": "Windows/WSL2"}}
EOJSON
)

REG_RESPONSE=$(curl -sf -X POST "${HUB_URL}${HUB_API_BASE}/fleet/register" \
    -H "Content-Type: application/json" \
    -d "$REG_PAYLOAD" 2>&1) || fail "Registration failed: ${REG_RESPONSE}"

REG_SUCCESS=$(echo "$REG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success',''))" 2>/dev/null)
REG_STATUS=$(echo "$REG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
NODE_ID=$(echo "$REG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('node_id',''))" 2>/dev/null)
API_KEY=$(echo "$REG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null)

[[ "$REG_SUCCESS" == "True" ]] || fail "Registration rejected: ${REG_RESPONSE}"
ok "Registered as ${NODE_ID} (status: ${REG_STATUS})"

# If pending, poll for approval
if [[ "$REG_STATUS" == "pending" ]]; then
    info "Waiting for admin approval (polling every 10s, timeout 10min)..."
    for i in $(seq 1 60); do
        sleep 10
        STATUS_RESP=$(curl -sf "${HUB_URL}${HUB_API_BASE}/fleet/status/${NODE_ID}?need_key=true" 2>/dev/null || echo '{}')
        POLL_STATUS=$(echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
        if [[ "$POLL_STATUS" == "approved" ]]; then
            API_KEY=$(echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null)
            ok "Approved! API key received."
            break
        elif [[ "$POLL_STATUS" == "denied" ]]; then
            fail "Registration denied by admin."
        fi
        echo -ne "\r  Waiting... (${i}/60)"
    done
    [[ -n "$API_KEY" ]] || fail "Timed out waiting for approval."
fi

# ── Step 4: Install Node Stack ─────────────────────────────────────
echo -e "\n${CYAN}Step 4: Installing Node Stack${NC}"

mkdir -p "${INSTALL_DIR}/migrations"
cd "$INSTALL_DIR"
ok "Install directory: ${INSTALL_DIR}"

# Download node files from hub
for FILE in $NODE_FILES; do
    info "Downloading ${FILE}..."
    curl -sf "${HUB_URL}${HUB_API_BASE}/nodes/${FILE}" -o "${FILE}" \
        || warn "Could not download ${FILE} from hub, using local copy if available"
done

# Download migrations
for MIG in 001_node_schema.sql 002_knowledge_projects.sql; do
    curl -sf "${HUB_URL}${HUB_API_BASE}/nodes/migrations/${MIG}" -o "migrations/${MIG}" 2>/dev/null \
        || warn "Could not download migration ${MIG}"
done

# Generate .env
DB_PASS=$(openssl rand -hex 16)
cat > .env <<EOENV
# A.R.C.H.I.E. Node Configuration — generated $(date -Iseconds)
NODE_ID=${NODE_ID}
HUB_URL=${HUB_URL}
HUB_API_KEY=${API_KEY}
DB_PASSWORD=${DB_PASS}
OLLAMA_PORT=11434
NODE_API_PORT=3001
COMFYUI_PORT=8188
HEARTBEAT_INTERVAL=30
NODE_TIMEZONE=America/Toronto
DOCKER_SOCK=/var/run/docker.sock
EOENV
ok "Generated .env with secure DB password"

# ── Step 5: Build & Start ──────────────────────────────────────────
echo -e "\n${CYAN}Step 5: Building & Starting Containers${NC}"

info "Building node image (first run may take 1-2 min)..."
docker compose build --quiet || fail "Docker build failed"
ok "Image built"

info "Starting services..."
docker compose up -d || fail "Docker compose up failed"
ok "Services starting"

# ── Step 6: Verify ─────────────────────────────────────────────────
echo -e "\n${CYAN}Step 6: Verification${NC}"

info "Waiting for services to become healthy (up to 3 min)..."
TIMEOUT=180
ELAPSED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
    HEALTHY=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
lines = sys.stdin.read().strip().split('\n')
healthy = sum(1 for l in lines if l and json.loads(l).get('Health','') == 'healthy')
print(healthy)
" 2>/dev/null || echo "0")
    RUNNING=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
lines = sys.stdin.read().strip().split('\n')
running = sum(1 for l in lines if l and json.loads(l).get('State','') == 'running')
print(running)
" 2>/dev/null || echo "0")
    echo -ne "\r  Services: ${RUNNING} running, ${HEALTHY} healthy (${ELAPSED}s/${TIMEOUT}s)  "
    if [[ "$HEALTHY" -ge 3 ]]; then
        echo ""
        ok "All core services healthy"
        break
    fi
    sleep 10
    ELAPSED=$((ELAPSED + 10))
done

if [[ "$HEALTHY" -lt 3 ]]; then
    warn "Not all services healthy after ${TIMEOUT}s. Check: docker compose logs"
fi

# GPU check inside Ollama
info "Verifying GPU access in Ollama..."
if docker exec archie_node_ollama nvidia-smi >/dev/null 2>&1; then
    ok "Ollama has GPU access"
else
    warn "Ollama cannot see GPU — check NVIDIA Container Toolkit"
fi

# Heartbeat test
info "Testing heartbeat to hub..."
HB_RESP=$(curl -sf -X POST "${HUB_URL}${HUB_API_BASE}/nodes/${NODE_ID}/heartbeat" \
    -H "Content-Type: application/json" \
    -H "X-Node-API-Key: ${API_KEY}" \
    -d '{"cpu_percent": 0, "ram_percent": 0, "status": "online"}' 2>&1) || true
if echo "$HB_RESP" | python3 -c "import sys,json; assert json.load(sys.stdin).get('success')" 2>/dev/null; then
    ok "Heartbeat received by hub"
else
    warn "Heartbeat failed — hub may not see this node yet. Check API key."
fi

# ── Done ───────────────────────────────────────────────────────────
echo -e "\n${GREEN}══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Node ${NODE_NAME} (${NODE_ID}) is deployed!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Install dir:  ${INSTALL_DIR}"
echo "  Ollama:       http://$(hostname -I | awk '{print $1}'):11434"
echo "  Node API:     http://$(hostname -I | awk '{print $1}'):3001"
echo "  Hub:          ${HUB_URL}"
echo ""
echo "  Commands:"
echo "    docker compose ps          # check status"
echo "    docker compose logs -f     # view logs"
echo "    docker compose down        # stop"
echo "    docker compose up -d       # restart"
echo ""
