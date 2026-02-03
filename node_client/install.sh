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
    echo ""
    echo -e "  ${CYAN}This node is now part of the A.R.C.H.I.E. compute mesh.${NC}"
    echo ""
}

# -- Main ----------------------------------------------------------------------

main() {
    print_banner
    check_root
    detect_hardware
    setup_ollama
    pull_models
    register_node
    install_heartbeat
    poll_for_approval
    print_summary
}

main "$@"
