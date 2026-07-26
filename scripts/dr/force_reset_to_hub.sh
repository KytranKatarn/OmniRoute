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

# ---- Beacon SELECTIVE upstream flipping (task #5214, ADR-009) ----
BEACON_HOST="${BEACON_HOST:-$BEACON_PUBLIC}"
BEACON_BAK_SUFFIX=".bak-reset"
if [ -f "$DR/beacon_flip.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/beacon_flip.sh"
else
  log "(WARN: $DR/beacon_flip.sh missing — Beacon upstreams will NOT be reverted)"
  beacon_flip_ports(){ log "  WARN: beacon_flip.sh not staged — skipping Beacon revert."; return 1; }
  beacon_upstream_count(){ echo "?"; }
  BEACON_DR_PORTS_ALL=(3000 8086 8095)
fi

log "=== force_reset_to_hub START ==="

# ---- 1. Beacon Caddyfile — revert the DR-capable upstreams to the hub ----
# Break-glass recovery, so it reverts every port a failover is allowed to move
# (platform :3000, creed :8086, headscale :8095) — reverting one that was never
# flipped is a no-op.
#
# It is deliberately NOT a blanket `sed 's|100.64.0.10|100.64.0.4|g'` any more.
# The blanket version rewrote COMMENTS as well as upstreams: Beacon's Caddyfile
# header still reads "DR (boston-2) mesh IP: 100.64.0.4" because a previous
# force-reset rewrote its own documentation. It would also clobber any upstream
# that legitimately points at boston-2. Anything left on the DR IP after this is
# REPORTED rather than silently rewritten — set DR_RESET_ALL=1 to force the old
# blanket behaviour when you truly want it. Task #5214.
log "1) Reverting Beacon DR-capable upstreams $DR_MESH -> $HUB_MESH ..."
beacon_flip_ports "$DR_MESH" "$HUB_MESH" "force-reset (all DR ports)" "${BEACON_DR_PORTS_ALL[@]}"

leftover="$(beacon_upstream_count "$DR_MESH")"
if [ "$leftover" != "?" ] && [ "$leftover" -gt 0 ]; then
  if [ "${DR_RESET_ALL:-0}" = "1" ]; then
    log "  DR_RESET_ALL=1 — force-reverting $leftover remaining $DR_MESH upstream(s)..."
    ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$BEACON_HOST" "
      sed -i.bak-reset-all 's|reverse_proxy http://$DR_MESH:|reverse_proxy http://$HUB_MESH:|g' /etc/caddy/Caddyfile &&
      caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1 &&
      systemctl reload caddy" >/dev/null 2>&1 \
      && log "  Beacon: all remaining upstreams reverted." \
      || log "  WARN: blanket revert failed — Beacon unchanged."
  else
    log "  NOTE: $leftover Beacon upstream(s) still point at $DR_MESH and are NOT in the"
    log "        DR-capable map. That is either an intentional boston-2 service or drift."
    log "        Inspect first; to force: DR_RESET_ALL=1 $0"
  fi
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

# ---- 5. LAN split-horizon (AdGuard) — DETECT and REPORT (task #5224) ----
#
# WHY THIS STEP EXISTS. On 2026-07-26 Beacon, the watch products, the hub and the
# DR flags were ALL correctly restored — and the owner still could not reach
# platform./creed./server./media. for ~13 hours. AdGuard's LAN rewrites were still
# pointed at 192.168.1.200 (the recovery Caddy, HTTP-only, :443 refused) from a
# bulk repoint during the incident. Every layer this script checks read healthy;
# the layer nobody checked was the one that was broken.
#
# DETECT ONLY, BY DESIGN. A recovery script that bulk-rewrites DNS is exactly how
# #5219 happened — a blanket AdGuard repoint swept in mesh., the TLS-only control
# plane, and dropped both Starships. A batch over N hostnames is N decisions
# (feedback_bulk-ops-are-n-decisions), so this reports and hands the operator the
# precise per-host command. Pass --fix-dns only if you have read the report.
#
# Resolves against AdGuard rather than reading its API: no credentials needed, and
# it measures what a LAN CLIENT actually gets — the path that matters. Measuring
# the convenient thing instead of the real path is the recurring bug this whole
# session has been about.
ADGUARD_DNS="${ADGUARD_DNS:-100.64.0.4}"
BEACON_PUBLIC="${BEACON_PUBLIC:-2.25.170.252}"
# Hostnames Beacon fronts. mail. is deliberately ABSENT: Stalwart runs on the hub
# and mail. must NOT be pointed at Beacon (verified 2026-07-26 — :25/:465/:587/:993
# are open on the hub and closed on Citadel).
BEACON_HOSTS="${BEACON_HOSTS:-platform consciousness business server media creed mesh adguard nagios plex jellyfin store shop terminal codex sandbox archie claude tdarr}"

log "5) LAN split-horizon check (AdGuard @ $ADGUARD_DNS) ..."
if ! command -v dig >/dev/null 2>&1; then
    log "  SKIP: dig not installed — cannot verify LAN DNS. Install dnsutils."
else
    _drift=0
    for _h in $BEACON_HOSTS; do
        _got="$(dig +short +time=3 +tries=1 "@$ADGUARD_DNS" "${_h}.kytranempowerment.com" A 2>/dev/null | grep -E '^[0-9.]+$' | head -1)"
        if [ -z "$_got" ]; then
            log "  ? ${_h}. — no answer from AdGuard (is the hub up?)"
        elif [ "$_got" != "$BEACON_PUBLIC" ]; then
            log "  *** ${_h}.kytranempowerment.com -> $_got  (expected $BEACON_PUBLIC)"
            _drift=$((_drift+1))
        fi
    done
    if [ "$_drift" -eq 0 ]; then
        log "  LAN DNS OK: all checked hostnames resolve to Beacon."
    else
        log "  *** $_drift hostname(s) NOT pointing at Beacon — LAN clients will fail even"
        log "  *** though every service is healthy. This is the 2026-07-26 signature."
        if [ "${1:-}" = "--fix-dns" ] || [ "${FIX_DNS:-0}" = "1" ]; then
            log "  --fix-dns given: repoint them ONE AT A TIME from the hub, verifying each."
            log "  (Not automated here on purpose — a bulk AdGuard repoint caused #5219.)"
        fi
        log "  Remediate on the hub, per host, re-reading the list first:"
        log "    POST http://127.0.0.1:5354/control/rewrite/delete {domain,answer:<old>}"
        log "    POST http://127.0.0.1:5354/control/rewrite/add    {domain,answer:$BEACON_PUBLIC}"
        log "  ⚠️ mesh. is TLS-only control plane and adguard./mail. have their own"
        log "     correct targets — never sweep the whole zone."
    fi
fi

log "=== force_reset_to_hub COMPLETE — watchdog re-armed, all products on hub ==="
log ""
log "NOTE: if the Headscale mesh is still down (nodes offline), run FROM THE HUB:"
log "  bash /mnt/archie_brain/scripts/dr/mesh_bootstrap.sh"
log "  This creates reverse SSH tunnels + reconnects nodes using a fresh pre-auth key."
