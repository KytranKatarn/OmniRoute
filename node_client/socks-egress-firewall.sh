#!/bin/sh
# #4014 — mesh-only firewall for the node_socks SOCKS5 egress proxy.
#
# node_socks publishes :1080 on 0.0.0.0 (a tailscale-IP bind is unreachable from
# mesh peers). Docker publishes ports PAST UFW (via the nat/FORWARD path), so a
# UFW rule does NOT protect it — an unauthenticated proxy on 0.0.0.0 would be a
# public open relay. Docker DOES honour the DOCKER-USER chain, so we DROP every
# non-mesh source to :1080 there. Mesh peers (100.64.0.0/10) fall through.
#
# Idempotent: safe to run repeatedly (boot, redeploy, docker restart).
set -eu

MESH_CIDR="100.64.0.0/10"
PORT=1080

# DOCKER-USER exists only once Docker has started. Wait briefly for it.
i=0
while ! iptables -L DOCKER-USER -n >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -gt 30 ] && { echo "DOCKER-USER chain never appeared — is Docker up?" >&2; exit 1; }
    sleep 1
done

# Insert the DROP rule once (check first so re-runs don't stack duplicates).
if ! iptables -C DOCKER-USER -p tcp --dport "$PORT" ! -s "$MESH_CIDR" -j DROP 2>/dev/null; then
    iptables -I DOCKER-USER -p tcp --dport "$PORT" ! -s "$MESH_CIDR" -j DROP
    echo "Inserted DOCKER-USER DROP for non-mesh tcp/$PORT"
else
    echo "DOCKER-USER DROP for non-mesh tcp/$PORT already present"
fi
