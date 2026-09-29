#!/usr/bin/env bash
# opencode_lane_guard_check.sh — is each lane's SCOPE GUARD claim true of the
# guard that is actually present?
#
# Split out of opencode_lane_audit.sh, which is now the orchestrator. Two
# reasons: runtime guard state is a different question from the image-file
# comments, and the combined file had outgrown the 9,000-char review pass window
# (past which a file is silently truncated for whoever reviews it — which is how
# this one reached 9,274 chars and merged without anyone noticing).
#
# THE POINT OF CHECK 1: a lane's log line must be verified against the GUARD,
# not against the STRING. An earlier version compared the text and reported the
# guarded lane 17686 as broken when its "scope guard armed" line was accurate —
# its /opt/lane-guard really does hold pre-push. This script checks claim vs state.
#
# READ-ONLY. Exit 0 = every claim true, 1 = a claim does not match reality.

set -uo pipefail

SOURCE_CONTAINER="archie_opencode_terminal"
GUARDED_CONTAINER="archie_opencode_terminal_host"
GUARDFREE_CONTAINER="archie_opencode_terminal_gf"

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
skip() { printf '  SKIP  %s\n' "$1"; }
head2() { printf '\n== %s\n' "$1"; }
in_container() { local c="$1"; shift; docker exec "$c" sh -lc "$*" 2>/dev/null; }
container_present() { docker inspect "$1" >/dev/null 2>&1; }

head2 "1. start.sh's scope-guard log line must MATCH the guard that is present"
# The claim and the reality are checked against EACH OTHER, not against a
# string. A guarded lane legitimately prints "scope guard armed" and a
# guard-free lane must not -- but the test is whether /opt/lane-guard actually
# holds a pre-push hook, because an earlier version of this check compared
# against the STRING and reported a correct guarded lane as broken.
for c in "$GUARDED_CONTAINER" "$GUARDFREE_CONTAINER"; do
    if ! container_present "$c"; then skip "$c not present"; continue; fi
    has_hook="no"
    in_container "$c" '[ -f /opt/lane-guard/pre-push ]' && has_hook="yes"
    # grep -c on no match exits 1 AND prints 0; `|| echo 0` then appends a
    # second 0, so take the first line only and strip anything non-numeric.
    claims="$(in_container "$c" 'grep -c "scope guard armed" /start.sh' | head -1 | tr -cd '0-9')"
    [ -z "$claims" ] && claims=0
    if [ "$has_hook" = "yes" ] && [ "${claims:-0}" -gt 0 ]; then
        pass "$c: prints 'armed' and /opt/lane-guard/pre-push exists (claim true)"
    elif [ "$has_hook" = "no" ] && [ "${claims:-0}" -eq 0 ]; then
        pass "$c: does not claim 'armed' and no guard present (claim true)"
    elif [ "$has_hook" = "yes" ]; then
        fail "$c: a guard IS present but start.sh never claims it armed"
        printf '        the lane has a scope guard that its own output does not\n'
        printf '        mention -- the reverse misreport, and the one that matters\n'
    else
        fail "$c: start.sh claims 'scope guard armed' but /opt/lane-guard/pre-push is ABSENT"
        printf '        a control that misreports its own state\n'
    fi
done

if container_present "$SOURCE_CONTAINER"; then
    out="$(in_container "$SOURCE_CONTAINER" 'grep -n "scope guard armed" /start.sh' || true)"
    if [ -n "$out" ]; then
        pass "$SOURCE_CONTAINER: holds the original guarded text (expected)"
    else
        fail "$SOURCE_CONTAINER: expected the ORIGINAL 'scope guard armed' text"
        printf '        if this changed, the source container is no longer the baseline\n'
        printf '        install_lane_docs() compares against it -- a drifted source\n'
        printf '        changes what counts as "edited by a human"\n'
    fi
else
    skip "$SOURCE_CONTAINER not present"
fi

# --------------------------------------------------------------------------
head2 "2. core.hooksPath must point where the flavor expects"
# lane_flavor() reads core.hooksPath and NEVER the container name, so a wrong
# value here silently installs the wrong instruction set. An unknown path
# installs nothing, which is safe but looks like a no-op bug.
for c in "$GUARDFREE_CONTAINER" "$GUARDED_CONTAINER"; do
    container_present "$c" || { skip "$c not present"; continue; }
    want="guard-free"
    [ "$c" = "$GUARDED_CONTAINER" ] && want="guarded"
    hooks="$(in_container "$c" 'git -C /work/archie-platform config --get core.hooksPath' || true)"
    case "$hooks" in
        /opt/no-guard)  got="guard-free" ;;
        /opt/lane-guard) got="guarded" ;;
        "")              got="unset" ;;
        *)               got="other($hooks)" ;;
    esac
    if [ "$got" = "$want" ]; then
        pass "$c: core.hooksPath=$hooks ($got, as expected)"
    else
        fail "$c: core.hooksPath=$hooks reads as '$got', expected '$want'"
        printf '        this is what selects the lane instruction set at install time\n'
    fi
done

# --------------------------------------------------------------------------
head2 "3. /opt/no-guard must exist and be EMPTY"
# It stands in for the guard as the hooksPath target. If anything is ever
# written into it, a hook could run in a lane that is supposed to have none.
if container_present "$GUARDFREE_CONTAINER"; then
    if in_container "$GUARDFREE_CONTAINER" '[ -d /opt/no-guard ]'; then
        n="$(in_container "$GUARDFREE_CONTAINER" 'ls -A /opt/no-guard 2>/dev/null | wc -l' || echo "?")"
        if [ "$n" = "0" ]; then
            pass "guard-free: /opt/no-guard exists and is empty"
        else
            fail "guard-free: /opt/no-guard holds $n entr(y/ies); a hook could run unguarded"
            in_container "$GUARDFREE_CONTAINER" 'ls -A /opt/no-guard' | sed 's/^/        /'
        fi
    else
        fail "guard-free: /opt/no-guard missing (hooksPath points at nothing)"
    fi
else
    skip "$GUARDFREE_CONTAINER not present"
fi

# --------------------------------------------------------------------------

printf '\n'
if [ "$fails" -gt 0 ]; then
  printf 'RESULT: %d guard claim(s) do not match reality.\n' "$fails"
  exit 1
fi
printf 'RESULT: every lane guard claim matches the guard present.\n'
exit 0
