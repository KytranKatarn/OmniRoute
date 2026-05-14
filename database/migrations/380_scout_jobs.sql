CREATE TABLE IF NOT EXISTS scout_jobs (
    id              SERIAL PRIMARY KEY,
    job_type        VARCHAR(50) NOT NULL,
    target_url      TEXT NOT NULL,
    params          JSONB DEFAULT '{}',
    egress_tier     INTEGER DEFAULT 1,
    egress_ip       VARCHAR(50),
    status          VARCHAR(20) DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed',
                                      'needs_review','approved','rejected')),
    requested_by    VARCHAR(100),
    agent_id        INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    data            JSONB,
    screenshots     JSONB DEFAULT '[]',
    network_log     JSONB DEFAULT '[]',
    findings        TEXT,
    error_log       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     VARCHAR(100),
    auto_approve    BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_scout_jobs_status
    ON scout_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scout_jobs_type
    ON scout_jobs(job_type, status);
