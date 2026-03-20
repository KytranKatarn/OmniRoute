-- Migration 121: Allow multiple portrait variants per agent with benchmark data
-- Supports multi-GPU fan-out generation and quality comparison

-- Drop unique constraint to allow multiple portraits per agent
ALTER TABLE agent_portraits DROP CONSTRAINT IF EXISTS agent_portraits_agent_id_key;

-- Add benchmark columns
ALTER TABLE agent_portraits
    ADD COLUMN IF NOT EXISTS model_used VARCHAR(100),
    ADD COLUMN IF NOT EXISTS gpu_host VARCHAR(100),
    ADD COLUMN IF NOT EXISTS gpu_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS generation_time_ms INTEGER,
    ADD COLUMN IF NOT EXISTS resolution_w INTEGER DEFAULT 512,
    ADD COLUMN IF NOT EXISTS resolution_h INTEGER DEFAULT 512,
    ADD COLUMN IF NOT EXISTS provider VARCHAR(50) DEFAULT 'comfyui',
    ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT;

-- Index for quick lookup of all variants for an agent
CREATE INDEX IF NOT EXISTS idx_agent_portraits_agent_id ON agent_portraits(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_portraits_approved ON agent_portraits(agent_id, approved);

COMMENT ON COLUMN agent_portraits.model_used IS 'Checkpoint model (sd_xl_base_1.0, v1-5-pruned, etc)';
COMMENT ON COLUMN agent_portraits.gpu_host IS 'Which host generated this (192.168.1.246, hub, cloud)';
COMMENT ON COLUMN agent_portraits.generation_time_ms IS 'How long generation took in milliseconds';
