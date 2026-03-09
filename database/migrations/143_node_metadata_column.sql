-- Add metadata JSONB column to remote_nodes for idle_agents and other node-reported data
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
COMMENT ON COLUMN remote_nodes.metadata IS 'Node-reported metadata including idle_agents from heartbeat';
