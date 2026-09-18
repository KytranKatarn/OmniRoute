#!/bin/bash
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export PROBE_OMNIROUTE_LIB=1
# shellcheck disable=SC1091
. "$HERE/probe_omniroute.sh"

pass=0; fail=0
check(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
         else echo "  FAIL  $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi; }

echo "=== tier1 (liveness) ==="
check "200 is ok"      "ok"   "$(classify_tier1 200 | head -1)"
check "500 is fail"    "fail" "$(classify_tier1 500 | head -1)"
check "no response is fail" "fail" "$(classify_tier1 '' | head -1)"

echo "=== tier2 (canary) ==="
check "200 is ok"   "ok"   "$(classify_tier2 200 | head -1)"
check "502 is fail" "fail" "$(classify_tier2 502 | head -1)"
check "401 is fail" "fail" "$(classify_tier2 401 | head -1)"
check "no response is fail" "fail" "$(classify_tier2 '' | head -1)"

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
