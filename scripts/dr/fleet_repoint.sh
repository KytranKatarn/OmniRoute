#!/bin/bash
# ============================================================================
# fleet_repoint.sh — ONE fleet node list + repoint/verify helpers, shared by
# failover.sh (hub -> DR), failback.sh restore-normal and force_reset_to_hub.sh
# (DR -> hub). Task #5278 (DR drill defect #7).
#
# WHY THIS FILE EXISTS. The 2026-07-27 drill repointed the three global
# outposts at boston-2 (failover.sh step 4) but the rollback that was actually
# used (force_reset_to_hub.sh + setup_replica.sh) restored Beacon, the watch
# products, the DB and the DR flags — and NEVER repointed the nodes. All three
# outposts sat orphaned for 9.6h with re-registration loops armed (the
# KB #270611 storm precondition) while the drill was recorded as a clean
# success. The node list lived only inside failover.sh, so no rollback path
# could iterate "the same nodes failover touched". This file makes the list a
# shared fact, like beacon_flip.sh does for the Beacon port map.
#
# SOURCED, not executed. Callers must define log() and DR before sourcing, and
# must degrade to a LOUD no-op when this file is not staged — never to a
# silent skip (skipping a repoint strands nodes; see #5278).
#
# A node list is not a rollback until the heartbeat comes back — after any
# repoint-to-hub, call fleet_verify_heartbeats and treat a timeout as a FAIL.
# ============================================================================

# The SAME nodes failover.sh repoints (global outposts: root@, /opt/archie-node,
# HUB_URL is BAKED container env — repoint.sh recreates the container, KB #270232).
# outpost-us (kytran@, .2) is deliberately NOT here: it hosts watch products +
# the SMTP relay, and its hub URLs are handled by the watch-product .env pass.
# EMPTY since 2026-08-29: singapore/lithuania/uk were retired, and they were the
# only nodes this list ever held. Deliberately NOT replaced with outpost-us or the
# Starships — the comment above explains why each is excluded. An empty list makes
# every repoint helper a clean no-op; callers already tolerate that.
FLEET_REPOINT_NODES=()
FLEET_REPOINT_MESH_IPS=""

# LAN Starships (Windows Docker Desktop, Famil@ SSH). Their sync containers keep
# HUB_URL=hub permanently and self-heal via node_sync v3 DR_HUB_URL auto-switch
# (switches to DR after 5 heartbeat failures, back after 3 good primary checks),
# so they never need a durable repoint — only a force-recreate to make the
# switch (either direction) immediate instead of ~2.5 min. A powered-down ship
# is fine: on boot node_sync starts against the primary HUB_URL.
FLEET_STARSHIP_MESH=( "100.64.0.3" "100.64.0.6" )

# Hub-side identity for heartbeat verification (matches failback.sh conventions).
FLEET_HUB_MESH="${FLEET_HUB_MESH:-100.64.0.4}"
FLEET_HUB_SSH="${FLEET_HUB_SSH:-kytran@$FLEET_HUB_MESH}"
FLEET_HUB_DB="${FLEET_HUB_DB:-archie_database}"

# The fleet SSH key has TWO historical paths on boston-2 ($DR/.ssh/id_ed25519 in
# failover/failback, $DR/.fleet_key in force_reset/rehearse). Resolve whichever
# exists so callers stop hardcoding one path and missing the other.
fleet_ssh_key(){
  local k
  for k in "${FLEET_KEY:-}" "$DR/.ssh/id_ed25519" "$DR/.fleet_key"; do
    [ -n "$k" ] && [ -f "$k" ] && { echo "$k"; return 0; }
  done
  return 1
}

# fleet_repoint_outposts <target_mesh_ip>
# Repoint every global outpost's sync container at <target>. Per-node and
# non-fatal — a dead node must not abort a failover OR a rollback. Returns the
# number of nodes that could NOT be repointed (0 = all done).
fleet_repoint_outposts(){
  local target="${1:?usage: fleet_repoint_outposts <mesh_ip>}" key node failed=0
  # No global outposts remain (singapore/lithuania/uk retired 2026-08-29). Return
  # BEFORE touching the ssh key or expanding the array: "${arr[@]}" on an empty array
  # is an unbound-variable error under the `set -u` that the sourcing scripts use.
  if [ "${#FLEET_REPOINT_NODES[@]}" -eq 0 ]; then
    log "  no global outposts to repoint (none remain)."
    return 0
  fi
  if ! key="$(fleet_ssh_key)"; then
    log "  WARN: no fleet SSH key ($DR/.ssh/id_ed25519 or $DR/.fleet_key) — cannot repoint outposts."
    log "        manual, per node: ssh <node> /opt/archie-node/repoint.sh $target"
    return "${#FLEET_REPOINT_NODES[@]}"
  fi
  for node in "${FLEET_REPOINT_NODES[@]}"; do
    if ssh -i "$key" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$node" \
         "/opt/archie-node/repoint.sh $target" >/dev/null 2>&1; then
      log "  repointed $node -> $target"
    else
      log "  WARN: could not repoint $node -> $target (down? on power-up run: /opt/archie-node/repoint.sh $target)"
      failed=$((failed+1))
    fi
  done
  return "$failed"
}

