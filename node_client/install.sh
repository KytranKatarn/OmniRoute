#!/bin/bash
set -e

# =============================================================================
# A.R.C.H.I.E. Remote Node Installer v1.0.0
# Installs and registers a compute node with the A.R.C.H.I.E. platform
# =============================================================================

ARCHIE_BASE_URL="http://192.168.1.200:3000"
REGISTER_ENDPOINT="/tools/bridge/api/nodes/register"
STATUS_ENDPOINT="/tools/bridge/api/nodes"
CLIENT_VERSION="1.0.0"
STARTER_MODELS=("qwen2.5:7b" "llama3.2:3b")

# -- Colors & Output ----------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_banner() {
    echo -e "${CYAN}"
    echo "  ╔═══════════════════════════════════════════════════════╗"
    echo "  ║          A.R.C.H.I.E. Node Installer v${CLIENT_VERSION}          ║"
    echo "  ║       Autonomous Resource for Compute & Hardware      ║"
    echo "  ╚═══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

info()    { echo -e "  ${BLUE}[INFO]${NC}    $1"; }
success() { echo -e "  ${GREEN}[OK]${NC}      $1"; }
warn()    { echo -e "  ${YELLOW}[WARN]${NC}    $1"; }
error()   { echo -e "  ${RED}[ERROR]${NC}   $1"; }
step()    { echo -e "\n  ${BOLD}${CYAN}>> $1${NC}"; }

# -- Step 1: Require Root -----------------------------------------------------

check_root() {
    step "Checking privileges"
    if [ "$(id -u)" -ne 0 ]; then
        error "This script must be run as root (use sudo)."
        echo -e "  ${YELLOW}Usage: sudo bash install.sh${NC}"
        exit 1
    fi
    success "Running as root"
}

# -- Step 2: Detect Hardware ---------------------------------------------------

detect_hardware() {
    step "Detecting hardware"

    # CPU
    CPU_CORES=$(nproc 2>/dev/null || echo "1")
    CPU_MODEL="unknown"
    if [ -f /proc/cpuinfo ]; then
        CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)
    fi
    if [ -z "$CPU_MODEL" ] || [ "$CPU_MODEL" = "" ]; then
        CPU_MODEL=$(uname -m)
    fi
    info "CPU: ${CPU_MODEL} (${CPU_CORES} cores)"

    # RAM
    RAM_GB=0
    if command -v free &>/dev/null; then
        RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
    elif [ -f /proc/meminfo ]; then
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        RAM_GB=$(( RAM_KB / 1048576 ))
    fi
    info "RAM: ${RAM_GB} GB"

    # GPU
    GPU_AVAILABLE=false
    GPU_MODEL="none"
    GPU_VRAM_GB=0
    if command -v nvidia-smi &>/dev/null; then
        GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true)
        if [ -n "$GPU_INFO" ]; then
            GPU_AVAILABLE=true
            GPU_MODEL=$(echo "$GPU_INFO" | head -1 | cut -d',' -f1 | xargs)
            GPU_VRAM_MIB=$(echo "$GPU_INFO" | head -1 | cut -d',' -f2 | grep -o '[0-9]*')
            GPU_VRAM_GB=$(( GPU_VRAM_MIB / 1024 ))
            info "GPU: ${GPU_MODEL} (${GPU_VRAM_GB} GB VRAM)"
        fi
    fi
    if [ "$GPU_AVAILABLE" = false ]; then
        VGA_INFO=$(lspci 2>/dev/null | grep -i vga | head -1 || true)
        if [ -n "$VGA_INFO" ]; then
            GPU_MODEL=$(echo "$VGA_INFO" | sed 's/.*: //')
            info "GPU: ${GPU_MODEL} (no NVIDIA driver)"
        else
            info "GPU: none detected"
        fi
    fi

    # Disk
    DISK_GB=$(df -BG / | awk 'NR==2{print $2}' | tr -d 'G')
    info "Disk: ${DISK_GB} GB"

    # OS
    OS_INFO="Linux $(uname -r)"
    if [ -f /etc/os-release ]; then
        OS_INFO=$(. /etc/os-release && echo "${PRETTY_NAME:-$NAME $VERSION}")
    fi
    info "OS: ${OS_INFO}"

    success "Hardware detection complete"
}

