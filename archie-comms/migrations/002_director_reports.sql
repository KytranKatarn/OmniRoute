-- Director Reports — directors report UP through hierarchy
-- A.R.C.H.I.E. triages and synthesizes for Kytran
CREATE TABLE IF NOT EXISTS director_reports (
    id SERIAL PRIMARY KEY,
    department VARCHAR(100) NOT NULL,
    director_agent VARCHAR(100),
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',  -- critical, high, medium, low
    category VARCHAR(50) NOT NULL,                    -- security, operations, engineering, etc.
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    escalated BOOLEAN DEFAULT FALSE,
    escalation_channel VARCHAR(20),  -- telegram, platform_chat, null if not escalated
    escalated_at TIMESTAMP,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_director_reports_severity ON director_reports(severity);
CREATE INDEX IF NOT EXISTS idx_director_reports_escalated ON director_reports(escalated) WHERE escalated = FALSE;
CREATE INDEX IF NOT EXISTS idx_director_reports_created ON director_reports(created_at);
CREATE INDEX IF NOT EXISTS idx_director_reports_dept ON director_reports(department);
