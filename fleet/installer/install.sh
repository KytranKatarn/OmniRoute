#!/usr/bin/env bash
# A.R.C.H.I.E. Fleet Installer — bootstraps KSO on any Linux machine
# Usage: curl -fsSL https://raw.githubusercontent.com/KytranKatarn/archie-fleet/main/install.sh | bash
#   or:  ./install.sh --type outpost --token <token>
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────
FLEET_VERSION="1.0.0"
HUB_URL="${ARCHIE_HUB_URL:-http://100.64.0.4:3000}"
MESH_SERVER="${ARCHIE_MESH_SERVER:-https://mesh.kytranempowerment.com}"
KSO_IMAGE="ghcr.io/kytrankatarn/kytran-system-operations:latest"
INSTALL_DIR="/opt/archie-fleet"
APPS_DIR="${INSTALL_DIR}/apps"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${CYAN}[ARCHIE]${NC} $1"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $1"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
err()  { echo -e "${RED}[ERROR ]${NC} $1"; }

# ── Parse Args ───────────────────────────────────────────────────────
NODE_TYPE=""
TOKEN=""
FORCE=false
UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type)      NODE_TYPE="$2"; shift 2 ;;
        --token)     TOKEN="$2"; shift 2 ;;
        --hub)       HUB_URL="$2"; shift 2 ;;
        --force)     FORCE=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        *)           err "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Uninstall ────────────────────────────────────────────────────────
