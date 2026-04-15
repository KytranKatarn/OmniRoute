#!/bin/bash
# A.R.C.H.I.E. Node — Linux Installer
# by Kytran Empowerment
#
# Usage: curl -fsSL https://raw.githubusercontent.com/KytranKatarn/archie-platform/main/node_client/install.sh | bash
#   or: ./install.sh

set -e

INSTALL_DIR="$HOME/archie-node"
COMPOSE_URL="https://raw.githubusercontent.com/KytranKatarn/archie-platform/main/node_client/docker-compose.node.yml"

echo ""
echo "  =========================================="
echo "   A.R.C.H.I.E. Node — by Kytran Empowerment"
echo "  =========================================="
echo ""

# Check/Install Docker
if ! command -v docker &>/dev/null; then
    echo "[1/5] Docker not found. Installing..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker "$USER"
    echo "[OK] Docker installed."
else
    echo "[1/5] Docker found: $(docker --version)"
fi

if ! docker compose version &>/dev/null; then
    echo "[!!] Docker Compose not found."
    exit 1
fi

# Check NVIDIA
if command -v nvidia-smi &>/dev/null; then
    GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    echo "[OK] GPU detected: $GPU"
    if ! dpkg -l nvidia-container-toolkit &>/dev/null 2>&1; then
        echo "     Installing NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
        sudo nvidia-ctk runtime configure --runtime=docker
        sudo systemctl restart docker
    fi
else
    echo "[~] No NVIDIA GPU — CPU-only mode."
fi

# Create directory and download compose
echo "[2/5] Setting up $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

echo "[3/5] Downloading docker-compose.yml..."
curl -fsSL "$COMPOSE_URL" -o "$INSTALL_DIR/docker-compose.yml"

# Register with hub
echo "[4/5] Node Registration"
if [ -f "$INSTALL_DIR/.env" ]; then
    echo "     Using existing .env config."
else
    read -p "     Hub URL (e.g. https://platform.kytranempowerment.com): " HUB_URL
    HUB_URL="${HUB_URL%/}"
    HOSTNAME_VAL=$(hostname)
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)
    RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
    GPU_MODEL=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "")
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    GPU_VRAM_GB=$(echo "scale=1; ${GPU_VRAM:-0}/1024" | bc 2>/dev/null || echo "0")
    HAS_GPU=$([ -n "$GPU_MODEL" ] && echo true || echo false)

    RESULT=$(curl -fsSL -X POST "$HUB_URL/tools/starbase/api/nodes/register" \
        -H "Content-Type: application/json" \
        -d "{\"node_name\":\"$HOSTNAME_VAL\",\"hostname\":\"$LOCAL_IP\",\"port\":11434,\"gpu_available\":$HAS_GPU,\"gpu_model\":\"$GPU_MODEL\",\"gpu_vram_gb\":$GPU_VRAM_GB,\"cpu_model\":\"$CPU_MODEL\",\"ram_gb\":$RAM_GB,\"os_info\":\"$(uname -srm)\",\"client_version\":\"4.0.0\",\"tags\":[\"linux\"]}")

    NODE_ID=$(echo "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('node_id',''))" 2>/dev/null)
    API_KEY=$(echo "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null)

    if [ -z "$NODE_ID" ]; then
        echo "     [!!] Auto-registration failed."
        read -p "     NODE_ID: " NODE_ID
        read -p "     HUB_API_KEY: " API_KEY
    else
        echo "     [OK] Registered as: $NODE_ID"
    fi

    cat > "$INSTALL_DIR/.env" << EOF
NODE_ID=$NODE_ID
NODE_NAME=$HOSTNAME_VAL
HUB_URL=$HUB_URL
HUB_API_KEY=$API_KEY
DB_PASSWORD=archie_node_default
OLLAMA_PORT=11434
NODE_API_PORT=3001
COMFYUI_PORT=8188
EOF
fi

# Write helper scripts
for cmd in start stop update; do
    cat > "$INSTALL_DIR/$cmd.sh" << SEOF
#!/bin/bash
cd "\$(dirname "\$0")"
case "$cmd" in
    start)  echo "Starting A.R.C.H.I.E. Node..."; docker compose up -d;;
    stop)   echo "Stopping A.R.C.H.I.E. Node..."; docker compose down;;
    update) echo "Updating A.R.C.H.I.E. Node..."; docker compose pull && docker compose up -d;;
esac
SEOF
    chmod +x "$INSTALL_DIR/$cmd.sh"
done

# Start
echo "[5/5] Starting A.R.C.H.I.E. Node..."
cd "$INSTALL_DIR"
docker compose up -d

echo ""
echo "  =========================================="
echo "   INSTALLATION COMPLETE"
echo "  =========================================="
echo "  Dir:      $INSTALL_DIR"
echo "  Commands: ./start.sh  ./stop.sh  ./update.sh"
echo "  Node appears in fleet within 2 minutes."
echo ""
