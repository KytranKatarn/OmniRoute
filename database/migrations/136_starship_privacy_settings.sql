-- Starship Command: privacy settings + setup token for node onboarding

ALTER TABLE remote_nodes
ADD COLUMN IF NOT EXISTS privacy_settings JSONB DEFAULT '{}'::jsonb;

ALTER TABLE remote_nodes
ADD COLUMN IF NOT EXISTS setup_token VARCHAR(64);

COMMENT ON COLUMN remote_nodes.privacy_settings IS 'Node privacy controls: share_hardware, share_models, share_job_stats, share_hostname, local_data_only';
COMMENT ON COLUMN remote_nodes.setup_token IS 'One-time token for node first-boot registration';
