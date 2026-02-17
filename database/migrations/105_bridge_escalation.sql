-- Migration 105: Bridge Escalation Support
-- Platform settings + dispatch escalation logging for smart router escalation paths

-- Global platform settings (key-value with typed values)
CREATE TABLE IF NOT EXISTS platform_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    value_type VARCHAR(20) DEFAULT 'string',  -- string, int, bool, json
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default settings for bridge escalation
INSERT INTO platform_settings (key, value, value_type, description) VALUES
    ('routing_mode', 'full', 'string', 'Smart router mode: full (all tiers), local (local models only), cloud (cloud models only)'),
    ('escalation_threshold', '3', 'int', 'Number of failures before escalating to next model tier'),
    ('escalation_auto_deny_minutes', '15', 'int', 'Minutes before unapproved escalation requests are auto-denied')
ON CONFLICT DO NOTHING;

-- Log of model escalation events (when a task is re-routed to a higher-tier model)
CREATE TABLE IF NOT EXISTS dispatch_escalation_log (
    id SERIAL PRIMARY KEY,
    original_agent_id INTEGER REFERENCES agents(id),
    original_model VARCHAR(100),
    escalated_model VARCHAR(100),
    escalated_provider VARCHAR(50),
    capability VARCHAR(50),
    module_id VARCHAR(100),
    reason TEXT,
    failure_count INTEGER,
    cost_usd NUMERIC(10,6) DEFAULT 0,
    approved_by VARCHAR(100),
    approval_method VARCHAR(20) DEFAULT 'auto',  -- auto, telegram, timeout
    success BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_del_created ON dispatch_escalation_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_del_agent ON dispatch_escalation_log(original_agent_id);
