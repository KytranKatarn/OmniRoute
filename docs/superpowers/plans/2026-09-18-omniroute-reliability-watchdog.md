# OmniRoute Reliability Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect an OmniRoute/OpenCode routing failure (the exact shape that went unnoticed for 22+ hours on 2026-09-17) within minutes, and alert through a path independent of OmniRoute and the hub.

**Architecture:** A hub-local cron script probes OmniRoute over loopback (3 tiers: liveness, authenticated provider-state, throttled deep canary) and pushes one heartbeat line to Citadel over the existing `hub_heartbeat.sh` SSH channel. A new `observe_omniroute()` function, folded into `dr_watchdog.sh`'s existing cycle at the same "never gated, always runs" position as `observe_and_alert()`, reads that heartbeat and alerts via the existing `tg_notify` helper on a confirmed bad reading or staleness. No new network exposure, no new SSH credential, no new systemd unit.

**Tech Stack:** bash, python3 (stdlib `urllib` only — matches every existing DR script; no new dependencies), existing DR SSH/Telegram infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-18-omniroute-reliability-watchdog-design.md`

## Global Constraints

- Never publish OmniRoute on the mesh IP or any interface beyond its existing `127.0.0.1:20128` loopback bind (it carries a tracked, unpatched CRITICAL Next.js CVE — see spec §3).
- Never modify `consec_down`, `armed_at`, `.failed_over`, `.awaiting_rebuild`, or any other DR-failover state. This watchdog is observation-only, same guarantee `observe_and_alert()` already makes.
- New watchdog-owned state lives under `/opt/archie-reliability/` on Citadel — never under `/opt/archie-dr/` (the pushed heartbeat *file* is the one exception: it rides `hub_heartbeat.sh`'s existing push channel and lives at `/opt/archie-dr/.omniroute_heartbeat` for that reason alone, but nothing else of this feature's state does).
- Reuse `tg_notify` (defined in `$DR/tg_notify.sh`, sourced by `dr_watchdog.sh`) for all alerts — no new Telegram integration.
- All new scripts follow the existing DR convention: `set -u` (or `-uo pipefail`), python3 stdlib only, a `PROBE_RESULT`-style stdout contract where the caller must parse text, never trust a bare exit code across an SSH hop.
- Deployment is manual `scp`, matching every other DR script (`scripts/dr/failover.sh` deploys `beacon_flip.sh`/`fleet_repoint.sh` the same way) — no CI/CD pipeline exists or should be introduced for this.
- Branch + PR, never main. 2 failures on any step → stop and ask.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/watchdog/probe_omniroute.sh` | Pure 3-tier probe against `127.0.0.1:20128`. No SSH, no push — just prints one result line. Independently testable. |
| `scripts/watchdog/omniroute_probe_heartbeat.sh` | Hub-cron orchestrator: calls `probe_omniroute.sh` (throttling the deep canary), pushes the result to Citadel over SSH — mirrors `hub_heartbeat.sh`'s push exactly. |
| `scripts/watchdog/test_probe_omniroute.sh` | Unit tests for the probe's pure classification logic (no network). |
| `scripts/dr/watchdog/dr_watchdog.sh` | **Modified**: new `observe_omniroute()` function + 4 new config vars, one new call site in `main()`. |
| `scripts/dr/watchdog/test_observe_omniroute.sh` | Unit tests for `observe_omniroute()`, mirroring `test_observe_alert.sh`'s exact harness style. |

---

## Task 1: Verify the real `/api/status` response shape

Before writing probe logic that parses OmniRoute's authenticated status endpoint, confirm what it actually returns — the field names below are an informed guess from the container's own log vocabulary (`"apiKeyId"`, `AUTH_001`/`AUTH_002` error codes), not a verified response body.

**Files:** none (verification only).

- [ ] **Step 1: Read the real API key and hit the endpoint once**

```bash
API_KEY="$(grep '^OMNIROUTE_API_KEY=' /mnt/archie_brain/.env | cut -d= -f2-)"
docker exec omniroute node -e "
const http=require('http');
http.get({host:'127.0.0.1',port:20128,path:'/api/status',headers:{Authorization:'Bearer $API_KEY'},timeout:5000}, res=>{
  let b='';res.on('data',d=>b+=d);res.on('end',()=>{console.log(res.statusCode);console.log(b);});
}).on('error',e=>console.log('ERR',e.message));
"
```

- [ ] **Step 2: Record the real shape**

