-- Node OTA update: flag for pull-based update via heartbeat
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS update_requested BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS update_requested_at TIMESTAMP;
COMMENT ON COLUMN remote_nodes.update_requested IS 'When true, next heartbeat tells node to self-update';
COMMENT ON COLUMN remote_nodes.update_requested_at IS 'When the update was requested';
