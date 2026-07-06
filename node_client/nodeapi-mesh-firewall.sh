#!/bin/sh
# Mesh-only firewall for node_api :3001 (security fix — KB #278720, #3763 gate).
#
# node_api publishes :3001 on 0.0.0.0 and its inbound endpoints are UNAUTHENTICATED
# (the design assumes node_api is mesh-internal: hub<->node over Headscale). But
# :3001 was never firewalled, so on public VPS nodes /diagnostics + /api/jobs/execute
# etc. were reachable from the open internet. Docker publishes ports PAST UFW (via the
# nat/FORWARD path), so a UFW rule does NOT protect it — Docker DOES honour DOCKER-USER.
#
# Allow: mesh peers (100.64.0.0/10, the hub<->node path), loopback + the docker bridge
#   (172.16.0.0/12) — node_sync forwards firewall-rule requests to node_api on
#   localhost:3001 (node_sync.py _handle_firewall_rule), so those MUST stay open.
# Drop: every other (public-internet) source to :3001.
#
# Idempotent: safe to run repeatedly (boot, redeploy, docker restart).
set -eu

PORT=3001
ALLOW="100.64.0.0/10 127.0.0.0/8 172.16.0.0/12"

# DOCKER-USER exists only once Docker has started. Wait briefly for it.
i=0
while ! iptables -L DOCKER-USER -n >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -gt 30 ] && { echo "DOCKER-USER chain never appeared — is Docker up?" >&2; exit 1; }
    sleep 1
done

# Allow the trusted sources (RETURN = leave DOCKER-USER, let Docker route normally).
# Insert at the top so they are evaluated before the DROP below.
for cidr in $ALLOW; do
    if ! iptables -C DOCKER-USER -p tcp --dport "$PORT" -s "$cidr" -j RETURN 2>/dev/null; then
        iptables -I DOCKER-USER 1 -p tcp --dport "$PORT" -s "$cidr" -j RETURN
        echo "Allowed $cidr -> tcp/$PORT"
    else
        echo "Allow $cidr -> tcp/$PORT already present"
    fi
done

# Drop everything else to :3001 (the public internet). Appended, so it runs after the
# RETURN allows above.
if ! iptables -C DOCKER-USER -p tcp --dport "$PORT" -j DROP 2>/dev/null; then
    iptables -A DOCKER-USER -p tcp --dport "$PORT" -j DROP
    echo "Inserted DOCKER-USER DROP for non-local tcp/$PORT (public blocked)"
else
    echo "DOCKER-USER DROP for tcp/$PORT already present"
fi
