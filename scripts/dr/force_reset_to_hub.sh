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
# BEACON_HOST is deliberately NOT set here. beacon_flip.sh owns the front-door
# address AND the BEACON_LOCAL auto-detect (#3245). Re-declaring it here shadowed
# that default with the Beacon VPS IP removed on 2026-08-28, so every DR ingress
# step still dialled a host that does not exist — the helper fix could not reach
# these callers. Override via the ENVIRONMENT if you ever need a different host.

log(){ echo "[$(date -u +%H:%M:%S)] [force-reset] $*" | tee -a "$DR/force_reset.log"; }

# ---- Beacon SELECTIVE upstream flipping (task #5214, ADR-009) ----
BEACON_BAK_SUFFIX=".bak-reset"
if [ -f "$DR/beacon_flip.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/beacon_flip.sh"
else
  log "(WARN: $DR/beacon_flip.sh missing — Beacon upstreams will NOT be reverted)"
  beacon_flip_ports(){ log "  WARN: beacon_flip.sh not staged — skipping Beacon revert."; return 1; }
  beacon_upstream_count(){ echo "?"; }
  beacon_maintenance_mode(){ log "  WARN: maintenance splash unavailable (helper not staged)."; return 1; }
  BEACON_DR_PORTS_ALL=(3000 8086 8095)
  BEACON_MAINTENANCE_HOSTS=()
fi

# ---- Fleet repoint helpers (task #5278) — ONE node list shared with failover ----
if [ -f "$DR/fleet_repoint.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/fleet_repoint.sh"
else
  log "(WARN: $DR/fleet_repoint.sh missing — fleet repoint-back will use loud no-ops)"
  fleet_repoint_outposts(){
    log "  WARN: fleet_repoint.sh not staged — outposts NOT repointed (manual, per node:"
    log "        ssh root@100.64.0.{5,7,8} /opt/archie-node/repoint.sh ${1:-<target>})"
    return 1
  }
  fleet_kick_starships(){ log "  (fleet_repoint.sh not staged — Starships self-heal in ~2.5 min)"; return 0; }
  fleet_verify_heartbeats(){ log "  WARN: fleet_repoint.sh not staged — heartbeats unverified."; return 1; }
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
    # Through the helper seam, not a bare ssh: on the Citadel front door there is
    # no host caddy and no ssh-to-self, so the old inline `caddy validate &&
    # systemctl reload caddy` could never succeed there. _beacon_ssh runs locally
    # when BEACON_LOCAL=1, and the emitters pick docker-exec vs systemd.
    _beacon_ssh "
      sed -i.bak-reset-all 's|reverse_proxy http://$DR_MESH:|reverse_proxy http://$HUB_MESH:|g' '${BEACON_CADDYFILE}' &&
      $(_beacon_validate_cmd) >/dev/null 2>&1 &&
      $(_beacon_reload_cmd)" >/dev/null 2>&1 \
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

# ---- 2b. FLEET NODES — repoint back to the hub + VERIFY heartbeats ----
# THE 2026-07-27 DRILL HOLE (#5278): this script restored Beacon, the watch
# products, the containers and the flags — and never repointed the FLEET, so
# all three global outposts kept HUB_URL=boston-2 for 9.6h, stuck in
# re-registration loops (the KB #270611 storm precondition; only the absence of
# a listener on 100.64.0.10:3000 prevented identity churn). A repoint on an
# already-hub-pointed node is an idempotent no-op, so this always runs.
log "2b) Repointing fleet nodes back to the hub ($HUB_MESH) ..."
fleet_repoint_outposts "$HUB_MESH" || log "  WARN: some outposts not repointed — repoint each on power-up."
fleet_kick_starships
# (heartbeat VERIFY runs as step 7, after the DR containers are stopped — the
#  nodes get steps 3-6 of runtime to reconnect, so the wait is usually instant)

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
# Shared per-host AdGuard helper (#5224). Sourced so a break-glass reset can
# actually RESTORE LAN DNS instead of only describing what is wrong.
if [ -f "$DR/adguard_flip.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/adguard_flip.sh"
else
  adguard_lan_check(){ log "  (adguard_flip.sh not staged — LAN DNS not checked)"; return 2; }
  adguard_lan_restore(){ log "  (adguard_flip.sh not staged — cannot restore LAN DNS)"; return 2; }
  adguard_lan_serves(){ log "  (adguard_flip.sh not staged — serve-check skipped)"; return 2; }
fi

ADGUARD_DNS="${ADGUARD_DNS:-100.64.0.4}"
# The DNS answer these hostnames are EXPECTED to resolve to. Citadel inherited the
# front door when the Beacon VPS was removed 2026-08-28.
BEACON_PUBLIC="${BEACON_PUBLIC:-2.25.133.122}"
# Hostnames Beacon fronts. mail. is deliberately ABSENT: Stalwart runs on the hub
# and mail. must NOT be pointed at Beacon (verified 2026-07-26 — :25/:465/:587/:993
# are open on the hub and closed on Citadel).
BEACON_HOSTS="${BEACON_HOSTS:-platform consciousness business server media creed mesh adguard nagios plex jellyfin store shop terminal codex sandbox archie claude tdarr}"

# Break-glass must also clear the ADR-012 splash, or hub-only hostnames stay on
# 503 after everything else is restored (#5226).
log "4b) Clearing any maintenance splash on Beacon ..."
beacon_maintenance_mode off "${BEACON_MAINTENANCE_HOSTS[@]}" \
  || log "  WARN: could not clear the maintenance splash."

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
            # PER-HOST, TLS-gated, mesh. never touched — adguard_flip.sh enforces
            # all three. Still opt-in: a recovery script that rewrites DNS on its
            # own initiative is how #5219 happened.
            log "  --fix-dns given: repointing per-host via adguard_flip.sh ..."
            adguard_lan_restore
            adguard_lan_check
        else
            log "  (re-run with --fix-dns to repoint per-host, TLS-gated, mesh. untouched)"
        fi
        log "  Remediate on the hub, per host, re-reading the list first:"
        log "    POST http://127.0.0.1:5354/control/rewrite/delete {domain,answer:<old>}"
        log "    POST http://127.0.0.1:5354/control/rewrite/add    {domain,answer:$BEACON_PUBLIC}"
        log "  ⚠️ mesh. is TLS-only control plane and adguard./mail. have their own"
        log "     correct targets — never sweep the whole zone."
    fi
fi

# ---- 6. Does each name RESOLVE **and** SERVE? (#5246) --------------------
# Matching the map is not proof a name works. On 2026-07-26 platform./creed./
# server./media. resolved to a host that was UP and the answer was defensible —
# but the recovery hub Caddy had `auto_https off` and REFUSED :443. Every layer
# anyone checked read healthy; the layer nobody checked was whether the name
# actually served. Detection only — this never writes.
log "6) end-to-end resolve-AND-serve check ..."
if adguard_lan_serves; then
  log "  every checked hostname resolves AND completes a TLS handshake."
else
  log "  *** at least one hostname does not serve (or could not be measured)."
  log "  *** This is the 2026-07-26 signature: healthy services, correct-looking"
  log "  *** DNS, and the name still unusable from the LAN."
fi

# ---- 7. VERIFY fleet heartbeats — a node list is not a rollback until they return (#5278) ----
log "7) Verifying fleet heartbeats against the hub DB ..."
fleet_verify_heartbeats 300 240 \
  || log "  *** FLEET NOT VERIFIED: outposts may still point at boston-2 (#5278 drill defect). Fix BEFORE calling this reset complete."

log "=== force_reset_to_hub COMPLETE — watchdog re-armed, all products on hub ==="
log ""
log "NOTE: if the Headscale mesh is still down (nodes offline), run FROM THE HUB:"
log "  bash /mnt/archie_brain/scripts/dr/mesh_bootstrap.sh"
log "  This creates reverse SSH tunnels + reconnects nodes using a fresh pre-auth key."
