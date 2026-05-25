#!/bin/bash
set -e

# =============================================================================
# A.R.C.H.I.E. Node Installer v3.0 — Linux
# Usage: curl -fsSL http://100.64.0.4:3000/tools/department-hq/api/nodes/install-node.sh | sudo bash
#   or:  sudo bash install-node.sh http://100.64.0.4:3000
# =============================================================================

CLIENT_VERSION="3.0.0"
INSTALL_DIR="/opt/archie-node"
UPGRADE_MODE=false

# -- Colors -------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# -- Helpers ------------------------------------------------------------------
ok()   { echo -e "      ${GREEN}[OK]${NC}    $1"; }
warn() { echo -e "      ${YELLOW}[WARN]${NC}  $1"; }
fail() { echo -e "      ${RED}[FAIL]${NC}  $1"; }
info() { echo -e "      ${BLUE}[...]${NC}   $1"; }
step() { echo -e "\n  ${BOLD}${CYAN}[$1/8]${NC} ${BOLD}$2${NC}"; }

# -- Failure Trap -------------------------------------------------------------
CURRENT_STEP=0
cleanup_on_failure() {
    local step=$CURRENT_STEP
    echo ""
    warn "Installation failed at step $step"
    if [ "$step" -ge 5 ] && [ "$UPGRADE_MODE" = "false" ]; then
        info "Cleaning up downloaded files..."
        rm -f "$INSTALL_DIR/docker-compose.yml" "$INSTALL_DIR/node_sync.py" \
              "$INSTALL_DIR/node_api.py" "$INSTALL_DIR/Dockerfile.node" 2>/dev/null
    fi
    fail "Check the error above and re-run the installer."
    exit 1
}
trap 'cleanup_on_failure' ERR

