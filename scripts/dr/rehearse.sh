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

# ---- 5b. Is the mesh. UPSTREAM still the tunnel? (task #5261) ----
# Checks 1-5 all answer "what does mesh. RESOLVE to". NONE of them asked what Beacon
# PROXIES to, and that is the half that stranded the fleet on 2026-07-26: the vhost
# pointed at 100.64.0.4:8095 (a MESH IP), so a hub reboot deadlocked — nodes needed the
# control plane to rejoin the mesh, and the control plane was only reachable over the
# mesh. This harness reported a clean 14/14 throughout. A green board that cannot see
# the failure mode is worse than no board.
#
# Correct upstream is the reverse tunnel (archie-mesh-tunnel.service on the hub):
#   reverse_proxy http://127.0.0.1:8095
# The hub's PUBLIC IP is also wrong — a dynamic residential lease that collides with
# the DDNS updater (#5260) and needs an inbound forward a router reset silently drops.
# MEASURED FROM HERE (boston-2), which is an OFF-HUB vantage. That matters: the hub can
# always reach its own Headscale regardless of whether Beacon or DNS work, so a check run
# on the hub proves nothing about the path real nodes use.
#
# This asserts BEHAVIOUR (does the control plane actually answer through Beacon?) rather
# than CONFIG. boston-2 has no SSH trust to Beacon, so the Caddyfile cannot be read from
# here -- see the caveat below. Behaviour is the better assertion anyway: it exercises
# DNS -> Beacon TLS -> upstream -> headscale in one shot, and it is the check that would
# have gone RED during the 2026-07-26 outage while every other check stayed green.
if curl -sf -o /dev/null --max-time 12 "https://mesh.kytranempowerment.com/key?v=118" 2>/dev/null; then
  ok "mesh. control plane ANSWERS end-to-end from off-hub (DNS -> Beacon -> upstream -> headscale)"
else
  bad "mesh. control plane does NOT answer from boston-2 — nodes cannot enroll or rotate keys; check archie-mesh-tunnel.service on the hub and the Beacon mesh. vhost"
fi

# CAVEAT (task #5261, still open): the above proves the chain WORKS, not that the upstream
# is the durable one. A mesh. vhost pointed at the hub's dynamic public IP would pass this
# check today and break on the next DHCP lease (#5260); one pointed at 100.64.0.4 would
# pass while the hub is up and deadlock on the next reboot. Asserting the upstream VALUE
# needs boston-2 -> Beacon SSH trust, which does not exist and is a deliberate decision to
# make consciously rather than as a side effect of a monitoring change.
unk "mesh. upstream VALUE unverified (no boston-2->Beacon SSH trust) — behaviour passed, config unasserted"

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

# ---- 9. Fleet nodes point at the HUB, and their heartbeats are fresh (#5278) ----
# The 2026-07-27 drill left all three global outposts with HUB_URL=boston-2 for
# 9.6h while this rehearsal reported all-pass: it validated shapes, not the
# outcome "every node heartbeats the hub" (same class as the #5265 splash
# finding — the rehearsal must assert outcomes). Two-part check, from here:
#   a) each REACHABLE outpost's baked HUB_URL is the hub mesh IP (the drill
#      signature is HUB_URL=100.64.0.10 while the machine is mesh-online)
#   b) remote_nodes.last_heartbeat < 5 min for every outpost, read from the
#      LOCAL replica — it streams from the hub, so a fresh replica answers with
#      hub truth (if check 1 failed, this data is stale and check 1 is the story)
# Starships are deliberately excluded: they self-heal via node_sync DR_HUB_URL
# and rest overnight, so a naive check here would fail on a healthy cluster.
_fleet_key=""
for _k in "$FLEET_KEY" "$DR/.ssh/id_ed25519" "$DR/.fleet_key"; do
  [ -n "$_k" ] && [ -f "$_k" ] && { _fleet_key="$_k"; break; }
done
if [ -z "$_fleet_key" ]; then
  unk "no fleet SSH key on this host — outpost HUB_URL not checked"
else
  # singapore/lithuania/uk retired 2026-08-29 — no global outpost remains to check.
  # Kept as an explicit empty set rather than deleted, so a future outpost is added
  # here and nowhere else. An UNKNOWN is never a pass, but "there are none" is a FACT.
  for _n in ${REHEARSE_OUTPOSTS:-}; do
    _url="$(ssh -i "$_fleet_key" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$_n" \
           "grep -h '^HUB_URL=' /opt/archie-node/sync.env 2>/dev/null || docker inspect archie_outpost_sync --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep '^HUB_URL='" 2>/dev/null | head -1)"
    case "$_url" in
      *"$HUB_MESH"*) ok "$_n HUB_URL points at the hub" ;;
      *"$DR_MESH"*)  bad "$_n HUB_URL points at boston-2 ($_url) — the #5278 drill signature; run /opt/archie-node/repoint.sh $HUB_MESH there" ;;
      "")            unk "$_n unreachable — HUB_URL not checked" ;;
      *)             bad "$_n HUB_URL is unexpected: $_url" ;;
    esac
  done
fi
# Empty mesh-IP set would build `IN ()` — a SQL syntax error whose empty result is
# indistinguishable from "unreadable". Report the real state instead of guessing.
_ips="${REHEARSE_OUTPOST_MESH_IPS:-}"
if [ -z "$_ips" ]; then
  ok "no global outposts remain to heartbeat-check (singapore/lithuania/uk retired 2026-08-29)"
  _hb=""
else
_hb="$(docker exec "$B2_CONTAINER" psql -U archie -d archie -p "$B2_PG" -tA -F'|' -c \
  "SELECT node_name, COALESCE(EXTRACT(EPOCH FROM NOW()-last_heartbeat)::int, 999999) FROM remote_nodes WHERE mesh_ip IN ($_ips) ORDER BY node_name;" 2>/dev/null)"
if [ -z "$_hb" ]; then unk "outpost heartbeats unreadable from the replica"
else
  while IFS='|' read -r _name _age; do
    [ -n "$_name" ] || continue
    if [ "${_age:-999999}" -le 300 ] 2>/dev/null; then ok "heartbeat fresh: $_name (${_age}s)"
    else bad "heartbeat STALE: $_name (${_age}s ago) — the node is not reporting to the hub (#5278)"; fi
  done <<< "$_hb"
fi
fi   # closes the empty-mesh-IP guard above

log "=== REHEARSAL: $PASS pass · $FAIL fail · $UNKNOWN unknown ==="
[ "$UNKNOWN" -gt 0 ] && log "NOTE: an UNKNOWN is not a pass — something could not be measured."
[ "$FAIL" -gt 0 ] && { log "DR is NOT in a state where a failover would go cleanly."; exit 1; }
log "Pre-flight clean. This does NOT prove a promotion/failback works — that needs the #4495 drill."
exit 0
