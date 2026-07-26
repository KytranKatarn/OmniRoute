#!/bin/bash
# ============================================================================
# Beacon front-door upstream flipping — SELECTIVE, data-driven. (Task #5214)
#
# Sourced by failover.sh / failback.sh / auto_failback.sh / force_reset_to_hub.sh
# so there is ONE implementation instead of four drifting copies of the same
# blanket `sed`.
#
# ---------------------------------------------------------------------------
# WHY THIS EXISTS — incident 2026-07-25
# ---------------------------------------------------------------------------
# Every one of those four scripts used to run, against Beacon's Caddyfile:
#
#     sed -i 's|100.64.0.4|100.64.0.10|g' /etc/caddy/Caddyfile
#
# That is a BLANKET substitution over the whole file. Beacon fronts ~20 upstreams
# and exactly ONE of them has a boston-2 counterpart, so a failover reliably took
# ~20 healthy hub-only services offline. During the incident KSO was "Up (healthy)"
# on the hub the entire time while server.kytranempowerment.com returned nothing,
# because Beacon had been told to route it to a machine that has never run it.
#
# Two failure modes, both structural:
#
#   1. It flips hostnames that have NO counterpart. Worse, it flips creed. (:8086)
#      and mesh. (:8095) BEFORE the steps that try to stage their DR counterparts
#      have run — so when that staging fails, the `else` branch logs "skipping"
#      while the hostname has ALREADY been pointed at a host with nothing on that
#      port. mesh. is the Headscale control plane; losing it during a mesh event
#      is the worst possible time.
#
#   2. It rewrites COMMENTS. Beacon's Caddyfile header documented the hub and DR
#      mesh IPs; a previous blanket revert rewrote the DR one, leaving the file
#      claiming "DR (boston-2) mesh IP: 100.64.0.4". The config corrupted its own
#      documentation.
#
# ADR-009 (decision #955): flipping a hostname to a host that cannot serve it is
# WORSE than leaving it pointed at a host that is merely down — the second is
# honest, the first sends operators to debug the wrong system.
#
# ---------------------------------------------------------------------------
# THE DESIGN WAS ALREADY THERE
# ---------------------------------------------------------------------------
# Beacon's Caddyfile defines a `(platform_backend)` snippet and every platform
# alias (platform./api./bridge./consciousness./mediahub.) does `import
# platform_backend`. Its own header says:
#
#     # (platform_backend) is the ONE line failover.sh flips hub<->boston-2 in DR
#
# The single-line flip was the intended contract. failover.sh simply never
# implemented it. This helper restores that intent.
#
# ---------------------------------------------------------------------------
# SAFETY PROPERTIES
# ---------------------------------------------------------------------------
#   * Every substitution is anchored on the literal `reverse_proxy http://`, so
#     comments, docs and unrelated text CANNOT be rewritten. Fixing bug (2) is a
#     property of the matcher, not of care taken at each call site.
#   * Substitutions are per-PORT, so a caller can only move the services it has
#     actually stood up.
#   * `caddy validate` failure ROLLS BACK from the .bak file. The old chain left
#     a modified-but-invalid Caddyfile on disk and merely skipped the reload — a
#     latent trap that detonates on the next unrelated reload.
#   * Every function is non-fatal and prints the exact manual command on failure,
#     matching how the DR scripts already treat Beacon (best-effort ingress).
# ============================================================================

# Callers define log(); fall back to a plain stamped echo when sourced bare.
if ! declare -F log >/dev/null 2>&1; then
    log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fi

# Beacon is addressed by PUBLIC IP on purpose — the mesh may be down in exactly
# the situations these scripts run.
BEACON_HOST="${BEACON_HOST:-root@2.25.170.252}"
FLEET_KEY="${FLEET_KEY:-/root/.ssh/id_ed25519}"
BEACON_CADDYFILE="${BEACON_CADDYFILE:-/etc/caddy/Caddyfile}"
BEACON_BAK_SUFFIX="${BEACON_BAK_SUFFIX:-.bak-dr}"
BEACON_SSH_OPTS="${BEACON_SSH_OPTS:--o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new}"

