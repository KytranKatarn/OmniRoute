#!/bin/bash
# ============================================================================
# mesh_bootstrap.sh — Re-bootstrap the Headscale mesh when VPS nodes are
# stuck offline after a hub outage.
#
# Run FROM THE HUB (192.168.1.200) — not from boston-2.
# Reason: creates REVERSE SSH tunnels hub→node to expose hub's Headscale
# at localhost:18095 on each node, bypassing the circular dependency where
# nodes can't reach mesh.kytranempowerment.com because Beacon is also offline.
#
#   bash /mnt/archie_brain/scripts/dr/mesh_bootstrap.sh
#
# What it does:
#   1. Generates a fresh reusable Headscale pre-auth key (2h TTL)
#   2. For each accessible node in PARALLEL:
#      - Creates reverse SSH tunnel: hub:8095 → node:18095
#      - Runs: tailscale up --login-server=http://127.0.0.1:18095 --authkey=<key> --reset
#   3. Waits 20s for WireGuard tunnels to establish
#   4. Restarts archie_outpost_proxy on outpost-us (Docker-based tailscale)
#   5. Reports Headscale online count
#
# Nodes bootstrapped directly (have SSH access from hub):
#   boston-2  root@2.25.133.122     (native tailscaled)
#   outpost-us kytran@76.13.107.109 (archie_outpost_proxy Docker container)
#
# Beacon and the singapore/lithuania/uk outposts were RETIRED (remote_nodes.status
# = 'retired'; Beacon's VPS was removed by Hostinger 2026-08-28, the three outposts
# were sunset 2026-08-29). Bootstrapping Beacon here dialled a host that no longer
# exists, and the old note claimed those three reconnect "once Beacon is back on
# mesh" — a recovery path through a machine that is gone. Citadel inherited the
# front door; mesh.kytranempowerment.com now resolves there.
# ============================================================================
set -uo pipefail
SSH_KEY="${SSH_KEY:-/home/kytran/.ssh/id_ed25519}"
TUNNEL_PORT=18095
LOG="/tmp/mesh_bootstrap_$(date +%Y%m%d_%H%M%S).log"
pids=()

log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "=== mesh_bootstrap.sh START ==="

# ---- 1. Generate pre-auth key ----
log "1) Generating Headscale pre-auth key..."
AUTHKEY=$(docker exec archie_headscale headscale preauthkeys create \
  --user archie-fleet --reusable --expiration 2h 2>/dev/null | tail -1 | tr -d '[:space:]')
[ -n "$AUTHKEY" ] || { log "ABORT: could not generate pre-auth key"; exit 1; }
log "  Key generated (length=${#AUTHKEY})"

# ---- 2. Bootstrap each node in parallel ----
log "2) Bootstrapping nodes in parallel..."

bootstrap_node(){
  local label="$1" ssh_user_host="$2" tailscale_cmd="$3"
  local tunnel_pid
  # Create reverse tunnel: hub:8095 exposed on node:TUNNEL_PORT
  ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
      -o ServerAliveInterval=15 -o ExitOnForwardFailure=yes \
      -f -N -R "${TUNNEL_PORT}:127.0.0.1:8095" "$ssh_user_host" 2>/dev/null
  tunnel_pid=$!
  sleep 2
  # Reconnect via tunnel
  if ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
         "$ssh_user_host" "$tailscale_cmd" >/dev/null 2>&1; then
    log "  $label: reconnected via tunnel"
  else
    log "  WARN: $label tailscale up failed (may reconnect on its own)"
  fi
}

# boston-2 (native tailscaled)
bootstrap_node "boston-2" "root@2.25.133.122" \
  "tailscale up --login-server=http://127.0.0.1:${TUNNEL_PORT} --authkey=${AUTHKEY} --reset" &
pids+=($!)

# Wait for direct-tailscale nodes
wait "${pids[@]}" 2>/dev/null || true
pids=()

# outpost-us (Docker-based — restart container after tunnel to trigger reconnect)
log "  outpost-us: restarting archie_outpost_proxy..."
ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
    "kytran@76.13.107.109" "docker restart archie_outpost_proxy" >/dev/null 2>&1 \
  && log "  outpost-us: proxy restarted" \
  || log "  WARN: outpost-us proxy restart failed"

# ---- 3. Wait for tunnels to establish ----
log "3) Waiting 20s for WireGuard tunnels to establish..."
sleep 20

# ---- 4. Report results ----
log "4) Headscale node status:"
online=$(docker exec archie_headscale headscale nodes list 2>/dev/null | grep -c "online" || echo 0)
total=$(docker exec archie_headscale headscale nodes list 2>/dev/null | grep -c "" || echo 0)
log "  ${online}/${total} nodes online"

# Ping boston-2 as quick mesh verify
if ping -c 1 -W 3 100.64.0.10 >/dev/null 2>&1; then
  log "  boston-2 ping: OK (mesh working)"
else
  log "  WARN: boston-2 ping failed — mesh still recovering, retry in 30s"
fi

log "=== mesh_bootstrap.sh COMPLETE — log: $LOG ==="
log "Note: singapore/lithuania/uk will reconnect automatically once Beacon is on mesh."
