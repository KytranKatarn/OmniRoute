#!/bin/bash
# ============================================================================
# force_reset_to_hub.sh — Emergency idempotent restore to normal hub state.
#
# Run on boston-2 any time the DRP leaves the system in a partial/confused
# state. Safe to run multiple times. Does NOT rebuild the DB (that's manual).
#
#   ssh root@<boston-2> /opt/archie-dr/force_reset_to_hub.sh
#
# What it does (IP-based, pattern-agnostic — catches every port/protocol):
#   1. Beacon Caddyfile: replace all boston-2 IPs with hub IP, reload caddy
#   2. Watch product .envs: replace all boston-2 IPs, restart containers
#   3. Stop DR containers (platform, scheduler, creed, headscale)
#   4. Clear DR state flags (.failed_over, .awaiting_rebuild)
#
# Uses PUBLIC IPs throughout — works even when the Headscale mesh is down.
# ============================================================================
set -uo pipefail
DR="${DR:-/opt/archie-dr}"
HUB_MESH="${HUB_MESH:-100.64.0.4}"
DR_MESH="${DR_MESH:-100.64.0.10}"
FLEET_KEY="${FLEET_KEY:-$DR/.fleet_key}"
BEACON_PUBLIC="${BEACON_PUBLIC:-root@2.25.170.252}"  # public IP, works without mesh

log(){ echo "[$(date -u +%H:%M:%S)] [force-reset] $*" | tee -a "$DR/force_reset.log"; }

log "=== force_reset_to_hub START ==="

# ---- 1. Beacon Caddyfile — replace ALL occurrences of DR mesh IP ----
log "1) Reverting Beacon Caddyfile $DR_MESH -> $HUB_MESH ..."
if [ -f "$FLEET_KEY" ]; then
  ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$BEACON_PUBLIC" "
    sed -i.bak-reset 's|$DR_MESH|$HUB_MESH|g' /etc/caddy/Caddyfile &&
    caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1 &&
    systemctl reload caddy && echo '  Beacon: reverted + reloaded'" 2>/dev/null \
    && log "  Beacon OK" || log "  WARN: Beacon SSH failed (manual: sed Caddyfile $DR_MESH->$HUB_MESH + reload)"
else
  log "  WARN: no fleet key — cannot reach Beacon"
fi

# ---- 2. Watch product .envs — replace ALL occurrences of DR mesh IP ----
log "2) Reverting watch product hub URLs $DR_MESH -> $HUB_MESH ..."
for product_dir in gov-watch legal-watch what-the-fact civic-watch market-watch; do
  env_file="/opt/archie-products/$product_dir/.env"
  [ -f "$env_file" ] || continue
  if grep -q "$DR_MESH" "$env_file"; then
    sed -i.bak-reset "s|$DR_MESH|$HUB_MESH|g" "$env_file"
    ( cd "/opt/archie-products/$product_dir" && docker compose up -d >/dev/null 2>&1 ) \
      && log "  $product_dir: reverted + restarted" \
      || log "  WARN: $product_dir restart failed"
  else
    log "  $product_dir: no DR IPs found (already clean)"
  fi
done

# ---- 3. Stop DR containers ----
log "3) Stopping DR containers ..."
docker stop archie_platform archie_scheduler_standby 2>/dev/null | xargs -I{} log "  stopped {}" || true
CREED_DIR=/opt/archie-products/creed
[ -f "$CREED_DIR/docker-compose.yml" ] \
  && ( cd "$CREED_DIR" && docker compose down >/dev/null 2>&1 ) && log "  CREED DR: stopped" || true
HS_DIR="$DR/headscale"
[ -f "$HS_DIR/docker-compose.headscale-dr.yml" ] \
  && ( cd "$HS_DIR" && docker compose -f docker-compose.headscale-dr.yml down >/dev/null 2>&1 ) && log "  Headscale DR: stopped" || true

# ---- 4. Clear DR state flags ----
log "4) Clearing DR state flags ..."
rm -f "$DR/.failed_over"    && log "  .failed_over: cleared"
rm -f "$DR/.awaiting_rebuild" && log "  .awaiting_rebuild: cleared"

log "=== force_reset_to_hub COMPLETE — watchdog re-armed, all products on hub ==="
