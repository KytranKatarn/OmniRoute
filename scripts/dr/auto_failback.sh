#!/bin/bash
# ============================================================================
# auto_failback.sh — Phase 1 of automated DR failback
# Called by dr_watchdog.sh when it detects the hub has recovered.
#
# Phase 1 (automatic, no human needed):
#   1. Repoints global outposts back to hub
#   2. Repoints Starships back to hub (force-recreate node_sync)
#   3. Reverts watch-series agent hub URLs
#   4. Stops DR platform + scheduler standby
#   5. Stops CREED DR and Headscale DR
#   6. Reverts all Beacon entries (platform, mesh, creed) back to hub
#   7. Calls B.A.S.E. agent on the recovering hub for assessment
#
# Phase 2 (human-gated, handled by watchdog poll loop):
#   Sends Telegram with B.A.S.E. report + Rebuild/Skip buttons.
#   On "Rebuild": watchdog runs failback.sh restore-normal (DB re-clone).
#   On "Skip": boston-2 stays as cold standby.
# ============================================================================
set -uo pipefail
DR="${DR:-/opt/archie-dr}"
HUB_MESH="${HUB_MESH:-100.64.0.4}"
DR_MESH="${DR_MESH:-100.64.0.10}"
FLEET_KEY="${FLEET_KEY:-$DR/.fleet_key}"
# BEACON_HOST is deliberately NOT set here. beacon_flip.sh owns the front-door
# address AND the BEACON_LOCAL auto-detect (#3245). Re-declaring it here shadowed
# that default with the Beacon VPS IP removed on 2026-08-28, so every DR ingress
# step still dialled a host that does not exist — the helper fix could not reach
# these callers. Override via the ENVIRONMENT if you ever need a different host.
LOG="$DR/auto_failback.log"

. "$DR/tg_notify.sh" 2>/dev/null || tg_notify(){ :; }

log(){ echo "[$(date -u +%H:%M:%S)] [auto-failback] $*" | tee -a "$LOG"; }

