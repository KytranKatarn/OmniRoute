-- Migration 384: Add node_used_id to task_execution_log
-- Phase A of fleet orchestration visibility (Project #303, KB #267241).
--
-- Pairs with migration 382 (dispatch_pending_queue.preferred_node_id, FORWARD-looking
-- "where work SHOULD go") to give us the BACKWARD-looking attribution
-- ("where work ACTUALLY ran"). Without this column, fleet utilization is invisible
-- in the canonical dispatch log — every model_name shared between hub and fleet
-- nodes (qwen2.5:7b, mistral:7b, llama3.2:3b) is unattributable.
--
-- NULL = hub-direct dispatch (the default path). Non-NULL = routed to a fleet node
-- via _dispatch_to_node. ON DELETE SET NULL preserves the historical row even if
-- a node is decommissioned (matches migration 382's choice).

ALTER TABLE task_execution_log
    ADD COLUMN IF NOT EXISTS node_used_id INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL;

-- Index optimised for the common "show me only fleet dispatches" query.
-- Partial index keeps it small — only rows with non-NULL attribution.
CREATE INDEX IF NOT EXISTS idx_task_execution_log_node_used
    ON task_execution_log (node_used_id, created_at DESC)
    WHERE node_used_id IS NOT NULL;

COMMENT ON COLUMN task_execution_log.node_used_id IS
    'FK to remote_nodes.id of the fleet node that executed this dispatch. '
    'NULL = hub-direct (default path). Populated by BridgeDispatcher._log_execution '
    'when _dispatch_to_node is the execution path. See KB #267241.';
