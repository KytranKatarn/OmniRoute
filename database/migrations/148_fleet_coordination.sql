-- Fleet Agent Coordination System
-- Spec: docs/superpowers/specs/2026-03-13-fleet-agent-coordination-design.md

BEGIN;

-- 1. Clean orphan node agents (any without Bridge parent)
DELETE FROM node_agents WHERE source_agent_id IS NULL;

-- 2. Enforce source_agent_id NOT NULL + ON DELETE RESTRICT
ALTER TABLE node_agents ALTER COLUMN source_agent_id SET NOT NULL;
ALTER TABLE node_agents DROP CONSTRAINT IF EXISTS node_agents_source_agent_id_fkey;
ALTER TABLE node_agents ADD CONSTRAINT node_agents_source_agent_id_fkey
    FOREIGN KEY (source_agent_id) REFERENCES agents(id) ON DELETE RESTRICT;

-- 3. Fleet-wide LLM uniqueness (active agents only)
-- Column is "model" not "primary_model"
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_unique_model_active
    ON agents (model) WHERE status = 'active' AND model IS NOT NULL;

-- 4. Station commands table
CREATE TABLE IF NOT EXISTS station_commands (
    id SERIAL PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES bridge_stations(id) ON DELETE CASCADE,
    command_name VARCHAR(100) NOT NULL,
    capability VARCHAR(100) NOT NULL,
    description TEXT,
    parameters_schema JSONB,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(station_id, command_name)
);

-- 5. Indexes for fleet dispatch
CREATE INDEX IF NOT EXISTS idx_node_agents_source ON node_agents(source_agent_id);
CREATE INDEX IF NOT EXISTS idx_node_agents_station ON node_agents USING GIN(station_codes);

COMMIT;
