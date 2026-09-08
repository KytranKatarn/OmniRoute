#!/bin/bash
# ============================================================================
# The DR scripts must not aim EXECUTABLE code at a retired node or a dead path.
#
#   bash scripts/dr/test_no_retired_targets.sh
#
# WHY THIS EXISTS (measured 2026-09-08):
#
# Retiring a node is a DATABASE change (remote_nodes.status='retired'), but the DR
# scripts hardcode hosts. Nothing connected the two, so retirement left live code
# dialling machines that no longer exist — and it stayed that way for weeks because
# a DR script is only executed during an incident, which is the worst possible
# moment to discover it:
#
#   • the Beacon VPS was removed 2026-08-28 and 5 scripts still ssh'd to it, so the
#     ENTIRE DR ingress layer was inert (the Sep-7 failover logged
#     "Beacon platform flip failed (ssh/rc=255)");
#   • mesh_bootstrap.sh still ran `bootstrap_node "beacon"`, and its header told the
#     operator that three other outposts recover "once Beacon is back on mesh" —
#     all four of those nodes are retired;
#   • failover.sh/failback.sh repointed the WTF database on
#     kytran@100.64.0.2:/opt/archie-products/what-the-fact, a path that does not
#     exist (WTF moved to Citadel and its DB is now Citadel-local).
#
# COMMENTS ARE ALLOWED and deliberately so — the history of why a host went away is
# worth keeping. Only executable references fail. That distinction is the whole test:
# a blanket grep would force deleting the explanations along with the bug.
#
# When a node is retired, add it here. The failure message is the instruction.
# ============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# host/path -> why it is dead. Keep in step with remote_nodes.status='retired'.
RETIRED=(
  "2.25.170.252|Beacon VPS, removed by Hostinger 2026-08-28 (Citadel inherited the front door)"
  "156.67.217.86|Outpost - Singapore, sunset 2026-08-29"
  "72.62.112.210|Outpost - Lithuania, sunset 2026-08-29"
  "2.24.130.153|Outpost - United Kingdom, sunset 2026-08-29"
  "100.64.0.11|Beacon mesh IP, node retired"
  "100.64.0.5|Outpost - Singapore mesh IP, node retired"
  "100.64.0.7|Outpost - Lithuania mesh IP, node retired"
  "100.64.0.8|Outpost - United Kingdom mesh IP, node retired"
  "/opt/archie-products/what-the-fact|WTF moved to Citadel; this path does not exist on outpost-us"
)

pass=0; fail=0
for entry in "${RETIRED[@]}"; do
  needle="${entry%%|*}"; why="${entry#*|}"
  # Strip comments and blank lines, keep the filename:line prefix for the report.
  hits="$(grep -rn -F "$needle" "$HERE"/*.sh "$HERE"/watchdog/*.sh 2>/dev/null \
          | grep -v "test_no_retired_targets.sh" \
          | awk -F: '{ line=""; for(i=3;i<=NF;i++) line = line (i>3 ? ":" : "") $i;
                       sub(/^[[:space:]]+/, "", line);
                       if (line !~ /^#/) print $1":"$2": "line }')"
  if [ -z "$hits" ]; then
    echo "  PASS  no executable reference to $needle"
    pass=$((pass+1))
  else
    echo "  FAIL  executable reference to $needle — $why"
    echo "$hits" | sed 's/^/          /'
    fail=$((fail+1))
  fi
done

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
