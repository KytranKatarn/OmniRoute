#!/bin/bash
# ============================================================================
# Unit test for the watchdog's OBSERVATION LANE.
#
#   bash scripts/dr/watchdog/test_observe_alert.sh
#
# THE BUG THIS PINS (measured 2026-09-08):
#
# The hub was down 20:08-20:22 UTC. dr-watchdog.timer was `active` and fired ~14
# cycles straight through the outage, each logging only:
#     "awaiting decision (rebuild/skip_rebuild/verify) — exit."
# It probed nothing and alerted nobody; the owner found the outage in a browser.
#
# .failed_over / .awaiting_rebuild are PROMOTION gates that sat ABOVE the probe,
# so disarming DR silently disarmed MONITORING too. The load-bearing assertion in
# this file is therefore test 8: an alert MUST still fire with both flags present.
# A degraded-DR posture is when you are most exposed — it must alert MORE, not go
# quiet. Everything else here exists to stop that alert becoming noise.
#
# No network, no SSH, no Telegram: probe_local and tg_notify are stubbed and the
# DR directory is a mktemp.
# ============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

export DR_WATCHDOG_LIB=1
# shellcheck disable=SC1091
. "$HERE/dr_watchdog.sh"

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
# DISABLED_FLAG is derived from $DR at source time, so BOTH must be redirected —
# pointing only $DR at the temp dir would leave the kill switch reading the real
# /opt/archie-dr and make test 7 pass for the wrong reason.
DR="$T"
DISABLED_FLAG="$T/.watchdog_disabled"

ALERTS="$T/alerts"; : > "$ALERTS"
LOGS="$T/logs";     : > "$LOGS"
# Flatten to ONE line per alert: the DOWN message is deliberately multi-line, and
# counting raw lines would report a single page as three.
tg_notify(){ printf '%s\n' "$(printf '%s' "$*" | tr '\n' ' ')" >> "$ALERTS"; }
log(){ printf '%s\n' "$*" >> "$LOGS"; }

PROBE_RESULT=up
probe_local(){ [ "$PROBE_RESULT" = "up" ]; }

FAKE_NOW=1000000
now_epoch(){ echo "$FAKE_NOW"; }

pass=0; fail=0
check(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
         else echo "  FAIL  $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi; }
# `grep -c` exits 1 on zero matches, so `grep -c . || echo 0` printed BOTH "0" and
# the fallback "0". wc is unambiguous on an empty file.
alerts_n(){ wc -l < "$ALERTS" | tr -d ' '; }
last_alert(){ tail -1 "$ALERTS" 2>/dev/null; }
reset(){ : > "$ALERTS"; : > "$LOGS"; rm -f "$T"/.hub_observed_state "$T"/.hub_observed_streak \
         "$T"/.hub_down_since "$T"/.watchdog_disabled "$T"/.failed_over "$T"/.awaiting_rebuild; }
has(){ grep -q "$1" "$ALERTS" 2>/dev/null && echo yes || echo no; }

echo "=== T1: the first observation is a silent baseline ==="
reset; PROBE_RESULT=up; observe_and_alert
check "no alert on first sight" 0 "$(alerts_n)"
check "state recorded" "up" "$(cat "$T/.hub_observed_state" 2>/dev/null)"

echo "=== T2: one bad cycle must NOT alert (confirmation threshold) ==="
PROBE_RESULT=down; observe_and_alert
check "still silent after 1/2" 0 "$(alerts_n)"
check "state NOT yet flipped" "up" "$(cat "$T/.hub_observed_state" 2>/dev/null)"

echo "=== T3: the second consecutive bad cycle alerts ==="
observe_and_alert
check "one alert" 1 "$(alerts_n)"
check "says DOWN" "yes" "$(has 'is DOWN')"
check "state flipped" "down" "$(cat "$T/.hub_observed_state" 2>/dev/null)"
check "says no failover was triggered" "yes" "$(has 'no failover has been triggered')"

echo "=== T4: staying down must NOT re-alert every 60s ==="
observe_and_alert; observe_and_alert; observe_and_alert
check "still exactly one alert" 1 "$(alerts_n)"

echo "=== T5: recovery alerts, and reports how long it was down ==="
FAKE_NOW=$((FAKE_NOW + 900))          # 15 minutes later
PROBE_RESULT=up; observe_and_alert; observe_and_alert
check "a second alert" 2 "$(alerts_n)"
check "says back" "yes" "$(has 'is back')"
check "reports 15 min" "yes" "$(has '15 min down')"

echo "=== T6: a single flapping cycle can never accumulate into a false alert ==="
reset; PROBE_RESULT=up; observe_and_alert            # baseline up
for _ in 1 2 3; do
  PROBE_RESULT=down; observe_and_alert               # 1/2 — holds
  PROBE_RESULT=up;   observe_and_alert               # steady, clears the streak
done
check "no alert from 3 isolated blips" 0 "$(alerts_n)"

echo "=== T7: .watchdog_disabled suppresses alerts — and SAYS SO ==="
reset; PROBE_RESULT=up; observe_and_alert
touch "$T/.watchdog_disabled"
PROBE_RESULT=down; observe_and_alert; observe_and_alert; observe_and_alert
check "silent during planned maintenance" 0 "$(alerts_n)"
check "but the suppression is logged, not silent" "yes" \
      "$(grep -q 'SUPPRESSED' "$LOGS" && echo yes || echo no)"

echo "=== T8: 🔴 THE REGRESSION — DR disarmed must NOT disarm monitoring ==="
# .failed_over + .awaiting_rebuild are exactly the state the hub was in on
# 2026-09-08, when 14 cycles passed in silence. Both present, and it must alert.
reset; PROBE_RESULT=up; observe_and_alert
touch "$T/.failed_over"; echo "$FAKE_NOW" > "$T/.awaiting_rebuild"
PROBE_RESULT=down; observe_and_alert; observe_and_alert
check "alerts anyway with .failed_over present" 1 "$(alerts_n)"
check "and it is the DOWN alert" "yes" "$(has 'is DOWN')"

echo "=== T9: observation must never break the promotion logic below it ==="
reset
probe_local(){ echo "simulated probe explosion" >&2; return 42; }
observe_and_alert; rc=$?
check "returns 0 even when the probe fails hard" 0 "$rc"
probe_local(){ [ "$PROBE_RESULT" = "up" ]; }

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
