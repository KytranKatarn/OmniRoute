#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. reliability — OmniRoute 2-tier local probe (Deep Space Nine
# phase 1). Runs ON THE HUB against loopback ONLY — OmniRoute's port is not
# mesh-reachable by design (it carries a tracked, unpatched CRITICAL CVE; see
# docs/superpowers/specs/2026-09-18-omniroute-reliability-watchdog-design.md
# §3 for why this must never change).
#
# Emits exactly one line on stdout:
#   tier1=ok|fail tier2=ok|fail|skipped detail="..."
#
# tier1: GET /api/health (no auth) — is the process even listening.
# tier2: one real completion through the OpenCode combo path
#        (POST /v1/chat/completions, Bearer $OMNIROUTE_API_KEY — the same
#        data-plane key the platform already uses successfully against this
#        gateway). This is the only remaining signal (§4 of the design spec
#        explains why the cheaper credential-count tier was dropped), so it
#        runs every cycle, not throttled. Skipped if tier1 failed — no point
#        spending a real completion call checking a dead container.
# ============================================================================
set -u

HOST="${OMNIROUTE_HOST:-127.0.0.1}"
PORT="${OMNIROUTE_PORT:-20128}"
API_KEY="${OMNIROUTE_API_KEY:-}"
TIMEOUT="${PROBE_TIMEOUT:-8}"

# ---- Pure helpers: classify an http status code. No network. ----
# Each echoes ok|fail and, on fail, a one-line reason on the second line.
classify_tier1(){
  local code="$1"
  [ "$code" = "200" ] && { echo ok; return; }
  echo "fail"; echo "health endpoint returned '${code:-no response}'"
}
classify_tier2(){
  local code="$1"
  [ "$code" = "200" ] && { echo ok; return; }
  echo "fail"; echo "canary completion returned '${code:-no response}'"
}

[ "${PROBE_OMNIROUTE_LIB:-0}" = "1" ] && return 0 2>/dev/null || true

_get(){
  # _get <path> — prints "STATUS\nBODY"; STATUS empty on connection failure.
  local path="$1"
  python3 - "$HOST" "$PORT" "$path" "$TIMEOUT" <<'PY'
import sys, urllib.request
host, port, path, timeout = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
req = urllib.request.Request("http://%s:%s%s" % (host, port, path))
try:
    resp = urllib.request.urlopen(req, timeout=timeout)
    print(resp.getcode()); print(resp.read(2000).decode("utf-8", "replace"))
except urllib.error.HTTPError as e:
    print(e.code); print(e.read(2000).decode("utf-8", "replace"))
except Exception as e:
    print(""); print(str(e))
PY
}

_canary(){
  python3 - "$HOST" "$PORT" "$API_KEY" "$TIMEOUT" <<'PY'
import sys, json, urllib.request
host, port, key, timeout = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
req = urllib.request.Request(
    "http://%s:%s/v1/chat/completions" % (host, port),
    data=json.dumps({"model": "auto/coding:free", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % key},
    method="POST",
)
try:
    print(urllib.request.urlopen(req, timeout=timeout).getcode())
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print("")
PY
}

out1="$(_get /api/health)"; code1="$(printf '%s\n' "$out1" | sed -n '1p')"
t1_result="$(classify_tier1 "$code1")"; tier1="$(printf '%s\n' "$t1_result" | sed -n '1p')"

if [ "$tier1" = "fail" ]; then
  detail="$(printf '%s\n' "$t1_result" | sed -n '2p')"
  echo "tier1=fail tier2=skipped detail=\"$detail\""
  exit 0
fi

if [ -z "$API_KEY" ]; then
  tier2=fail; t2_detail="OMNIROUTE_API_KEY not set"
else
  code2="$(_canary)"
  t2_result="$(classify_tier2 "$code2")"
  tier2="$(printf '%s\n' "$t2_result" | sed -n '1p')"
  t2_detail="$(printf '%s\n' "$t2_result" | sed -n '2p')"
fi

detail="ok"
[ "$tier2" = "fail" ] && detail="$t2_detail"
echo "tier1=ok tier2=$tier2 detail=\"$detail\""