# -- Banner -------------------------------------------------------------------
show_banner() {
    echo ""
    echo -e "  ${CYAN}${BOLD}╔═══════════════════════════════════════╗${NC}"
    echo -e "  ${CYAN}${BOLD}║  A.R.C.H.I.E. Node Installer v3.0   ║${NC}"
    echo -e "  ${CYAN}${BOLD}║  Linux Fleet Deployment              ║${NC}"
    echo -e "  ${CYAN}${BOLD}╚═══════════════════════════════════════╝${NC}"
    echo ""
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    show_banner

    # ── Step 1: Prerequisites ────────────────────────────────────────────────
    CURRENT_STEP=1
    step "1" "Checking prerequisites..."

    if [ "$(id -u)" -ne 0 ]; then
        fail "This installer must be run as root (use sudo)"
        exit 1
    fi
    ok "Running as root"

    if ! command -v curl &>/dev/null; then
        fail "curl is required but not installed"
        exit 1
    fi
    ok "curl available"

    if ! command -v jq &>/dev/null; then
        info "Installing jq..."
        if command -v apt-get &>/dev/null; then
            apt-get update -qq && apt-get install -y -qq jq >/dev/null 2>&1
        elif command -v dnf &>/dev/null; then
            dnf install -y -q jq >/dev/null 2>&1
        elif command -v yum &>/dev/null; then
            yum install -y -q jq >/dev/null 2>&1
        else
            fail "Cannot install jq — no supported package manager found"
            exit 1
        fi
        ok "jq installed"
    else
        ok "jq available"
    fi

    # Hub URL
    HUB_URL="${1:-}"
    if [ -z "$HUB_URL" ]; then
        echo -n "  Enter hub URL (e.g. https://platform.kytranempowerment.com): "
        read -r HUB_URL
    fi
    HUB_URL="${HUB_URL%/}"
    if [ -z "$HUB_URL" ]; then
        fail "Hub URL is required"
        exit 1
    fi
    ok "Hub URL: $HUB_URL"

    # Re-provision check
    if [ -f "$INSTALL_DIR/.env" ]; then
        warn "Existing installation detected at $INSTALL_DIR"
        if docker compose -f "$INSTALL_DIR/docker-compose.yml" ps --status running 2>/dev/null | grep -q "running"; then
            echo ""
            echo -e "  ${BOLD}Choose an option:${NC}"
            echo "    1) Upgrade (keep registration, update containers)"
            echo "    2) Fresh Install (remove everything, re-register)"
            echo -n "  Choice [1/2]: "
            read -r CHOICE
            case "$CHOICE" in
                1)
                    UPGRADE_MODE=true
                    # Source existing env for NODE_ID and API_KEY
                    # shellcheck disable=SC1091
                    source "$INSTALL_DIR/.env"
                    ok "Upgrade mode — keeping node ID $NODE_ID"
                    ;;
                2)
                    info "Removing existing installation..."
                    cd "$INSTALL_DIR" && docker compose down 2>/dev/null || true
                    cd /
                    rm -rf "$INSTALL_DIR"
                    ok "Old installation removed"
                    ;;
                *)
                    fail "Invalid choice"
                    exit 1
                    ;;
            esac
        else
            info "No running containers — performing fresh install"
            rm -rf "$INSTALL_DIR"
        fi
    fi

    mkdir -p "$INSTALL_DIR"

    # ── Step 2: Hardware Detection ───────────────────────────────────────────
    CURRENT_STEP=2
    step "2" "Detecting hardware..."

    CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)
    CPU_CORES=$(nproc)
    RAM_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}')
    if [ -z "$RAM_GB" ] || [ "$RAM_GB" = "0" ]; then
        RAM_GB=$(awk '/^MemTotal:/{printf "%d", $2/1024/1024}' /proc/meminfo)
    fi
    DISK_FREE_GB=$(df -BG / | awk 'NR==2{print $4}' | tr -d 'G')
    OS_INFO=$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo "Unknown Linux")

    ok "CPU: $CPU_MODEL ($CPU_CORES cores)"
    ok "RAM: ${RAM_GB}GB"
    ok "Disk: ${DISK_FREE_GB}GB free"
    ok "OS:  $OS_INFO"

    # GPU detection
    GPU_AVAILABLE=false
    GPU_MODEL="none"
    GPU_VRAM_GB=0
    if command -v nvidia-smi &>/dev/null; then
        GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true)
        if [ -n "$GPU_INFO" ]; then
            GPU_AVAILABLE=true
            GPU_MODEL=$(echo "$GPU_INFO" | head -1 | cut -d',' -f1 | xargs)
            GPU_VRAM_RAW=$(echo "$GPU_INFO" | head -1 | cut -d',' -f2 | xargs)
            GPU_VRAM_GB=$(echo "$GPU_VRAM_RAW" | grep -oP '\d+' | head -1)
            GPU_VRAM_GB=$(( GPU_VRAM_GB / 1024 ))
            ok "GPU: $GPU_MODEL (${GPU_VRAM_GB}GB VRAM)"
        fi
    fi
    if [ "$GPU_AVAILABLE" = "false" ]; then
        info "No NVIDIA GPU detected — CPU-only mode"
    fi

    # Local IP
    LOCAL_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
    if [ -z "$LOCAL_IP" ]; then
        LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    ok "IP: $LOCAL_IP"

    # ── Step 3: Docker Setup ────────────────────────────────────────────────
    CURRENT_STEP=3
    step "3" "Setting up Docker..."

    if ! command -v docker &>/dev/null; then
        info "Installing Docker Engine..."
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker
        systemctl start docker
        ok "Docker installed"
    else
        ok "Docker available"
    fi

    if ! docker info &>/dev/null; then
        fail "Docker daemon is not running"
        exit 1
    fi
    ok "Docker daemon running"

    if ! docker compose version &>/dev/null; then
        fail "Docker Compose v2 is required (docker compose)"
        exit 1
    fi
    ok "Docker Compose v2 available"

    # Detect and stop native Ollama
    if curl -s --max-time 3 "http://localhost:11434/api/tags" &>/dev/null; then
        warn "Native Ollama detected on port 11434"
        warn "Docker will manage Ollama — stopping native instance"
        systemctl stop ollama 2>/dev/null || true
        systemctl disable ollama 2>/dev/null || true
        ok "Native Ollama stopped (Docker Ollama will take over)"
    fi

    # Install NVIDIA Container Toolkit if GPU present
    if [ "$GPU_AVAILABLE" = "true" ]; then
        if ! docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
            info "Installing NVIDIA Container Toolkit..."
            if command -v apt-get &>/dev/null; then
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
                    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
                    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
                    | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
                apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit >/dev/null 2>&1
            fi
            nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true
            systemctl restart docker
            ok "NVIDIA Container Toolkit installed"
        else
            ok "NVIDIA Container Toolkit available"
        fi
    fi

    # ── Step 4: Register with Hub ────────────────────────────────────────────
    CURRENT_STEP=4
    if [ "$UPGRADE_MODE" = "true" ]; then
        step "4" "Registration (skipped — upgrade mode)"
        ok "Using existing node ID: $NODE_ID"
    else
        step "4" "Registering with hub..."

        PAYLOAD=$(jq -n \
            --arg name "$(hostname)" \
            --arg ip "$LOCAL_IP" \
            --argjson gpu "$GPU_AVAILABLE" \
            --arg gpu_model "$GPU_MODEL" \
            --argjson gpu_vram "$GPU_VRAM_GB" \
            --argjson cpu_cores "$CPU_CORES" \
            --arg cpu_model "$CPU_MODEL" \
            --argjson ram "$RAM_GB" \
            --argjson disk "$DISK_FREE_GB" \
            --arg os_info "$OS_INFO" \
            --arg ver "$CLIENT_VERSION" \
            '{node_name:$name, hostname:$ip, vpn_ip:$ip, port:11434,
              gpu_available:$gpu, gpu_model:$gpu_model, gpu_vram_gb:$gpu_vram,
              cpu_cores:$cpu_cores, cpu_model:$cpu_model, ram_gb:$ram, disk_gb:$disk,
              os_info:$os_info, client_version:$ver, tags:["linux"]}')

        info "Sending registration to $HUB_URL..."
        RESPONSE=$(curl -s -X POST "$HUB_URL/tools/department-hq/api/nodes/register" \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD")

        # Parse response
        NODE_ID=$(echo "$RESPONSE" | jq -r '.node_id // empty')
        API_KEY=$(echo "$RESPONSE" | jq -r '.api_key // empty')
        ERROR=$(echo "$RESPONSE" | jq -r '.error // empty')

        if [ -n "$ERROR" ]; then
            fail "Registration failed: $ERROR"
            exit 1
        fi
        if [ -z "$NODE_ID" ]; then
            fail "Registration failed — no node_id in response"
            fail "Response: $RESPONSE"
            exit 1
        fi

        ok "Registered as node $NODE_ID"
    fi

    # ── Step 5: Download Stack Files ─────────────────────────────────────────
    CURRENT_STEP=5
    step "5" "Downloading stack files..."

    # Write .env
    cat > "$INSTALL_DIR/.env" <<ENVEOF
NODE_ID=$NODE_ID
HUB_URL=$HUB_URL
HUB_API_KEY=$API_KEY
DB_PASSWORD=archie_node_default
OLLAMA_PORT=11434
NODE_API_PORT=3001
HEARTBEAT_INTERVAL=30
NODE_TIMEZONE=America/Toronto
ENVEOF
    ok ".env"

    # Download files from hub
    API_BASE="$HUB_URL/tools/department-hq/api/nodes"
    for file in docker-compose.node.yml node_sync.py node_api.py Dockerfile.node; do
        outname="$file"
        [ "$file" = "docker-compose.node.yml" ] && outname="docker-compose.yml"
        curl -fsSL "$API_BASE/$file" -o "$INSTALL_DIR/$outname"
        ok "$outname"
    done

    mkdir -p "$INSTALL_DIR/migrations"
    curl -fsSL "$API_BASE/migrations/001_node_schema.sql" \
        -o "$INSTALL_DIR/migrations/001_node_schema.sql"
    curl -fsSL "$API_BASE/migrations/002_knowledge_projects.sql" \
        -o "$INSTALL_DIR/migrations/002_knowledge_projects.sql"
    ok "migrations"

    # Strip GPU config if no NVIDIA GPU
    if [ "$GPU_AVAILABLE" = "false" ]; then
        info "Patching docker-compose.yml for CPU-only mode..."
        sed -i '/deploy:/,/capabilities: \[gpu\]/d' "$INSTALL_DIR/docker-compose.yml"
        sed -i '/NVIDIA_VISIBLE_DEVICES/d' "$INSTALL_DIR/docker-compose.yml"
        ok "GPU config removed for CPU-only"
    fi

    # Handle ComfyUI
    if [ "$GPU_AVAILABLE" = "true" ] && [ "$DISK_FREE_GB" -ge 50 ]; then
        ok "ComfyUI enabled (GPU + ${DISK_FREE_GB}GB free)"
    else
        info "Removing ComfyUI service (GPU: $GPU_AVAILABLE, Free disk: ${DISK_FREE_GB}GB)"
        sed -i '/^  comfyui:/,/^  [a-z]/{ /^  comfyui:/d; /^  [a-z]/!d; }' \
            "$INSTALL_DIR/docker-compose.yml"
        sed -i '/comfyui_data:/d' "$INSTALL_DIR/docker-compose.yml"
        ok "ComfyUI removed"
    fi

    # ── Step 6: Build & Start ────────────────────────────────────────────────
    CURRENT_STEP=6
    step "6" "Building containers..."

    cd "$INSTALL_DIR"
    docker compose build --no-cache
    ok "Build complete"

    CONTAINER_COUNT=4
    if [ "$GPU_AVAILABLE" = "true" ] && [ "$DISK_FREE_GB" -ge 50 ]; then
        CONTAINER_COUNT=5
    fi
    info "Starting ${CONTAINER_COUNT}-container stack..."
    docker compose up -d
    ok "Containers started"

    # ── Step 7: Wait for Approval ────────────────────────────────────────────
    CURRENT_STEP=7
    if [ "$UPGRADE_MODE" = "true" ]; then
        step "7" "Approval (skipped — upgrade mode)"
        ok "Node already approved"
    else
        step "7" "Waiting for admin approval..."
        info "Node registered as PENDING — an admin must approve in DHQ Fleet"
        info "Hub: $HUB_URL/tools/department-hq#fleet"

        APPROVED=false
        SPIN=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
        i=0
        while [ "$APPROVED" = "false" ]; do
            printf "\r      ${BLUE}[${SPIN[$((i % 10))]}]${NC}   Waiting for approval...  "
            STATUS=$(curl -s "$HUB_URL/tools/department-hq/api/nodes/$NODE_ID/status" \
                -H "X-Node-API-Key: $API_KEY" 2>/dev/null | jq -r '.status // "pending"' 2>/dev/null)
            if [ "$STATUS" = "online" ] || [ "$STATUS" = "approved" ]; then
                APPROVED=true
            fi
            i=$((i + 1))
            sleep 10
        done
        echo ""
        ok "Node approved! Models are being pushed to your node..."
    fi

    # ── Step 8: Verify & Summary ─────────────────────────────────────────────
    CURRENT_STEP=8
    step "8" "Verifying..."

    sleep 5
    docker compose ps

    echo ""
    echo -e "  ${GREEN}${BOLD}╔═══════════════════════════════════════╗${NC}"
    echo -e "  ${GREEN}${BOLD}║  A.R.C.H.I.E. Node Setup Complete!   ║${NC}"
    echo -e "  ${GREEN}${BOLD}╚═══════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Node ID:${NC}     $NODE_ID"
    echo -e "  ${BOLD}Hub URL:${NC}     $HUB_URL"
    echo -e "  ${BOLD}Ollama:${NC}      http://localhost:11434"
    echo -e "  ${BOLD}Node API:${NC}    http://localhost:3001"
    echo -e "  ${BOLD}GPU:${NC}         $([ "$GPU_AVAILABLE" = "true" ] && echo "$GPU_MODEL" || echo "CPU only")"
    echo -e "  ${BOLD}ComfyUI:${NC}     $([ "$GPU_AVAILABLE" = "true" ] && [ "$DISK_FREE_GB" -ge 50 ] && echo "http://localhost:8188" || echo "Not enabled")"
    echo ""
    echo -e "  ${CYAN}Management commands:${NC}"
    echo "    cd $INSTALL_DIR && docker compose ps"
    echo "    cd $INSTALL_DIR && docker compose logs -f"
    echo "    cd $INSTALL_DIR && docker compose down"
    echo "    cd $INSTALL_DIR && docker compose up -d"
    echo ""
}

main "$@"
