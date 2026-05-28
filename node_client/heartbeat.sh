#!/bin/bash
# =============================================================================
# A.R.C.H.I.E. Node Client - Linux Heartbeat Service
# Version: 1.0.0
# Sends periodic heartbeats with system metrics to the ARCHIE platform
# =============================================================================

CLIENT_VERSION="1.1.0"
CONFIG_PATH="/etc/archie-node/config.json"
LOG_PATH="/var/log/archie-node/heartbeat.log"
MAX_LOG_LINES=1000

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
log_msg() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    local entry="[$timestamp] [$level] $message"
    echo "$entry"

    # Ensure log directory exists
    local log_dir
    log_dir=$(dirname "$LOG_PATH")
    mkdir -p "$log_dir" 2>/dev/null

    # Append to log
    echo "$entry" >> "$LOG_PATH" 2>/dev/null

    # Trim log to last MAX_LOG_LINES
    if [ -f "$LOG_PATH" ]; then
        local line_count
        line_count=$(wc -l < "$LOG_PATH" 2>/dev/null || echo 0)
        if [ "$line_count" -gt "$MAX_LOG_LINES" ]; then
            tail -n "$MAX_LOG_LINES" "$LOG_PATH" > "${LOG_PATH}.tmp" 2>/dev/null && mv "${LOG_PATH}.tmp" "$LOG_PATH" 2>/dev/null
        fi
    fi
}

# -----------------------------------------------------------------------------
# Load Configuration
# -----------------------------------------------------------------------------
load_config() {
    if [ ! -f "$CONFIG_PATH" ]; then
        log_msg "ERROR" "Config file not found at $CONFIG_PATH"
        log_msg "ERROR" "Copy config.example.json to $CONFIG_PATH and fill in your values."
        exit 1
    fi
    if ! command -v jq &>/dev/null; then
        log_msg "ERROR" "jq is required but not installed. Install with: sudo apt install jq"
        exit 1
    fi
    NODE_ID=$(jq -r '.node_id' "$CONFIG_PATH")
    API_KEY=$(jq -r '.api_key' "$CONFIG_PATH")
    SERVER_URL=$(jq -r '.server_url' "$CONFIG_PATH")
    HEARTBEAT_INTERVAL=$(jq -r '.heartbeat_interval // 30' "$CONFIG_PATH")
    OLLAMA_PORT=$(jq -r '.ollama_port // 11434' "$CONFIG_PATH")

    if [ -z "$NODE_ID" ] || [ "$NODE_ID" = "null" ] || \
       [ -z "$API_KEY" ] || [ "$API_KEY" = "null" ] || \
       [ -z "$SERVER_URL" ] || [ "$SERVER_URL" = "null" ]; then
        log_msg "ERROR" "Config missing required fields: node_id, api_key, server_url"
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Collect CPU Usage (from /proc/stat, two samples 1s apart)
# -----------------------------------------------------------------------------
get_cpu_usage() {
    local cpu1 cpu2 idle1 idle2 total1 total2
    read -r _ user1 nice1 system1 idle1 iowait1 irq1 softirq1 _ < /proc/stat
    total1=$((user1 + nice1 + system1 + idle1 + iowait1 + irq1 + softirq1))
    sleep 1
    read -r _ user2 nice2 system2 idle2 iowait2 irq2 softirq2 _ < /proc/stat
    total2=$((user2 + nice2 + system2 + idle2 + iowait2 + irq2 + softirq2))

    local total_diff=$((total2 - total1))
    local idle_diff=$((idle2 - idle1))
    if [ "$total_diff" -gt 0 ]; then
        echo $(( (total_diff - idle_diff) * 100 / total_diff ))
    else
        echo 0
    fi
}

# -----------------------------------------------------------------------------
# Collect Memory Usage
# -----------------------------------------------------------------------------
get_memory_usage() {
    if command -v free &>/dev/null; then
        free | awk '/^Mem:/ { printf "%.1f", ($3/$2)*100 }'
    else
        echo 0
    fi
}

# -----------------------------------------------------------------------------
# Collect GPU Usage (NVIDIA only)
# -----------------------------------------------------------------------------
get_gpu_usage() {
    if command -v nvidia-smi &>/dev/null; then
        local gpu_val
        gpu_val=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d '[:space:]')
        if [ -n "$gpu_val" ]; then
            echo "$gpu_val"
            return
        fi
    fi
    echo "null"
}

# -----------------------------------------------------------------------------
# Hardware Detection (sent once, updated via COALESCE on hub)
# -----------------------------------------------------------------------------
get_cpu_model() {
    if [ -f /proc/cpuinfo ]; then
        grep -m1 "model name" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ //' || echo "null"
    else
        echo "null"
    fi
}

get_cpu_core_count() {
    nproc 2>/dev/null || echo "null"
}

get_ram_total_gb() {
    if [ -f /proc/meminfo ]; then
        local kb
        kb=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}')
        if [ -n "$kb" ]; then
            echo "scale=1; $kb / 1048576" | bc 2>/dev/null || echo "null"
            return
        fi
    fi
    echo "null"
}

