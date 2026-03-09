-- Link node_agents to hub agents table + version tracking for smart sync
ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS hub_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS config_version INTEGER DEFAULT 1;

-- Backfill hub_agent_id for existing node_agents by matching name
UPDATE node_agents na
SET hub_agent_id = a.id
FROM agents a
WHERE na.name = a.name AND na.hub_agent_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_node_agents_hub_agent ON node_agents(hub_agent_id);
