-- Migration 374: restore session tracking
-- Tracks sandbox restore attempts and their QA status

CREATE TABLE IF NOT EXISTS module_restore_sessions (
    id              SERIAL PRIMARY KEY,
    backup_id       INTEGER NOT NULL REFERENCES backup_log(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','sandbox_ready','qa_running','qa_passed','qa_failed','promoting','promoted','failed')),
    sandbox_schema  TEXT,
    sandbox_url     TEXT,
    qa_run_id       INTEGER,
    qa_passed       INTEGER DEFAULT 0,
    qa_total        INTEGER DEFAULT 0,
    qa_failures     JSONB DEFAULT '[]',
    triggered_by    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restore_sessions_backup ON module_restore_sessions(backup_id);
CREATE INDEX IF NOT EXISTS idx_restore_sessions_status ON module_restore_sessions(status);
