-- Migration 115: Bridge Jobs — Workload tracking for multi-step bridge operations
-- Project #91: Bridge Dispatcher Enhancement

CREATE TABLE IF NOT EXISTS bridge_jobs (
    id SERIAL PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,           -- 'batch_translate', 'reindex', etc.
    module_source VARCHAR(100),              -- e.g. 'consciousness_linguistics'
    description TEXT,                        -- "Translate 191 keys to French"
    total_steps INTEGER NOT NULL DEFAULT 1,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    failed_steps INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/running/completed/failed/cancelled
    agent_name VARCHAR(100),                 -- primary agent working on it
    metadata JSONB DEFAULT '{}'::jsonb,      -- {language, batch_size, strings_ok, strings_failed, ...}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Index for active job lookups (UI polling)
CREATE INDEX IF NOT EXISTS idx_bridge_jobs_status ON bridge_jobs(status);
CREATE INDEX IF NOT EXISTS idx_bridge_jobs_created ON bridge_jobs(created_at DESC);

-- Link task_execution_log entries to their parent job
ALTER TABLE task_execution_log
    ADD COLUMN IF NOT EXISTS job_id INTEGER REFERENCES bridge_jobs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_tel_job_id ON task_execution_log(job_id) WHERE job_id IS NOT NULL;
