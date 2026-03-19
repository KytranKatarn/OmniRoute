-- Migration 178: Code Health upgrade columns
-- Task #1082: commit_hash in snapshots, stale + last_audit_snapshot_id in audit_log

DO $$
BEGIN
    -- Add commit_hash to code_metrics_snapshots
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'code_metrics_snapshots' AND column_name = 'commit_hash'
    ) THEN
        ALTER TABLE code_metrics_snapshots ADD COLUMN commit_hash VARCHAR(40);
    END IF;

    -- Add stale flag to code_audit_log
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'code_audit_log' AND column_name = 'stale'
    ) THEN
        ALTER TABLE code_audit_log ADD COLUMN stale BOOLEAN DEFAULT FALSE;
    END IF;

    -- Add last_audit_snapshot_id to code_audit_log
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'code_audit_log' AND column_name = 'last_audit_snapshot_id'
    ) THEN
        ALTER TABLE code_audit_log ADD COLUMN last_audit_snapshot_id INTEGER REFERENCES code_metrics_snapshots(id);
    END IF;
END $$;
