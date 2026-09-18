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
reset; write_hb 'tier1=ok tier2=ok detail="ok"'; observe_omniroute
check "no alert on first sight" 0 "$(alerts_n)"
check "state recorded ok" "ok" "$(cat "$RELIABILITY_DIR/.omniroute_observed_state" 2>/dev/null)"

echo "=== T2: one bad cycle must NOT alert (confirmation threshold) ==="
write_hb 'tier1=ok tier2=fail detail="opencode provider reports 0 credentials"'
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
write_hb 'tier1=ok tier2=ok detail="ok"'
observe_omniroute; observe_omniroute
check "a second alert" 2 "$(alerts_n)"
check "says recovered" "yes" "$(has 'recovered')"

echo "=== T6: tier1=fail alerts as a container-down message, not a provider one ==="
reset; write_hb 'tier1=ok tier2=ok detail="ok"'; observe_omniroute
write_hb 'tier1=fail tier2=skipped detail="health endpoint returned 500"'
observe_omniroute; observe_omniroute
check "one alert" 1 "$(alerts_n)"
check "says DOWN, not degraded" "yes" "$(has 'is DOWN')"

echo "=== T7: 🔴 THE FALSE-POSITIVE GUARD — a stale heartbeat alerts distinctly from a reported failure ==="
reset; write_hb 'tier1=ok tier2=ok detail="ok"'; observe_omniroute
FAKE_NOW=$((FAKE_NOW + 1000))   # older than OMNIROUTE_HEARTBEAT_MAX_AGE (600s default)
observe_omniroute; observe_omniroute
check "one alert" 1 "$(alerts_n)"
check "says heartbeat stale, not OmniRoute down" "yes" "$(has 'heartbeat is stale')"

echo "=== T8: .omniroute_watchdog_disabled suppresses alerts — and says so in the log ==="
reset; write_hb 'tier1=ok tier2=ok detail="ok"'; observe_omniroute
touch "$OMNIROUTE_DISABLED_FLAG"
write_hb 'tier1=fail tier2=skipped detail="x"'
observe_omniroute; observe_omniroute
check "silent during planned maintenance" 0 "$(alerts_n)"
check "suppression is logged" "yes" "$(grep -q 'SUPPRESSED' "$LOGS" && echo yes || echo no)"

echo "=== T9: 🔴 must never touch DR failover state ==="
reset
touch "$DR/.failed_over"
before_failed_over="$(md5sum "$DR/.failed_over" 2>/dev/null)"
write_hb 'tier1=fail tier2=skipped detail="x"'
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
