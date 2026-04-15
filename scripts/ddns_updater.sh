#!/usr/bin/env bash
# DDNS Updater for ARCHIE Platform
# Updates Hostinger DNS A records when public IP changes
# Subdomains: archie, adguard, nagios, plex, n8n, voice, store, mediahub, consciousness, bridge, brainstorm, server, business @ kytranempowerment.com

set -euo pipefail

DOMAIN="kytranempowerment.com"
SUBDOMAINS=("archie" "platform" "adguard" "nagios" "plex" "n8n" "voice" "store" "mediahub" "consciousness" "bridge" "brainstorm" "server" "business" "proxy" "mail" "mail-admin" "webmail" "mesh" "creed")
IP_FILE="/mnt/archie_brain/scripts/.ddns_last_ip"
LOG_FILE="/mnt/archie_brain/scripts/ddns_updater.log"
ENV_FILE="/mnt/archie_brain/.env"
API_BASE="https://developers.hostinger.com"
TTL=300

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

# Resolve API key
if [ -z "${HOSTINGER_API_KEY:-}" ]; then
    if [ -f "$ENV_FILE" ]; then
        HOSTINGER_API_KEY=$(grep -E '^HOSTINGER_API_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    fi
fi

if [ -z "${HOSTINGER_API_KEY:-}" ]; then
    log "ERROR: HOSTINGER_API_KEY not set and not found in $ENV_FILE"
    exit 1
fi

# Get current public IP
CURRENT_IP=$(curl -s --max-time 10 https://api.ipify.org)

if [ -z "$CURRENT_IP" ]; then
    log "ERROR: Failed to retrieve public IP from api.ipify.org"
    exit 1
fi

# Validate IP format
if ! [[ "$CURRENT_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    log "ERROR: Invalid IP format received: $CURRENT_IP"
    exit 1
fi

# Compare against last known IP
LAST_IP=""
if [ -f "$IP_FILE" ]; then
    LAST_IP=$(cat "$IP_FILE" 2>/dev/null || true)
fi

if [ "$CURRENT_IP" = "$LAST_IP" ]; then
    touch "$IP_FILE"  # Update mtime so health checks see we're running
    log "No change — IP is still $CURRENT_IP"
    exit 0
fi

log "IP changed: ${LAST_IP:-<none>} -> $CURRENT_IP"

# Build zone array in Hostinger API format
ZONE="["
for i in "${!SUBDOMAINS[@]}"; do
    [ "$i" -gt 0 ] && ZONE+=","
    ZONE+="{\"name\":\"${SUBDOMAINS[$i]}\",\"type\":\"A\",\"ttl\":$TTL,\"records\":[{\"content\":\"$CURRENT_IP\"}]}"
done
ZONE+="]"

PAYLOAD="{\"zone\":$ZONE,\"overwrite\":true}"

# Update DNS via Hostinger API
HTTP_CODE=$(curl -s -o /tmp/ddns_response.txt -w '%{http_code}' \
    --max-time 30 \
    -X PUT \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $HOSTINGER_API_KEY" \
    -d "$PAYLOAD" \
    "$API_BASE/api/dns/v1/zones/$DOMAIN")

RESPONSE=$(cat /tmp/ddns_response.txt 2>/dev/null || echo "<no response body>")
rm -f /tmp/ddns_response.txt

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
    echo "$CURRENT_IP" > "$IP_FILE"
    log "SUCCESS: Updated ${SUBDOMAINS[*]} -> $CURRENT_IP (HTTP $HTTP_CODE)"
else
    log "ERROR: Hostinger API returned HTTP $HTTP_CODE — $RESPONSE"
    exit 1
fi

# Cron entry (run every 5 minutes):
# */5 * * * * /mnt/archie_brain/scripts/ddns_updater.sh
