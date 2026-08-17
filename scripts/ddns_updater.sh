#!/usr/bin/env bash
# DDNS Updater for ARCHIE Platform
# Updates Hostinger DNS A records when public IP changes
# Subdomains: archie, adguard, nagios, plex, n8n, voice, store, mediahub, consciousness, bridge, brainstorm, server, business @ kytranempowerment.com

set -euo pipefail

DOMAIN="kytranempowerment.com"
# #5260: ONLY names that genuinely live on the hub's dynamic public IP belong
# here. `mail` is the sole one — Stalwart is hub-fronted and MX must track the
# residential lease. EVERYTHING ELSE is Beacon-fronted (2.25.170.252) or
# Citadel-fronted and must NEVER be DDNS'd:
#   - On 2026-08-14 22:10 EDT (snapshot 172469584) this script pushed ALL 21
#     names — including the PROTECTED Headscale control plane `mesh.` — to the
#     hub IP with overwrite:true. Two corrective zone updates ~17-40 min later
#     restored the Beacon set, but the run also RESURRECTED six deliberately
#     deleted records (n8n/proxy/webmail/mail-admin/brainstorm + voice) at the
#     hub IP. The hub has NO :443 listener, so mesh at the hub IP kills node
#     enrollment/key rotation (fleet.md: mesh. is PROTECTED).
SUBDOMAINS=("mail")

# Hard denylist — belt and braces against anyone re-adding a fronted name to
# SUBDOMAINS above. Mirrors adguard_service.PROTECTED_REWRITES (task #5219),
# which only guards the AdGuard/LAN path; this script talks straight to the
# Hostinger API and needs its own refusal.
PROTECTED_NAMES=("mesh" "platform" "creed" "server" "business" "mediahub" "consciousness" "bridge" "store" "terminal" "archie" "adguard" "nagios" "plex" "media" "jellyfin" "claude" "codex" "sandbox" "shop" "voice")
for sub in "${SUBDOMAINS[@]}"; do
    for prot in "${PROTECTED_NAMES[@]}"; do
        if [ "$sub" = "$prot" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') - FATAL: '$sub' is a PROTECTED (Beacon/Citadel-fronted) name and must never be DDNS'd to the hub IP (#5260). Refusing to run." >> "/mnt/archie_brain/scripts/ddns_updater.log"
            exit 1
        fi
    done
done
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
