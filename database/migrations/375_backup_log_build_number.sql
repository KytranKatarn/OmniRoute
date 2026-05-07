-- Migration 375: add build_number to backup_log
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS build_number INTEGER;
CREATE INDEX IF NOT EXISTS idx_backup_log_build_number ON backup_log(build_number);
