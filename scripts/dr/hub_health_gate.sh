#!/bin/bash
# Hub post-boot health gate (#4996) — detects "hub is UP but BROKEN".
#
# WHY THIS EXISTS
# On 2026-07-19 a 76-minute power outage was followed by a hub that came back
# "up" and yet was completely broken, and NOTHING noticed:
#   archie_database restarted with ZERO docker networks, so archie_platform and
#   archie_scheduler crash-looped on `could not translate host name
#   "archie_database"`. (`docker start` does NOT reattach compose networks.)
#
# The existing hub_heartbeat.sh could not catch this: it gates on
#   docker exec archie_database pg_isready
# and `docker exec` does NOT traverse the network — so pg_isready happily
# succeeded on a container that nothing could reach. DR covers "hub is DEAD";
# this gate covers "hub is UP but BROKEN".
#
# Two further traps this encodes:
#   * a container can report State.Health = "healthy" with 0 networks, because
#     its healthcheck is local-only. Health is NOT evidence of reachability.
#   * `docker start <ctr>` does not restore networks; only compose up does.
#
# USAGE
#   hub_health_gate.sh            # check only (default) — SAFE, changes nothing
#   hub_health_gate.sh --heal     # additionally reattach a container that has
#                                 # ZERO networks (the one provably-safe repair)
#   hub_health_gate.sh --quiet    # only emit output when something is wrong
#
# Exit: 0 = all invariants hold, 1 = at least one violation (after any healing).
set -uo pipefail

NETWORK=archie_network
CRITICAL=(archie_database archie_platform archie_scheduler)
DB_CONTAINER=archie_database
DB_HOST=archie_database
DB_PORT=5432
HTTP_URL=http://127.0.0.1:3000/
STATE_DIR=/var/lib/archie-health-gate
LOG=${ARCHIE_HEALTH_GATE_LOG:-/var/log/archie-health-gate.log}

HEAL=0
QUIET=0
for a in "$@"; do
    case "$a" in
    --heal) HEAL=1 ;;
    --quiet) QUIET=1 ;;
    esac
done

VIOLATIONS=()
say() { [ "$QUIET" = "1" ] || echo "$*"; }
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG" 2>/dev/null || true; }
violation() {
    VIOLATIONS+=("$1")
    echo "VIOLATION: $1"
    log "VIOLATION: $1"
}

# --- invariant 1: every critical container is attached to the shared network ---
# This is the one that actually broke. Checked FIRST because everything else
# depends on it.
for c in "${CRITICAL[@]}"; do
    if ! docker inspect "$c" >/dev/null 2>&1; then
        violation "$c does not exist"
        continue
    fi
    running=$(docker inspect "$c" --format '{{.State.Running}}' 2>/dev/null)
    if [ "$running" != "true" ]; then
        violation "$c is not running (State.Running=$running)"
        continue
    fi
    n=$(docker inspect "$c" --format '{{len .NetworkSettings.Networks}}' 2>/dev/null)
    on_net=$(docker inspect "$c" --format "{{if index .NetworkSettings.Networks \"$NETWORK\"}}yes{{else}}no{{end}}" 2>/dev/null)

    if [ "${n:-0}" = "0" ]; then
        if [ "$HEAL" = "1" ]; then
            say "  healing: $c has 0 networks -> docker network connect $NETWORK $c"
            log "HEAL attempt: docker network connect $NETWORK $c"
            if docker network connect "$NETWORK" "$c" >/dev/null 2>&1; then
                say "  healed: $c attached to $NETWORK (restart it if it is crash-looping)"
                log "HEAL ok: $c"
            else
                violation "$c has 0 networks and reattach FAILED"
            fi
        else
            violation "$c has 0 docker networks (crash-loop imminent; --heal reattaches)"
        fi
    elif [ "$on_net" != "yes" ]; then
        # Deliberately NOT auto-healed: the container is on *some* network, so
        # this may be an intentional topology. Report and let a human decide.
        violation "$c is not attached to $NETWORK (has $n other network(s))"
    fi
done