if [ "$UNINSTALL" = true ]; then
    log "Uninstalling A.R.C.H.I.E. Fleet..."
    if [ -d "$INSTALL_DIR" ]; then
        for app_dir in "$APPS_DIR"/*/; do
            [ -f "${app_dir}docker-compose.yml" ] && docker compose -f "${app_dir}docker-compose.yml" down 2>/dev/null || true
        done
        [ -f "$INSTALL_DIR/docker-compose.yml" ] && docker compose -f "$INSTALL_DIR/docker-compose.yml" down 2>/dev/null || true
        rm -rf "$INSTALL_DIR"
        ok "Fleet removed from $INSTALL_DIR"
    else
        warn "No fleet installation found at $INSTALL_DIR"
    fi
    exit 0
fi

# ── Banner ───────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     A.R.C.H.I.E. Fleet Installer v${FLEET_VERSION}          ║${NC}"
echo -e "${CYAN}║     Autonomous Fleet Node Bootstrap              ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Detect OS ────────────────────────────────────────────────
log "Step 1/5: Detecting OS..."

if [ ! -f /etc/os-release ]; then
    err "Cannot detect OS. /etc/os-release not found."
    exit 1
fi

# shellcheck source=/dev/null
source /etc/os-release
ARCH=$(uname -m)

if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
    err "Unsupported OS: $ID. Requires Ubuntu 22.04+ or Debian 12+."
    exit 1
fi

if [[ "$ID" == "ubuntu" ]] && [[ "${VERSION_ID%%.*}" -lt 22 ]]; then
    err "Ubuntu $VERSION_ID is too old. Requires 22.04+."
    exit 1
fi

if [[ "$ID" == "debian" ]] && [[ "${VERSION_ID%%.*}" -lt 12 ]]; then
    err "Debian $VERSION_ID is too old. Requires 12+."
    exit 1
fi

ok "OS: $PRETTY_NAME ($ARCH)"

# ── Step 2: Install Dependencies ─────────────────────────────────────
log "Step 2/5: Installing dependencies..."

if command -v docker &>/dev/null && [ "$FORCE" = false ]; then
    ok "Docker already installed: $(docker --version)"
else
    log "Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$ID/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$ID $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    ok "Docker installed: $(docker --version)"
fi

if command -v tailscale &>/dev/null && [ "$FORCE" = false ]; then
    ok "Tailscale already installed"
else
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    ok "Tailscale installed"
fi

if ! command -v jq &>/dev/null; then
    apt-get install -y -qq jq
fi
ok "Dependencies ready"

# ── Step 3: Node Type ────────────────────────────────────────────────
log "Step 3/5: Configuring node type..."

if [ -z "$NODE_TYPE" ]; then
    echo ""
    echo "  Select node type:"
    echo "    1) outpost   — Lightweight VPS (1 CPU, 2GB RAM min)"
    echo "    2) starship  — Full compute node (4+ CPU, 16GB RAM, GPU recommended)"
    echo ""
    read -rp "  Enter choice [1/2]: " choice
    case "$choice" in
        1|outpost)  NODE_TYPE="outpost" ;;
        2|starship) NODE_TYPE="starship" ;;
        *)          err "Invalid choice"; exit 1 ;;
    esac
fi

if [[ "$NODE_TYPE" != "outpost" && "$NODE_TYPE" != "starship" ]]; then
    err "Invalid node type: $NODE_TYPE. Must be outpost or starship."
    exit 1
fi

ok "Node type: $NODE_TYPE"

# ── Step 4: Fleet Registration ────────────────────────────────────────
log "Step 4/5: Registering with fleet..."

NODE_NAME=""
read -rp "  Node name (e.g., us-east-1, home-lab): " NODE_NAME
NODE_NAME="${NODE_NAME:-unnamed-$(hostname)}"

if [ -z "$TOKEN" ]; then
    echo ""
    echo "  Registration method:"
    echo "    1) Token — paste a pre-generated registration token (instant)"
    echo "    2) Request approval — admin must approve in Starbase"
    echo ""
    read -rp "  Enter choice [1/2]: " reg_choice
    case "$reg_choice" in
        1)
            read -rp "  Paste registration token: " TOKEN
            ;;
        2)
            TOKEN=""
            ;;
        *)
            err "Invalid choice"; exit 1
            ;;
    esac
fi

REG_PAYLOAD=$(jq -n \
    --arg name "$NODE_NAME" \
    --arg type "$NODE_TYPE" \
    --arg token "$TOKEN" \
    '{name: $name, type: $type, token: (if $token == "" then null else $token end)}')

REG_RESPONSE=$(curl -sS -X POST "${HUB_URL}/starbase/api/fleet/register" \
    -H "Content-Type: application/json" \
    -d "$REG_PAYLOAD" 2>/dev/null) || {
    err "Cannot reach hub at $HUB_URL. Is the mesh connected?"
    exit 1
}

REG_SUCCESS=$(echo "$REG_RESPONSE" | jq -r '.success')
REG_STATUS=$(echo "$REG_RESPONSE" | jq -r '.status')
NODE_ID=$(echo "$REG_RESPONSE" | jq -r '.node_id')
API_KEY=$(echo "$REG_RESPONSE" | jq -r '.api_key // empty')

if [ "$REG_SUCCESS" != "true" ]; then
    REG_ERROR=$(echo "$REG_RESPONSE" | jq -r '.error')
    err "Registration failed: $REG_ERROR"
    exit 1
fi

if [ "$REG_STATUS" = "pending" ]; then
    log "Waiting for admin approval in Starbase..."
    ATTEMPTS=0
    MAX_ATTEMPTS=60
    while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
        sleep 10
        STATUS_RESP=$(curl -sS "${HUB_URL}/starbase/api/fleet/status/${NODE_ID}?need_key=true" 2>/dev/null) || continue
        STATUS=$(echo "$STATUS_RESP" | jq -r '.status')
        if [ "$STATUS" = "approved" ]; then
            API_KEY=$(echo "$STATUS_RESP" | jq -r '.api_key // empty')
            break
        elif [ "$STATUS" = "denied" ]; then
            err "Registration denied by admin."
            exit 1
        fi
        ATTEMPTS=$((ATTEMPTS + 1))
        echo -ne "\r  Waiting... ($((ATTEMPTS * 10))s / 600s)"
    done
    echo ""
    if [ "$STATUS" != "approved" ]; then
        err "Approval timed out after 10 minutes. Ask admin to approve node $NODE_ID."
        exit 1
    fi
fi

ok "Registered: $NODE_ID (status: approved)"

# ── Step 5: Join Mesh + Start KSO ────────────────────────────────────
log "Step 5/5: Starting KSO..."

TAILSCALE_STATUS=$(tailscale status --json 2>/dev/null | jq -r '.BackendState' 2>/dev/null || echo "unknown")
if [ "$TAILSCALE_STATUS" != "Running" ] || [ "$FORCE" = true ]; then
    log "Joining mesh network..."
    echo ""
    echo "  To join the mesh, you need a Headscale pre-auth key."
    echo "  Generate one on the hub: headscale preauthkeys create --user archie-fleet"
    echo ""
    read -rp "  Paste Headscale auth key (or press Enter to skip mesh): " MESH_KEY
    if [ -n "$MESH_KEY" ]; then
        tailscale up --login-server "$MESH_SERVER" --authkey "$MESH_KEY" --hostname "$NODE_NAME"
        ok "Mesh connected: $(tailscale ip -4)"
    else
        warn "Skipping mesh — KSO will connect to hub via public IP"
    fi
else
    ok "Mesh already connected: $(tailscale ip -4)"
fi

mkdir -p "$INSTALL_DIR" "$APPS_DIR"

cat > "${INSTALL_DIR}/.env" <<ENVEOF
# A.R.C.H.I.E. Fleet Node Configuration
# Generated by install.sh — $(date -u +%Y-%m-%dT%H:%M:%SZ)
NODE_ID=${NODE_ID}
NODE_TYPE=${NODE_TYPE}
NODE_NAME=${NODE_NAME}
KSM_HUB_URL=${HUB_URL}
KSM_HUB_API_KEY=${API_KEY}
KSM_NODE_TYPE=${NODE_TYPE}
KSM_APPS_DIR=/opt/archie-fleet/apps
KSM_SECRET_KEY=$(openssl rand -hex 32)
ENVEOF

cat > "${INSTALL_DIR}/docker-compose.yml" <<COMPOSEEOF
services:
  kso:
    image: ${KSO_IMAGE}
    container_name: archie_kso
    restart: unless-stopped
    ports:
      - "8085:8080"
    env_file:
      - .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - ./data:/data
      - ${APPS_DIR}:/opt/archie-fleet/apps
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.5"
COMPOSEEOF

log "Pulling KSO image..."
cd "$INSTALL_DIR"
docker compose pull
docker compose up -d

log "Waiting for KSO to start..."
for i in $(seq 1 30); do
    if curl -sS http://localhost:8085/api/health &>/dev/null; then
        break
    fi
    sleep 2
done

if curl -sS http://localhost:8085/api/health &>/dev/null; then
    ok "KSO is running at http://localhost:8085"
else
    warn "KSO may still be starting — check: docker logs archie_kso"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     A.R.C.H.I.E. Fleet Node — INSTALLED         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Node ID:   ${NODE_ID}$(printf '%*s' $((26 - ${#NODE_ID})) '')║${NC}"
echo -e "${GREEN}║  Type:      ${NODE_TYPE}$(printf '%*s' $((26 - ${#NODE_TYPE})) '')║${NC}"
echo -e "${GREEN}║  KSO:       http://localhost:8085$(printf '%*s' 5 '')║${NC}"
echo -e "${GREEN}║  Apps Dir:  /opt/archie-fleet/apps$(printf '%*s' 4 '')║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Next steps:"
echo "    1. Open KSO at http://$(hostname -I | awk '{print $1}'):8085"
echo "    2. Go to the Apps tab to browse and deploy products"
echo "    3. View this node in Starbase on the hub"
echo ""
