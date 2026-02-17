-- ============================================================================
-- Migration 093: Autonomy Agent Loop
-- Purpose: Tables for the proactive agent loop — approval queue, loop logging,
--          and autonomy configuration
-- Created: 2026-02-17
-- ============================================================================

-- Autonomy approval queue — tier-2 actions await human approval here
CREATE TABLE IF NOT EXISTS autonomy_approval_queue (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(100) NOT NULL,       -- 'send_email', 'external_webhook', 'browser_task', 'data_deletion'
    action_data JSONB NOT NULL DEFAULT '{}', -- serialized action payload
    tier INTEGER NOT NULL DEFAULT 2,         -- 1=auto-approve, 2=require human
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'expired', 'executed', 'failed'
    priority INTEGER DEFAULT 5,              -- 1-10, lower = higher
    requested_by VARCHAR(100),               -- system component that requested
    reason TEXT,                             -- human-readable explanation
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP,
    rejected_reason TEXT,
    executed_at TIMESTAMP,
    execution_result JSONB,
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '24 hours'),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Autonomy loop execution log — tracks every cycle of the agent loop
CREATE TABLE IF NOT EXISTS autonomy_loop_log (
    id SERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,          -- 'email_queue', 'scheduled_tasks', 'reminders', 'approvals'
    status VARCHAR(50) NOT NULL DEFAULT 'success', -- 'success', 'partial', 'error', 'skipped'
    items_processed INTEGER DEFAULT 0,
    items_failed INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    details JSONB DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Autonomy configuration — per-feature toggles and settings
CREATE TABLE IF NOT EXISTS autonomy_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(100) NOT NULL UNIQUE,
    config_value JSONB NOT NULL DEFAULT '{}',
    description TEXT,
    updated_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON autonomy_approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_approval_queue_tier ON autonomy_approval_queue(tier, status);
CREATE INDEX IF NOT EXISTS idx_approval_queue_expires ON autonomy_approval_queue(expires_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_approval_queue_created ON autonomy_approval_queue(created_at);
CREATE INDEX IF NOT EXISTS idx_loop_log_job ON autonomy_loop_log(job_name, created_at);
CREATE INDEX IF NOT EXISTS idx_loop_log_status ON autonomy_loop_log(status);
CREATE INDEX IF NOT EXISTS idx_loop_log_created ON autonomy_loop_log(created_at);
CREATE INDEX IF NOT EXISTS idx_autonomy_config_key ON autonomy_config(config_key);

-- Default configuration
INSERT INTO autonomy_config (config_key, config_value, description) VALUES
    ('agent_loop_enabled', '{"enabled": true}', 'Master switch for the agent loop'),
    ('email_queue_enabled', '{"enabled": true, "interval_seconds": 60, "batch_size": 10}', 'Email queue processing'),
    ('scheduled_tasks_enabled', '{"enabled": true, "interval_seconds": 30}', 'Scheduled task execution'),
    ('reminders_enabled', '{"enabled": true, "interval_seconds": 30}', 'Reminder notification processing'),
    ('approval_queue_enabled', '{"enabled": true, "interval_seconds": 60, "auto_expire_hours": 24}', 'Approval queue processing'),
    ('tier1_auto_approve', '{"types": ["notification", "reminder", "kb_update", "briefing", "internal_log"]}', 'Action types that auto-approve (tier 1)'),
    ('tier2_require_approval', '{"types": ["send_email", "external_webhook", "browser_new_domain", "data_deletion"]}', 'Action types requiring human approval (tier 2)')
ON CONFLICT (config_key) DO NOTHING;

-- Grant permissions
GRANT ALL ON autonomy_approval_queue TO archie;
GRANT ALL ON autonomy_loop_log TO archie;
GRANT ALL ON autonomy_config TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE autonomy_approval_queue IS 'Queue for actions requiring human approval before execution';
COMMENT ON TABLE autonomy_loop_log IS 'Execution log for the proactive agent loop jobs';
COMMENT ON TABLE autonomy_config IS 'Configuration for autonomy features and agent loop settings';
