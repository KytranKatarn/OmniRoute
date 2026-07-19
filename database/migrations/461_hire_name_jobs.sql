-- 461_hire_name_jobs.sql
-- Async hire-name Generate (#4969). The DHQ Approvals "Generate" name button ran
-- suggest_name SYNCHRONOUSLY (6-23s, up to ~60s worst case) holding a gunicorn
-- worker thread. This backs an async flow: POST creates a job + a background thread
-- runs the (slow) generation; the frontend polls GET by job_id. archie_platform
-- runs 4 gunicorn workers, so the job state MUST be shared (DB) — an in-memory dict
-- would let the POST and the poll land on different workers. Idempotent.
CREATE TABLE IF NOT EXISTS hire_name_jobs (
    job_id      UUID        PRIMARY KEY,
    hire_id     INTEGER,
    capability  TEXT,
    status      TEXT        NOT NULL DEFAULT 'generating',  -- generating | done | error
    result      JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- prune_old() sweeps by age; index the sweep + any hire-scoped lookups.
CREATE INDEX IF NOT EXISTS idx_hire_name_jobs_created ON hire_name_jobs (created_at);