# -- Step 3: Install/Verify Ollama --------------------------------------------

setup_ollama() {
    step "Setting up Ollama"

    if command -v ollama &>/dev/null; then
        OLLAMA_VER=$(ollama --version 2>/dev/null || echo "unknown")
        success "Ollama already installed (${OLLAMA_VER})"
    else
        info "Ollama not found, installing..."
        curl -fsSL https://ollama.com/install.sh | sh
        if ! command -v ollama &>/dev/null; then
            error "Ollama installation failed"
            exit 1
        fi
        success "Ollama installed successfully"
    fi

    # Configure Ollama to listen on all interfaces via systemd override
    info "Configuring Ollama to listen on 0.0.0.0..."
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/override.conf <<EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
EOF

    systemctl daemon-reload
    systemctl restart ollama
    success "Ollama configured with OLLAMA_HOST=0.0.0.0"

    # Wait for Ollama to become ready
    info "Waiting for Ollama API to respond..."
    OLLAMA_READY=false
    for i in $(seq 1 15); do
        if curl -s http://localhost:11434/api/tags &>/dev/null; then
            OLLAMA_READY=true
            break
        fi
        sleep 2
    done

    if [ "$OLLAMA_READY" = false ]; then
        error "Ollama failed to start within 30 seconds"
        exit 1
    fi
    success "Ollama API is responding on port 11434"
}

# -- Step 4: Pull Starter Models -----------------------------------------------

pull_models() {
    step "Pulling starter models"

    for model in "${STARTER_MODELS[@]}"; do
        info "Pulling ${model} (this may take a while)..."
        if ollama pull "$model"; then
            success "Pulled ${model}"
        else
            warn "Failed to pull ${model}, skipping"
        fi
    done
}

# -- Step 5: Register with A.R.C.H.I.E. ---------------------------------------

