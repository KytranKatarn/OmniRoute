-- 317_backup_log_schema.sql
-- Canonical backup_log schema. Idempotent — safe to re-run.
-- Preserves legacy columns (backup_type, file_size_bytes, completed_at, created_by)
-- so backup_triage.sh keeps working during the Phase 0 → Phase 1 transition.
--
-- Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md §4
-- Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 2

BEGIN;

CREATE TABLE IF NOT EXISTS backup_log (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Canonical columns (Phase 1+).
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS component            TEXT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS tier                 TEXT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS size_bytes           BIGINT DEFAULT 0;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS duration_ms          INTEGER DEFAULT 0;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS verification_status  TEXT DEFAULT 'not_yet_run';
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS notes                TEXT;

-- Legacy columns that may or may not exist — ensure they do so both old and new writers work.
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS backup_type     VARCHAR(50);
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS file_path       VARCHAR(500);
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS status          VARCHAR(50);
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS error_message   TEXT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS completed_at    TIMESTAMP;

-- Backfill component/tier from legacy backup_type where rows pre-exist.
UPDATE backup_log
   SET component = COALESCE(component, backup_type),
       tier      = COALESCE(tier,      'primary')
 WHERE component IS NULL OR tier IS NULL;

-- Backfill size_bytes from file_size_bytes (separate UPDATE — size_bytes default of 0
-- prevents the COALESCE trick from working).
UPDATE backup_log
   SET size_bytes = file_size_bytes
 WHERE (size_bytes IS NULL OR size_bytes = 0)
   AND file_size_bytes IS NOT NULL
   AND file_size_bytes > 0;

-- Indexes for watchdog (freshness + tier health).
CREATE INDEX IF NOT EXISTS idx_backup_log_created_at
    ON backup_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_log_component_tier
    ON backup_log (component, tier, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_log_status_nonsuccess
    ON backup_log (status) WHERE status != 'success';

COMMIT;
