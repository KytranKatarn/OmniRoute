-- Migration 183: Add result_payload JSONB to mesh_sync_log
-- Stores the full result dict from node ACKs (shell output, exit codes, download stats)
ALTER TABLE mesh_sync_log
ADD COLUMN IF NOT EXISTS result_payload JSONB;

COMMENT ON COLUMN mesh_sync_log.result_payload IS 'Full result dict from node handler ACK (output, exit_code, etc.)';
