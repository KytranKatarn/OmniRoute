-- AI-generated compliance remediation plans
-- Each plan is an F.O.R.G.E.-generated runbook for a specific rule,
-- customized to the current deployment state.

CREATE TABLE IF NOT EXISTS compliance_remediation_plans (
    id SERIAL PRIMARY KEY,
    rule_id VARCHAR(100) NOT NULL,
    scan_id UUID,
    pack_id VARCHAR(100),

    -- AI analysis
    generated_by VARCHAR(100) DEFAULT 'F.O.R.G.E.',
    model_used VARCHAR(100),
    generated_at TIMESTAMP DEFAULT NOW(),

    -- Plan content (all JSONB so we can add fields without migration)
    affected_containers JSONB,     -- array of container names
    impact_analysis TEXT,          -- markdown explanation
    prerequisites JSONB,           -- array of strings
    steps JSONB NOT NULL,          -- array of {action, why, safe_auto, completed, completed_at, notes}
    rollback_plan TEXT,
    estimated_downtime VARCHAR(100),
    best_window VARCHAR(200),
    exemption_candidate BOOLEAN DEFAULT FALSE,
    exemption_reason TEXT,

    -- Execution tracking
    status VARCHAR(50) DEFAULT 'generated',  -- generated|in_progress|complete|exempted|cancelled
    started_at TIMESTAMP,
    started_by INTEGER REFERENCES users(id),
    completed_at TIMESTAMP,
    completed_by INTEGER REFERENCES users(id),
    completion_notes TEXT,

    -- For STIG audit export
    audit_hash VARCHAR(64),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comp_plans_rule ON compliance_remediation_plans(rule_id);
CREATE INDEX IF NOT EXISTS idx_comp_plans_status ON compliance_remediation_plans(status);
CREATE INDEX IF NOT EXISTS idx_comp_plans_scan ON compliance_remediation_plans(scan_id);
