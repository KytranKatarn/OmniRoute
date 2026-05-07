CREATE TABLE IF NOT EXISTS deployment_package_jobs (
    id              SERIAL PRIMARY KEY,
    package_name    VARCHAR(255) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'queued',
    progress_pct    INTEGER      DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT valid_pkg_status
        CHECK (status IN ('queued', 'building', 'ready', 'failed', 'expired'))
);
CREATE INDEX IF NOT EXISTS idx_deployment_package_jobs_status
    ON deployment_package_jobs(status, created_at DESC);
