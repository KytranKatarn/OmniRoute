#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. DR — hub reachability probe (1-vantage).
# Copied to each quorum outpost (root@, /opt/archie-dr/probe_hub.sh) and run by
# the boston-2 coordinator over SSH every cycle. Also run locally by the
# coordinator for boston-2's own vantage.
#
# Probes the hub MESH IP on BOTH:
#   • TCP  100.64.0.4:5432   (Postgres — matches failover.sh split-brain guard)
#   • HTTP 100.64.0.4:3000/login
# BOTH must fail to call the hub "down from here" (a single-port blip is not an
# outage). Mesh IP only — MagicDNS dies with the hub, so never use a hostname.
#
# Exit 0  = hub REACHABLE from this vantage (at least one of TCP/HTTP answered)
# Exit 1  = hub DOWN from this vantage (both failed)
#
# Pure bash + /dev/tcp + python3 urllib (no curl, no extra deps). Self-contained.
# ============================================================================
set -u

HUB_MESH="${HUB_MESH:-100.64.0.4}"
PG_PORT="${HUB_PG_PORT:-5432}"
HTTP_PORT="${HUB_HTTP_PORT:-3000}"
TCP_TIMEOUT="${PROBE_TCP_TIMEOUT:-5}"
HTTP_TIMEOUT="${PROBE_HTTP_TIMEOUT:-8}"

# --- TCP probe: Postgres port ---
tcp_ok=1
if timeout "$TCP_TIMEOUT" bash -c "echo > /dev/tcp/$HUB_MESH/$PG_PORT" 2>/dev/null; then
  tcp_ok=0
fi

# --- HTTP probe: /login returns any HTTP status code ---
http_ok=1
code=$(HUB_MESH="$HUB_MESH" HTTP_PORT="$HTTP_PORT" HTTP_TIMEOUT="$HTTP_TIMEOUT" python3 - <<'PY' 2>/dev/null
import os, urllib.request
host = os.environ["HUB_MESH"]; port = os.environ["HTTP_PORT"]; to = float(os.environ["HTTP_TIMEOUT"])
try:
    print(urllib.request.urlopen("http://%s:%s/login" % (host, port), timeout=to).getcode())
except urllib.error.HTTPError as e:
    print(e.code)   # an HTTP error still proves the server answered → hub is UP
except Exception:
    print("ERR")
PY
)
[ "$code" != "ERR" ] && [ -n "$code" ] && http_ok=0

# Reachable if EITHER port answered.
#
# 🔴 The PROBE_RESULT sentinel is the CONTRACT; the exit code is a convenience.
# probe_outpost parses stdout, because an exit code is not trustworthy across
# transports — measured 2026-09-08: PowerShell's `exit 1` over `ssh "powershell
# -Command -"` arrives as exit 0. Worse, the old caller mapped every non-255 exit
# to "down", so a host that could not RUN the probe (no bash on Windows) cast a
# permanent false DOWN-VOTE, indistinguishable from a real outage report.
# NO SENTINEL means "could not run" and MUST be read as unreachable, never down.
if [ "$tcp_ok" -eq 0 ] || [ "$http_ok" -eq 0 ]; then
  echo "PROBE_RESULT=up"
  exit 0   # hub UP from here
fi
echo "PROBE_RESULT=down"
exit 1     # hub DOWN from here
