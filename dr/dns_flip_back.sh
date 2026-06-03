#!/bin/bash
# DNS FAILBACK — point platform.kytranempowerment.com A-record BACK to the hub.
# The reverse of dns_flip.sh. Run on boston-2 during a Phase 6 failback, AFTER
# the hub is live again at its (possibly NEW) public IP.
#
#   /opt/archie-dr/dns_flip_back.sh <hub_public_ip>
#
# ⚠️ The hub's public IP CHANGES if the hub was physically moved, so it is a
# REQUIRED argument — there is deliberately NO default, to avoid pointing the
# record at a stale/dead IP. Mirrors dns_flip.sh exactly (same Hostinger DNS
# API, the WAF user-agent quirk, and the delete-then-create dance).
#
# REQUIRES (already staged for the forward flip): /opt/archie-dr/.hostinger_token
set -uo pipefail
TOKEN_FILE=/opt/archie-dr/.hostinger_token
DOMAIN=kytranempowerment.com
NAME=platform
TARGET="${1:-}"

[ -n "$TARGET" ] || { echo "ABORT: usage: $0 <hub_public_ip>   (the hub's CURRENT public IP — it CHANGES if the hub was moved)"; exit 1; }
echo "$TARGET" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || { echo "ABORT: '$TARGET' is not an IPv4 address"; exit 1; }
[ -f "$TOKEN_FILE" ] || { echo "ABORT: no Hostinger token at $TOKEN_FILE"; exit 1; }
TOKEN=$(cat "$TOKEN_FILE")

echo "Failback DNS: $NAME.$DOMAIN A-record -> $TARGET (hub)..."
# Same two REQUIRED quirks as dns_flip.sh (KB #270039 / #270040):
#  -A "Mozilla/5.0": Hostinger WAF 403s the default curl UA before auth.
#  PUT overwrite:false APPENDS → DELETE the old platform A first, then CREATE.
UA="Mozilla/5.0"
BASE="https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN"
DEL=$(curl -s -o /dev/null -w '%{http_code}' -A "$UA" -X DELETE "$BASE" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"filters\":[{\"name\":\"$NAME\",\"type\":\"A\"}]}")
echo "  delete old $NAME A -> HTTP $DEL"
RESP=$(curl -s -w '\n%{http_code}' -A "$UA" -X PUT "$BASE" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"overwrite\":false,\"zone\":[{\"name\":\"$NAME\",\"type\":\"A\",\"ttl\":300,\"records\":[{\"content\":\"$TARGET\"}]}]}")
CODE=$(echo "$RESP" | tail -1)
echo "  create $NAME A=$TARGET -> HTTP $CODE"
{ [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; } \
  && echo "✅ failed back to hub — TTL 300 → ~5 min propagation. Verify: dig $NAME.$DOMAIN @1.1.1.1" \
  || { echo "⚠️ DNS failback FAILED (HTTP $CODE): $(echo "$RESP" | head -1)"; exit 2; }
