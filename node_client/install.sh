#!/bin/bash
set -e

# =============================================================================
# A.R.C.H.I.E. Unified Node Client — Linux Installer v2.0.0
# Usage: curl -fsSL http://YOUR_HUB:3000/tools/starbase/api/nodes/install.sh | sudo bash
#   or:  sudo bash install.sh http://192.168.1.200:3000
# =============================================================================

CLIENT_VERSION="2.0.0"
INSTALL_DIR="/opt/archie-node"
CONFIG_DIR="/etc/archie-node"
CONFIG_PATH="$CONFIG_DIR/config.json"
SYNC_SCRIPT="$INSTALL_DIR/node_sync.py"
SERVICE_NAME="archie-node"
OLD_SERVICE_NAME="archie-node-heartbeat"
OLLAMA_PORT=11434
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
    echo "  ============================================="
    echo "   A.R.C.H.I.E. Unified Node Installer v${CLIENT_VERSION}"
    echo "   Linux One-Click Setup"
    echo "  ============================================="
    echo -e "${NC}"
}

info()    { echo -e "  ${BLUE}[INFO]${NC}    $1"; }
success() { echo -e "  ${GREEN}[OK]${NC}      $1"; }
warn()    { echo -e "  ${YELLOW}[WARN]${NC}    $1"; }
error()   { echo -e "  ${RED}[ERROR]${NC}   $1"; }
step()    { echo -e "\n  ${BOLD}${CYAN}>> $1${NC}"; }

# =============================================================================
# STEP 1: Prerequisites
# =============================================================================

