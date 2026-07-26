#!/bin/bash
# ============================================================================
# derper — a SECOND sovereign DERP region, outside the Starbase failure domain.
# Task #5220 · ADR-013 (sovereign relays only) · spec:
#   docs/superpowers/specs/2026-07-26-derp-relay-off-hub-5220.md
#
# WHY
# The Starbase hosted the ONLY DERP region (headscale's embedded region 900), so
# the relay of last resort sat inside the very failure domain it exists to
# survive. During the 2026-07-25 outage, node-to-node paths that needed a relay
# went fully dark instead of degrading. It also made `tailscale netcheck`
# self-referential: it could only STUN against the hub it was measuring, so
# "UDP: false" was unmeasurable and had previously been misread as a blocked port.
#
# DESIGN — every choice here is load-bearing:
#
#   ADDITIVE. Region 900 on the hub is left completely untouched. This ADDS
#   region 901 on Beacon. Rollback = delete the map + the derp.paths line.
#   Additive is also what makes -verify-clients safe (see below).
#
#   OPTION A (derper on :8443, own cert). Caddy owns :443 on Beacon for ~20
#   front-door hostnames, so derper cannot take the standard port. The usual
#   objection to a non-standard port is that restrictive networks block it —
#   but every fleet node is a fixed host on a known network, and the ONE roaming
#   client (shuttle-kytran) falls back to region 900 if :8443 is blocked.
#   Additive deployment neutralises A's only real weakness.
#
#   BUILT FROM OFFICIAL SOURCE, VERSION-PINNED. Tailscale publishes no official
#   derper image; the only pullable one is third-party, which sits badly against
#   ADR-013. We compile tailscale.com/cmd/derper at the SAME version the fleet
#   runs, in a throwaway golang container. Pin DERPER_VERSION to match
#   `tailscale version` on the nodes.
#
#   CERT SYNC IS AUTOMATED, NOT MANUAL. Caddy owns ACME (it already does for the
#   other hostnames); a timer copies the cert to derper's certdir and restarts it
#   on change. A hand-copied cert silently expires in ~60 days — the SAME class
#   of latent failure as the ad-hoc SSH tunnel that took Beacon and Citadel off
#   the control plane for a month (KB #284829). Automate it or it will rot.
#
#   -verify-clients. Only nodes in THIS tailnet may relay, so a publicly
#   reachable relay is not an open one. It depends on Beacon's local tailscaled;
#   if that drops, derper refuses clients. Acceptable ONLY because region 900
#   still exists — the fleet degrades rather than breaks.
#
#   -http-port -1. derper also opens :80 by default (ACME/redirect). Caddy owns
#   :80 here, so the HTTP listener MUST be disabled or derper exits with
#   "listen tcp :80: bind: address already in use".
#
# ⚠️ UFW: Beacon runs `policy DROP` and allowed only 22/80/443. Without the
# rules below, derper listens happily on *:8443 while every external client is
# silently dropped — advertising a region nothing can reach, which is exactly
# the ADR-009 failure (pointing clients at a host that cannot serve them).
#
# Run ON Beacon as root.  Idempotent.
# ============================================================================
set -euo pipefail

DERP_HOST="${DERP_HOST:-derp.kytranempowerment.com}"
DERP_PORT="${DERP_PORT:-8443}"
STUN_PORT="${STUN_PORT:-3478}"
# Keep in step with `tailscale version` on the fleet.
DERPER_VERSION="${DERPER_VERSION:-v1.98.3}"
# tailscale.com pins a Go floor well above golang:1.23; use a current toolchain.
GO_IMAGE="${GO_IMAGE:-golang:alpine}"
PREFIX=/opt/derp

log(){ echo "[derp-install] $*"; }

log "1/6 prerequisites"
command -v docker >/dev/null || { echo "docker required (used only to BUILD)"; exit 1; }
mkdir -p "$PREFIX/bin" "$PREFIX/certs"

log "2/6 build derper $DERPER_VERSION from official tailscale source"
if [ ! -x "$PREFIX/bin/derper" ] || [ "${FORCE_REBUILD:-0}" = "1" ]; then
    docker run --rm -v "$PREFIX/bin":/out "$GO_IMAGE" sh -c \
        "apk add --no-cache git >/dev/null 2>&1; GOBIN=/out go install tailscale.com/cmd/derper@${DERPER_VERSION}"
    [ -x "$PREFIX/bin/derper" ] || { echo "BUILD FAILED"; exit 1; }
else
    log "  already built (FORCE_REBUILD=1 to rebuild)"
