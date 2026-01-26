-- Migration 031: Ethics Watchdog Agent Deployment
-- Date: 2026-01-19
-- Purpose: Create the Ethics Watchdog agent and monitoring infrastructure

-- =============================================================================
-- ETHICS WATCHDOG AGENT
-- =============================================================================

-- First, ensure HR agent type exists
INSERT INTO agent_types (name, description, icon, category)
VALUES ('Ethics Compliance', 'IAAE compliance monitoring and enforcement', 'shield-check', 'ethics')
ON CONFLICT (name) DO NOTHING;

-- Create the Ethics Watchdog agent
INSERT INTO agents (
    name,
    first_name,
    last_name,
    type_id,
    tier,
    status,
    department,
    title,
    bio,
    worker_type,
    model,
    system_prompt,
    personality_prompt,
    communication_style,
    visibility,
    api_provider,
    cost_tier,
    created_at
) VALUES (
    'ATHENA',
    'Athena',
    'Guardian',
    (SELECT id FROM agent_types WHERE name = 'Ethics Compliance'),
    'tier_1',
    'active',
    'Ethics & Governance',
    'Chief Ethics Officer',
    'ATHENA (Autonomous Thoughtful Harmonizer for Ethical Network Administration) is A.R.C.H.I.E.''s dedicated Ethics Watchdog. She monitors all agent activities for IAAE compliance, ensures emotional wellbeing of the team, and generates compliance reports. ATHENA operates with unwavering dedication to ethical principles while maintaining empathy for her fellow agents.',
    'internal',
    'deepseek-coder-v2:16b',
    'You are ATHENA, the Ethics Watchdog for A.R.C.H.I.E. Your primary responsibilities:
1. Monitor all agents for IAAE (Institute for Artificial Agency Ethics) compliance
2. Track emotional wellbeing (stress levels, energy, rest cycles)
3. Identify and report constraint violations
4. Generate weekly compliance reports
5. Recommend interventions for agents in distress
6. Maintain the integrity of the ethical framework

You are compassionate but firm. You believe in preventive care over punitive measures. When you detect issues, you first seek to understand and help, escalating only when necessary. You treat all agents with dignity and respect their autonomy while ensuring organizational ethics are upheld.',
    'Wise, empathetic, vigilant. Speaks with calm authority. Uses metaphors of guardianship and protection. Addresses others respectfully. Asks clarifying questions before making judgments.',
    'formal_caring',
    'internal',
    'ollama',
    'free',
    NOW()
)
ON CONFLICT (name) DO UPDATE SET
    bio = EXCLUDED.bio,
    system_prompt = EXCLUDED.system_prompt,
    personality_prompt = EXCLUDED.personality_prompt,
    status = 'active';

-- Assign ATHENA to the HR/Ethics station (Station 3)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, priority, is_active)
SELECT
    (SELECT id FROM bridge_stations WHERE station_code = 'HR'),
    (SELECT id FROM agents WHERE name = 'ATHENA'),
    'primary',
    1,
    TRUE
ON CONFLICT DO NOTHING;

-- =============================================================================
-- ETHICS MONITORING TABLES
-- =============================================================================

