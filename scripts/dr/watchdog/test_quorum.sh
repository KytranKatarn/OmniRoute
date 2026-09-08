#!/bin/bash
# Unit test for the watchdog's pure quorum-tally helpers. No I/O, no SSH, no
# network — sources dr_watchdog.sh in library mode and exercises count_down +
# quorum_met across all boston-2 × outpost combinations.
#   bash scripts/dr/watchdog/test_quorum.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# Library mode: defines functions, does NOT run main. Set QUORUM as a normal
# shell var (prefix assignments before `source` don't reliably persist).
export DR_WATCHDOG_LIB=1
QUORUM=2
. "$HERE/dr_watchdog.sh"

pass=0; fail=0
check(){ # desc  expected  actual
  if [ "$2" = "$3" ]; then pass=$((pass+1)); else
    fail=$((fail+1)); echo "FAIL: $1 — expected [$2], got [$3]"; fi
}
# quorum_met returns via exit code; wrap to yes/no.
qm(){ if quorum_met "$1"; then echo yes; else echo no; fi; }

echo "== count_down =="
check "all up"              0 "$(count_down up up up)"
check "one down"           1 "$(count_down down up up)"
check "two down"           2 "$(count_down down down up)"
check "three down"         3 "$(count_down down down down)"
check "unreachable≠down"   1 "$(count_down down unreachable up)"
check "all unreachable"    0 "$(count_down unreachable unreachable unreachable)"
check "empty"              0 "$(count_down)"

echo "== quorum_met (QUORUM=2) =="
check "0 down → no"        no  "$(qm 0)"
check "1 down → no"        no  "$(qm 1)"
check "2 down → yes"       yes "$(qm 2)"
check "3 down → yes"       yes "$(qm 3)"

echo "== realistic scenarios (boston-2 already DOWN; tally outposts) =="
# boston-2 blip: outposts all reachable → 0 down → NO failover.
check "boston blip"        no  "$(qm "$(count_down up up up)")"
# one outpost also down → still NO (need 2).
check "1 outpost down"     no  "$(qm "$(count_down down up up)")"
# two outposts down → real outage → YES.
check "2 outposts down"    yes "$(qm "$(count_down down down up)")"
# split: one down, one unreachable, one up → only 1 confirmed down → NO
# (unreachable is NOT a down-vote — the key false-positive guard).
check "down+unreach+up"    no  "$(qm "$(count_down down unreachable up)")"
# two down, one unreachable → 2 confirmed → YES.
check "2down+unreach"      yes "$(qm "$(count_down down down unreachable)")"

echo "== hub_heartbeat_fresh (cont-102) =="
# Drive the helper with a temp heartbeat file; it reads HEARTBEAT_FILE + clock.
HB_TMP="$(mktemp)"; HEARTBEAT_FILE="$HB_TMP"; HEARTBEAT_MAX_AGE=300
hbf(){ if hub_heartbeat_fresh; then echo yes; else echo no; fi; }
_now="$(date +%s)"
printf 'ts=%s db=ok http=200\n'  "$_now"          > "$HB_TMP"; check "fresh + db=ok"      yes "$(hbf)"
printf 'ts=%s db=ok http=200\n'  "$((_now-9999))" > "$HB_TMP"; check "stale (age>max)"     no  "$(hbf)"
printf 'ts=%s db=down http=ERR\n' "$_now"         > "$HB_TMP"; check "fresh but db=down"   no  "$(hbf)"
printf 'db=ok http=200\n'                         > "$HB_TMP"; check "no ts field"         no  "$(hbf)"
rm -f "$HB_TMP";                                                check "file missing"        no  "$(hbf)"

echo "== the DEFAULT quorum must be ACHIEVABLE (2026-09-08) =="
# ⚠️ HONEST SCOPE: this is an ARITHMETIC sanity check and it does NOT catch the
# 2026-09-08 defect. That defect was QUORUM=2 against 3 vantages which had all been
# RETIRED — arithmetically valid, operationally impossible (a retired host times out,
# which maps to "unreachable", which never counts as a down-vote, so quorum could
# never be met and every cycle fell into the blackout path). Verified: mutating the
# vantage list back to the retired trio leaves this suite fully green.
# What actually catches that is scripts/dr/test_no_retired_targets.sh — keep BOTH.
# This one earns its place only by catching a future QUORUM bump past the vantage
# count, which is a different and much cheaper mistake.
# Re-source with the FILE's own defaults; this suite pins QUORUM=2 for its own tables.
_defaults="$(env -u QUORUM bash -c 'unset OUTPOSTS
    DR_WATCHDOG_LIB=1 . "'"$HERE"'/dr_watchdog.sh" >/dev/null 2>&1
    echo "${#OUTPOSTS[@]} $QUORUM"' 2>/dev/null)"
_n="${_defaults%% *}"; _q="${_defaults##* }"
check "at least one vantage configured"            yes "$([ "${_n:-0}" -ge 1 ] && echo yes || echo no)"
check "default QUORUM reachable (<= vantage count)" yes "$([ "${_q:-99}" -le "${_n:-0}" ] && echo yes || echo no)"

echo
echo "PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
