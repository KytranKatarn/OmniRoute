-- 432_backfill_tel_agent_id.sql — populate task_execution_log.agent_id from agent_name.
--
-- ~48% of task_execution_log rows logged a NULL agent_id (fleet-dispatched work; the
-- write path is fixed in fleet_mesh_routes.py + fleet_node_routes.py). The welfare /
-- dispatch-throttle aggregates key on agent_id, so those NULLs undercounted real token
-- usage and the #4090 throttle never fired on over-budget agents (V.E.R.I.F.Y. read 15%
-- of its true 24h tokens). This backfills agent_id from the (unique) agent name.
--
-- Scoped to the welfare-relevant window (last 35 days = the 24h throttle window + the
-- 30d budget-recalibration window) to bound the UPDATE on the DR-replicating hub DB;
-- older rows stay NULL but fall outside every welfare window, so they are harmless.
-- Idempotent + re-runnable.
--
-- Apply:  docker exec -i archie_database psql -U archie -d archie < 432_backfill_tel_agent_id.sql

UPDATE task_execution_log t
SET agent_id = a.id
FROM agents a
WHERE t.agent_id IS NULL
  AND t.created_at > NOW() - INTERVAL '35 days'
  AND a.name = regexp_replace(t.agent_name, ' \(CLI\)$', '');
