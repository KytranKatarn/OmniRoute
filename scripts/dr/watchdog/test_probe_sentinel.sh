#!/bin/bash
# ============================================================================
# A vantage that CANNOT ANSWER must never be counted as one REPORTING AN OUTAGE.
#
#   bash scripts/dr/watchdog/test_probe_sentinel.sh
#
# THE BUG THIS PINS (measured 2026-09-08, #3249):
#
# probe_outpost mapped every non-255 exit to "down". The LAN Starships are
# Windows — no bash — so `bash -s` exited non-255 and both voted "down" against a
# hub that was verifiably UP. Two such phantom votes satisfy QUORUM=2 PERMANENTLY,
# so the first mesh hiccup on a healthy hub would arm and auto-promote after the
# 300s window — manufacturing the split-brain the 2026-09-07 failover left behind.
#
# The exit code cannot carry this verdict. Measured: PowerShell's `exit 1` over
# `ssh "powershell -NoProfile -Command -"` arrives at the caller as **exit 0**.
# So the CONTRACT is the stdout sentinel, and its absence means "could not run":
#
#     PROBE_RESULT=up    -> up
#     PROBE_RESULT=down  -> down
#     anything else      -> unreachable   <- never a down-vote
#
# `unreachable` is the safe answer because count_down ignores it: an unusable
# vantage can stall a failover but can never cause one. That asymmetry is the
# entire point and every assertion below defends one side of it.
#
# No network: `ssh` is stubbed as a shell function.
# ============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DR_WATCHDOG_LIB=1
# shellcheck disable=SC1091
. "$HERE/dr_watchdog.sh"

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
touch "$T/fakekey"; FLEET_KEY="$T/fakekey"
PROBE_SCRIPT="$HERE/probe_hub.sh"; PROBE_SCRIPT_PS="$HERE/probe_hub.ps1"
HUB_MESH=100.64.0.4; SSH_TIMEOUT=5

SSH_OUT=""; SSH_RC=0; SSH_SEEN="$T/seen"
ssh(){ printf '%s\n' "$*" > "$SSH_SEEN"; cat >/dev/null 2>&1 || true;
       [ -n "$SSH_OUT" ] && printf '%s\n' "$SSH_OUT"; return "$SSH_RC"; }

pass=0; fail=0
check(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
         else echo "  FAIL  $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi; }

echo "=== the sentinel decides the vote ==="
SSH_OUT="PROBE_RESULT=up";   SSH_RC=0; check "up sentinel -> up"     up   "$(probe_outpost kytran@100.64.0.2)"
SSH_OUT="PROBE_RESULT=down"; SSH_RC=1; check "down sentinel -> down" down "$(probe_outpost kytran@100.64.0.2)"

echo "=== 🔴 THE REGRESSION: no sentinel is UNREACHABLE, never down ==="
# Each of these is a real way a vantage fails to run the probe. The old code
# called every one of them "down".
SSH_OUT="bash: command not found"; SSH_RC=127
check "wrong shell (the Windows case) -> unreachable" unreachable "$(probe_outpost Famil@100.64.0.3)"
SSH_OUT=""; SSH_RC=1
check "silent non-zero -> unreachable"                unreachable "$(probe_outpost kytran@100.64.0.2)"
SSH_OUT="The system cannot find the path specified."; SSH_RC=1
check "windows cmd noise -> unreachable"              unreachable "$(probe_outpost Famil@100.64.0.6)"
SSH_OUT=""; SSH_RC=255
check "ssh itself failed -> unreachable"              unreachable "$(probe_outpost kytran@100.64.0.2)"

echo "=== a spurious exit code must NOT override a good sentinel ==="
# PowerShell's `exit 1` arrives as 0 and vice versa; the sentinel wins either way.
SSH_OUT="PROBE_RESULT=down"; SSH_RC=0
check "down sentinel with exit 0 -> down" down "$(probe_outpost 'Famil@100.64.0.3|pwsh')"
SSH_OUT="PROBE_RESULT=up";   SSH_RC=9
check "up sentinel with exit 9 -> up"     up   "$(probe_outpost kytran@100.64.0.2)"

echo "=== the |pwsh suffix selects the Windows probe, and is not part of the host ==="
SSH_OUT="PROBE_RESULT=up"; SSH_RC=0
probe_outpost 'Famil@100.64.0.3|pwsh' >/dev/null
check "pwsh vantage invokes powershell" yes \
      "$(grep -q 'powershell' "$SSH_SEEN" && echo yes || echo no)"
check "the |pwsh suffix is stripped from the ssh target" yes \
      "$(grep -q 'Famil@100.64.0.3' "$SSH_SEEN" && ! grep -q 'pwsh|' "$SSH_SEEN" && echo yes || echo no)"
probe_outpost kytran@100.64.0.2 >/dev/null
check "un-suffixed vantage uses bash" yes \
      "$(grep -q 'bash -s' "$SSH_SEEN" && echo yes || echo no)"

echo "=== a missing fleet key is unreachable, not down ==="
FLEET_KEY="$T/nope"
check "no key -> unreachable" unreachable "$(probe_outpost kytran@100.64.0.2)"
FLEET_KEY="$T/fakekey"

echo "=== and unreachable can never trip the quorum ==="
check "3 unreachable -> 0 down-votes" 0 "$(count_down unreachable unreachable unreachable)"
# QUORUM is set explicitly: this asserts the ARITHMETIC, not whichever default
# the sourced file happens to carry today.
check "2 unreachable + 1 down does not reach QUORUM=2" no \
      "$(QUORUM=2; if quorum_met "$(count_down unreachable unreachable down)" 2>/dev/null; then echo yes; else echo no; fi)"
check "2 real down votes DO reach QUORUM=2" yes \
      "$(QUORUM=2; if quorum_met "$(count_down down down unreachable)" 2>/dev/null; then echo yes; else echo no; fi)"

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
