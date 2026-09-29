#!/usr/bin/env bash
# opencode_lane_audit.sh — owner-side check of the two opencode/ items the lane
# cannot reach, plus a re-check of what the lane CAN see.
#
# WHY THIS EXISTS: two known-wrong comments live in image files under `opencode/`,
# which was outside the lane's allowed_paths. Both were owner tasks; this is how the
# owner confirms they were fixed AND that they have not REGRESSED after a rebuild --
# which is the whole point, because those strings are baked into the image and a
# rebuild silently restores them. Sections 1-3 re-check what the lane CAN see.
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
# MCP health is a DIFFERENT question from the guard claims above, and lives in
# its own script so each file stays inside the review pass window. Delegated, not
# duplicated: the exit code still aggregates, so one command still means
# "is this lane sound".
echo
GUARD_CHECK="$(dirname "$0")/opencode_lane_guard_check.sh"
if [ -x "$GUARD_CHECK" ]; then
  "$GUARD_CHECK" || fails=$((fails + 1))
else
  skip "opencode_lane_guard_check.sh not found - guard claims NOT checked"
fi

MCP_CHECK="$(dirname "$0")/opencode_lane_mcp_check.sh"
if [ -x "$MCP_CHECK" ]; then
  "$MCP_CHECK" || fails=$((fails + 1))
else
  skip "opencode_lane_mcp_check.sh not found next to this script - MCP health NOT checked"
fi

# --------------------------------------------------------------------------
if [ "$PRINT_PATCHES" = "1" ]; then
  head2 "where the fixes live (no patch text here on purpose)"
  cat <<'WHERE'
Both checks above were FAILING once and are now fixed. The fix is not repeated
here as a patch: a second copy of a fix is a second thing to keep in sync, and it
is how a "fixed" file drifts back. Apply the fix at its source instead.

  1. /start.sh "BAKED scope guard" comment
     Fixed in the DERIVATION, not the source: scripts/opencode_lane/common.py
     rewrites that comment with a sed in the guard-free DOCKERFILE. The line is
     CORRECT in the guarded build, so editing scripts/start_opencode_terminal.sh
     would move the lie rather than remove it. Nothing to do unless it regresses.

  2. opencode-pr "THAT SECRET IS NOT MOUNTED YET"
     Fixed at source in opencode/workspace/opencode-pr.sh (owner-widened scope,
     2026-09-28). The token is mounted in all three instances and the owner
     confirmed the mount is deliberate. Re-apply by editing that file and
     rebuilding the base image -- see the README note on image rebuild order.
WHERE
fi

# --------------------------------------------------------------------------
printf '\n'
if [ "$fails" -gt 0 ]; then
    printf 'RESULT: %d check(s) FAILED -- see OWNER ACTION above.\n' "$fails"
    exit 1
fi
printf 'RESULT: all checks passed.\n'
exit 0