# --- invariant 2: the DB is reachable BY NAME from the platform container ---
# The check hub_heartbeat.sh is missing. `docker exec ... pg_isready` on the DB
# itself passes with 0 networks; this asserts the path that actually matters.
if docker inspect archie_platform >/dev/null 2>&1 &&
    [ "$(docker inspect archie_platform --format '{{.State.Running}}' 2>/dev/null)" = "true" ]; then
    if ! docker exec archie_platform python3 -c "
import socket,sys
try:
    socket.create_connection(('$DB_HOST', $DB_PORT), 5).close()
except Exception as e:
    print(e); sys.exit(1)
" >/dev/null 2>&1; then
        violation "archie_platform cannot reach $DB_HOST:$DB_PORT by name (DNS or network detached)"
    fi
else
    violation "archie_platform is not running"
fi

# --- invariant 3: postgres actually accepts connections ---
if ! docker exec "$DB_CONTAINER" pg_isready -U archie >/dev/null 2>&1; then
    violation "$DB_CONTAINER not accepting connections (pg_isready failed)"
fi

# --- invariant 4: the platform answers HTTP ---
code=$(docker exec archie_platform python3 -c "
import urllib.request
try:
    r = urllib.request.urlopen('$HTTP_URL', timeout=8)
    print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print(0)
" 2>/dev/null | tr -d '[:space:]')
case "$code" in
200 | 302 | 301 | 401 | 403) say "  http $HTTP_URL -> $code" ;;
*) violation "platform HTTP $HTTP_URL returned '$code' (expected 200/302/401)" ;;
esac

# --- report ---------------------------------------------------------------
mkdir -p "$STATE_DIR" 2>/dev/null || true
if [ ${#VIOLATIONS[@]} -eq 0 ]; then
    say "hub health gate: OK (all invariants hold)"
    log "OK"
    echo ok >"$STATE_DIR/last_status" 2>/dev/null || true
    exit 0
fi

echo "hub health gate: ${#VIOLATIONS[@]} VIOLATION(S)"
echo broken >"$STATE_DIR/last_status" 2>/dev/null || true

# Telegram alert. Delivery is made PROVABLE (#4995 is the same class of bug:
# "(alert sent)" logged unconditionally with stderr swallowed). We capture the
# HTTP status and log it, so a silent failure is visible after the fact.
# NOTE: this deliberately does NOT go through the platform's notify API — the
# whole point is that the platform may be the broken thing.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    msg="A.R.C.H.I.E. hub health gate: ${#VIOLATIONS[@]} violation(s)%0A"
    for v in "${VIOLATIONS[@]}"; do msg="$msg- $v%0A"; done
    # SECURITY: the bot token is passed via the ENVIRONMENT, never as an argv
    # parameter. Command-line arguments are world-readable via `ps aux` on a
    # multi-user host, so `python3 - "$TELEGRAM_BOT_TOKEN"` would leak the token
    # to every local user for the lifetime of the call. /proc/<pid>/environ is
    # readable only by the process owner and root.
    tg_code=$(
        TG_TOKEN="$TELEGRAM_BOT_TOKEN" TG_CHAT="$TELEGRAM_CHAT_ID" TG_TEXT="$msg" \
            python3 - <<'PY' 2>/dev/null || echo 0
import os, urllib.parse, urllib.request
tok = os.environ['TG_TOKEN']
chat = os.environ['TG_CHAT']
text = os.environ['TG_TEXT'].replace('%0A', '\n')
data = urllib.parse.urlencode({'chat_id': chat, 'text': text}).encode()
try:
    r = urllib.request.urlopen(f'https://api.telegram.org/bot{tok}/sendMessage', data=data, timeout=10)
    print(r.status)
except Exception:
    print(0)
PY
    )
    if [ "$tg_code" = "200" ]; then
        log "telegram delivered (HTTP 200)"
    else
        log "telegram NOT delivered (HTTP '$tg_code') — alert exists only in this log"
        echo "  (telegram delivery failed: HTTP '$tg_code')"
    fi
else
    log "telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset)"
fi

exit 1
