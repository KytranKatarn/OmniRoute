#!/bin/bash
# Block until the Headscale mesh IP exists, so Docker can bind containers to it.
#
# WHY: archie_database publishes 5432 on BOTH 192.168.1.200 and 100.64.0.4
# (docker-compose.yml, added by PR #822 / task #2142 — Citadel's DR replica dials
# 100.64.0.4:5432 via primary_conninfo, so the mesh bind is load-bearing).
# 100.64.0.4 lives on tailscale1, brought up by tailscaled-headscale.service.
# If Docker starts a container before that address is assignable:
#     failed to bind host port 100.64.0.4:5432/tcp: cannot assign requested address
# -> postgres exits 255 with NO network attached -> archie_platform restart-loops on
#    "could not translate host name archie_database" -> the whole hub is down.
# That is exactly what happened 2026-09-08 20:08 UTC.
#
# BOUNDED ON PURPOSE: on timeout we exit 0 and let Docker start anyway. This removes a
# RACE; it must never become a new way to wedge the host at boot. If the address really
# is missing, the DB fails loudly the same way it did before — which is the honest outcome.
IFACE="${ARCHIE_MESH_IFACE:-tailscale1}"
ADDR="${ARCHIE_MESH_ADDR:-100.64.0.4}"
for _ in $(seq 1 60); do
    if ip -4 addr show "$IFACE" 2>/dev/null | grep -qw "$ADDR"; then
        echo "mesh IP $ADDR present on $IFACE"
        exit 0
    fi
    sleep 1
done
echo "WARN: mesh IP $ADDR not present on $IFACE after 60s — starting Docker anyway" >&2
exit 0
