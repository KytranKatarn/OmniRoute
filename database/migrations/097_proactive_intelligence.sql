-- ============================================================================
-- Migration 097: Proactive Intelligence
-- Purpose: Daily briefings, anomaly detection, scheduled report generation
-- Created: 2026-02-17
-- ============================================================================

-- Briefing configuration and history
CREATE TABLE IF NOT EXISTS briefings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    briefing_type VARCHAR(50) NOT NULL DEFAULT 'daily', -- 'morning', 'evening', 'weekly', 'custom'
    schedule_cron VARCHAR(100) NOT NULL,     -- e.g. '0 7 * * *' for 7 AM daily
    user_id INTEGER REFERENCES users(id),
    sections JSONB DEFAULT '["notifications", "emails", "tasks", "anomalies", "calendar"]',
    delivery_channels JSONB DEFAULT '["notification", "telegram"]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Briefing history (generated briefings)
CREATE TABLE IF NOT EXISTS briefing_history (
    id SERIAL PRIMARY KEY,
    briefing_id INTEGER REFERENCES briefings(id),
    content TEXT NOT NULL,
    summary TEXT,                            -- short version for Telegram
    sections_data JSONB DEFAULT '{}',       -- raw data per section
    delivery_status JSONB DEFAULT '{}',     -- which channels delivered successfully
    generated_at TIMESTAMP DEFAULT NOW()
);

-- Anomaly detection rules
CREATE TABLE IF NOT EXISTS anomaly_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    rule_type VARCHAR(50) NOT NULL,          -- 'sql_threshold', 'rate_spike', 'absence'
    rule_config JSONB NOT NULL,              -- SQL query, threshold, time window, etc.
    severity VARCHAR(20) DEFAULT 'warning',  -- 'info', 'warning', 'critical'
    check_interval_minutes INTEGER DEFAULT 15,
    is_active BOOLEAN DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    last_triggered_at TIMESTAMP,
    consecutive_triggers INTEGER DEFAULT 0,
    cooldown_minutes INTEGER DEFAULT 60,     -- don't re-trigger within this window
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Anomaly detection results
CREATE TABLE IF NOT EXISTS anomaly_detections (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER REFERENCES anomaly_rules(id),
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    current_value NUMERIC,
    threshold_value NUMERIC,
    detection_data JSONB DEFAULT '{}',
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by INTEGER REFERENCES users(id),
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Scheduled reports
CREATE TABLE IF NOT EXISTS scheduled_reports (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    report_type VARCHAR(50) NOT NULL,        -- 'email_summary', 'crm_activity', 'system_health', 'custom'
    schedule_cron VARCHAR(100) NOT NULL,
    user_id INTEGER REFERENCES users(id),
    report_config JSONB DEFAULT '{}',       -- custom parameters, date range, filters
    output_format VARCHAR(20) DEFAULT 'text', -- 'text', 'html', 'json'
    delivery_channels JSONB DEFAULT '["notification"]',
    is_active BOOLEAN DEFAULT TRUE,
    last_generated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_briefings_active ON briefings(is_active);
CREATE INDEX IF NOT EXISTS idx_briefings_user ON briefings(user_id);
CREATE INDEX IF NOT EXISTS idx_briefing_history_briefing ON briefing_history(briefing_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_anomaly_rules_active ON anomaly_rules(is_active);
CREATE INDEX IF NOT EXISTS idx_anomaly_rules_check ON anomaly_rules(last_checked_at) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_anomaly_detections_rule ON anomaly_detections(rule_id, created_at);
CREATE INDEX IF NOT EXISTS idx_anomaly_detections_sev ON anomaly_detections(severity, acknowledged);
CREATE INDEX IF NOT EXISTS idx_scheduled_reports_active ON scheduled_reports(is_active);

-- Default briefings for Kytran (user_id = 2)
INSERT INTO briefings (name, briefing_type, schedule_cron, user_id, sections, delivery_channels) VALUES
    ('Morning Briefing', 'morning', '0 7 * * *', 2,
     '["notifications", "emails", "tasks", "anomalies", "calendar"]',
     '["notification", "telegram"]'),
    ('Evening Summary', 'evening', '0 20 * * *', 2,
     '["notifications", "emails", "tasks", "anomalies"]',
     '["notification", "telegram"]')
ON CONFLICT DO NOTHING;

-- Default anomaly rules
INSERT INTO anomaly_rules (name, description, rule_type, rule_config, severity, check_interval_minutes) VALUES
    ('Email Volume Spike',
     'Alert when incoming email count in the last hour is 3x the daily average',
     'sql_threshold',
     '{"query": "SELECT COUNT(*) as val FROM email_inbox WHERE created_at > NOW() - INTERVAL ''1 hour''", "threshold_query": "SELECT (COUNT(*)::float / GREATEST(EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at))) / 3600, 1)) * 3 as val FROM email_inbox WHERE created_at > NOW() - INTERVAL ''7 days''", "comparison": ">"}',
     'warning', 15),

    ('Failed Login Attempts',
     'Alert on more than 5 failed logins in 15 minutes',
     'sql_threshold',
     '{"query": "SELECT COUNT(*) as val FROM audit_log WHERE action = ''LOGIN_FAILED'' AND created_at > NOW() - INTERVAL ''15 minutes''", "threshold": 5, "comparison": ">"}',
     'critical', 5),

    ('Agent Loop Failures',
     'Alert when agent loop has more than 3 failures in the last hour',
     'sql_threshold',
     '{"query": "SELECT COUNT(*) as val FROM autonomy_loop_log WHERE status = ''error'' AND created_at > NOW() - INTERVAL ''1 hour''", "threshold": 3, "comparison": ">"}',
     'warning', 15),

    ('Pending Approvals Backlog',
     'Alert when more than 10 approvals are pending for over 12 hours',
     'sql_threshold',
     '{"query": "SELECT COUNT(*) as val FROM autonomy_approval_queue WHERE status = ''pending'' AND created_at < NOW() - INTERVAL ''12 hours''", "threshold": 10, "comparison": ">"}',
     'info', 60)
ON CONFLICT DO NOTHING;

-- Grant permissions
GRANT ALL ON briefings TO archie;
GRANT ALL ON briefing_history TO archie;
GRANT ALL ON anomaly_rules TO archie;
GRANT ALL ON anomaly_detections TO archie;
GRANT ALL ON scheduled_reports TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE briefings IS 'Scheduled briefing configurations (morning, evening, weekly)';
COMMENT ON TABLE briefing_history IS 'Generated briefing content and delivery status';
COMMENT ON TABLE anomaly_rules IS 'SQL-based anomaly detection rules with thresholds';
COMMENT ON TABLE anomaly_detections IS 'Triggered anomaly alerts with values and acknowledgement';
COMMENT ON TABLE scheduled_reports IS 'Scheduled report generation configurations';
