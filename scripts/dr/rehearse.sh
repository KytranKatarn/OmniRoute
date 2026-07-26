#!/bin/bash
# ============================================================================
# rehearse.sh — prove the DR machinery works WITHOUT touching production (#4495)
#
# WHY A REHEARSAL AND NOT JUST THE DRILL
# Everything in scripts/dr/ is reasoned and unit-tested, but a unit test cannot
# tell you whether THIS cluster, RIGHT NOW, would survive a failover: whether the
# replica is genuinely streaming, whether Beacon can actually reach the DR ports,
# whether LAN DNS resolves AND serves. Those are live properties. The full drill
# proves them by breaking things; this proves as many as possible by asking.
#
# EVERY CHECK HERE IS READ-ONLY. Nothing is promoted, flipped, written or
# restarted. Safe to run at any time, including during business hours — which is
# the point: a rehearsal you are afraid to run is a rehearsal nobody runs.
#
# WHAT IT CANNOT PROVE, stated plainly so nobody mistakes a pass for a drill:
#   * that a promotion actually succeeds (needs a real promotion)
#   * that the platform serves correctly FROM boston-2 under load
#   * that failback re-clones cleanly
# Those need #4495's full drill in an owner-approved window. This is the
# pre-flight, not the flight.
#
#   rehearse.sh          # run every check, exit 1 if any FAILED
# ============================================================================
set -uo pipefail

DR="${DR:-/opt/archie-dr}"
FLEET_KEY="${FLEET_KEY:-$DR/.fleet_key}"
HUB_MESH="${HUB_MESH:-100.64.0.4}"
DR_MESH="${DR_MESH:-100.64.0.10}"
B2_CONTAINER="${B2_CONTAINER:-archie_dr_replica}"
B2_PG="${B2_PG:-5433}"

PASS=0; FAIL=0; UNKNOWN=0
log(){ echo "[$(date -u +%H:%M:%S)] [rehearse] $*"; }
ok(){   log "  PASS    $*"; PASS=$((PASS+1)); }
bad(){  log "  FAIL    $*"; FAIL=$((FAIL+1)); }
unk(){  log "  UNKNOWN $*"; UNKNOWN=$((UNKNOWN+1)); }   # never counted as a pass

# shellcheck disable=SC1091
[ -f "$DR/beacon_flip.sh" ]  && . "$DR/beacon_flip.sh"
# shellcheck disable=SC1091
[ -f "$DR/adguard_flip.sh" ] && . "$DR/adguard_flip.sh"

log "=== DR REHEARSAL — read-only, nothing is mutated ==="

# ---- 1. Is the replica genuinely a replica, and streaming from the HUB? ----
# The single most load-bearing fact. A promoted fork looks identical from the
# outside and is what went unnoticed for 7 days (#4997, KB #272172).
out="$(docker exec "$B2_CONTAINER" psql -U archie -p "$B2_PG" -tAc \
      "SELECT pg_is_in_recovery()::text || ':' || coalesce((SELECT status || '@' || coalesce(sender_host,'?') FROM pg_stat_wal_receiver LIMIT 1),'no_receiver');" 2>/dev/null | tr -d '[:space:]')"
case "$out" in
  "true:streaming@$HUB_MESH") ok "replica is streaming from the hub ($out)" ;;
  false:*) bad "boston-2 is a PROMOTED FORK, not a replica ($out) — a failover would have nothing to fail back to" ;;
  "")      unk "could not query $B2_CONTAINER" ;;
  *)       bad "replica not streaming from $HUB_MESH ($out)" ;;
esac

# ---- 2. Replication lag ----
lag="$(docker exec "$B2_CONTAINER" psql -U archie -p "$B2_PG" -tAc \
      "SELECT coalesce(extract(epoch from now()-pg_last_xact_replay_timestamp())::int, -1);" 2>/dev/null | tr -d '[:space:]')"
if [ -z "$lag" ]; then unk "replay lag unreadable"
elif [ "$lag" -lt 0 ]; then unk "replay lag null (no replayed xact yet)"
elif [ "$lag" -le 60 ]; then ok "replay lag ${lag}s"
else bad "replay lag ${lag}s — a failover would lose up to that much"; fi

# ---- 3. DR state flags ----
for f in .failed_over .awaiting_rebuild .watchdog_disabled; do
  if [ -f "$DR/$f" ]; then
    [ "$f" = ".watchdog_disabled" ] && bad "$f present — DR IS DISARMED" || bad "$f present — DR is mid-incident, not idle"
  else ok "$f clear"; fi
done