# ---------------------------------------------------------------------------
# THE DR-CAPABLE SERVICE MAP — the whole point of this file.
#
# A port belongs here ONLY if boston-2 actually serves it during a failover.
# Verified against scripts/dr/docker-compose.standby.yml and the boston-2
# staging steps in failover.sh on 2026-07-26:
#
#   3000  platform  — archie_platform_standby binds 100.64.0.10:3000.  ALWAYS.
#                     Covers platform./api./bridge./consciousness./mediahub.
#                     via the (platform_backend) snippet: one line, five hosts.
#   8086  C.R.E.E.D.— ONLY if failover.sh step 4e staged and started it.
#                     Covers creed.kytranempowerment.com + api.creed-ai.org.
#   8095  Headscale — ONLY if failover.sh step 4f staged and started the DR
#                     control plane. Flipped by that step, never up front.
#
# Everything else on Beacon is HUB-ONLY and must never be flipped:
#   3002 archie_comms · 8091 KBS (business./shop./store.) · 8085 KSO ·
#   8105 Media Hub · 8082 Nagios · 32400 Plex · 8096 Jellyfin · 3003 sandbox ·
#   7681 terminal · 7683 codex · 5354 AdGuard · 8265 Tdarr
#
# To make a new service DR-capable: stand up its counterpart on boston-2 FIRST,
# then add its port here. Adding a port without a counterpart re-creates the
# exact outage this file exists to prevent.
# ---------------------------------------------------------------------------
BEACON_DR_PORT_PLATFORM=3000
BEACON_DR_PORT_CREED=8086
BEACON_DR_PORT_HEADSCALE=8095

# All ports a failover is ever ALLOWED to move. Used by the failback/reset paths
# to revert exactly the set that could have been flipped, and by the verifier.
BEACON_DR_PORTS_ALL=("$BEACON_DR_PORT_PLATFORM" "$BEACON_DR_PORT_CREED" "$BEACON_DR_PORT_HEADSCALE")

_beacon_ssh() {
    # shellcheck disable=SC2086
    ssh -i "$FLEET_KEY" $BEACON_SSH_OPTS "$BEACON_HOST" "$@"
}

# beacon_flip_ports <from_ip> <to_ip> <label> <port> [port...]
#
# Repoints ONLY the named ports from <from_ip> to <to_ip>, then validates and
# reloads once. Rolls back on invalid config. Non-fatal: returns 1 and logs the
# manual command so the operator can finish by hand.
beacon_flip_ports() {
    local from_ip="$1" to_ip="$2" label="$3"
    shift 3
    local ports=("$@")

    if [ "${#ports[@]}" -eq 0 ]; then
        log "  Beacon: no ports requested for $label — nothing to flip."
        return 0
    fi

    if [ ! -f "$FLEET_KEY" ]; then
        log "  WARN: fleet key $FLEET_KEY missing — cannot flip Beacon ($label)."
        log "        manual: on Beacon, repoint ports ${ports[*]} $from_ip -> $to_ip in $BEACON_CADDYFILE + reload caddy"
        return 1
    fi

    # Anchored to the START of a line (optional leading whitespace only), so the
    # directive must be the first token. A comment line begins with '#', so it
    # can never match — including the header comment that QUOTES a reverse_proxy
    # line to document this very flip. Substring-anchoring is not enough: it
    # rewrites that comment, which is how Beacon's header came to claim
    # "DR (boston-2) mesh IP: 100.64.0.4".
    local sed_args="" p
    for p in "${ports[@]}"; do
        sed_args+=" -e 's|^\\([[:space:]]*\\)reverse_proxy http://${from_ip}:${p}|\\1reverse_proxy http://${to_ip}:${p}|'"
    done

    local remote="
        set -e
        cp -f '${BEACON_CADDYFILE}' '${BEACON_CADDYFILE}${BEACON_BAK_SUFFIX}'
        sed -i${sed_args} '${BEACON_CADDYFILE}'
        if caddy validate --adapter caddyfile --config '${BEACON_CADDYFILE}' >/dev/null 2>&1; then
            systemctl reload caddy
        else
            mv -f '${BEACON_CADDYFILE}${BEACON_BAK_SUFFIX}' '${BEACON_CADDYFILE}'
            echo 'CADDY_VALIDATE_FAILED_ROLLED_BACK' >&2
            exit 9
        fi
    "

    # Capture the ssh status explicitly. `$?` read after `if cmd; then ...; fi`
    # is the exit status of the IF STATEMENT (zero when no branch ran), not of
    # cmd — so the rollback case (rc=9) would be invisible.
    local rc=0
    _beacon_ssh "$remote" >/dev/null 2>&1 || rc=$?

    if [ "$rc" -eq 0 ]; then
        log "  Beacon: $label — ports ${ports[*]} now $from_ip -> $to_ip (validated + reloaded)."
        return 0
    fi

    if [ "$rc" -eq 9 ]; then
        log "  WARN: Beacon $label flip produced an INVALID Caddyfile — ROLLED BACK, Beacon unchanged."
    else
        log "  WARN: Beacon $label flip failed (ssh/rc=$rc) — Beacon unchanged."
    fi
    log "        manual: on Beacon, for each of ports ${ports[*]}:"
    log "          sed -i 's|reverse_proxy http://$from_ip:<port>|reverse_proxy http://$to_ip:<port>|g' $BEACON_CADDYFILE"
    log "          caddy validate --adapter caddyfile --config $BEACON_CADDYFILE && systemctl reload caddy"
    return 1
}

