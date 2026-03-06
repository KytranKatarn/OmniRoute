#!/bin/bash
# ============================================================
# configure_ollama.sh — Auto-configure Ollama based on hardware
# ============================================================
# Run on any machine to set optimal Ollama resource limits.
# Reads actual CPU/RAM and applies percentage-based allocation.
#
# Usage: sudo ./configure_ollama.sh [--cpu-pct 70] [--ram-reserve 16]
#
# Defaults:
#   CPU: 70% of cores for Ollama inference
#   RAM reserve: 16GB kept free for system/Docker (rest available for models)
#   Max loaded models: auto-calculated from available RAM
#   Keep alive: 24h
#   Parallel: 4 concurrent requests
# ============================================================

set -euo pipefail

# ── Defaults (override with flags) ──
CPU_PCT=${CPU_PCT:-70}
RAM_RESERVE_GB=${RAM_RESERVE_GB:-16}
KEEP_ALIVE=${KEEP_ALIVE:-24h}
NUM_PARALLEL=${NUM_PARALLEL:-4}
OLLAMA_MODELS_PATH=${OLLAMA_MODELS_PATH:-/mnt/data2/ollama/models}

# ── Parse arguments ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cpu-pct) CPU_PCT="$2"; shift 2 ;;
        --ram-reserve) RAM_RESERVE_GB="$2"; shift 2 ;;
        --keep-alive) KEEP_ALIVE="$2"; shift 2 ;;
        --parallel) NUM_PARALLEL="$2"; shift 2 ;;
        --models-path) OLLAMA_MODELS_PATH="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Detect hardware ──
TOTAL_CORES=$(nproc)
TOTAL_RAM_GB=$(python3 -c "import psutil; print(int(psutil.virtual_memory().total / (1024**3)))" 2>/dev/null || free -g | awk '/^Mem:/{print $2}')

# ── Calculate allocations ──
OLLAMA_CORES=$(python3 -c "import math; print(max(2, math.floor($TOTAL_CORES * $CPU_PCT / 100)))")
CPU_QUOTA=$(( OLLAMA_CORES * 100 ))
AVAILABLE_FOR_MODELS=$(( TOTAL_RAM_GB - RAM_RESERVE_GB ))
# Estimate: average model ~5GB, leave some headroom
MAX_LOADED=$(python3 -c "print(max(3, min(20, $AVAILABLE_FOR_MODELS // 5)))")

echo "============================================================"
echo "  OLLAMA AUTO-CONFIGURATION"
echo "============================================================"
echo "  Hardware detected:"
echo "    CPU cores:  $TOTAL_CORES"
echo "    RAM total:  ${TOTAL_RAM_GB}GB"
echo ""
echo "  Allocation (${CPU_PCT}% CPU, ${RAM_RESERVE_GB}GB RAM reserved):"
echo "    OLLAMA_NUM_CPU:          $OLLAMA_CORES / $TOTAL_CORES cores"
echo "    CPUQuota:                ${CPU_QUOTA}%"
echo "    RAM for models:          ~${AVAILABLE_FOR_MODELS}GB"
echo "    OLLAMA_MAX_LOADED_MODELS: $MAX_LOADED"
echo "    OLLAMA_KEEP_ALIVE:       $KEEP_ALIVE"
echo "    OLLAMA_NUM_PARALLEL:     $NUM_PARALLEL"
echo "============================================================"

# ── Check for existing API key ──
OLLAMA_API_KEY=""
OVERRIDE_FILE="/etc/systemd/system/ollama.service.d/override.conf"
if [ -f "$OVERRIDE_FILE" ]; then
    EXISTING_KEY=$(grep 'OLLAMA_API_KEY' "$OVERRIDE_FILE" | sed 's/.*OLLAMA_API_KEY=//' | tr -d '"' || true)
    if [ -n "$EXISTING_KEY" ]; then
        OLLAMA_API_KEY="$EXISTING_KEY"
    fi
fi

# ── Write systemd override ──
mkdir -p /etc/systemd/system/ollama.service.d

cat > "$OVERRIDE_FILE" << EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MODELS=$OLLAMA_MODELS_PATH"
${OLLAMA_API_KEY:+Environment="OLLAMA_API_KEY=$OLLAMA_API_KEY"}
Environment="OLLAMA_KEEP_ALIVE=$KEEP_ALIVE"
Environment="OLLAMA_NUM_PARALLEL=$NUM_PARALLEL"
Environment="OLLAMA_MAX_LOADED_MODELS=$MAX_LOADED"
Environment="OLLAMA_NUM_CPU=$OLLAMA_CORES"
CPUQuota=${CPU_QUOTA}%
EOF

echo ""
echo "  Written to: $OVERRIDE_FILE"

# ── Apply ──
systemctl daemon-reload
echo "  systemd reloaded"
echo ""
echo "  Run 'sudo systemctl restart ollama' to apply."
echo "  (This will unload all models — they re-warm on platform startup)"
echo "============================================================"
