#!/bin/bash
# ============================================================================
# hub_dns_update.sh — re-point EVERY hub-facing subdomain to a new hub IP.
#
# The hub is the only on-prem (non-static) endpoint; when it MOVES, its public
# IP changes and all ~27 subdomains A-record'd to it break at once. This updates
# them in a single command. (boston-2 + the outposts are static Hostinger IPs
# and are left untouched.)
#
#   scripts/hub_dns_update.sh <new_hub_ip>            # update all hub records
#   scripts/hub_dns_update.sh --auto                 # detect THIS host's public IP
#   scripts/hub_dns_update.sh <new_hub_ip> --dry-run # show what would change
#
# Old hub IP is auto-detected from the live `platform` A-record (override with
# OLD_HUB_IP=...). Token: $HOSTINGER_API_KEY, else read from the repo root .env.
# Mirrors dns_flip.sh exactly: Mozilla UA (Hostinger WAF) + delete-then-create
# (PUT overwrite:false APPENDS; overwrite:true wipes the zone). KB #270039/#270040.
# ============================================================================
set -uo pipefail
DOMAIN="${HOSTINGER_DOMAIN:-kytranempowerment.com}"
UA="Mozilla/5.0"
BASE="https://developers.hostinger.com/api/dns/v1/zones/$DOMAIN"

DRY=0; AUTO=0; NEW_IP=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1;;
    --auto) AUTO=1;;
    -*) echo "unknown option: $a"; exit 1;;
    *) NEW_IP="$a";;
  esac
done

# --- token ---
TOKEN="${HOSTINGER_API_KEY:-}"
if [ -z "$TOKEN" ]; then
  for ENVF in "$(dirname "$0")/../.env" /mnt/archie_brain/.env; do
    [ -f "$ENVF" ] || continue
    TOKEN=$(grep -E '^HOSTINGER_API_KEY=' "$ENVF" | head -1 | cut -d= -f2- | tr -d '"'\'' ')
    [ -n "$TOKEN" ] && break
  done
fi
[ -n "$TOKEN" ] || { echo "ABORT: no Hostinger token (set HOSTINGER_API_KEY or add it to .env)"; exit 1; }

# --- new IP ---
if [ "$AUTO" = 1 ] && [ -z "$NEW_IP" ]; then
  NEW_IP=$(curl -s --max-time 8 https://api.ipify.org 2>/dev/null || true)
  echo "auto-detected this host's public IP: ${NEW_IP:-<none>}"
fi
[ -n "$NEW_IP" ] || { echo "usage: $0 <new_hub_ip> [--dry-run]   (or --auto to detect this host's public IP)"; exit 1; }
echo "$NEW_IP" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || { echo "ABORT: '$NEW_IP' is not an IPv4 address"; exit 1; }

auth=(-A "$UA" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")

# --- pull zone + resolve OLD hub IP ---
ZONE=$(curl -s "${auth[@]}" "$BASE")
[ -n "$ZONE" ] || { echo "ABORT: could not fetch DNS zone"; exit 2; }
OLD_IP="${OLD_HUB_IP:-}"
[ -n "$OLD_IP" ] || OLD_IP=$(echo "$ZONE" | jq -r '.[] | select(.name=="platform" and .type=="A") | .records[0].content' 2>/dev/null)
[ -n "$OLD_IP" ] && [ "$OLD_IP" != "null" ] || { echo "ABORT: could not determine the OLD hub IP (set OLD_HUB_IP=...)"; exit 2; }

if [ "$OLD_IP" = "$NEW_IP" ]; then echo "Nothing to do — hub records already point at $NEW_IP."; exit 0; fi

# --- find every A-record on the OLD hub IP ---
mapfile -t NAMES < <(echo "$ZONE" | jq -r --arg ip "$OLD_IP" '.[] | select(.type=="A") | select(any(.records[]; .content==$ip)) | .name' | sort -u)
echo "Hub move: re-point $OLD_IP -> $NEW_IP  (${#NAMES[@]} subdomains)"
printf '  %s\n' "${NAMES[@]}"
[ "${#NAMES[@]}" -gt 0 ] || { echo "No A-records point at $OLD_IP — nothing to do."; exit 0; }

if [ "$DRY" = 1 ]; then echo "[DRY-RUN] no changes made."; exit 0; fi

# --- update each: delete old A then create new A=NEW_IP ---
fail=0
for n in "${NAMES[@]}"; do
  curl -s -o /dev/null -w '' "${auth[@]}" -X DELETE "$BASE" \
    -d "{\"filters\":[{\"name\":\"$n\",\"type\":\"A\"}]}"
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X PUT "$BASE" \
    -d "{\"overwrite\":false,\"zone\":[{\"name\":\"$n\",\"type\":\"A\",\"ttl\":300,\"records\":[{\"content\":\"$NEW_IP\"}]}]}")
  if [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; then echo "  ✅ $n -> $NEW_IP"; else echo "  ⚠️ $n FAILED (HTTP $CODE)"; fail=$((fail+1)); fi
done
echo "Done. ${#NAMES[@]} records, $fail failures. TTL 300 → ~5 min propagation. Verify: dig +short platform.$DOMAIN @1.1.1.1"
[ "$fail" -eq 0 ]
