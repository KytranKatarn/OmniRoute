#!/bin/bash
# scripts/dr/reconcile_fleet_identity.sh  [--apply]
#
# DR remediation FIX7 (postmortem: .claude/dr-postmortem-and-remediation.md).
# Detects and (with --apply) repairs fleet nodes orphaned by a re-registration
# storm — the failure mode that took 7/9 nodes offline on 2026-06-05. Run on the
# HUB (where archie_database lives). Dry-run by default; --apply makes changes.
#
# What it does:
#   1. REPORT  — approved rows that look orphaned (stale heartbeat) AND have a
#                matching pending 'standard' junk duplicate on the same hostname.
#   2. --apply — delete ONLY FK-safe pending duplicates (no node_agents / no
#                model_load_state references) that map to an approved original.
#   3. --apply — re-activate approved rows that are still heartbeat-fresh.
#   4. Always  — print the per-node repoint command each still-stale node needs
#                (deleting the DB row does NOT move a live process off a junk id;
#                the node's sync container must reload its env NODE_ID).
#
# This tool NEVER mints, approves, or re-keys a node — it only removes junk and
# surfaces the manual action. Recovery of the live process is via a sync-container
# restart (reloads env NODE_ID) or /opt/archie-node/repoint.sh on the node itself.
set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# DB container: archie_database on the hub; override to the promoted replica on the
# DR base during a failover, e.g. DB_CONTAINER=archie_dr_replica reconcile_fleet_identity.sh
DB_CONTAINER="${DB_CONTAINER:-archie_database}"
PSQL=(docker exec "$DB_CONTAINER" psql -U archie -d archie -v ON_ERROR_STOP=1 -tAc)
HUB_MESH_IP="${HUB_MESH_IP:-100.64.0.4}"

echo "== Fleet identity reconcile ($([ "$APPLY" = 1 ] && echo APPLY || echo dry-run)) =="
echo ""

echo "-- Orphan candidates (approved+stale with a matching pending duplicate) --"
"${PSQL[@]}" "
  SELECT a.id||' '||a.node_id||' ('||a.deployment_mode||')  <=  junk:'||p.id||' '||p.node_id||'  host='||COALESCE(p.hostname,'?')
  FROM remote_nodes a
  JOIN remote_nodes p ON a.hostname = p.hostname AND a.hostname IS NOT NULL AND a.id <> p.id
  WHERE a.approval_status = 'approved'
    AND p.approval_status = 'pending'
  ORDER BY a.id;"
echo ""

echo "-- Pending 'standard' junk rows (storm signature; none expected in a healthy fleet) --"
"${PSQL[@]}" "
  SELECT id||' '||node_id||'  host='||COALESCE(hostname,'?')||'  created='||created_at
  FROM remote_nodes
  WHERE approval_status = 'pending' AND deployment_mode = 'standard'
  ORDER BY created_at DESC;"
echo ""

if [ "$APPLY" = 1 ]; then
  echo "-- APPLY: deleting FK-safe pending duplicates that map to an approved original --"
  # Clean dependent telemetry first (FK on node_db_id), then the rows themselves.
  "${PSQL[@]}" "
    DELETE FROM model_load_state m
    USING remote_nodes p
    WHERE m.node_db_id = p.id
      AND p.approval_status = 'pending'
      AND EXISTS (SELECT 1 FROM remote_nodes a
                  WHERE a.approval_status='approved' AND a.hostname = p.hostname AND a.id <> p.id);"
  DELETED=$("${PSQL[@]}" "
    WITH del AS (
      DELETE FROM remote_nodes p
      WHERE p.approval_status = 'pending'
        AND NOT EXISTS (SELECT 1 FROM node_agents      na WHERE na.node_id   = p.id)
        AND NOT EXISTS (SELECT 1 FROM model_load_state m  WHERE m.node_db_id = p.id)
        AND EXISTS (SELECT 1 FROM remote_nodes a
                    WHERE a.approval_status='approved' AND a.hostname = p.hostname AND a.id <> p.id)
      RETURNING 1)
    SELECT count(*) FROM del;")
  echo "   deleted $DELETED FK-safe junk row(s)"

  echo "-- APPLY: re-activating approved rows that are still heartbeat-fresh (<5 min) --"
  "${PSQL[@]}" "
    UPDATE remote_nodes SET is_active = TRUE
    WHERE approval_status = 'approved'
      AND last_heartbeat > NOW() - INTERVAL '5 minutes'
      AND is_active = FALSE;"
  echo "   done"
  echo ""
fi

echo "-- Per-node action still required (approved rows with a STALE heartbeat) --"
echo "   The live process holds a junk id; restart its sync container (reloads env"
echo "   NODE_ID) or run repoint.sh on the node. Commands below:"
"${PSQL[@]}" "
  SELECT '   # '||node_id||' ('||COALESCE(hostname,'?')||', mode='||deployment_mode||', stale '||
         COALESCE(EXTRACT(EPOCH FROM NOW()-last_heartbeat)::int::text,'never')||'s):  '||
         CASE WHEN deployment_mode='starship'
              THEN 'ssh Famil@<lan-ip> \"docker restart archie_node_sync\"'
              ELSE 'ssh root@<ip> \"/opt/archie-node/repoint.sh '||'${HUB_MESH_IP}'||'\"' END
  FROM remote_nodes
  WHERE approval_status = 'approved'
    AND (last_heartbeat IS NULL OR last_heartbeat < NOW() - INTERVAL '3 minutes')
  ORDER BY id;"
echo ""
echo "== reconcile complete =="
[ "$APPLY" = 1 ] || echo "   (dry-run — re-run with --apply to delete FK-safe junk rows)"
