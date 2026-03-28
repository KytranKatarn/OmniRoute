-- Migration 202: Department HQ tables
-- dept_work_sessions: groups related Bridge jobs into meaningful work units
-- department_metrics: aggregated performance snapshots per department
-- 2026-03-27

BEGIN;

-- 1. Work sessions table
CREATE TABLE IF NOT EXISTS dept_work_sessions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    department VARCHAR(100) NOT NULL,
    session_type VARCHAR(50) NOT NULL,  -- audit, fix, analysis, translation, indexing, etc.
    title VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, completed, failed, partial
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    CONSTRAINT chk_dept_work_sessions_status CHECK (
        status IN ('active', 'completed', 'failed', 'partial')
    )
);

CREATE INDEX IF NOT EXISTS idx_dept_work_sessions_department ON dept_work_sessions (department);
CREATE INDEX IF NOT EXISTS idx_dept_work_sessions_status ON dept_work_sessions (status);
CREATE INDEX IF NOT EXISTS idx_dept_work_sessions_agent ON dept_work_sessions (agent_id);
CREATE INDEX IF NOT EXISTS idx_dept_work_sessions_started ON dept_work_sessions (started_at DESC);

-- 2. Department metrics table (computed daily by Job #59)
CREATE TABLE IF NOT EXISTS department_metrics (
    id SERIAL PRIMARY KEY,
    department VARCHAR(100) NOT NULL,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    jobs_completed INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    avg_response_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    sessions_completed INTEGER DEFAULT 0,
    kpis JSONB DEFAULT '{}',  -- department-specific metrics
    creed_score DECIMAL(5,2),
    computed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dept_metrics_department ON department_metrics (department);
CREATE INDEX IF NOT EXISTS idx_dept_metrics_period ON department_metrics (period_end DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dept_metrics_dept_period
    ON department_metrics (department, period_start, period_end);

COMMIT;
