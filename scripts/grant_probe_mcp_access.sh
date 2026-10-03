#!/usr/bin/env bash
# grant_probe_mcp_access.sh — let the MCP gateway read P.R.O.B.E. QA tables
#
# WHY
#   archie_mcp_gateway connects as `codex_ro`, a read-only role deliberately
#   scoped to 40 knowledge/memory/project tables. Zero qa_* tables. So the MCP
#   tools list_qa_suites / get_qa_results fail with:
#       permission denied for table qa_test_suites
#   The data is not missing — the `archie` role can read it fine. Only the MCP
#   surface is gated.
#
#   This widens that deliberate boundary. It is reversible (see --revoke).
#
# SCOPE
#   Grants SELECT only, on three tables, to one role. No INSERT/UPDATE/DELETE,
#   no other role, no other table.
#
# USAGE
#   scripts/grant_probe_mcp_access.sh            # show current state, change nothing
#   scripts/grant_probe_mcp_access.sh --apply    # apply, then verify
#   scripts/grant_probe_mcp_access.sh --revoke   # undo
#
# VERIFY IT CAN FAIL
#   Before --apply, each table prints "no". If it printed "yes" already you do
#   not need this script.

set -euo pipefail

ROLE="codex_ro"
DB="archie"
TABLES=(qa_test_suites qa_test_runs qa_test_results)
ACTION="status"

for arg in "$@"; do
  case "$arg" in
    --apply)  ACTION="apply"  ;;
    --revoke) ACTION="revoke" ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

psql_as_admin() {
  docker exec -i archie_database psql -U archie -d "$DB" -tAX -c "$1"
}

have_role() {
  local n
  n=$(psql_as_admin "SELECT count(*) FROM pg_roles WHERE rolname='${ROLE}';")
  [ "$n" = "1" ]
}

if ! have_role; then
  echo "FATAL: role '${ROLE}' does not exist." >&2
  echo "The MCP gateway DB_USER is probably not codex_ro any more. Check:" >&2
  echo "  docker exec archie_mcp_gateway sh -c 'echo \$DB_USER'" >&2
  exit 1
fi

show_state() {
  local t
  printf '  %-18s %s\n' "TABLE" "SELECT?"
  for t in "${TABLES[@]}"; do
    local yn
    yn=$(psql_as_admin "SELECT CASE WHEN has_table_privilege('${ROLE}','public.${t}','SELECT') THEN 'yes' ELSE 'no' END;")
    printf '  %-18s %s\n' "$t" "$yn"
  done
}

case "$ACTION" in
  status)
    echo "current access for role '${ROLE}' (read-only):"
    show_state
    echo
    echo "No changes made. Re-run with --apply to grant, or --revoke to undo."
    ;;

  apply)
    echo "granting SELECT on ${#TABLES[@]} tables to ${ROLE} ..."
    for t in "${TABLES[@]}"; do
      # Idempotent. Scoped to public schema + one table.
      psql_as_admin "GRANT SELECT ON public.${t} TO ${ROLE};" >/dev/null
      echo "  granted: ${t}"
    done
    echo
    echo "after:"
    show_state
    echo
    echo "Confirm through the MCP tool (this is the check that matters):"
    echo "  list_qa_suites should now return suites instead of 'permission denied'."
    ;;

  revoke)
    echo "revoking SELECT from ${ROLE} ..."
    for t in "${TABLES[@]}"; do
      psql_as_admin "REVOKE SELECT ON public.${t} FROM ${ROLE};" >/dev/null
      echo "  revoked: ${t}"
    done
    echo
    echo "after:"
    show_state
    ;;
esac
