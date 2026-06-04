#!/bin/bash
# beacon_dns_migrate.sh — point 22 hub subdomains to Beacon front-door.
#
# Before running: Beacon Caddyfile must already be deployed + caddy reloaded.
# After running: Let's Encrypt certs provision automatically (TTL 300 = ~5 min).
#
# Excluded (keep at hub 173.182.133.96): mail, mail-admin, mta-sts, n8n, voice
#
# Rollback: run hub_dns_update.sh <hub_ip> to revert all records back to hub.
# ---------------------------------------------------------------------------
set -uo pipefail

BEACON_IP="2.25.170.252"
DOMAIN="kytranempowerment.com"
UA="Mozilla/5.0"
BASE="https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN"
DRY="${DRY:-0}"

SUBDOMAINS=(
  adguard archie brainstorm bridge business claude consciousness
  creed jellyfin media mediahub mesh nagios platform plex
  proxy sandbox server shop store terminal webmail
)

TOKEN="${HOSTINGER_API_KEY:-}"
if [ -z "$TOKEN" ]; then
  for ENVF in "$(dirname "$0")/../.env" /mnt/archie_brain/.env; do
    [ -f "$ENVF" ] || continue
    TOKEN=$(grep -E '^HOSTINGER_API_KEY=' "$ENVF" | head -1 | cut -d= -f2- | tr -d '"'\'' ')
    [ -n "$TOKEN" ] && break
  done
fi
[ -n "$TOKEN" ] || { echo "ABORT: no HOSTINGER_API_KEY"; exit 1; }

auth=(-A "$UA" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")

echo "Migrating ${#SUBDOMAINS[@]} subdomains -> Beacon $BEACON_IP"
[ "$DRY" = "1" ] && echo "[DRY-RUN] no changes will be made."

fail=0
for n in "${SUBDOMAINS[@]}"; do
  if [ "$DRY" = "1" ]; then
    echo "  [dry] $n.$DOMAIN -> $BEACON_IP"
    continue
  fi
  curl -s -o /dev/null -w '' "${auth[@]}" -X DELETE "$BASE" \
    -d "{\"filters\":[{\"name\":\"$n\",\"type\":\"A\"}]}"
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X PUT "$BASE" \
    -d "{\"overwrite\":false,\"zone\":[{\"name\":\"$n\",\"type\":\"A\",\"ttl\":300,\"records\":[{\"content\":\"$BEACON_IP\"}]}]}")
  if [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; then
    echo "  ✅ $n.$DOMAIN -> $BEACON_IP"
  else
    echo "  ⚠️  $n.$DOMAIN FAILED (HTTP $CODE)"
    fail=$((fail+1))
  fi
done

echo ""
echo "Done. ${#SUBDOMAINS[@]} subdomains, $fail failures."
echo "Caddy will auto-provision TLS certs as DNS propagates (~5 min, TTL 300)."
echo "Verify: dig +short platform.$DOMAIN @1.1.1.1"
echo ""
echo "To rollback: OLD_HUB_IP=$BEACON_IP scripts/hub_dns_update.sh <hub_ip>"
[ "$fail" -eq 0 ]
