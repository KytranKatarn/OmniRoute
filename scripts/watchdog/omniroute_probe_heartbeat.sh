#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. reliability — OmniRoute heartbeat (producer side, hub cron).
#
# Runs ON THE HUB via cron (every 5 min — see Task 5). Probes OmniRoute over
# loopback (probe_omniroute.sh) and pushes the result to Citadel over the SAME
# SSH channel hub_heartbeat.sh already uses — same key, same target, no new
# credential.
#
# No throttling here: the canary IS the only remaining signal (the cheaper
# credential-count tier was dropped — see the design spec §4), so it runs
# every invocation. The 5-minute cron interval itself is what bounds the real
# free-tier completion cost (~288 tiny 1-token pings/day).
# ============================================================================
set -uo pipefail

DR_NODE_PUBLIC="${DR_NODE_PUBLIC:-2.25.133.122}"
DR_NODE_USER="${DR_NODE_USER:-root}"
HEARTBEAT_FILE="${HEARTBEAT_FILE:-/opt/archie-dr/.omniroute_heartbeat}"   # path ON boston-2
SSH_KEY="${DR_SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_TIMEOUT="${HB_SSH_TIMEOUT:-8}"
PROBE_SCRIPT="${PROBE_SCRIPT:-$(cd "$(dirname "$0")" && pwd)/probe_omniroute.sh}"
VERBOSE="${OMNIROUTE_HB_VERBOSE:-0}"; [ "${1:-}" = "-v" ] && VERBOSE=1

log(){ [ "$VERBOSE" = "1" ] && echo "[$(date -u +%H:%M:%SZ)] $*"; return 0; }

probe_line="$(bash "$PROBE_SCRIPT" 2>/dev/null)"
[ -n "$probe_line" ] || probe_line='tier1=fail tier2=skipped detail="PROBE HARNESS ERROR: probe script produced no output"'

payload="ts=$(date +%s) $probe_line"

if [ ! -f "$SSH_KEY" ]; then
  log "WARN: SSH key $SSH_KEY missing — cannot post heartbeat."
  exit 0
fi
if printf '%s\n' "$payload" | ssh -i "$SSH_KEY" -o ConnectTimeout="$SSH_TIMEOUT" -o BatchMode=yes \
       -o StrictHostKeyChecking=accept-new \
       "${DR_NODE_USER}@${DR_NODE_PUBLIC}" \
       "umask 022; cat > '$HEARTBEAT_FILE'" >/dev/null 2>&1; then
  log "posted -> ${DR_NODE_USER}@${DR_NODE_PUBLIC}:${HEARTBEAT_FILE}  [$payload]"
else
  log "WARN: could not reach ${DR_NODE_PUBLIC} to post heartbeat (it will age out)."
fi
exit 0