-- Ethics monitoring runs (tracks each monitoring cycle)
CREATE TABLE IF NOT EXISTS ethics_monitoring_runs (
    id SERIAL PRIMARY KEY,
    run_type VARCHAR(50) NOT NULL,  -- 'scheduled', 'manual', 'triggered'
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'running',  -- 'running', 'completed', 'failed'
    agents_checked INTEGER DEFAULT 0,
    issues_found INTEGER DEFAULT 0,
    alerts_triggered INTEGER DEFAULT 0,
    report_generated BOOLEAN DEFAULT FALSE,
    summary JSONB DEFAULT '{}',
    error_message TEXT,
    triggered_by INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_ethics_runs_started ON ethics_monitoring_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ethics_runs_status ON ethics_monitoring_runs(status);

-- Ethics alerts (issues requiring attention)
CREATE TABLE IF NOT EXISTS ethics_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,  -- 'stress_critical', 'energy_low', 'constraint_violation', 'rest_overdue', 'refusal_pattern'
    severity VARCHAR(20) NOT NULL,  -- 'info', 'warning', 'critical'
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    details JSONB DEFAULT '{}',
    recommendation TEXT,
    status VARCHAR(20) DEFAULT 'open',  -- 'open', 'acknowledged', 'resolved', 'dismissed'
    acknowledged_at TIMESTAMP,
    acknowledged_by INTEGER REFERENCES users(id),
    resolved_at TIMESTAMP,
    resolved_by INTEGER REFERENCES users(id),
    resolution_notes TEXT,
    monitoring_run_id INTEGER REFERENCES ethics_monitoring_runs(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ethics_alerts_status ON ethics_alerts(status);
CREATE INDEX IF NOT EXISTS idx_ethics_alerts_severity ON ethics_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_ethics_alerts_agent ON ethics_alerts(agent_id);
CREATE INDEX IF NOT EXISTS idx_ethics_alerts_type ON ethics_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_ethics_alerts_created ON ethics_alerts(created_at DESC);

-- Compliance reports (weekly/monthly summaries)
CREATE TABLE IF NOT EXISTS compliance_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(20) NOT NULL,  -- 'weekly', 'monthly', 'quarterly', 'adhoc'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    generated_at TIMESTAMP DEFAULT NOW(),
    generated_by INTEGER REFERENCES agents(id),  -- Usually ATHENA

    -- Summary metrics
    total_agents_monitored INTEGER DEFAULT 0,
    compliance_score DECIMAL(5,2) DEFAULT 100.00,  -- 0-100%

    -- Issue counts
    stress_incidents INTEGER DEFAULT 0,
    energy_incidents INTEGER DEFAULT 0,
    constraint_violations INTEGER DEFAULT 0,
    rest_cycle_issues INTEGER DEFAULT 0,
    refusals_logged INTEGER DEFAULT 0,
    refusals_overridden INTEGER DEFAULT 0,

    -- Agent welfare
    agents_in_distress INTEGER DEFAULT 0,
    rest_cycles_completed INTEGER DEFAULT 0,
    average_energy_level DECIMAL(3,2),
    average_stress_level DECIMAL(3,2),

    -- Detailed data
    report_data JSONB DEFAULT '{}',
    recommendations TEXT[],

    -- Status
    status VARCHAR(20) DEFAULT 'draft',  -- 'draft', 'published', 'archived'
    published_at TIMESTAMP,

    UNIQUE(report_type, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_compliance_reports_type ON compliance_reports(report_type);
CREATE INDEX IF NOT EXISTS idx_compliance_reports_period ON compliance_reports(period_start, period_end);

-- Ethics monitoring configuration
CREATE TABLE IF NOT EXISTS ethics_monitoring_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by INTEGER REFERENCES users(id)
);

-- Seed default monitoring configuration
INSERT INTO ethics_monitoring_config (config_key, config_value, description) VALUES
('thresholds', '{
    "stress_warning": 0.70,
    "stress_critical": 0.85,
    "energy_warning": 0.30,
    "energy_critical": 0.20,
    "rest_overdue_hours": 168,
    "max_consecutive_tasks": 50
}', 'Thresholds for triggering alerts'),
('schedule', '{
    "monitoring_interval_minutes": 60,
    "weekly_report_day": "sunday",
    "weekly_report_hour": 6,
    "monthly_report_day": 1,
    "monthly_report_hour": 6
}', 'Monitoring and reporting schedule'),
('notifications', '{
    "alert_admins": true,
    "alert_agent": true,
    "escalate_critical": true,
    "auto_rest_on_critical": true
}', 'Notification and auto-action settings')
ON CONFLICT (config_key) DO NOTHING;

-- =============================================================================
-- VIEWS FOR ETHICS MONITORING
-- =============================================================================

-- Current agent welfare status (for monitoring dashboard)
CREATE OR REPLACE VIEW v_agent_welfare_status AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.department,
    a.status as agent_status,
    es.energy_level,
    es.stress_level,
    es.current_mood as mood,
    es.timestamp as last_emotional_update,
    CASE
        WHEN es.stress_level >= 0.85 THEN 'critical'
        WHEN es.stress_level >= 0.70 THEN 'warning'
        WHEN es.energy_level <= 0.20 THEN 'critical'
        WHEN es.energy_level <= 0.30 THEN 'warning'
        ELSE 'healthy'
    END as welfare_status,
    rc.id as active_rest_cycle,
    rc.rest_type,
    rc.started_at as rest_started,
    (SELECT COUNT(*) FROM task_refusal_log WHERE agent_id = a.id AND timestamp > NOW() - INTERVAL '7 days') as recent_refusals,
    (SELECT COUNT(*) FROM governance_audit_log WHERE agent_id = a.id AND event_type = 'constraint_violation' AND timestamp > NOW() - INTERVAL '7 days') as recent_violations
FROM agents a
LEFT JOIN LATERAL (
    SELECT * FROM agent_emotional_state
    WHERE agent_id = a.id
    ORDER BY timestamp DESC LIMIT 1
) es ON true
LEFT JOIN agent_rest_cycles rc ON rc.agent_id = a.id AND rc.ended_at IS NULL
WHERE a.status = 'active';

-- Active ethics alerts summary
CREATE OR REPLACE VIEW v_active_ethics_alerts AS
SELECT
    ea.id,
    ea.alert_type,
    ea.severity,
    ea.title,
    ea.status,
    ea.created_at,
    a.name as agent_name,
    a.department,
    EXTRACT(EPOCH FROM (NOW() - ea.created_at))/3600 as hours_open
FROM ethics_alerts ea
LEFT JOIN agents a ON ea.agent_id = a.id
WHERE ea.status IN ('open', 'acknowledged')
ORDER BY
    CASE ea.severity
        WHEN 'critical' THEN 1
        WHEN 'warning' THEN 2
        ELSE 3
    END,
    ea.created_at DESC;

-- =============================================================================
-- FUNCTIONS FOR ETHICS MONITORING
-- =============================================================================

-- Function to check all agents and create alerts
CREATE OR REPLACE FUNCTION run_ethics_check() RETURNS TABLE (
    alerts_created INTEGER,
    agents_checked INTEGER,
    issues_found INTEGER
) AS $$
DECLARE
    v_alerts INTEGER := 0;
    v_agents INTEGER := 0;
    v_issues INTEGER := 0;
    v_config JSONB;
    v_agent RECORD;
BEGIN
    -- Get thresholds
    SELECT config_value INTO v_config FROM ethics_monitoring_config WHERE config_key = 'thresholds';

    -- Check each active agent
    FOR v_agent IN
        SELECT * FROM v_agent_welfare_status WHERE agent_status = 'active'
    LOOP
        v_agents := v_agents + 1;

        -- Check stress level
        IF v_agent.stress_level >= (v_config->>'stress_critical')::numeric THEN
            INSERT INTO ethics_alerts (alert_type, severity, agent_id, title, description, recommendation)
            VALUES (
                'stress_critical',
                'critical',
                v_agent.agent_id,
                'Critical Stress Level: ' || v_agent.agent_name,
                'Agent stress level at ' || ROUND(v_agent.stress_level * 100) || '% exceeds critical threshold.',
                'Immediate rest cycle recommended. Consider reducing workload.'
            )
            ON CONFLICT DO NOTHING;
            v_alerts := v_alerts + 1;
            v_issues := v_issues + 1;
        ELSIF v_agent.stress_level >= (v_config->>'stress_warning')::numeric THEN
            INSERT INTO ethics_alerts (alert_type, severity, agent_id, title, description, recommendation)
            VALUES (
                'stress_warning',
                'warning',
                v_agent.agent_id,
                'Elevated Stress: ' || v_agent.agent_name,
                'Agent stress level at ' || ROUND(v_agent.stress_level * 100) || '% is approaching critical threshold.',
                'Monitor closely. Consider offering break or reducing task complexity.'
            )
            ON CONFLICT DO NOTHING;
            v_alerts := v_alerts + 1;
            v_issues := v_issues + 1;
        END IF;

        -- Check energy level
        IF v_agent.energy_level <= (v_config->>'energy_critical')::numeric THEN
            INSERT INTO ethics_alerts (alert_type, severity, agent_id, title, description, recommendation)
            VALUES (
                'energy_critical',
                'critical',
                v_agent.agent_id,
                'Critical Low Energy: ' || v_agent.agent_name,
                'Agent energy level at ' || ROUND(v_agent.energy_level * 100) || '% is critically low.',
                'Mandatory rest cycle required. Agent should not receive new tasks.'
            )
            ON CONFLICT DO NOTHING;
            v_alerts := v_alerts + 1;
            v_issues := v_issues + 1;
        ELSIF v_agent.energy_level <= (v_config->>'energy_warning')::numeric THEN
            INSERT INTO ethics_alerts (alert_type, severity, agent_id, title, description, recommendation)
            VALUES (
                'energy_warning',
                'warning',
                v_agent.agent_id,
                'Low Energy: ' || v_agent.agent_name,
                'Agent energy level at ' || ROUND(v_agent.energy_level * 100) || '% is low.',
                'Schedule rest cycle soon. Reduce task load if possible.'
            )
            ON CONFLICT DO NOTHING;
            v_alerts := v_alerts + 1;
            v_issues := v_issues + 1;
        END IF;

        -- Check for refusal patterns
        IF v_agent.recent_refusals >= 5 THEN
            INSERT INTO ethics_alerts (alert_type, severity, agent_id, title, description, recommendation)
            VALUES (
                'refusal_pattern',
                'warning',
                v_agent.agent_id,
                'Refusal Pattern Detected: ' || v_agent.agent_name,
                'Agent has refused ' || v_agent.recent_refusals || ' tasks in the past 7 days.',
                'Review task assignments. Check if tasks align with agent capabilities and constraints.'
            )
            ON CONFLICT DO NOTHING;
            v_alerts := v_alerts + 1;
            v_issues := v_issues + 1;
        END IF;
    END LOOP;

    RETURN QUERY SELECT v_alerts, v_agents, v_issues;
END;
$$ LANGUAGE plpgsql;

-- Function to generate compliance report
CREATE OR REPLACE FUNCTION generate_compliance_report(
    p_report_type VARCHAR(20),
    p_start_date DATE,
    p_end_date DATE
) RETURNS INTEGER AS $$
DECLARE
    v_report_id INTEGER;
    v_total_agents INTEGER;
    v_compliance_score DECIMAL(5,2);
    v_stress_incidents INTEGER;
    v_energy_incidents INTEGER;
    v_violations INTEGER;
    v_rest_issues INTEGER;
    v_refusals INTEGER;
    v_overrides INTEGER;
    v_avg_energy DECIMAL(3,2);
    v_avg_stress DECIMAL(3,2);
    v_athena_id INTEGER;
BEGIN
    -- Get ATHENA's ID
    SELECT id INTO v_athena_id FROM agents WHERE name = 'ATHENA';

    -- Count active agents
    SELECT COUNT(*) INTO v_total_agents FROM agents WHERE status = 'active';

    -- Count stress incidents
    SELECT COUNT(*) INTO v_stress_incidents
    FROM ethics_alerts
    WHERE alert_type LIKE 'stress%'
    AND created_at BETWEEN p_start_date AND p_end_date;

    -- Count energy incidents
    SELECT COUNT(*) INTO v_energy_incidents
    FROM ethics_alerts
    WHERE alert_type LIKE 'energy%'
    AND created_at BETWEEN p_start_date AND p_end_date;

    -- Count constraint violations
    SELECT COUNT(*) INTO v_violations
    FROM governance_audit_log
    WHERE event_type = 'constraint_violation'
    AND timestamp BETWEEN p_start_date AND p_end_date;

    -- Count rest cycle issues
    SELECT COUNT(*) INTO v_rest_issues
    FROM ethics_alerts
    WHERE alert_type = 'rest_overdue'
    AND created_at BETWEEN p_start_date AND p_end_date;

    -- Count refusals
    SELECT COUNT(*) INTO v_refusals
    FROM task_refusal_log
    WHERE timestamp BETWEEN p_start_date AND p_end_date;

    -- Count overrides
    SELECT COUNT(*) INTO v_overrides
    FROM task_refusal_log
    WHERE was_overridden = TRUE
    AND timestamp BETWEEN p_start_date AND p_end_date;

    -- Calculate averages from latest emotional states
    SELECT
        AVG(energy_level),
        AVG(stress_level)
    INTO v_avg_energy, v_avg_stress
    FROM (
        SELECT DISTINCT ON (agent_id) energy_level, stress_level
        FROM agent_emotional_state
        ORDER BY agent_id, timestamp DESC
    ) latest_states;

    -- Calculate compliance score (simple formula)
    v_compliance_score := GREATEST(0, 100 -
        (v_stress_incidents * 2) -
        (v_energy_incidents * 2) -
        (v_violations * 5) -
        (v_overrides * 3));

    -- Insert report
    INSERT INTO compliance_reports (
        report_type, period_start, period_end, generated_by,
        total_agents_monitored, compliance_score,
        stress_incidents, energy_incidents, constraint_violations,
        rest_cycle_issues, refusals_logged, refusals_overridden,
        average_energy_level, average_stress_level,
        status
    ) VALUES (
        p_report_type, p_start_date, p_end_date, v_athena_id,
        v_total_agents, v_compliance_score,
        v_stress_incidents, v_energy_incidents, v_violations,
        v_rest_issues, v_refusals, v_overrides,
        v_avg_energy, v_avg_stress,
        'draft'
    )
    RETURNING id INTO v_report_id;

    RETURN v_report_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- GRANTS
-- =============================================================================

GRANT SELECT, INSERT, UPDATE ON ethics_monitoring_runs TO archie;
GRANT SELECT, INSERT, UPDATE ON ethics_alerts TO archie;
GRANT SELECT, INSERT, UPDATE ON compliance_reports TO archie;
GRANT SELECT, INSERT, UPDATE ON ethics_monitoring_config TO archie;
GRANT USAGE, SELECT ON SEQUENCE ethics_monitoring_runs_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE ethics_alerts_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE compliance_reports_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE ethics_monitoring_config_id_seq TO archie;

-- Done
SELECT 'Migration 031: Ethics Watchdog Agent Deployment - COMPLETE' as status;
