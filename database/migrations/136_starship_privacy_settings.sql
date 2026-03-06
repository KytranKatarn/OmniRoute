-- Add privacy_settings JSONB column to remote_nodes
-- Allows starship operators to control what data is shared with the fleet

ALTER TABLE remote_nodes
ADD COLUMN IF NOT EXISTS privacy_settings JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN remote_nodes.privacy_settings IS 'Node privacy controls: share_hardware, share_models, share_job_stats, share_hostname, local_data_only';
