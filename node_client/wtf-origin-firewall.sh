#!/bin/sh
# #4319 Phase 1 — mesh-only lock for the WTF origins on Citadel.
#   8103 wtf-consumer (what-the-fact.com origin, behind the Beacon NA edge)
#   8104 wtf-tech (what-the-fact.tech — served by Citadel's own ingress Caddy)
#   8106 wtf-ingest-api (internal entity-graph ingest — mesh/bridge callers only)
#
# Each origin must be reachable ONLY via: the mesh (the edge + hub, 100.64.0.0/10),
# the docker bridge (Citadel's own ingress Caddy + sibling product containers,
# 172.16.0.0/12), and loopback. Docker publishes these ports on 0.0.0.0 PAST UFW
# (nat/FORWARD path), so a UFW rule does NOT protect them. Docker DOES honour the
# DOCKER-USER chain, so we allow those sources (RETURN) and DROP every other
# (public) source there. Mirrors socks-egress-firewall.sh (#4014).
# Idempotent — safe to re-run. Extended to 8104/8106 per #4558.
set -eu

PORTS="8103 8104 8106"
MESH="100.64.0.0/10"
BRIDGE="172.16.0.0/12"
LOOP="127.0.0.0/8"

# DOCKER-USER exists only once Docker has started. Wait briefly for it.
i=0
while ! iptables -L DOCKER-USER -n >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -gt 30 ] && { echo "DOCKER-USER chain never appeared — is Docker up?" >&2; exit 1; }
    sleep 1
done

add4() { # $1 = port, $2 = match args (may be empty), $3 = target
    if ! iptables -C DOCKER-USER -p tcp --dport "$1" $2 -j "$3" 2>/dev/null; then
        iptables -I DOCKER-USER -p tcp --dport "$1" $2 -j "$3"
    fi
}

add6() {
    if ! ip6tables -C DOCKER-USER -p tcp --dport "$1" $2 -j "$3" 2>/dev/null; then
        ip6tables -I DOCKER-USER -p tcp --dport "$1" $2 -j "$3"
    fi
}

HAVE6=0
ip6tables -L DOCKER-USER -n >/dev/null 2>&1 && HAVE6=1

for PORT in $PORTS; do
    # Insert DROP FIRST, then the RETURNs, so (with -I prepend) the RETURNs end up
    # ABOVE the DROP: 100.64 / 172.16 / 127 RETURN, then DROP.
    add4 "$PORT" "" DROP
    add4 "$PORT" "-s $LOOP" RETURN
    add4 "$PORT" "-s $BRIDGE" RETURN
    add4 "$PORT" "-s $MESH" RETURN

    # IPv6 — origins also publish [::]. Allow ULA (mesh/docker) + loopback, drop public GUA.
    if [ "$HAVE6" = 1 ]; then
        add6 "$PORT" "" DROP
        add6 "$PORT" "-s ::1/128" RETURN
        add6 "$PORT" "-s fc00::/7" RETURN
    fi
done

echo "WTF origin mesh-only lock applied for tcp ports: $PORTS (mesh+bridge+loopback RETURN, public DROP)"
