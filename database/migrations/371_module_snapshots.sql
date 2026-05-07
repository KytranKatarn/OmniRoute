-- Migration 371: module_snapshots table for pre-deploy and manual module checkpoints
CREATE TABLE IF NOT EXISTS module_snapshots (
    id                SERIAL PRIMARY KEY,
    module_name       TEXT NOT NULL,
    snapshot_type     TEXT NOT NULL CHECK (snapshot_type IN ('auto', 'manual', 'pre_deploy')),
    trigger_source    TEXT NOT NULL,
    file_paths        JSONB DEFAULT '[]',
    db_tables         JSONB DEFAULT '[]',
    backup_id         INTEGER REFERENCES backup_log(id) ON DELETE SET NULL,
    clearance_task_id INTEGER,
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_module_snapshots_module ON module_snapshots(module_name);
CREATE INDEX IF NOT EXISTS idx_module_snapshots_created ON module_snapshots(created_at DESC);
