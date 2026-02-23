-- Migration 118: Training & Lounge Upgrade
-- Date: 2026-02-23
-- Purpose: Add node training support columns and rest cycle emotional snapshots

-- Add node training columns to training_assignments
ALTER TABLE training_assignments
ADD COLUMN IF NOT EXISTS source_node_id INTEGER,
ADD COLUMN IF NOT EXISTS source_node_name VARCHAR(200),
ADD COLUMN IF NOT EXISTS training_type VARCHAR(30) DEFAULT 'internal';

-- Add emotional state snapshot columns to rest cycles for delta tracking
ALTER TABLE agent_rest_cycles
ADD COLUMN IF NOT EXISTS stress_at_start NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS energy_at_start NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS stress_at_end NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS energy_at_end NUMERIC(3,2);

COMMENT ON COLUMN training_assignments.source_node_id IS 'Node ID if training request came from external node';
COMMENT ON COLUMN training_assignments.training_type IS 'internal, node_incoming, or node_outgoing';
COMMENT ON COLUMN agent_rest_cycles.stress_at_start IS 'Stress level when rest began (for delta display)';
COMMENT ON COLUMN agent_rest_cycles.energy_at_end IS 'Energy level when rest ended (for delta display)';