fi

log "3/6 Caddy site block so Caddy obtains + renews the LE cert"
if ! grep -q "$DERP_HOST" /etc/caddy/Caddyfile; then
    cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak-derp-$(date -u +%Y%m%d-%H%M%S)"
    cat >> /etc/caddy/Caddyfile <<EOF

# $DERP_HOST — exists so Caddy obtains/renews the cert derper reads (certmode
# manual). derper listens on :$DERP_PORT; Caddy keeps :443. Task #5220.
$DERP_HOST {
	respond "derp relay endpoint is :$DERP_PORT" 200
}
EOF
    # VALIDATE BEFORE RELOADING — this file fronts ~20 hostnames.
    caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null
    systemctl reload caddy
    log "  Caddyfile validated + reloaded"
else
    log "  site block already present"
fi

log "4/6 cert sync (automated — a hand-copied cert expires silently)"
cat > "$PREFIX/sync-cert.sh" <<EOF
#!/bin/bash
set -euo pipefail
H=$DERP_HOST
SRC=\$(ls -d /var/lib/caddy/.local/share/caddy/certificates/*/\$H 2>/dev/null | head -1)
DST=$PREFIX/certs
[ -n "\$SRC" ] && [ -f "\$SRC/\$H.crt" ] || { echo "caddy cert for \$H not found"; exit 1; }
if ! cmp -s "\$SRC/\$H.crt" "\$DST/\$H.crt" 2>/dev/null; then
  install -m 644 "\$SRC/\$H.crt" "\$DST/\$H.crt"
  install -m 600 "\$SRC/\$H.key" "\$DST/\$H.key"
  echo "cert updated — restarting derper"
  systemctl restart derper || true
fi
EOF
chmod +x "$PREFIX/sync-cert.sh"

cat > /etc/systemd/system/derper.service <<EOF
[Unit]
Description=Tailscale DERP relay (region 901, Beacon) — task #5220
After=network-online.target caddy.service tailscaled.service
Wants=network-online.target

[Service]
ExecStart=$PREFIX/bin/derper -hostname $DERP_HOST -a :$DERP_PORT -stun -stun-port $STUN_PORT -certmode manual -certdir $PREFIX/certs -http-port -1 -verify-clients
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/derper-cert.service <<EOF
[Unit]
Description=Sync Caddy LE cert into derper certdir
[Service]
Type=oneshot
ExecStart=$PREFIX/sync-cert.sh
EOF

cat > /etc/systemd/system/derper-cert.timer <<'EOF'
[Unit]
Description=Daily derper cert sync (Caddy renews ~60d; unsynced = silent expiry)
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF

log "5/6 firewall — without this derper listens but every client is DROPPED"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow "$DERP_PORT/tcp" comment "derper DERP relay (#5220)" >/dev/null
    ufw allow "$STUN_PORT/udp" comment "derper STUN (#5220)" >/dev/null
    log "  ufw: $DERP_PORT/tcp + $STUN_PORT/udp allowed"
fi

log "6/6 start"
"$PREFIX/sync-cert.sh"
systemctl daemon-reload
systemctl enable --now derper.service derper-cert.timer >/dev/null

sleep 3
systemctl is-active --quiet derper || { journalctl -u derper -n 20 --no-pager; exit 1; }
log "derper active on :$DERP_PORT (STUN :$STUN_PORT)"

cat <<EOF

NEXT (on the hub, not here):
  1. Copy headscale/derp-beacon.yaml into the headscale data volume:
       docker cp headscale/derp-beacon.yaml archie_headscale:/var/lib/headscale/derp-beacon.yaml
     (config.yaml is mounted as a single FILE, so the map lives in the volume to
      avoid a docker-compose change.)
  2. headscale config.yaml: derp.paths -> [/var/lib/headscale/derp-beacon.yaml]
  3. VALIDATE OFFLINE FIRST — check the EXIT CODE, not just absent output:
       docker exec archie_headscale headscale configtest; echo "exit=\$?"
  4. VERIFY THE ENDPOINT IS REACHABLE BEFORE ADVERTISING IT. A region clients
     cannot reach is worse than no region (ADR-009):
       openssl s_client -connect $DERP_HOST:$DERP_PORT -servername $DERP_HOST
       ... then GET /derp/probe  ->  expect HTTP/1.1 200 OK
  5. docker compose restart archie_headscale
  6. Confirm with the AUTHORITATIVE tool, from a node:
       tailscale netcheck     # expect BOTH regions + "UDP: true"
EOF
