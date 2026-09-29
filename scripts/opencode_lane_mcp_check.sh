#!/usr/bin/env bash
# opencode_lane_mcp_check.sh — are the MCP servers the lanes declare actually usable?
#
# Split out of opencode_lane_audit.sh (which audits the GUARD claims) because MCP
# health is a different question, and because the combined file had grown past the
# 9,000-char review pass window -- where a file is silently truncated for whoever
# reviews it, which is how the audit script reached 9,274 chars unnoticed.
#
# WHY THIS NEEDS ITS OWN CHECK: the two MCP servers fail in OPPOSITE ways.
#
#   archie-kb      remote HTTP  -> needs nothing on disk. Keeps working.
#   hostinger-api  local-exec   -> opencode.json runs a binary that lives in the
#                                  /opencode-home VOLUME, not in the image.
#
# So a fresh or recreated volume loses hostinger while archie-kb carries on
# working, every guard check still passes, and the loss is easy to miss. That is
# exactly what happened on 2026-09-29: found on the guard-free lane, and the same
# check immediately found it missing on the guarded lane too.
#
# READ-ONLY. Changes nothing in any container.
#
# Usage:  scripts/opencode_lane_mcp_check.sh
# Exit:   0 = every declared local-exec MCP has its binary; 1 = one or more missing

set -uo pipefail

SOURCE_CONTAINER="archie_opencode_terminal"
GUARDED_CONTAINER="archie_opencode_terminal_host"
GUARDFREE_CONTAINER="archie_opencode_terminal_gf"

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
skip() { printf '  SKIP  %s\n' "$1"; }
in_container() { local c="$1"; shift; docker exec "$c" sh -lc "$*" 2>/dev/null; }
container_present() { docker inspect "$1" >/dev/null 2>&1; }

printf '== local-exec MCP servers must have their binary present ==\n'

for c in "$GUARDFREE_CONTAINER" "$SOURCE_CONTAINER" "$GUARDED_CONTAINER"; do
    container_present "$c" || { skip "$c not present"; continue; }

    # Ask the lane's OWN config what it declares, rather than hardcoding a list:
    # a server added to opencode.json later is then covered automatically.
    bins="$(in_container "$c" 'python3 -c "
import json
d = json.load(open(\"/opencode-home/config/opencode/opencode.json\"))
for name, v in (d.get(\"mcp\") or {}).items():
    if not isinstance(v, dict):
        continue
    if v.get(\"type\") == \"remote\":
        continue
    for b in (v.get(\"command\") or []):
        if isinstance(b, str) and b.startswith(\"/\"):
            print(name, b)
"')"

    if [ -z "$bins" ]; then
        skip "$c: declares no local-exec MCP server"
        continue
    fi

    while read -r name bin; do
        [ -n "${bin:-}" ] || continue
        if in_container "$c" "[ -x '$bin' ]"; then
            pass "$c: $name -> $(basename "$bin") present"
        else
            fail "$c: $name -> $bin MISSING (that MCP will not start)"
            printf '        guard-free self-heals this at boot (lane-docs-boot). The\n'
            printf '        guarded lanes do not. Reinstall with:\n'
            printf '          docker exec -u 0 %s sh -lc "cd /opencode-home/opt && npm install --no-audit --no-fund"\n' "$c"
        fi
    done <<EOF
$bins
EOF
    # A local-exec MCP whose command reads a SECRET PATH is only as healthy as the
    # mount behind it. The mount is applied at container-create time, so editing
    # opencode.json to read /run/secrets/... without recreating the container leaves
    # a config pointing at a file that does not exist -- and the MCP fails with no
    # message anywhere. This is exactly the half-finished state of 2026-09-29, so
    # it is checked rather than assumed.
    refs="$(in_container "$c" 'python3 -c "
import json
d = json.load(open(\"/opencode-home/config/opencode/opencode.json\"))
for name, v in (d.get(\"mcp\") or {}).items():
    if not isinstance(v, dict):
        continue
    for b in (v.get(\"command\") or []):
        if isinstance(b, str) and \"/run/secrets/\" in b:
            import re
            for m in re.findall(r\"/run/secrets/[A-Za-z0-9_.-]+\", b):
                print(name, m)
"')"
    if [ -z "$refs" ]; then
        continue   # no secret-path MCP: nothing further to verify
    fi
    while read -r name path; do
        [ -n "${path:-}" ] || continue
        if in_container "$c" "[ -r '$path' ]"; then
            pass "$c: $name secret path $path readable"
        else
            fail "$c: $name reads $path but it is NOT MOUNTED"
            printf '        opencode.json points at a secret the container does not have.\n'
            printf '        Mounts apply at create time: recreate the lane, it is not enough\n'
            printf '        to edit the config. Until then this MCP cannot authenticate.\n'
        fi
    done <<EOF
$refs
EOF
done

printf '\n'
if [ "$fails" -gt 0 ]; then
    printf 'RESULT: %d MCP server(s) missing their binary.\n' "$fails"
    exit 1
fi
printf 'RESULT: every declared local-exec MCP has its binary.\n'
exit 0