Note whether the `opencode` provider's credential count and circuit-breaker state appear under those field names or different ones (e.g. `credentialCount` vs `credentials`, nested under a `providers` array vs a top-level object keyed by provider name). If `/api/status` doesn't carry per-provider detail, try `/api/providers` instead (also seen in the container's route surface this session).

- [ ] **Step 3: Adjust the grep patterns in Task 2's `probe_omniroute.sh` to match**

The implementation in Task 2 below uses `grep -qi '"opencode"[^}]*"credentials"[[:space:]]*:[[:space:]]*0'` and a matching pattern for the circuit-breaker flag — placeholders for the *real* field names found in Step 2, not for the *logic*. Update both patterns (and the JSON key names in the `detail=` messages) to match what you actually observed before moving on. If the shape is structurally different (e.g. an array), rewrite the two `grep` checks as a short inline `python3 -c` JSON parse instead — the rest of the script is unaffected either way.

---

## Task 2: Write the probe script

**Files:**
- Create: `scripts/watchdog/probe_omniroute.sh`
- Test: `scripts/watchdog/test_probe_omniroute.sh`

**Interfaces:**
- Produces: a stdout contract — exactly one line, `tier1=ok|fail tier2=ok|fail|skipped tier3=ok|fail|skipped detail="..."` — consumed by Task 3's heartbeat script (which forwards the line verbatim to Citadel) and Task 4's `observe_omniroute()` (which greps it for `tier1=fail`/`tier2=fail`/`tier3=fail`).

- [ ] **Step 1: Write the pure classification helpers (no I/O, unit-testable)**

Create `scripts/watchdog/probe_omniroute.sh`:

```bash
#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. reliability — OmniRoute 3-tier local probe (Deep Space Nine
# phase 1). Runs ON THE HUB against loopback ONLY — OmniRoute's port is not
# mesh-reachable by design (it carries a tracked, unpatched CRITICAL CVE; see
# docs/superpowers/specs/2026-09-18-omniroute-reliability-watchdog-design.md
# §3 for why this must never change).
#
# Emits exactly one line on stdout:
#   tier1=ok|fail tier2=ok|fail|skipped tier3=ok|fail|skipped detail="..."
#
# tier1: GET /api/health (no auth) — is the process even listening.
# tier2: GET /api/status (Bearer $OMNIROUTE_API_KEY) — real per-provider
#        credential/circuit-breaker state, no LLM cost. Skipped if tier1 failed.
# tier3: one real completion through the OpenCode combo path. Only runs when
#        the caller passes DEEP_CANARY=1 (throttled by omniroute_probe_heartbeat.sh,
#        since it costs a real free-tier call). Skipped otherwise or if tier1/2 failed.
# ============================================================================
set -u

HOST="${OMNIROUTE_HOST:-127.0.0.1}"
PORT="${OMNIROUTE_PORT:-20128}"
API_KEY="${OMNIROUTE_API_KEY:-}"
TIMEOUT="${PROBE_TIMEOUT:-8}"
DEEP_CANARY="${DEEP_CANARY:-0}"

# ---- Pure helpers: classify an (http_code, body) pair. No network. ----
# Each echoes ok|fail and, on fail, a one-line reason on the second line.
classify_tier1(){
  local code="$1"
  [ "$code" = "200" ] && { echo ok; return; }
  echo "fail"; echo "health endpoint returned '${code:-no response}'"
}
classify_tier2(){
  local code="$1" body="$2"
  if [ "$code" != "200" ]; then
    echo "fail"; echo "status endpoint returned '${code:-no response}'"; return
  fi
  if printf '%s' "$body" | grep -qi '"opencode"[^}]*"credentials"[[:space:]]*:[[:space:]]*0'; then
    echo "fail"; echo "opencode provider reports 0 credentials"; return
  fi
  if printf '%s' "$body" | grep -qi '"opencode"[^}]*"circuitBreaker"[[:space:]]*:[[:space:]]*true'; then
    echo "fail"; echo "opencode provider circuit breaker is open"; return
  fi
  echo "ok"
}
classify_tier3(){
  local code="$1"
  [ "$code" = "200" ] && { echo ok; return; }
  echo "fail"; echo "canary completion returned '${code:-no response}'"
}
```

- [ ] **Step 2: Write the failing tests for the pure helpers**

Create `scripts/watchdog/test_probe_omniroute.sh`:

```bash
#!/bin/bash
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export PROBE_OMNIROUTE_LIB=1
# shellcheck disable=SC1091
. "$HERE/probe_omniroute.sh"

pass=0; fail=0
check(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
         else echo "  FAIL  $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi; }

echo "=== tier1 ==="
check "200 is ok"      "ok"   "$(classify_tier1 200 | head -1)"
check "500 is fail"    "fail" "$(classify_tier1 500 | head -1)"
check "no response is fail" "fail" "$(classify_tier1 '' | head -1)"

echo "=== tier2 ==="
check "non-200 is fail" "fail" "$(classify_tier2 401 '' | head -1)"
check "zero credentials is fail" "fail" \
  "$(classify_tier2 200 '{"providers":{"opencode":{"credentials":0}}}' | head -1)"
check "breaker open is fail" "fail" \
  "$(classify_tier2 200 '{"providers":{"opencode":{"credentials":3,"circuitBreaker":true}}}' | head -1)"
check "healthy is ok" "ok" \
  "$(classify_tier2 200 '{"providers":{"opencode":{"credentials":3,"circuitBreaker":false}}}' | head -1)"
echo "=== 🔴 THE REGRESSION THIS PINS: a lone free-tier model failing in the fallback combo must NOT count ==="
check "unrelated model 402 in the body is still ok" "ok" \
  "$(classify_tier2 200 '{"providers":{"opencode":{"credentials":3,"circuitBreaker":false}},"lastError":"muse-spark-1.2: 402 quota exhausted"}' | head -1)"

echo "=== tier3 ==="
check "200 is ok"   "ok"   "$(classify_tier3 200 | head -1)"
check "502 is fail" "fail" "$(classify_tier3 502 | head -1)"

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
```

Add a library guard to `probe_omniroute.sh` so this test can source it without running network calls — append after the classify functions, before the `_get`/main logic written in Step 4:

```bash
[ "${PROBE_OMNIROUTE_LIB:-0}" = "1" ] && return 0 2>/dev/null || true
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
chmod +x scripts/watchdog/probe_omniroute.sh scripts/watchdog/test_probe_omniroute.sh
bash scripts/watchdog/test_probe_omniroute.sh
```

Expected: `classify_tier1`/`classify_tier2`/`classify_tier3` are undefined (script only has the guard so far) — FAIL with "command not found."

- [ ] **Step 4: Add the network glue (the part that calls the classify helpers)**

Append to `scripts/watchdog/probe_omniroute.sh`, after the library guard from Step 2:

```bash
_get(){
  # _get <path> [auth] — prints "STATUS\nBODY"; STATUS empty on connection failure.
  local path="$1" auth="${2:-0}"
  python3 - "$HOST" "$PORT" "$path" "$auth" "$API_KEY" "$TIMEOUT" <<'PY'
import sys, urllib.request
host, port, path, auth, key, timeout = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], float(sys.argv[6])
req = urllib.request.Request("http://%s:%s%s" % (host, port, path))
if auth == "1" and key:
    req.add_header("Authorization", "Bearer %s" % key)
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
    data=json.dumps({"model": "opencode/auto", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode(),
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

out1="$(_get /api/health 0)"; code1="$(printf '%s\n' "$out1" | sed -n '1p')"
t1_result="$(classify_tier1 "$code1")"; tier1="$(printf '%s\n' "$t1_result" | sed -n '1p')"

if [ "$tier1" = "fail" ]; then
  detail="$(printf '%s\n' "$t1_result" | sed -n '2p')"
  echo "tier1=fail tier2=skipped tier3=skipped detail=\"$detail\""
  exit 0
fi

if [ -z "$API_KEY" ]; then
  tier2=fail; t2_detail="OMNIROUTE_API_KEY not set"
else
  out2="$(_get /api/status 1)"
  code2="$(printf '%s\n' "$out2" | sed -n '1p')"
  body2="$(printf '%s\n' "$out2" | sed -n '2,$p')"
  t2_result="$(classify_tier2 "$code2" "$body2")"
  tier2="$(printf '%s\n' "$t2_result" | sed -n '1p')"
  t2_detail="$(printf '%s\n' "$t2_result" | sed -n '2p')"
fi

tier3=skipped; t3_detail=""
if [ "$DEEP_CANARY" = "1" ] && [ "$tier2" = "ok" ]; then
  code3="$(_canary)"
  t3_result="$(classify_tier3 "$code3")"
  tier3="$(printf '%s\n' "$t3_result" | sed -n '1p')"
  t3_detail="$(printf '%s\n' "$t3_result" | sed -n '2p')"
fi

detail="ok"
[ "$tier2" = "fail" ] && detail="$t2_detail"
[ "$tier3" = "fail" ] && detail="$t3_detail"
echo "tier1=ok tier2=$tier2 tier3=$tier3 detail=\"$detail\""
```

- [ ] **Step 5: Run the unit test again to verify it passes**

```bash
bash scripts/watchdog/test_probe_omniroute.sh
```

Expected: `RESULT: 8 pass · 0 fail`.

- [ ] **Step 6: Manual live check against the real hub (requires Task 1's confirmed field names)**

```bash
OMNIROUTE_API_KEY="$(grep '^OMNIROUTE_API_KEY=' /mnt/archie_brain/.env | cut -d= -f2-)" \
  bash scripts/watchdog/probe_omniroute.sh
```

Expected right now (OmniRoute's OpenCode credential is still broken as of this session): `tier1=ok tier2=fail tier3=skipped detail="..."`. If tier2 instead reports `ok`, the field names from Task 1 don't match reality yet — go back and fix them before continuing.

- [ ] **Step 7: Commit**

```bash
git add scripts/watchdog/probe_omniroute.sh scripts/watchdog/test_probe_omniroute.sh
git commit -m "feat(watchdog): add OmniRoute 3-tier local probe"
```

---

## Task 3: Write the hub-side heartbeat pusher

**Files:**
- Create: `scripts/watchdog/omniroute_probe_heartbeat.sh`

**Interfaces:**
- Consumes: `scripts/watchdog/probe_omniroute.sh`'s stdout contract (Task 2).
- Produces: pushes one line to `/opt/archie-dr/.omniroute_heartbeat` on Citadel, format `ts=<epoch> <probe line>` — consumed by Task 4's `observe_omniroute()`.

- [ ] **Step 1: Write the script, modeled directly on `hub_heartbeat.sh`'s push mechanism**

Create `scripts/watchdog/omniroute_probe_heartbeat.sh`:

```bash
#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. reliability — OmniRoute heartbeat (producer side, hub cron).
#
# Runs ON THE HUB via cron. Probes OmniRoute over loopback (probe_omniroute.sh)
# and pushes the result to Citadel over the SAME SSH channel hub_heartbeat.sh
# already uses — same key, same target, no new credential.
#
# Throttles the deep canary (tier 3) to roughly every 15th invocation, tracked
# in a local counter file, since it costs a real free-tier completion.
# ============================================================================
set -uo pipefail

DR_NODE_PUBLIC="${DR_NODE_PUBLIC:-2.25.133.122}"
DR_NODE_USER="${DR_NODE_USER:-root}"
HEARTBEAT_FILE="${HEARTBEAT_FILE:-/opt/archie-dr/.omniroute_heartbeat}"   # path ON boston-2
SSH_KEY="${DR_SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_TIMEOUT="${HB_SSH_TIMEOUT:-8}"
PROBE_SCRIPT="${PROBE_SCRIPT:-$(cd "$(dirname "$0")" && pwd)/probe_omniroute.sh}"
COUNTER_FILE="${COUNTER_FILE:-/opt/archie_omniroute_watchdog/.cycle_count}"
CANARY_EVERY="${CANARY_EVERY:-15}"
VERBOSE="${OMNIROUTE_HB_VERBOSE:-0}"; [ "${1:-}" = "-v" ] && VERBOSE=1

log(){ [ "$VERBOSE" = "1" ] && echo "[$(date -u +%H:%M:%SZ)] $*"; return 0; }

mkdir -p "$(dirname "$COUNTER_FILE")" 2>/dev/null || true
n=$(( $(cat "$COUNTER_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$COUNTER_FILE"
deep=0
[ $(( n % CANARY_EVERY )) -eq 0 ] && deep=1

probe_line="$(DEEP_CANARY="$deep" bash "$PROBE_SCRIPT" 2>/dev/null)"
[ -n "$probe_line" ] || probe_line='tier1=fail tier2=skipped tier3=skipped detail="probe script produced no output"'

payload="ts=$(date +%s) $probe_line"

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
```

- [ ] **Step 2: Make it executable and dry-run it locally on the hub**

```bash
chmod +x scripts/watchdog/omniroute_probe_heartbeat.sh
OMNIROUTE_API_KEY="$(grep '^OMNIROUTE_API_KEY=' /mnt/archie_brain/.env | cut -d= -f2-)" \
  bash scripts/watchdog/omniroute_probe_heartbeat.sh -v
```

Expected: a `posted -> root@2.25.133.122:/opt/archie-dr/.omniroute_heartbeat  [ts=... tier1=ok tier2=fail tier3=skipped detail="..."]` line (reflecting the current live, still-broken OpenCode credential).

- [ ] **Step 3: Verify the file actually landed on Citadel**

```bash
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 "cat /opt/archie-dr/.omniroute_heartbeat"
```

Expected: the exact payload line from Step 2.

- [ ] **Step 4: Commit**

```bash
git add scripts/watchdog/omniroute_probe_heartbeat.sh
git commit -m "feat(watchdog): push OmniRoute heartbeat to Citadel over the existing SSH channel"
```

---

## Task 4: Add `observe_omniroute()` to `dr_watchdog.sh`

**Files:**
- Modify: `scripts/dr/watchdog/dr_watchdog.sh` — add config vars near line 111 (after `HEARTBEAT_MAX_AGE`), add the new function near line 460 (after `observe_and_alert()`, before `main()`), add one call in `main()` at line ~465 (immediately after `observe_and_alert || true`).
- Test: `scripts/dr/watchdog/test_observe_omniroute.sh`

**Interfaces:**
- Consumes: `tg_notify` (already defined/sourced in this file), `log`, `now_epoch` (all pre-existing).
- Produces: nothing consumed by later tasks — this is the terminal alerting step.

- [ ] **Step 1: Add the new config vars**

In `scripts/dr/watchdog/dr_watchdog.sh`, immediately after the existing line `HEARTBEAT_MAX_AGE="${HEARTBEAT_MAX_AGE:-300}"   # seconds; older = stale (hub really gone)`, add:

```bash
# OmniRoute reliability heartbeat (Deep Space Nine phase 1). Pushed by
# omniroute_probe_heartbeat.sh on the hub every ~2 min over this SAME SSH
# path. Separate file/state from the hub-DR heartbeat above — this watchdog
# never touches DR failover state (see observe_omniroute()).
OMNIROUTE_HEARTBEAT_FILE="${OMNIROUTE_HEARTBEAT_FILE:-$DR/.omniroute_heartbeat}"
OMNIROUTE_HEARTBEAT_MAX_AGE="${OMNIROUTE_HEARTBEAT_MAX_AGE:-240}"   # seconds; ~2x the hub's push interval
OMNIROUTE_CONFIRM="${OMNIROUTE_CONFIRM:-2}"   # consecutive bad readings before alerting
RELIABILITY_DIR="${RELIABILITY_DIR:-/opt/archie-reliability}"
OMNIROUTE_DISABLED_FLAG="${OMNIROUTE_DISABLED_FLAG:-$RELIABILITY_DIR/.omniroute_watchdog_disabled}"
```

- [ ] **Step 2: Add the `observe_omniroute()` function**

Immediately after the closing `}` of `observe_and_alert()` (the line `}` right before `main(){`), add:

```bash
# ── OMNIROUTE OBSERVATION LANE (Deep Space Nine phase 1) ────────────────────
# Reads a heartbeat PUSHED from the hub (omniroute_probe_heartbeat.sh, over
# the same SSH channel hub_heartbeat.sh already uses) rather than probing
# OmniRoute directly — its port is loopback-only on purpose (tracked,
# unpatched CRITICAL CVE; see the design spec §3). Never reach for it over
# the mesh.
#
# SAFE BY CONSTRUCTION, identical guarantee to observe_and_alert(): observes
# only, never touches consec_down/armed_at/.failed_over/.watchdog_disabled,
# never returns non-zero. All of ITS OWN state lives under $RELIABILITY_DIR,
# never under $DR, so it can never be confused with — or cleared by — DR
# failover bookkeeping.
observe_omniroute(){
  local hf="$OMNIROUTE_HEARTBEAT_FILE"
  local sf="$RELIABILITY_DIR/.omniroute_observed_state" kf="$RELIABILITY_DIR/.omniroute_observed_streak"
  local confirm="${OMNIROUTE_CONFIRM:-2}" obs last streak now line ts detail

  mkdir -p "$RELIABILITY_DIR" 2>/dev/null || true

  if [ -f "$OMNIROUTE_DISABLED_FLAG" ]; then
    log "omniroute observation: alerts SUPPRESSED by $OMNIROUTE_DISABLED_FLAG (planned maintenance)."
    return 0
  fi

  now="$(now_epoch)"
  line="$(cat "$hf" 2>/dev/null || echo '')"
  ts="$(printf '%s\n' "$line" | sed -n 's/.*ts=\([0-9][0-9]*\).*/\1/p')"
  detail="$(printf '%s\n' "$line" | sed -n 's/.*detail="\([^"]*\)".*/\1/p')"

  if [ -z "$ts" ] || [ $(( now - ts )) -gt "${OMNIROUTE_HEARTBEAT_MAX_AGE:-240}" ]; then
    obs="stale"
    detail="no heartbeat received in the last ${OMNIROUTE_HEARTBEAT_MAX_AGE}s — check the hub-side cron and SSH push"
  elif printf '%s\n' "$line" | grep -q 'tier1=fail'; then
    obs="down"
  elif printf '%s\n' "$line" | grep -qE 'tier2=fail|tier3=fail'; then
    obs="degraded"
  else
    obs="ok"
  fi

  last="$(cat "$sf" 2>/dev/null || echo '')"

  # Steady state — nothing to say. Clearing the streak here is what makes a
  # single flapping cycle unable to accumulate into a false report.
  if [ "$obs" = "$last" ]; then rm -f "$kf"; return 0; fi

  # First ever run: adopt current state silently, same as observe_and_alert.
  if [ -z "$last" ]; then
    echo "$obs" > "$sf"
    log "omniroute observation: baseline recorded as $obs (no alert on first observation)."
    return 0
  fi

  streak=$(( $(cat "$kf" 2>/dev/null || echo 0) + 1 ))
  echo "$streak" > "$kf"
  if [ "$streak" -lt "$confirm" ]; then
    log "omniroute observation: looks $obs (${streak}/${confirm} confirmations) — holding."
    return 0
  fi

  rm -f "$kf"
  echo "$obs" > "$sf"

  case "$obs" in
    ok)
      log "omniroute observation: RECOVERED — alerting."
      tg_notify "✅ <b>OmniRoute recovered</b> — OpenCode routing is healthy again."
      ;;
    down)
      log "omniroute observation: container unreachable confirmed over ${confirm} checks — alerting."
      tg_notify "🔴 <b>OmniRoute is DOWN</b> — the container itself is not answering on the hub.
<i>Check: docker ps --filter name=omniroute · docker logs omniroute</i>
<i>Observation only — does not affect hub DR posture.</i>"
      ;;
    degraded)
      log "omniroute observation: provider degraded confirmed over ${confirm} checks — alerting."
      tg_notify "🟠 <b>OmniRoute is up, but OpenCode routing is broken</b>
${detail}
<i>Re-auth via Settings → Providers (SSH tunnel: ssh -L 20128:127.0.0.1:20128 kytran@192.168.1.200).</i>
<i>Observation only — does not affect hub DR posture.</i>"
      ;;
    stale)
      log "omniroute observation: heartbeat stale confirmed over ${confirm} checks — alerting."
      tg_notify "🟡 <b>OmniRoute heartbeat is stale</b>
${detail}
<i>This may be the hub-side cron or SSH push, not necessarily OmniRoute itself.</i>"
      ;;
  esac
  return 0
}
```

The inserted block ends at that closing `}` — the next line in the real file is the pre-existing `main(){`.

- [ ] **Step 3: Wire the single call site in `main()`**

Change:

```bash
main(){
  # 0. OBSERVE + ALERT. Deliberately ABOVE every gate below — see the comment on
  #    observe_and_alert. `|| true` so observation can never break promotion logic.
  observe_and_alert || true
  # 1. Disarm / planned-maintenance kill switch.
```

to:

```bash
main(){
  # 0. OBSERVE + ALERT. Deliberately ABOVE every gate below — see the comment on
  #    observe_and_alert. `|| true` so observation can never break promotion logic.
  observe_and_alert || true
  # 0b. OmniRoute reliability observation (Deep Space Nine phase 1) — same
  #     "never gated, never breaks the caller" guarantee, own independent
  #     kill switch, own state directory. See observe_omniroute() above.
  observe_omniroute || true
  # 1. Disarm / planned-maintenance kill switch.
```

- [ ] **Step 4: Write the failing test**

Create `scripts/dr/watchdog/test_observe_omniroute.sh`, mirroring `test_observe_alert.sh`'s exact harness:

```bash
#!/bin/bash
# Unit test for observe_omniroute() — mirrors test_observe_alert.sh's harness.
# No network, no SSH, no Telegram: tg_notify is stubbed and both DR and
# RELIABILITY_DIR are mktemps.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

export DR_WATCHDOG_LIB=1
# shellcheck disable=SC1091
. "$HERE/dr_watchdog.sh"

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
DR="$T"
RELIABILITY_DIR="$T/reliability"
OMNIROUTE_HEARTBEAT_FILE="$T/.omniroute_heartbeat"
OMNIROUTE_DISABLED_FLAG="$RELIABILITY_DIR/.omniroute_watchdog_disabled"
mkdir -p "$RELIABILITY_DIR"

ALERTS="$T/alerts"; : > "$ALERTS"
LOGS="$T/logs";     : > "$LOGS"
tg_notify(){ printf '%s\n' "$(printf '%s' "$*" | tr '\n' ' ')" >> "$ALERTS"; }
log(){ printf '%s\n' "$*" >> "$LOGS"; }

FAKE_NOW=1000000
now_epoch(){ echo "$FAKE_NOW"; }
write_hb(){ printf 'ts=%s %s\n' "$FAKE_NOW" "$1" > "$OMNIROUTE_HEARTBEAT_FILE"; }

pass=0; fail=0
check(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
         else echo "  FAIL  $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi; }
alerts_n(){ wc -l < "$ALERTS" | tr -d ' '; }
has(){ grep -q "$1" "$ALERTS" 2>/dev/null && echo yes || echo no; }
reset(){ : > "$ALERTS"; : > "$LOGS"
  rm -f "$RELIABILITY_DIR"/.omniroute_observed_state "$RELIABILITY_DIR"/.omniroute_observed_streak \
        "$OMNIROUTE_DISABLED_FLAG" "$OMNIROUTE_HEARTBEAT_FILE"; }

echo "=== T1: first observation is a silent baseline ==="
reset; write_hb 'tier1=ok tier2=ok tier3=skipped detail="ok"'; observe_omniroute
check "no alert on first sight" 0 "$(alerts_n)"
check "state recorded ok" "ok" "$(cat "$RELIABILITY_DIR/.omniroute_observed_state" 2>/dev/null)"

echo "=== T2: one bad cycle must NOT alert (confirmation threshold) ==="
write_hb 'tier1=ok tier2=fail tier3=skipped detail="opencode provider reports 0 credentials"'
observe_omniroute
check "still silent after 1/2" 0 "$(alerts_n)"

echo "=== T3: second consecutive bad cycle alerts, and names the provider ==="
observe_omniroute
check "one alert" 1 "$(alerts_n)"
check "says OpenCode routing broken" "yes" "$(has 'OpenCode routing is broken')"
check "includes the detail" "yes" "$(has '0 credentials')"

echo "=== T4: staying degraded must NOT re-alert every cycle ==="
observe_omniroute; observe_omniroute
check "still exactly one alert" 1 "$(alerts_n)"

echo "=== T5: recovery alerts ==="
write_hb 'tier1=ok tier2=ok tier3=skipped detail="ok"'
observe_omniroute; observe_omniroute
check "a second alert" 2 "$(alerts_n)"
check "says recovered" "yes" "$(has 'recovered')"

echo "=== T6: tier1=fail alerts as a container-down message, not a provider one ==="
reset; write_hb 'tier1=ok tier2=ok tier3=skipped detail="ok"'; observe_omniroute
write_hb 'tier1=fail tier2=skipped tier3=skipped detail="health endpoint returned 500"'
observe_omniroute; observe_omniroute
check "one alert" 1 "$(alerts_n)"
check "says DOWN, not degraded" "yes" "$(has 'is DOWN')"

echo "=== T7: 🔴 THE FALSE-POSITIVE GUARD — a stale heartbeat alerts distinctly from a reported failure ==="
reset; write_hb 'tier1=ok tier2=ok tier3=skipped detail="ok"'; observe_omniroute
FAKE_NOW=$((FAKE_NOW + 1000))   # older than OMNIROUTE_HEARTBEAT_MAX_AGE (240s default)
observe_omniroute; observe_omniroute
check "one alert" 1 "$(alerts_n)"
check "says heartbeat stale, not OmniRoute down" "yes" "$(has 'heartbeat is stale')"

echo "=== T8: .omniroute_watchdog_disabled suppresses alerts — and says so in the log ==="
reset; write_hb 'tier1=ok tier2=ok tier3=skipped detail="ok"'; observe_omniroute
touch "$OMNIROUTE_DISABLED_FLAG"
write_hb 'tier1=fail tier2=skipped tier3=skipped detail="x"'
observe_omniroute; observe_omniroute
check "silent during planned maintenance" 0 "$(alerts_n)"
check "suppression is logged" "yes" "$(grep -q 'SUPPRESSED' "$LOGS" && echo yes || echo no)"

echo "=== T9: 🔴 must never touch DR failover state ==="
reset
touch "$DR/.failed_over"
before_failed_over="$(md5sum "$DR/.failed_over" 2>/dev/null)"
write_hb 'tier1=fail tier2=skipped tier3=skipped detail="x"'
observe_omniroute; observe_omniroute
check "consec_down untouched" "" "$(cat "$DR/watchdog_state" 2>/dev/null)"
check ".failed_over still present" "yes" "$([ -f "$DR/.failed_over" ] && echo yes || echo no)"

echo "=== T10: observation must never break its caller, even with a garbled heartbeat ==="
reset
printf 'garbage not a real heartbeat line' > "$OMNIROUTE_HEARTBEAT_FILE"
observe_omniroute; rc=$?
check "returns 0 on a garbled heartbeat" 0 "$rc"

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
```

- [ ] **Step 5: Run it to verify it fails**

```bash
chmod +x scripts/dr/watchdog/test_observe_omniroute.sh
bash scripts/dr/watchdog/test_observe_omniroute.sh
```

Expected: FAIL — `observe_omniroute: command not found` (Steps 1-3 haven't landed in the actual file yet if you're following strict TDD order; if you already applied Steps 1-3 above, skip to Step 6).

- [ ] **Step 6: Apply Steps 1-3 to the real file, then run again**

```bash
bash scripts/dr/watchdog/test_observe_omniroute.sh
```

Expected: `RESULT: 10 pass · 0 fail`.

- [ ] **Step 7: Run the *existing* DR test suites to confirm nothing broke**

```bash
bash scripts/dr/watchdog/test_observe_alert.sh
bash scripts/dr/watchdog/test_probe_sentinel.sh
bash scripts/dr/watchdog/test_quorum.sh
```

Expected: all three still report `0 fail` — proves the new config vars/function/call-site didn't disturb the existing DR logic (this is the direct check for the Global Constraint "never touch DR failover state").

- [ ] **Step 8: Commit**

```bash
git add scripts/dr/watchdog/dr_watchdog.sh scripts/dr/watchdog/test_observe_omniroute.sh
git commit -m "feat(watchdog): add OmniRoute observation lane to dr_watchdog.sh, additive only"
```

---

## Task 5: Deploy and prove it live

**Files:** none (deployment + live verification only).

- [ ] **Step 1: Deploy the probe + heartbeat scripts to the hub**

The hub already runs these scripts locally (this repo IS `/mnt/archie_brain` on the hub) — no `scp` needed for the hub side. Just add the cron entry:

```bash
(crontab -l 2>/dev/null; echo "*/2 * * * * OMNIROUTE_API_KEY=\"\$(grep '^OMNIROUTE_API_KEY=' /mnt/archie_brain/.env | cut -d= -f2-)\" /mnt/archie_brain/scripts/watchdog/omniroute_probe_heartbeat.sh >/dev/null 2>&1") | crontab -
crontab -l | grep omniroute
```

- [ ] **Step 2: Deploy the modified `dr_watchdog.sh` to Citadel**

```bash
scp -i ~/.ssh/id_ed25519 scripts/dr/watchdog/dr_watchdog.sh root@100.64.0.10:/opt/archie-dr/watchdog/dr_watchdog.sh
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 "mkdir -p /opt/archie-reliability && bash -n /opt/archie-dr/watchdog/dr_watchdog.sh && echo SYNTAX_OK"
```

Expected: `SYNTAX_OK` (a syntax check, not a run — confirms the edit didn't introduce a shell error before the live timer picks it up).

- [ ] **Step 3: Watch one real cycle**

```bash
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 "journalctl -u dr-watchdog.service --since '3 min ago' --no-pager | grep -i omniroute"
```

Expected, given OpenCode's credential is still broken as of this plan: after enough cycles to clear `OMNIROUTE_CONFIRM=2`, a line like `omniroute observation: provider degraded confirmed over 2 checks — alerting.` and confirmation the Telegram alert was sent (check the actual chat).

- [ ] **Step 4: The recovery half of the drill**

Once you've confirmed the alert fires (Step 3), re-authenticate OmniRoute's OpenCode connection manually:

```bash
ssh -i ~/.ssh/id_ed25519 -L 20128:127.0.0.1:20128 kytran@192.168.1.200
# then, on your local machine, open http://localhost:20128, Settings → Providers,
# reconnect OpenCode
```

Then confirm recovery is detected:

```bash
OMNIROUTE_API_KEY="$(grep '^OMNIROUTE_API_KEY=' /mnt/archie_brain/.env | cut -d= -f2-)" bash /mnt/archie_brain/scripts/watchdog/omniroute_probe_heartbeat.sh -v
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 "journalctl -u dr-watchdog.service --since '3 min ago' --no-pager | grep -i 'omniroute.*recover'"
```

Expected: `omniroute observation: RECOVERED — alerting.` and a "recovered" message in Telegram.

- [ ] **Step 5: Final commit (deployment notes only, no code change)**

If any field-name adjustments were needed in Task 1/2 based on what Step 3 or 4 actually showed, amend those commits now rather than leaving the plan's assumptions uncorrected in git history.

---

## Explicitly out of scope for this plan (see spec §11)

Do not add: Codex CLI integration, quota/rate-limit tracking, a 9Router evaluation, a new systemd timer, or any mesh-IP exposure for OmniRoute. Each is a separate future spec.
