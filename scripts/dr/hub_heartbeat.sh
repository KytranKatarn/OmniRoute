#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. DR — HUB LIVENESS HEARTBEAT (producer side)  [cont-102, #276817]
#
# Runs ON THE HUB via cron (every 60s). Proves the hub is ALIVE over a channel
# that does NOT depend on the Headscale mesh, so the boston-2 DR watchdog can
# tell "hub fell off the mesh" (DO NOT fail over) from "hub is dead" (fail over).
#
# WHY THIS EXISTS: every DR pull-probe targets the hub MESH IP 100.64.0.4. When
# the hub's tailscaled client drops (e.g. cont-101 NPM-decommission collateral),
# boston-2 + all outposts see the hub "down" at once even though its DB/platform
# are fine — a FALSE quorum that auto-promoted a stale replica. The hub keeps
# OUTBOUND public internet during a mesh outage, so it PUSHES this heartbeat to
# boston-2's PUBLIC IP (NOT the mesh IP) where the watchdog reads it.
#
# Health-gated: only writes the heartbeat when the local Postgres is accepting
# connections (pg_isready). A sick hub stops posting → the heartbeat ages out →
# the watchdog is free to fail over. DB liveness is the gate because promoting
# the replica while the hub DB is alive is exactly the split-brain we must avoid.
#
# Pure bash + docker + python3 urllib. No curl, no extra deps. Quiet by design
# (cron-friendly); pass -v / HB_VERBOSE=1 for a one-line status on stdout.
# ============================================================================
set -uo pipefail

# ---- Config (env-overridable) ----
DR_NODE_PUBLIC="${DR_NODE_PUBLIC:-2.25.133.122}"   # boston-2 PUBLIC IP — mesh-independent on purpose
DR_NODE_USER="${DR_NODE_USER:-root}"
HEARTBEAT_FILE="${HEARTBEAT_FILE:-/opt/archie-dr/.hub_heartbeat}"   # path ON boston-2
SSH_KEY="${DR_SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_TIMEOUT="${HB_SSH_TIMEOUT:-8}"
DB_CONTAINER="${HB_DB_CONTAINER:-archie_database}"
DB_USER="${HB_DB_USER:-archie}"
PLATFORM_URL="${HB_PLATFORM_URL:-http://127.0.0.1:3000/login}"
HTTP_TIMEOUT="${HB_HTTP_TIMEOUT:-5}"
VERBOSE="${HB_VERBOSE:-0}"; [ "${1:-}" = "-v" ] && VERBOSE=1

log(){ [ "$VERBOSE" = "1" ] && echo "[$(date -u +%H:%M:%SZ)] $*"; return 0; }

# ---- 1. LOCAL DB liveness (the gate) ----
db="down"
if docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" >/dev/null 2>&1; then
  db="ok"
fi

# ---- 2. LOCAL platform liveness (informational; any HTTP code = serving) ----
http=$(PLATFORM_URL="$PLATFORM_URL" HTTP_TIMEOUT="$HTTP_TIMEOUT" python3 - <<'PY' 2>/dev/null
import os, urllib.request
url = os.environ["PLATFORM_URL"]; to = float(os.environ["HTTP_TIMEOUT"])
try:
    print(urllib.request.urlopen(url, timeout=to).getcode())
except urllib.error.HTTPError as e:
    print(e.code)            # an HTTP error still proves the server answered
except Exception:
    print("ERR")
PY
)
[ -n "$http" ] || http="ERR"

# ---- 3. Gate: only push when the DB is alive ----
if [ "$db" != "ok" ]; then
  log "DB not ready (db=$db http=$http) — NOT posting heartbeat (lets it age out so DR can act)."
  exit 0
fi

# ---- 4. Push the heartbeat to boston-2's PUBLIC IP (survives a mesh outage) ----
payload="ts=$(date +%s) db=${db} http=${http} host=$(hostname -s 2>/dev/null || echo hub)"
if [ ! -f "$SSH_KEY" ]; then
  log "WARN: SSH key $SSH_KEY missing — cannot post heartbeat."
  exit 0
fi
if ssh -i "$SSH_KEY" -o ConnectTimeout="$SSH_TIMEOUT" -o BatchMode=yes \
       -o StrictHostKeyChecking=accept-new \
       "${DR_NODE_USER}@${DR_NODE_PUBLIC}" \
       "umask 022; printf '%s\n' '$payload' > '$HEARTBEAT_FILE'" >/dev/null 2>&1; then
  log "posted -> ${DR_NODE_USER}@${DR_NODE_PUBLIC}:${HEARTBEAT_FILE}  [$payload]"
else
  log "WARN: could not reach ${DR_NODE_PUBLIC} to post heartbeat (it will age out)."
fi
exit 0
