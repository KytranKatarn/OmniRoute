#!/bin/bash
# ⚠️ DEPRECATED for the automated DR flow (task #3787, 2026-06-08).
# platform.kytranempowerment.com now lives PERMANENTLY on the Beacon front-door
# (2.25.170.252); failover is handled by flipping Beacon's Caddy upstream
# (failover.sh step 4c), NOT by moving this A-record. failover.sh no longer calls
# this script. Flipping platform off Beacon previously STRANDED it on boston-2
# (failback forgot to flip it back). KEEP only as a MANUAL EMERGENCY tool for the
# narrow case where Beacon ITSELF is down and you must point platform straight at
# boston-2 (expect a fresh TLS provision on boston-2's Caddy).
#
# Phase 5 — DNS FLIP: point platform.kytranempowerment.com at boston-2 (DR).
# Called by failover.sh during a real failover. SELF-CONTAINED on boston-2.
#
# REQUIRES (owner must stage, ONE TIME):
#   /opt/archie-dr/.hostinger_token  — a Hostinger API bearer token (chmod 600)
#
# ⚠️ UNTESTABLE without breaking prod (flipping the real record redirects live
# users). VERIFY the API payload once against a THROWAWAY subdomain before relying
# on it. Current A-record: platform -> 173.182.133.96 (hub), TTL 300.
set -uo pipefail
TOKEN_FILE=/opt/archie-dr/.hostinger_token
DOMAIN=kytranempowerment.com
NAME=platform
TARGET=2.25.133.122   # boston-2 public IP

[ -f "$TOKEN_FILE" ] || { echo "ABORT: no Hostinger token at $TOKEN_FILE (owner must stage it)"; exit 1; }
TOKEN=$(cat "$TOKEN_FILE")

echo "Flipping $NAME.$DOMAIN A-record -> $TARGET (Hostinger DNS API)..."
# Two REQUIRED quirks (both verified 2026-06-02, KB #270039/#270040):
#  - `-A "Mozilla/5.0"`: Hostinger's WAF 403s the default curl/urllib UA before auth.
#  - PUT overwrite:false APPENDS a same-name+type record (would round-robin a dead hub),
#    and overwrite:true wipes the WHOLE zone — so DELETE the old platform A, then CREATE.
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
  && echo "✅ flipped — TTL 300 → ~5 min propagation. Verify: dig $NAME.$DOMAIN" \
  || { echo "⚠️ DNS flip FAILED (HTTP $CODE): $(echo "$RESP" | head -1)"; exit 2; }