main() {
    print_banner

    # -- Get Hub URL --
    HUB_URL="${1:-}"
    if [ -z "$HUB_URL" ]; then
        read -p "  Enter A.R.C.H.I.E. Hub URL (e.g. http://192.168.1.200:3000): " HUB_URL
    fi
    if [ -z "$HUB_URL" ]; then
        error "Hub URL is required."
        exit 1
    fi
    HUB_URL="${HUB_URL%/}"  # Strip trailing slash

    step "Step 1/8: Checking prerequisites"

    # Root check
    if [ "$(id -u)" -ne 0 ]; then
        error "This script must be run as root (use sudo)."
        exit 1
    fi
    success "Running as root"

    # Python check
    PYTHON_CMD=""
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            PY_VER=$($cmd --version 2>&1)
            PYTHON_CMD="$cmd"
            success "Python found: $PY_VER"
            break
        fi
    done
    if [ -z "$PYTHON_CMD" ]; then
        info "Python 3 not found, installing..."
        if command -v apt-get &>/dev/null; then
            apt-get update -qq && apt-get install -y -qq python3
        elif command -v dnf &>/dev/null; then
            dnf install -y python3
        elif command -v yum &>/dev/null; then
            yum install -y python3
        else
            error "Cannot auto-install Python 3. Please install manually."
            exit 1
        fi
        PYTHON_CMD="python3"
        success "Python 3 installed"
    fi

    # curl check
    if ! command -v curl &>/dev/null; then
        error "curl is required but not found."
        exit 1
    fi

    # Create directories
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    success "Directories ready: $INSTALL_DIR, $CONFIG_DIR"

    # =============================================================================
    # STEP 2: Detect Hardware
    # =============================================================================

    step "Step 2/8: Detecting hardware"

    CPU_CORES=$(nproc 2>/dev/null || echo "1")
    CPU_MODEL="unknown"
    if [ -f /proc/cpuinfo ]; then
        CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)
    fi
    [ -z "$CPU_MODEL" ] && CPU_MODEL=$(uname -m)
    info "CPU: ${CPU_MODEL} (${CPU_CORES} cores)"

    RAM_GB=0
    if command -v free &>/dev/null; then
        RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
    elif [ -f /proc/meminfo ]; then
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        RAM_GB=$(( RAM_KB / 1048576 ))
    fi
    info "RAM: ${RAM_GB} GB"

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
        info "GPU: none detected (CPU inference only)"
    fi

    DISK_GB=$(df -BG / | awk 'NR==2{print $2}' | tr -d 'G')
    info "Disk: ${DISK_GB} GB"

    OS_INFO="Linux $(uname -r)"
    if [ -f /etc/os-release ]; then
        OS_INFO=$(. /etc/os-release && echo "${PRETTY_NAME:-$NAME $VERSION}")
    fi
    info "OS: ${OS_INFO}"

    success "Hardware detection complete"

    # =============================================================================
    # STEP 3: Detect Ollama
    # =============================================================================

    step "Step 3/8: Detecting Ollama"

    OLLAMA_READY=false
    if curl -s "http://localhost:$OLLAMA_PORT/api/tags" &>/dev/null; then
        OLLAMA_READY=true
        MODEL_COUNT=$(curl -s "http://localhost:$OLLAMA_PORT/api/tags" | $PYTHON_CMD -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
        success "Ollama responding on localhost:$OLLAMA_PORT ($MODEL_COUNT models)"
    else
        warn "Ollama not detected on localhost:$OLLAMA_PORT"
        info "Install with: curl -fsSL https://ollama.com/install.sh | sh"
        info "Continuing without Ollama — node_sync.py will retry on startup."
    fi

    # =============================================================================
    # STEP 4: Download node_sync.py
    # =============================================================================

    step "Step 4/8: Downloading unified node client"

    SYNC_URL="${HUB_URL}/tools/starbase/api/nodes/node_sync.py"
    info "Downloading from ${SYNC_URL}..."
    if curl -fsSL "$SYNC_URL" -o "$SYNC_SCRIPT"; then
        chmod +x "$SYNC_SCRIPT"
        success "Downloaded node_sync.py to $SYNC_SCRIPT"
    else
        error "Failed to download node_sync.py from $SYNC_URL"
        exit 1
    fi

    # =============================================================================
    # STEP 5: Register with Hub
    # =============================================================================

    step "Step 5/8: Registering with hub"

    NODE_NAME=$(hostname)
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "$LOCAL_IP" ]; then
        LOCAL_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
    fi
    [ -z "$LOCAL_IP" ] && LOCAL_IP="127.0.0.1"

    info "Node name: ${NODE_NAME}"
    info "Local IP:  ${LOCAL_IP}"

    REGISTER_URL="${HUB_URL}/tools/starbase/api/nodes/register"
    PAYLOAD=$(cat <<ENDJSON
{
    "node_name": "${NODE_NAME}",
    "vpn_ip": "${LOCAL_IP}",
    "hostname": "${LOCAL_IP}",
    "port": $OLLAMA_PORT,
    "gpu_available": ${GPU_AVAILABLE},
    "gpu_model": "${GPU_MODEL}",
    "gpu_vram_gb": ${GPU_VRAM_GB},
    "cpu_cores": ${CPU_CORES},
    "cpu_model": "${CPU_MODEL}",
    "ram_gb": ${RAM_GB},
    "disk_gb": ${DISK_GB},
    "os_info": "${OS_INFO}",
    "ollama_available": ${OLLAMA_READY},
    "client_version": "${CLIENT_VERSION}",
    "tags": ["linux"]
}
ENDJSON
)

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

    NODE_ID=$(echo "$BODY" | $PYTHON_CMD -c "import sys,json; print(json.load(sys.stdin).get('node_id',''))" 2>/dev/null)
    API_KEY=$(echo "$BODY" | $PYTHON_CMD -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null)

    if [ -z "$NODE_ID" ] || [ -z "$API_KEY" ]; then
        error "Could not extract node_id or api_key from registration response"
        exit 1
    fi

    success "Registered as node: ${NODE_ID}"

    # =============================================================================
    # STEP 6: Write config.json
    # =============================================================================

    step "Step 6/8: Writing configuration"

    cat > "$CONFIG_PATH" <<CONFIGJSON
{
    "node_id": "${NODE_ID}",
    "hub_url": "${HUB_URL}",
    "hub_api_key": "${API_KEY}",
    "ollama_host": "http://localhost:${OLLAMA_PORT}",
    "heartbeat_interval": 30,
    "sync_poll_interval": 60,
    "archie_version": "${CLIENT_VERSION}",
    "client_version": "${CLIENT_VERSION}",
    "node_name": "${NODE_NAME}",
    "registered_at": "$(date -Iseconds)"
}
CONFIGJSON
    chmod 600 "$CONFIG_PATH"
    success "Config saved to $CONFIG_PATH"

    # =============================================================================
    # STEP 7: Create systemd service (replaces old heartbeat service)
    # =============================================================================

    step "Step 7/8: Installing systemd service"

    # Stop and disable old heartbeat service if it exists
    if systemctl is-active --quiet "$OLD_SERVICE_NAME" 2>/dev/null; then
        systemctl stop "$OLD_SERVICE_NAME"
        systemctl disable "$OLD_SERVICE_NAME"
        rm -f "/etc/systemd/system/${OLD_SERVICE_NAME}.service"
        success "Removed old $OLD_SERVICE_NAME service"
    fi

    cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=A.R.C.H.I.E. Unified Node Client — heartbeats, sync, and OTA
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=${PYTHON_CMD} ${SYNC_SCRIPT}
WorkingDirectory=${INSTALL_DIR}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=CONFIG_FILE=${CONFIG_PATH}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl start "$SERVICE_NAME"
    success "Service ${SERVICE_NAME} enabled and started"

    # =============================================================================
    # STEP 8: Verify and Summary
    # =============================================================================

    step "Step 8/8: Verifying"

    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Node sync service is running"
    else
        warn "Service may still be starting — check: journalctl -u $SERVICE_NAME -f"
    fi

    echo ""
    echo -e "  ${GREEN}${BOLD}=============================================${NC}"
    echo -e "  ${GREEN}${BOLD}  A.R.C.H.I.E. Node Setup Complete!         ${NC}"
    echo -e "  ${GREEN}${BOLD}=============================================${NC}"
    echo ""
    echo -e "  ${BOLD}Node ID:${NC}     ${NODE_ID}"
    echo -e "  ${BOLD}Node Name:${NC}   ${NODE_NAME}"
    echo -e "  ${BOLD}Local IP:${NC}    ${LOCAL_IP}"
    echo -e "  ${BOLD}Hub URL:${NC}     ${HUB_URL}"
    echo -e "  ${BOLD}Ollama:${NC}      http://localhost:${OLLAMA_PORT}"
    echo -e "  ${BOLD}Config:${NC}      ${CONFIG_PATH}"
    echo -e "  ${BOLD}Client:${NC}      ${SYNC_SCRIPT}"
    echo -e "  ${BOLD}Service:${NC}     ${SERVICE_NAME}"
    echo ""
    echo -e "  ${CYAN}The node is now sending heartbeats and polling${NC}"
    echo -e "  ${CYAN}for sync commands. An admin must approve this${NC}"
    echo -e "  ${CYAN}node on the A.R.C.H.I.E. dashboard.${NC}"
    echo ""
    echo -e "  ${BOLD}Management commands:${NC}"
    echo "    systemctl status $SERVICE_NAME"
    echo "    journalctl -u $SERVICE_NAME -f"
    echo "    systemctl restart $SERVICE_NAME"
    echo ""
}

main "$@"
