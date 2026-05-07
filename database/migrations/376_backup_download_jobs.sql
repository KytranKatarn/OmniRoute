-- Migration 376: async backup download job tracking
CREATE TABLE IF NOT EXISTS backup_download_jobs (
    id              SERIAL PRIMARY KEY,
    backup_name     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','preparing','ready','failed','expired')),
    archive_path    TEXT,
    error           TEXT,
    file_size_bytes BIGINT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '1 hour',
    downloaded_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_download_jobs_backup  ON backup_download_jobs(backup_name);
CREATE INDEX IF NOT EXISTS idx_download_jobs_status  ON backup_download_jobs(status);
CREATE INDEX IF NOT EXISTS idx_download_jobs_expires ON backup_download_jobs(expires_at);