get_gpu_model_name() {
    if command -v nvidia-smi &>/dev/null; then
        nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | tr -d '\n' || echo "null"
    else
        echo "null"
    fi
}

get_gpu_vram_gb() {
    if command -v nvidia-smi &>/dev/null; then
        local mb
        mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d '[:space:]')
        if [ -n "$mb" ]; then
            echo "scale=1; $mb / 1024" | bc 2>/dev/null || echo "null"
            return
        fi
    fi
    echo "null"
}

# -----------------------------------------------------------------------------
# Check Ollama Status and Models
# -----------------------------------------------------------------------------
get_ollama_status() {
    local response
    response=$(curl -s --max-time 5 "http://localhost:${OLLAMA_PORT}/api/tags" 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$response" ]; then
        local online="true"
        local models
        models=$(echo "$response" | jq -c '[.models[]? | {name: .name, size: .size}]' 2>/dev/null || echo "[]")
        echo "{\"online\":$online,\"models\":$models}"
    else
        echo '{"online":false,"models":[]}'
    fi
}

# -----------------------------------------------------------------------------
# Get System Uptime (seconds)
# -----------------------------------------------------------------------------
get_uptime_seconds() {
    awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || echo 0
}

# -----------------------------------------------------------------------------
# Send Heartbeat (captures response for update signals)
# -----------------------------------------------------------------------------
HEARTBEAT_RESPONSE=""
send_heartbeat() {
    local payload="$1"
    local url="${SERVER_URL}/tools/department-hq/api/nodes/${NODE_ID}/heartbeat"
    local tmpfile
    tmpfile=$(mktemp)

    local http_code
    http_code=$(curl -s -o "$tmpfile" -w "%{http_code}" \
        --max-time 15 \
        -X POST "$url" \
        -H "X-Node-API-Key: ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    HEARTBEAT_RESPONSE=$(cat "$tmpfile" 2>/dev/null)
    rm -f "$tmpfile"

    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        return 0
    else
        log_msg "ERROR" "Heartbeat POST failed with HTTP $http_code"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Self-Update: download new package, extract, restart
# -----------------------------------------------------------------------------
self_update() {
    local update_url="$1"
    local full_url="${SERVER_URL}${update_url}"
    local update_dir="/tmp/archie-node-update"
    local install_dir="/opt/archie-node"

    log_msg "INFO" "=== SELF-UPDATE STARTING ==="
    log_msg "INFO" "Downloading update from: $full_url"

    rm -rf "$update_dir"
    mkdir -p "$update_dir"

    # Download the package
    local http_code
    http_code=$(curl -s -o "$update_dir/update.tar.gz" -w "%{http_code}" \
        --max-time 120 \
        -H "X-Node-API-Key: ${API_KEY}" \
        "$full_url" 2>/dev/null)

    if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 300 ]; then
        log_msg "ERROR" "Update download failed with HTTP $http_code"
        rm -rf "$update_dir"
        return 1
    fi

    # Verify it's a valid archive
    if ! tar -tzf "$update_dir/update.tar.gz" &>/dev/null; then
        log_msg "ERROR" "Downloaded file is not a valid tar.gz"
        rm -rf "$update_dir"
        return 1
    fi

    log_msg "INFO" "Download complete, extracting..."
    tar -xzf "$update_dir/update.tar.gz" -C "$update_dir" 2>/dev/null

    # Look for the new heartbeat script
    local new_heartbeat
    new_heartbeat=$(find "$update_dir" -name "heartbeat.sh" -type f | head -1)

    if [ -z "$new_heartbeat" ]; then
        log_msg "ERROR" "No heartbeat.sh found in update package"
        rm -rf "$update_dir"
        return 1
    fi

    # Backup current script
    local self_path
    self_path=$(readlink -f "$0")
    cp "$self_path" "${self_path}.bak" 2>/dev/null
    log_msg "INFO" "Backed up current script to ${self_path}.bak"

    # Replace with new version
    cp "$new_heartbeat" "$self_path"
    chmod +x "$self_path"
    log_msg "INFO" "Updated heartbeat script in place"

    # Copy any other updated files to install dir
    if [ -d "$install_dir" ]; then
        find "$update_dir" -type f ! -name "update.tar.gz" -exec cp {} "$install_dir/" \; 2>/dev/null
        log_msg "INFO" "Copied updated files to $install_dir"
    fi

    rm -rf "$update_dir"
    log_msg "INFO" "=== SELF-UPDATE COMPLETE — RESTARTING ==="

    # Re-exec self to pick up new code
    exec "$self_path"
}

# =============================================================================
# Main
# =============================================================================
log_msg "INFO" "A.R.C.H.I.E. Node Client v${CLIENT_VERSION} starting..."
load_config
log_msg "INFO" "Node ID: ${NODE_ID}"
log_msg "INFO" "Server:  ${SERVER_URL}"
log_msg "INFO" "Interval: ${HEARTBEAT_INTERVAL}s"

while true; do
    # Collect metrics
    cpu_usage=$(get_cpu_usage)
    mem_usage=$(get_memory_usage)
    gpu_usage=$(get_gpu_usage)
    ollama_json=$(get_ollama_status)
    ollama_online=$(echo "$ollama_json" | jq -r '.online')
    ollama_models=$(echo "$ollama_json" | jq -c '.models')
    uptime_secs=$(get_uptime_seconds)
    host_name=$(hostname)

    # Hardware specs (auto-detected)
    hw_cpu_model=$(get_cpu_model)
    hw_cpu_cores=$(get_cpu_core_count)
    hw_ram_gb=$(get_ram_total_gb)
    hw_gpu_model=$(get_gpu_model_name)
    hw_gpu_vram_gb=$(get_gpu_vram_gb)

    # OS detection — works from inside Docker container
    # WSL2/Docker Desktop on Windows exposes "microsoft" in /proc/version
    if grep -qi "microsoft\|wsl" /proc/version 2>/dev/null; then
        hw_os_type="windows"
        hw_os_name="Windows (Docker Desktop)"
    elif [ -f /etc/os-release ]; then
        hw_os_type=$(grep '^ID=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')
        hw_os_name=$(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '"')
        [ -z "$hw_os_type" ] && hw_os_type="linux"
        [ -z "$hw_os_name" ] && hw_os_name="Linux"
    else
        hw_os_type="linux"
        hw_os_name="Linux"
    fi

    # Build JSON payload
    payload=$(jq -n \
        --arg status "online" \
        --argjson cpu "$cpu_usage" \
        --arg mem "$mem_usage" \
        --arg gpu "$gpu_usage" \
        --argjson ollama_on "$ollama_online" \
        --argjson ollama_m "$ollama_models" \
        --arg ver "$CLIENT_VERSION" \
        --argjson uptime "$uptime_secs" \
        --arg hname "$host_name" \
        --arg hw_cpu_model "$hw_cpu_model" \
        --arg hw_cpu_cores "$hw_cpu_cores" \
        --arg hw_ram_gb "$hw_ram_gb" \
        --arg hw_gpu_model "$hw_gpu_model" \
        --arg hw_gpu_vram_gb "$hw_gpu_vram_gb" \
        --arg hw_os_type "$hw_os_type" \
        --arg hw_os_name "$hw_os_name" \
        '{
            status: $status,
            current_load: ($cpu | tonumber),
            cpu_usage: ($cpu | tonumber),
            memory_usage: ($mem | tonumber),
            gpu_usage: (if $gpu == "null" then 0 else ($gpu | tonumber) end),
            ollama_online: $ollama_on,
            ollama_models: $ollama_m,
            client_version: $ver,
            cpu_model: (if $hw_cpu_model == "null" then null else $hw_cpu_model end),
            cpu_cores: (if $hw_cpu_cores == "null" then null else ($hw_cpu_cores | tonumber) end),
            ram_gb: (if $hw_ram_gb == "null" then null else ($hw_ram_gb | tonumber) end),
            gpu_model: (if $hw_gpu_model == "null" then null else $hw_gpu_model end),
            gpu_vram_gb: (if $hw_gpu_vram_gb == "null" then null else ($hw_gpu_vram_gb | tonumber) end),
            os_type: $hw_os_type,
            os_name: $hw_os_name,
            details: {
                uptime: $uptime,
                hostname: $hname
            }
        }')

    # Send heartbeat
    if send_heartbeat "$payload"; then
        model_count=$(echo "$ollama_models" | jq 'length' 2>/dev/null || echo 0)
        gpu_str="N/A"
        [ "$gpu_usage" != "null" ] && gpu_str="${gpu_usage}%"
        log_msg "INFO" "Heartbeat sent - CPU: ${cpu_usage}% | RAM: ${mem_usage}% | GPU: ${gpu_str} | Ollama: ${ollama_online} (${model_count} models)"

        # Check if server is requesting a self-update
        if [ -n "$HEARTBEAT_RESPONSE" ]; then
            local update_flag
            update_flag=$(echo "$HEARTBEAT_RESPONSE" | jq -r '.update_available // false' 2>/dev/null)
            if [ "$update_flag" = "true" ]; then
                local update_url
                update_url=$(echo "$HEARTBEAT_RESPONSE" | jq -r '.update_url // empty' 2>/dev/null)
                local latest_ver
                latest_ver=$(echo "$HEARTBEAT_RESPONSE" | jq -r '.latest_version // "unknown"' 2>/dev/null)
                log_msg "INFO" "Server requested update to v${latest_ver}"
                if [ -n "$update_url" ]; then
                    self_update "$update_url"
                    # If self_update returns (failed), continue running
                    log_msg "WARN" "Self-update failed, continuing with current version"
                fi
            fi
        fi
    else
        log_msg "WARN" "Heartbeat failed - will retry in ${HEARTBEAT_INTERVAL}s"
    fi

    sleep "$HEARTBEAT_INTERVAL"
done
