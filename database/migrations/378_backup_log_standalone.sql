ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS standalone_name VARCHAR(100);
CREATE INDEX IF NOT EXISTS idx_backup_log_standalone
    ON backup_log(standalone_name) WHERE standalone_name IS NOT NULL;