# beacon_upstream_count <ip> — echo how many `reverse_proxy http://<ip>:` upstreams
# Beacon currently serves. Echoes "?" when Beacon is unreachable so callers can
# tell "none left" apart from "could not measure".
beacon_upstream_count() {
    local ip="$1" out
    out="$(_beacon_ssh "grep -c 'reverse_proxy http://${ip}:' '${BEACON_CADDYFILE}' 2>/dev/null || true" 2>/dev/null | tr -d '[:space:]')"
    case "$out" in
        ''|*[!0-9]*) echo "?" ;;
        *)           echo "$out" ;;
    esac
}

# beacon_verify_selective <hub_ip> <min_hub_upstreams_expected>
#
# The assertion from task #5214: after a failover, Beacon must STILL be routing
# the hub-only services to the hub. A count of 0 means a blanket flip happened
# and ~20 healthy services just went dark.
beacon_verify_selective() {
    local hub_ip="$1" min_expected="${2:-10}" n
    n="$(beacon_upstream_count "$hub_ip")"
    if [ "$n" = "?" ]; then
        log "  Beacon verify: SKIPPED (Beacon unreachable — cannot measure)."
        return 0
    fi
    if [ "$n" -lt "$min_expected" ]; then
        log "  *** Beacon verify FAILED: only $n hub upstreams remain (expected >= $min_expected)."
        log "  *** A BLANKET flip has taken hub-only services (KSO/media/KBS/plex/...) offline."
        log "  *** Recover: /opt/archie-dr/force_reset_to_hub.sh"
        return 1
    fi
    log "  Beacon verify OK: $n hub-only upstreams still point at the hub (selective flip confirmed)."
    return 0
}

# dr_service_listening <host> <port> <label>
#
# "Is this service really serving, on the path BEACON uses?"  Shared by
# failover / failback / auto_failback / force_reset so the rule cannot drift
# between them (task #5225).
#
# HOST IS A PARAMETER ON PURPOSE. Failover asks "is boston-2 ready to receive
# these hostnames?" ($DR_MESH); failback asks "is the hub ready to take them
# back?" ($HUB_MESH). Both directions are the SAME question about a different
# host, and both were previously wrong:
#   • failover probed 127.0.0.1 — a loopback-only bind passed while Beacon still
#     got connection refused (fixed in e574508b5).
#   • failback probed nothing at all. Its only check was hub POSTGRES :5432, so
#     all three hostnames went back to a hub that might not be serving HTTP yet
#     — the same ADR-009 / decision #955 violation, in reverse.
#
# Beacon reaches these at <host>:<port> over the mesh, so that is what we probe.
# Residual gap (documented, not fixed here): probing from this host proves the
# service is bound beyond loopback, not that Beacon can traverse UFW to reach it.
# The complete check probes FROM Beacon via _beacon_ssh — task #5222.
dr_service_listening() {
    local host="$1" port="$2" label="${3:-service}" i
    local attempts="${DR_PROBE_ATTEMPTS:-10}" interval="${DR_PROBE_INTERVAL:-3}"
    for i in $(seq 1 "$attempts"); do
        if timeout 3 bash -c "echo > /dev/tcp/${host}/${port}" 2>/dev/null; then
            return 0
        fi
        sleep "$interval"
    done
    # Name the documented loopback-bind trap explicitly rather than reporting a
    # generic "not listening" — the operator fix differs completely.
    if timeout 3 bash -c "echo > /dev/tcp/127.0.0.1/${port}" 2>/dev/null; then
        log "  *** $label IS listening on 127.0.0.1:${port} but NOT on ${host}:${port}."
        log "  *** Loopback-only bind — Beacon cannot reach it. Bind 0.0.0.0 (or"
        log "  *** ${host}) and allow 100.64.0.0/10 to port ${port}. See DR_RUNBOOK.md."
    fi
    return 1
}

# beacon_flip_ports_when_ready <from_ip> <to_ip> <label> <port...>
#
# Flip ONLY the ports the destination is actually serving. A port the target
# cannot serve is LEFT WHERE IT IS — pointing a hostname at a host that cannot
# serve it is worse than leaving it pointed at one that is merely down
# (ADR-009 / decision #955). Reports each skip rather than failing silently.
beacon_flip_ports_when_ready() {
    local from_ip="$1" to_ip="$2" label="$3"; shift 3
    local ready=() skipped=() p
    for p in "$@"; do
        if dr_service_listening "$to_ip" "$p" "$label :$p"; then
            ready+=("$p")
        else
            skipped+=("$p")
            log "  SKIP :$p — ${to_ip} is not serving it; leaving that hostname where it is."
        fi
    done
    if [ "${#skipped[@]}" -gt 0 ]; then
        log "  $label: ${#skipped[@]} port(s) NOT flipped (${skipped[*]}) — destination not ready."
    fi
    if [ "${#ready[@]}" -eq 0 ]; then
        log "  $label: nothing to flip — ${to_ip} is serving none of the requested ports."
        return 1
    fi
    beacon_flip_ports "$from_ip" "$to_ip" "$label" "${ready[@]}"
}