# fleet_kick_starships — force-recreate each Starship's sync container so
# node_sync's primary/DR selection re-evaluates NOW instead of in ~2.5 min.
# Always returns 0: a powered-down ship self-heals on boot by design.
fleet_kick_starships(){
  local key ship
  key="$(fleet_ssh_key)" || { log "  (no fleet SSH key — Starships self-heal in ~2.5 min)"; return 0; }
  for ship in "${FLEET_STARSHIP_MESH[@]}"; do
    if ssh -i "$key" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "Famil@$ship" \
         "docker compose -f C:\\archie-node\\docker-compose.yml up -d --force-recreate --no-deps sync" >/dev/null 2>&1; then
      log "  Starship $ship: node_sync recreated (re-evaluates primary vs DR now)"
    else
      log "  (Starship $ship unreachable — powered down or resting; self-heals on boot)"
    fi
  done
  return 0
}

# fleet_verify_heartbeats [max_age_s=300] [wait_s=180]
# THE VERIFY STEP (#5278): poll the HUB DB (over hub SSH) until every repointed
# outpost's remote_nodes.last_heartbeat is younger than max_age_s, waiting up to
# wait_s. Prints per-node ages either way. Returns 0 only when ALL are fresh.
# Only meaningful after a repoint TO THE HUB — during a failover the hub is down
# and there is nothing to verify against.
fleet_verify_heartbeats(){
  local max_age="${1:-300}" wait_s="${2:-180}" key deadline out stale name age
  # Nothing to verify is VACUOUSLY verified — but say so out loud rather than
  # returning a bare success. An empty list would otherwise build `mesh_ip IN ()`,
  # a SQL syntax error, whose empty result reads as "could not read heartbeats" and
  # reports "repoint UNVERIFIED" during a real failback.
  if [ -z "$FLEET_REPOINT_MESH_IPS" ]; then
    log "  no global outposts remain — no heartbeats to verify (nothing was repointed)."
    return 0
  fi
  key="$(fleet_ssh_key)" || { log "  WARN: no fleet SSH key — cannot verify heartbeats from here."; return 1; }
  deadline=$(( $(date +%s) + wait_s ))
  while :; do
    out="$(ssh -i "$key" -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$FLEET_HUB_SSH" \
      "docker exec $FLEET_HUB_DB psql -U archie -d archie -At -F'|' -c \
       \"SELECT node_name, COALESCE(EXTRACT(EPOCH FROM NOW()-last_heartbeat)::int, 999999) FROM remote_nodes WHERE mesh_ip IN ($FLEET_REPOINT_MESH_IPS) ORDER BY node_name;\"" 2>/dev/null)"
    if [ -z "$out" ]; then
      log "  WARN: could not read heartbeats from the hub DB (hub SSH or psql failed) — repoint UNVERIFIED."
      return 1
    fi
    stale=0
    while IFS='|' read -r name age; do
      [ -n "$name" ] || continue
      [ "${age:-999999}" -le "$max_age" ] 2>/dev/null || stale=$((stale+1))
    done <<< "$out"
    if [ "$stale" -eq 0 ]; then
      while IFS='|' read -r name age; do
        [ -n "$name" ] && log "  heartbeat OK: $name (${age}s)"
      done <<< "$out"
      log "  all outpost heartbeats fresh (<${max_age}s) — repoint VERIFIED."
      return 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "  FAIL: $stale outpost(s) still silent after ${wait_s}s:"
      while IFS='|' read -r name age; do
        [ -n "$name" ] || continue
        [ "${age:-999999}" -gt "$max_age" ] 2>/dev/null && log "    $name last_heartbeat ${age}s ago"
      done <<< "$out"
      log "  The repoint did NOT take — a node list is not a rollback until the heartbeat returns (#5278)."
      return 1
    fi
    sleep 15
  done
}