register_node() {
    step "Registering with A.R.C.H.I.E. platform"

    NODE_NAME=$(hostname)
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "$LOCAL_IP" ]; then
        LOCAL_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
    fi
    info "Node name: ${NODE_NAME}"
    info "Local IP:  ${LOCAL_IP}"

    PAYLOAD=$(cat <<ENDJSON
{
    "node_name": "${NODE_NAME}",
    "vpn_ip": "${LOCAL_IP}",
    "hostname": "${NODE_NAME}",
    "port": 11434,
    "gpu_available": ${GPU_AVAILABLE},
    "gpu_model": "${GPU_MODEL}",
    "gpu_vram_gb": ${GPU_VRAM_GB},
    "cpu_cores": ${CPU_CORES},
    "cpu_model": "${CPU_MODEL}",
    "ram_gb": ${RAM_GB},
    "disk_gb": ${DISK_GB},
    "os_info": "${OS_INFO}",
    "ollama_available": true,
    "client_version": "${CLIENT_VERSION}",
    "tags": ["linux"]
}
ENDJSON
)

    REGISTER_URL="${ARCHIE_BASE_URL}${REGISTER_ENDPOINT}"
    info "Registering at ${REGISTER_URL}..."

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$REGISTER_URL" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD")

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
        error "Registration failed (HTTP ${HTTP_CODE})"
        error "Response: ${BODY}"
        exit 1
    fi

    # Extract node_id and api_key from response
    NODE_ID=$(echo "$BODY" | grep -o '"node_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | cut -d'"' -f4)
    API_KEY=$(echo "$BODY" | grep -o '"api_key"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | cut -d'"' -f4)

    if [ -z "$NODE_ID" ] || [ -z "$API_KEY" ]; then
        error "Could not extract node_id or api_key from registration response"
        exit 1
    fi

    # Save config with all required fields for heartbeat
    mkdir -p /etc/archie-node
    cat > /etc/archie-node/config.json <<CONFIGJSON
{
    "node_id": "${NODE_ID}",
    "api_key": "${API_KEY}",
    "server_url": "${ARCHIE_BASE_URL}",
    "node_name": "${NODE_NAME}",
    "ollama_port": 11434,
    "heartbeat_interval": 30,
    "client_version": "${CLIENT_VERSION}",
    "registered_at": "$(date -Iseconds)"
}
CONFIGJSON
    chmod 600 /etc/archie-node/config.json
    success "Configuration saved to /etc/archie-node/config.json"
    success "Registered as node: ${NODE_ID}"
}

# -- Step 6: Install Heartbeat Service ----------------------------------------

install_heartbeat() {
    step "Installing heartbeat service"

    mkdir -p /opt/archie-node

    # Copy heartbeat script if it exists alongside installer, otherwise create stub
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "${SCRIPT_DIR}/heartbeat.sh" ]; then
        cp "${SCRIPT_DIR}/heartbeat.sh" /opt/archie-node/heartbeat.sh
        info "Copied heartbeat.sh from installer directory"
    else
        warn "heartbeat.sh not found beside installer, creating default"
        cat > /opt/archie-node/heartbeat.sh <<'HEARTBEAT'
#!/bin/bash
# A.R.C.H.I.E. Node Heartbeat - sends periodic status to platform
CONFIG_FILE="/etc/archie-node/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config not found at $CONFIG_FILE" >&2
    exit 1
fi
NODE_ID=$(grep -o '"node_id"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" | head -1 | cut -d'"' -f4)
API_KEY=$(grep -o '"api_key"[[:space:]]*:[[:space:]]*"[^"]*"' "$CONFIG_FILE" | head -1 | cut -d'"' -f4)
BASE_URL="http://192.168.1.200:3000"
while true; do
    curl -s -X POST "${BASE_URL}/tools/bridge/api/nodes/${NODE_ID}/heartbeat" \
        -H "Content-Type: application/json" \
        -H "X-Node-API-Key: ${API_KEY}" \
        -d '{"status":"online"}' > /dev/null 2>&1
    sleep 30
done
HEARTBEAT
    fi
    chmod +x /opt/archie-node/heartbeat.sh
    success "Heartbeat script installed to /opt/archie-node/heartbeat.sh"

    # Create systemd service
    cat > /etc/systemd/system/archie-node-heartbeat.service <<EOF
[Unit]
Description=A.R.C.H.I.E. Node Heartbeat Service
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/archie-node/heartbeat.sh
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable archie-node-heartbeat.service
    systemctl start archie-node-heartbeat.service
    success "Heartbeat service enabled and started"
}

# -- Step 7: Poll for Approval -------------------------------------------------

poll_for_approval() {
    step "Waiting for admin approval"

    info "Node registered and pending approval."
    info "An admin must approve this node in the A.R.C.H.I.E. dashboard."
    echo ""

    STATUS_URL="${ARCHIE_BASE_URL}${STATUS_ENDPOINT}/${NODE_ID}/status"
    APPROVED=false
    ATTEMPT=0

    while [ "$APPROVED" = false ]; do
        ATTEMPT=$((ATTEMPT + 1))
        RESP=$(curl -s "$STATUS_URL" -H "X-Node-API-Key: ${API_KEY}" 2>/dev/null || echo "")

        NODE_STATUS=$(echo "$RESP" | grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | cut -d'"' -f4)

        if [ "$NODE_STATUS" = "approved" ] || [ "$NODE_STATUS" = "active" ]; then
            APPROVED=true
        else
            printf "\r  ${YELLOW}[WAIT]${NC}    Polling for approval... (attempt %d, status: %s)  " "$ATTEMPT" "${NODE_STATUS:-unknown}"
            sleep 5
        fi
    done

    echo ""
    success "Node has been approved!"
}

# -- Step 8: Deployment Mode ---------------------------------------------------

choose_deployment_mode() {
    echo ""
    echo -e "  ${BOLD}${CYAN}═══════════════════════════════════════════════${NC}"
    echo -e "  ${BOLD}${CYAN}  DEPLOYMENT MODE${NC}"
    echo -e "  ${BOLD}${CYAN}═══════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}1)${NC} Ollama-only (current setup — just LLM serving)"
    echo -e "  ${BOLD}2)${NC} Full-stack  (complete ARCHIE business node with Docker)"
    echo ""
    read -p "  Choose deployment mode [1/2]: " DEPLOY_MODE
}

install_docker_stack() {
    step "Installing full-stack Docker deployment"

    # --- Docker Engine ---
    if command -v docker &>/dev/null; then
        success "Docker already installed ($(docker --version))"
    else
        info "Docker not found, installing via get.docker.com..."
        curl -fsSL https://get.docker.com | sh
        if ! command -v docker &>/dev/null; then
            error "Docker installation failed"
            exit 1
        fi
        success "Docker installed successfully"
    fi

    # --- Docker Compose ---
    if docker compose version &>/dev/null; then
        success "Docker Compose available ($(docker compose version --short 2>/dev/null || echo 'OK'))"
    else
        error "docker compose not available. Please install Docker Compose v2."
        exit 1
    fi

    # --- NVIDIA Container Toolkit (if GPU detected) ---
    if [ "$GPU_AVAILABLE" = true ]; then
        if dpkg -l 2>/dev/null | grep -q nvidia-container-toolkit; then
            success "NVIDIA Container Toolkit already installed"
        else
            info "GPU detected but NVIDIA Container Toolkit not found, installing..."
            if command -v apt-get &>/dev/null; then
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
                    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
                    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
                    | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
                apt-get update -qq
                apt-get install -y -qq nvidia-container-toolkit
                nvidia-ctk runtime configure --runtime=docker
                systemctl restart docker
                success "NVIDIA Container Toolkit installed and configured"
            else
                warn "Non-apt system detected. Please install nvidia-container-toolkit manually."
            fi
        fi
    fi

    # --- Create deployment directory ---
    DEPLOY_DIR="/opt/archie-node"
    mkdir -p "${DEPLOY_DIR}"
    info "Deployment directory: ${DEPLOY_DIR}"

    # --- Download docker-compose.node.yml ---
    COMPOSE_URL="${ARCHIE_BASE_URL}/tools/bridge/api/nodes/docker-compose.node.yml"
    info "Downloading docker-compose.node.yml from ${COMPOSE_URL}..."
    curl -fsSL "${COMPOSE_URL}" -o "${DEPLOY_DIR}/docker-compose.yml"
    success "Downloaded docker-compose.yml"

    # --- Download Dockerfile.node ---
    DOCKERFILE_URL="${ARCHIE_BASE_URL}/tools/bridge/api/nodes/Dockerfile.node"
    info "Downloading Dockerfile.node from ${DOCKERFILE_URL}..."
    curl -fsSL "${DOCKERFILE_URL}" -o "${DEPLOY_DIR}/Dockerfile.node"
    success "Downloaded Dockerfile.node"

    # --- Download node_sync.py ---
    SYNC_URL="${ARCHIE_BASE_URL}/tools/bridge/api/nodes/node_sync.py"
    info "Downloading node_sync.py from ${SYNC_URL}..."
    curl -fsSL "${SYNC_URL}" -o "${DEPLOY_DIR}/node_sync.py"
    success "Downloaded node_sync.py"

    # --- Download node_api.py ---
    API_URL="${ARCHIE_BASE_URL}/tools/bridge/api/nodes/node_api.py"
    info "Downloading node_api.py from ${API_URL}..."
    curl -fsSL "${API_URL}" -o "${DEPLOY_DIR}/node_api.py"
    success "Downloaded node_api.py"

    # --- Download migrations ---
    mkdir -p "${DEPLOY_DIR}/migrations"
    MIGRATION_URL="${ARCHIE_BASE_URL}/tools/bridge/api/nodes/migrations/001_node_schema.sql"
    info "Downloading migrations/001_node_schema.sql..."
    curl -fsSL "${MIGRATION_URL}" -o "${DEPLOY_DIR}/migrations/001_node_schema.sql"
    success "Downloaded migration 001"

    MIGRATION2_URL="${ARCHIE_BASE_URL}/tools/bridge/api/nodes/migrations/002_knowledge_projects.sql"
    info "Downloading migrations/002_knowledge_projects.sql..."
    curl -fsSL "${MIGRATION2_URL}" -o "${DEPLOY_DIR}/migrations/002_knowledge_projects.sql"
    success "Downloaded migration 002"

    # --- Build node Docker image ---
    info "Building node Docker image (this may take a minute)..."
    (cd "${DEPLOY_DIR}" && docker compose build --no-cache)
    success "Built node containers"

    # --- Generate credentials and detect host ---
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    HOST_IP=$(hostname -I | awk '{print $1}')
    ARCHIE_VERSION="${CLIENT_VERSION}"

    info "Host IP: ${HOST_IP}"

    # --- Detect timezone ---
    NODE_TZ="America/Toronto"
    if [ -f /etc/timezone ]; then
        NODE_TZ=$(cat /etc/timezone)
    elif [ -L /etc/localtime ]; then
        NODE_TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
    fi
    info "Timezone: ${NODE_TZ}"

    # --- Create .env file ---
    cat > "${DEPLOY_DIR}/.env" <<DOTENV
# A.R.C.H.I.E. Business Node Configuration
# Generated by install.sh on $(date -Iseconds)
NODE_ID=${NODE_ID}
HUB_URL=${ARCHIE_BASE_URL}
HUB_API_KEY=${API_KEY}
DB_PASSWORD=${DB_PASSWORD}
ARCHIE_VERSION=${ARCHIE_VERSION}
HOST_IP=${HOST_IP}
DEPLOYMENT_MODE=business_node
NODE_TIMEZONE=${NODE_TZ}
DOTENV
    chmod 600 "${DEPLOY_DIR}/.env"
    success "Environment file created at ${DEPLOY_DIR}/.env"

    # --- Start containers ---
    info "Starting containers..."
    (cd "${DEPLOY_DIR}" && docker compose up -d)
    success "Docker stack is running"

    # --- Print Docker stack info ---
    echo ""
    echo -e "  ${GREEN}${BOLD}--- Full-Stack Deployment Active (4 containers) ---${NC}"
    echo -e "  ${BOLD}Containers:${NC}  ollama, postgres, sync, node_api"
    echo -e "  ${BOLD}Node API:${NC}    http://${HOST_IP}:3001"
    echo -e "  ${BOLD}Ollama:${NC}      http://${HOST_IP}:11434"
    echo -e "  ${BOLD}Compose:${NC}     ${DEPLOY_DIR}/docker-compose.yml"
    echo -e "  ${BOLD}Env File:${NC}    ${DEPLOY_DIR}/.env"
    echo ""

    FULL_STACK_DEPLOYED=true
}

# -- Summary -------------------------------------------------------------------

print_summary() {
    echo ""
    echo -e "  ${GREEN}${BOLD}=============================================${NC}"
    echo -e "  ${GREEN}${BOLD}  A.R.C.H.I.E. Node Installation Complete!  ${NC}"
    echo -e "  ${GREEN}${BOLD}=============================================${NC}"
    echo ""
    echo -e "  ${BOLD}Node ID:${NC}     ${NODE_ID}"
    echo -e "  ${BOLD}Node Name:${NC}   $(hostname)"
    echo -e "  ${BOLD}Local IP:${NC}    ${LOCAL_IP}"
    echo -e "  ${BOLD}Ollama:${NC}      http://localhost:11434"
    echo -e "  ${BOLD}Config:${NC}      /etc/archie-node/config.json"
    echo -e "  ${BOLD}Heartbeat:${NC}   systemctl status archie-node-heartbeat"
    if [ "${FULL_STACK_DEPLOYED}" = true ]; then
        echo -e "  ${BOLD}Mode:${NC}        Full-stack (4 containers: ollama, postgres, sync, node_api)"
        echo -e "  ${BOLD}Node API:${NC}    http://${HOST_IP:-$LOCAL_IP}:3001"
        echo -e "  ${BOLD}Compose:${NC}     /opt/archie-node/docker-compose.yml"
    else
        echo -e "  ${BOLD}Mode:${NC}        Ollama-only"
    fi
    echo ""
    echo -e "  ${CYAN}This node is now part of the A.R.C.H.I.E. compute mesh.${NC}"
    echo ""
}

# -- Main ----------------------------------------------------------------------

main() {
    FULL_STACK_DEPLOYED=false
    print_banner
    check_root
    detect_hardware
    setup_ollama
    pull_models
    register_node
    install_heartbeat
    poll_for_approval
    choose_deployment_mode
    if [ "$DEPLOY_MODE" = "2" ]; then
        install_docker_stack
    fi
    print_summary
}

main "$@"
