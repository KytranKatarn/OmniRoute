-- Migration 382: Add preferred_node_id to dispatch_pending_queue
-- Enables fleet-node-preferred dispatch routing (Phase 2, Project #303)
-- When an agent is assigned to a fleet node, the dispatcher stores that
-- node's DB id here so model_dispatch_worker routes inference to the right hardware.

ALTER TABLE dispatch_pending_queue
    ADD COLUMN IF NOT EXISTS preferred_node_id INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_dispatch_queue_preferred_node
    ON dispatch_pending_queue (preferred_node_id)
    WHERE preferred_node_id IS NOT NULL AND status = 'queued';