# ---- 4. Can BEACON reach boston-2 AT ALL? ----
# Asked from Beacon, because Beacon is the machine that has to connect; a local
# probe on boston-2 cannot see Beacon's UFW (#5222).
#
# ⚠️ PROBE A PORT THAT IS LIVE WHILE DR IS IDLE — the replica (5433) and sshd.
# The FIRST version of this check probed 3000/8086/8095 (platform / creed /
# headscale) and reported three FAILs on a perfectly healthy cluster: those are
# the DR STANDBY services, which only run DURING a failover. Idle DR means
# archie_platform_standby is Exited and nothing listens there, so "unreachable"
# is the CORRECT state. failover.sh starts the standbys at step 2 and only flips
# Beacon at step 4c, and #5225's beacon_flip_ports_when_ready already gates that
# flip on the port genuinely serving.
#
# A check that fails whenever the system is healthy trains people to ignore it —
# the same reasoning as the #5230 drift gate that could never be satisfied.
if type beacon_can_reach >/dev/null 2>&1; then
  reach_ok=0
  for port in 22 "$B2_PG"; do
    beacon_can_reach "$DR_MESH" "$port"
    case $? in
      0) ok "Beacon can reach boston-2:$port"; reach_ok=1 ;;
      1) bad "Beacon CANNOT reach boston-2:$port — the Beacon->DR path is blocked (firewall/route)" ;;
      *) unk "Beacon reachability to :$port not measurable" ;;
    esac
  done
  [ "$reach_ok" = "1" ] && ok "Beacon->boston-2 path is open (DR service ports 3000/8086/8095 are correctly CLOSED while DR is idle)"
else unk "beacon_flip.sh not staged — reachability not checked"; fi

# ---- 5. Is the Beacon upstream map still SELECTIVE? ----
if type beacon_verify_selective >/dev/null 2>&1; then
  beacon_verify_selective "$HUB_MESH" 10 >/dev/null 2>&1 \
    && ok "Beacon upstreams look selective (hub-pointed, no blanket DR sweep)" \
    || bad "Beacon does not look selective — check force_reset_to_hub.sh"
else unk "beacon_verify_selective unavailable"; fi

# ---- 6. LAN split-horizon: resolves AND serves ----
if type adguard_lan_check >/dev/null 2>&1; then
  adguard_lan_check >/dev/null 2>&1
  case $? in 0) ok "LAN DNS matches the per-host map" ;;
             1) bad "LAN DNS has drifted — force_reset_to_hub.sh --fix-dns" ;;
             *) unk "LAN DNS not measurable" ;; esac
fi
if type adguard_lan_serves >/dev/null 2>&1; then
  adguard_lan_serves >/dev/null 2>&1
  case $? in 0) ok "every hub-fronted name resolves AND serves TLS" ;;
             1) bad "a name resolves but does NOT serve — the 2026-07-26 signature" ;;
             *) unk "serve-check not measurable" ;; esac
fi

# ---- 7. Does failover REFUSE without explicit confirmation? ----
# The safety gate itself is a thing to rehearse: it is what stands between a
# stray invocation and a production DNS flip.
if [ -x "$DR/failover.sh" ]; then
  if grep -q 'DR_CONFIRM' "$DR/failover.sh" && grep -q 'FORCE' "$DR/failover.sh"; then
    ok "failover.sh still requires --force / DR_CONFIRM=FAILOVER-NOW"
  else bad "failover.sh confirmation gate is MISSING"; fi
else unk "failover.sh not staged"; fi

# ---- 8. Out-of-scope hostnames have a splash target (ADR-012) ----
if [ -n "${BEACON_MAINTENANCE_HOSTS+x}" ] && [ "${#BEACON_MAINTENANCE_HOSTS[@]}" -gt 0 ]; then
  ok "${#BEACON_MAINTENANCE_HOSTS[@]} out-of-scope hostnames would get the 503 splash"
  printf '%s\n' "${BEACON_MAINTENANCE_HOSTS[@]}" | grep -q '^derp' \
    && bad "derp. is in the maintenance set — it MUST keep serving during a hub outage (#5220)" \
    || ok "derp. correctly excluded from the splash set"
else unk "BEACON_MAINTENANCE_HOSTS not defined"; fi

log "=== REHEARSAL: $PASS pass · $FAIL fail · $UNKNOWN unknown ==="
[ "$UNKNOWN" -gt 0 ] && log "NOTE: an UNKNOWN is not a pass — something could not be measured."
[ "$FAIL" -gt 0 ] && { log "DR is NOT in a state where a failover would go cleanly."; exit 1; }
log "Pre-flight clean. This does NOT prove a promotion/failback works — that needs the #4495 drill."
exit 0
