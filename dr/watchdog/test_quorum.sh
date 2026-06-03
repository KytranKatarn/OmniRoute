#!/bin/bash
# Unit test for the watchdog's pure quorum-tally helpers. No I/O, no SSH, no
# network — sources dr_watchdog.sh in library mode and exercises count_down +
# quorum_met across all boston-2 × outpost combinations.
#   bash dr/watchdog/test_quorum.sh
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

echo
echo "PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
