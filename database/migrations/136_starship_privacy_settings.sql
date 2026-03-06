-- Starship Command: privacy settings + setup token for node onboarding

ALTER TABLE remote_nodes
ADD COLUMN IF NOT EXISTS privacy_settings JSONB DEFAULT '{}'::jsonb;

ALTER TABLE remote_nodes
ADD COLUMN IF NOT EXISTS setup_token VARCHAR(64);

COMMENT ON COLUMN remote_nodes.privacy_settings IS 'Node privacy controls: share_hardware, share_models, share_job_stats, share_hostname, local_data_only';
COMMENT ON COLUMN remote_nodes.setup_token IS 'One-time token for node first-boot registration';

-- Per-node agent access controls
CREATE TABLE IF NOT EXISTS node_agent_access (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    is_allowed BOOLEAN DEFAULT true,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(node_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_node_agent_access_node ON node_agent_access(node_id);
