#!/usr/bin/env bash
# opencode_lane_audit.sh — owner-side check of the two opencode/ items the lane
# cannot reach, plus a re-check of what the lane CAN see.
#
# WHY THIS EXISTS: `opencode/` is outside config/agents/opencode.yaml
# allowed_paths, so the opencode lane cannot edit the image files where two
# known-wrong comments live. Both are recorded as owner tasks; this script is how
# the owner confirms they were fixed, and how anyone confirms they have not
# REGRESSED after a rebuild. The rebuild case is the whole point: these strings
# are baked into the image, so a rebuilt image silently restores them.
#
# READ-ONLY. It changes nothing, in any container and on the host. Every fix it
# suggests is printed for a human to apply, never applied here.
#
# Usage:  scripts/opencode_lane_audit.sh            # audit the live containers
#         scripts/opencode_lane_audit.sh --print    # also print suggested patches
#
# Exit: 0 = every check passed, 1 = at least one check FAILED (see "OWNER ACTION").

set -uo pipefail

# Canonical 17685 is the SOURCE container: its files are the comparison baseline
# for install_lane_docs(), so it is expected to hold the ORIGINAL guarded text.
# The other two are derived lanes and are expected to hold the corrected text.
SOURCE_CONTAINER="archie_opencode_terminal"
GUARDED_CONTAINER="archie_opencode_terminal_host"
GUARDFREE_CONTAINER="archie_opencode_terminal_gf"

PRINT_PATCHES=0
[ "${1:-}" = "--print" ] && PRINT_PATCHES=1

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
skip() { printf '  SKIP  %s\n' "$1"; }
head2() { printf '\n== %s\n' "$1"; }

# Run a command inside a container, tolerating a missing container.
in_container() {
    local c="$1"; shift
    docker exec "$c" sh -lc "$*" 2>/dev/null
}
container_present() { docker inspect "$1" >/dev/null 2>&1; }

# --------------------------------------------------------------------------
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
head2 "4. the image files that still carry wrong comments (OWNER ACTION)"
# Both are comments, not behaviour: the runtime is already correct. They are
# checked here because they are baked into the image, so a rebuild restores
# them and nothing else would notice.
if container_present "$GUARDFREE_CONTAINER"; then
    out="$(in_container "$GUARDFREE_CONTAINER" "grep -n 'BAKED scope guard' /start.sh" || true)"
    if [ -z "$out" ]; then
        pass "guard-free: /start.sh no longer claims a 'BAKED scope guard'"
    else
        fail "guard-free: /start.sh comment is wrong for a guard-free build: $out"
        printf '        comment only -- line 90 correctly prints DISABLED. Cosmetic,\n'
        printf '        but it misdescribes the image to whoever reads it next.\n'
    fi
fi
out="$(docker exec "$GUARDFREE_CONTAINER" sh -lc 'grep -rn "NOT MOUNTED YET" /usr/local/bin/opencode-pr /opencode-home/bin/opencode-pr 2>/dev/null' || true)"
if [ -z "$out" ]; then
    pass "opencode-pr: no 'NOT MOUNTED YET' header (owner decision was: mount IS deliberate)"
else
    fail "opencode-pr still says the secret is deliberately NOT mounted, which is FALSE:"
    printf '%s\n' "$out" | sed 's/^/        /'
    printf '        the owner confirmed on 2026-09-28 that the mount is deliberate.\n'
fi

# --------------------------------------------------------------------------
if [ "$PRINT_PATCHES" = "1" ]; then
    head2 "suggested patches (NOT applied -- image rebuild paths, owner only)"
    cat <<'PATCHES'
# 1. start.sh, in opencode/workspace/ (or the image build context):
#    the comment on the "Git identity + ..." line should not mention a baked
#    guard in a build that has none. Suggested:
#
#    -# Git identity + the BAKED scope guard on the lane's own clone.
#    +# Git identity + the lane's own clone. Guard-free build: hooksPath points
#    +# at an EMPTY /opt/no-guard, so there is no scope guard here by design.
#
# 2. opencode-pr's header, in opencode/ (the helper the lane reads BEFORE it
#    ships). It currently states a secret is deliberately absent when one is
#    present. Replace that paragraph with the decision as recorded in
#    docs/superpowers/specs/2026-09-27-opencode-guard-free-terminal.md:
#
#    -THAT SECRET IS NOT MOUNTED YET, and that is deliberate: ...
#    +/run/secrets/opencode_github_token IS mounted, deliberately (owner
#    +confirmed 2026-09-28). Having it is not permission to use it: this lane
#    +still never merges, never approves its own PR, and ships via opencode-pr.
PATCHES
fi

# --------------------------------------------------------------------------
printf '\n'
if [ "$fails" -gt 0 ]; then
    printf 'RESULT: %d check(s) FAILED -- see OWNER ACTION above.\n' "$fails"
    exit 1
fi
printf 'RESULT: all checks passed.\n'
exit 0