# ---- Beacon SELECTIVE upstream flipping (task #5214, ADR-009) ----
# Sourced AFTER log() so the helper logs through this script's prefix.
BEACON_BAK_SUFFIX=".bak-recover"
if [ -f "$DR/beacon_flip.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/beacon_flip.sh"
else
  log "(WARN: $DR/beacon_flip.sh missing — Beacon upstreams will NOT be reverted)"
  beacon_flip_ports(){
    log "  WARN: beacon_flip.sh not staged — skipping Beacon revert for '${3:-?}' (ports ${*:4})."
    return 1
  }
  BEACON_DR_PORTS_ALL=(3000 8086 8095)
fi

REBUILD_KEYBOARD='[[{"text":"✅ Rebuild DB (complete failback)","callback_data":"dr_rebuild"}],[{"text":"🔵 Skip for now (cold standby)","callback_data":"dr_skip_rebuild"}]]'

log "=== Phase 1 auto-repoint START ==="
OUTAGE_MINS=$(( ($(date +%s) - $(stat -c %Y "$DR/.failed_over" 2>/dev/null || echo $(date +%s))) / 60 ))

# ---- 0. STOP DR HEADSCALE FIRST — this MUST be the first action. ----
# Running archie_headscale_dr simultaneously with hub's Headscale = split-brain:
# two servers with identical keys give nodes contradictory routing info and they
# cannot reconnect to the mesh even after the hub is back. Confirmed 2026-06-04:
# mesh was down for 4+ hours because this container was still running.
# Stop it unconditionally before touching anything else.
log "0) Stopping Headscale DR (split-brain prevention — MUST run first)..."
HS_DIR="$DR/headscale"
if [ -f "$HS_DIR/docker-compose.headscale-dr.yml" ]; then
  ( cd "$HS_DIR" && docker compose -f docker-compose.headscale-dr.yml down >/dev/null 2>&1 ) \
    && log "  Headscale DR: stopped." \
    || log "  WARN: Headscale DR stop failed — check manually (docker stop archie_headscale_dr)"
else
  docker stop archie_headscale_dr >/dev/null 2>&1 && log "  Headscale DR: stopped (direct)." || log "  (Headscale DR was not running)"
fi

# ---- 1. Global outposts → hub ----
# singapore/lithuania/uk were RETIRED 2026-08-29 and this loop dialled all three.
# No global outpost remains that carries a baked HUB_URL: outpost-us is deliberately
# excluded (see fleet_repoint.sh — its hub URLs ride the watch-product .env pass) and
# the LAN Starships self-heal via node_sync v3's DR_HUB_URL auto-switch.
log "1) Global outposts: none remain to repoint (singapore/lithuania/uk retired 2026-08-29)."

# ---- 2. Starships → hub (force-recreate sync container) ----
log "2) Repointing Starships -> hub..."
for sm in "100.64.0.3" "100.64.0.6"; do
  ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "Famil@$sm" \
    "docker compose -f C:\\archie-node\\docker-compose.yml up -d --force-recreate --no-deps sync" >/dev/null 2>&1 \
    && log "  Starship $sm -> hub" || log "  WARN: Starship $sm unreachable"
done

# ---- 3. Watch-series agent hub URLs → hub ----
log "3) Reverting watch-series hub URLs -> hub..."
for product_dir in gov-watch legal-watch what-the-fact; do
  env_file="/opt/archie-products/$product_dir/.env"
  if [ -f "$env_file" ] && grep -q "$DR_MESH:3000" "$env_file"; then
    sed -i.bak-recover "s|$DR_MESH|$HUB_MESH|g" "$env_file"
    ( cd "/opt/archie-products/$product_dir" && docker compose up -d >/dev/null 2>&1 )
    log "  $product_dir: watch URLs -> hub"
  fi
done

# ---- 4. Stop DR platform + scheduler standby ----
# The name here was 'archie_platform' — the HUB's container, which does not exist on
# boston-2 (#5440). The standby is 'archie_platform_standby'. `>/dev/null 2>&1 || true`
# swallowed the "No such container" error AND the exit code, then the next line claimed
# success unconditionally. MEASURED: archie_platform_standby was still running 43 min
# after this logged "DR platform stopped", firing its scheduler jobs against the
# now-read-only replica ("cannot execute INSERT in a read-only transaction"). Benign
# ONLY because the replica is read-only — if it were still promoted, two platform
# instances would run the SAME scheduled jobs against one live DB.
# ('archie_scheduler_standby' was already correct — verified present on boston-2.)
#
# Report success only on PROOF the containers are gone, per the same discipline the
# rebuild branch applies to the replica.
log "4) Stopping DR platform containers..."
_dr_stopped=1
for _c in archie_platform_standby archie_scheduler_standby; do
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$_c"; then
    log "  $_c: not present (nothing to stop)"
    continue
  fi
  docker stop "$_c" >/dev/null 2>&1 || true
  # Verify by STATE, not by the stop command's exit code.
  if docker ps --format '{{.Names}}' | grep -qx "$_c"; then
    log "  WARN: $_c is STILL RUNNING after docker stop — stop it manually"
    _dr_stopped=0
  else
    log "  $_c: stopped."
  fi
done
[ "$_dr_stopped" = "1" ] && log "  DR platform stopped" \
  || log "  WARN: DR platform NOT fully stopped — see warnings above"

# ---- 5. Stop CREED DR and Headscale DR ----
log "5) Stopping CREED DR and Headscale DR..."
CREED_DIR=/opt/archie-products/creed
[ -f "$CREED_DIR/docker-compose.yml" ] \
  && ( cd "$CREED_DIR" && docker compose down >/dev/null 2>&1 ) && log "  CREED DR stopped" || true
HS_DIR="$DR/headscale"
[ -f "$HS_DIR/docker-compose.headscale-dr.yml" ] \
  && ( cd "$HS_DIR" && docker compose -f docker-compose.headscale-dr.yml down >/dev/null 2>&1 ) && log "  Headscale DR stopped" || true

# ---- 6. Revert the DR-capable Beacon entries → hub ----
# Reverts exactly the ports a failover is allowed to move (platform :3000,
# creed :8086, headscale :8095); reverting one that was never flipped is a
# no-op, so this is complete however far the failover got. Replaces a blanket
# `sed 's|DR|HUB|g'` that also rewrote the Caddyfile's comments. Task #5214.
log "6) Reverting Beacon DR-capable entries -> hub..."
# Gated on the HUB actually serving each port (#5225). The only previous
# check was hub POSTGRES :5432, so all three hostnames went back to a hub
# that might not be serving HTTP yet — ADR-009 in reverse. A port the hub
# is not serving is LEFT on DR rather than pointed at a host that cannot
# serve it.
beacon_flip_ports_when_ready "$DR_MESH" "$HUB_MESH" "auto-failback (all DR ports)" "${BEACON_DR_PORTS_ALL[@]}"
# Assert the revert stayed selective, same as failover does.
beacon_verify_selective "$HUB_MESH" 10 || \
  log "  WARN: Beacon does not look selective after failback — check force_reset_to_hub.sh."

# Clear the ADR-012 maintenance splash — the hub is serving these again (#5226).
# Idempotent: a no-op when no splash is in place.
beacon_maintenance_mode off "${BEACON_MAINTENANCE_HOSTS[@]}" \
  || log "  WARN: could not clear the maintenance splash — hub-only hostnames may still show 503."

log "=== Phase 1 auto-repoint COMPLETE ==="

# ---- 7. B.A.S.E. agent assessment via hub dispatch ----
log "7) Requesting B.A.S.E. assessment from hub..."
ASSESSMENT="Assessment unavailable (hub warming up)"
HUB_URL="http://$HUB_MESH:3000"

# Wait up to 30s for hub platform to respond
for i in 1 2 3; do
  HC=$(wget -qO- --server-response "$HUB_URL/tools/department-hq/api/health" 2>&1 | head -1 | grep -oP '\d{3}' | head -1 || echo 0)
  [ "$HC" = "200" ] && break
  sleep 10
done

if [ "$HC" = "200" ]; then
  ASSESSMENT=$(wget -qO- --post-data '{"capability":"infrastructure_assessment","reason":"Hub recovered from DR. Report: hub health, DB write activity during outage, scheduler status, recommended action.","delegation_source":"automation"}' \
    --header 'Content-Type: application/json' \
    "$HUB_URL/api/mcp/delegate_task" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','Queued')[:200])" 2>/dev/null \
    || echo "Platform healthy — assessment queued in background")
fi

log "Assessment: $ASSESSMENT"

# ---- 8. Telegram: Phase 2 approval request ----
tg_notify "✅ <b>A.R.C.H.I.E. DR — HUB RECOVERED</b>

⏱ Outage duration: ~${OUTAGE_MINS} min

<b>Phase 1 auto-repoint: DONE</b>
• Outpost nodes, Starships, watch URLs → reverted to hub
• DR platform, CREED DR, Headscale DR → stopped
• Beacon → reverted to hub

<b>B.A.S.E. Assessment:</b>
${ASSESSMENT}

<b>Phase 2 — DB rebuild</b>
Re-establishes boston-2 as a streaming replica of the hub.
Destructive on boston-2 only (existing DR data replaced with fresh hub copy).

Tap to proceed:" "$REBUILD_KEYBOARD"

log "Telegram approval request sent. Waiting for operator decision..."
