-- 170_creed_violations.sql
-- Enables C.R.E.E.D. to track per-dispatch ethics violations
-- Part of Capability Routing Expansion (2026-04-28)

CREATE TABLE IF NOT EXISTS creed_violations (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    agent_name VARCHAR(100),
    violation_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) DEFAULT 'low'
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT,
    dispatch_context JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'active'
        CHECK (status IN ('active', 'resolved', 'dismissed')),
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_creed_violations_agent
    ON creed_violations(agent_id);
CREATE INDEX IF NOT EXISTS idx_creed_violations_status
    ON creed_violations(status, severity);
CREATE INDEX IF NOT EXISTS idx_creed_violations_created
    ON creed_violations(created_at DESC);
