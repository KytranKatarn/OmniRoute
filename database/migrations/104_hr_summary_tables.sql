-- Migration 104: HR Summary Tables (Project #91 — Phase 7)
-- Agent daily work summaries + alert system for IAAE/HR tracking

-- Daily summary of each agent's work (aggregated from task_execution_log)
CREATE TABLE IF NOT EXISTS agent_daily_summary (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    summary_date DATE NOT NULL DEFAULT CURRENT_DATE,
    total_tasks INTEGER DEFAULT 0,
    successful_tasks INTEGER DEFAULT 0,
    failed_tasks INTEGER DEFAULT 0,
    total_duration_ms BIGINT DEFAULT 0,
    avg_duration_ms NUMERIC(10, 1) DEFAULT 0,
    models_used TEXT[] DEFAULT '{}',
    modules_served TEXT[] DEFAULT '{}',
    capabilities_used TEXT[] DEFAULT '{}',
    utilization_pct NUMERIC(5, 2) DEFAULT 0,
    error_rate_pct NUMERIC(5, 2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (agent_id, summary_date)
);

CREATE INDEX IF NOT EXISTS idx_ads_agent_date ON agent_daily_summary(agent_id, summary_date DESC);
CREATE INDEX IF NOT EXISTS idx_ads_date ON agent_daily_summary(summary_date DESC);

-- Agent alerts for governance and HR monitoring
CREATE TABLE IF NOT EXISTS agent_alerts (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id),
    alert_type VARCHAR(50) NOT NULL,   -- overwork, high_error_rate, model_failure, idle, governance_violation
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',  -- info, warning, critical
    title VARCHAR(200) NOT NULL,
    message TEXT,
    details JSONB DEFAULT '{}',
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(100),
    notified_telegram BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aa_agent ON agent_alerts(agent_id);
CREATE INDEX IF NOT EXISTS idx_aa_unresolved ON agent_alerts(resolved, created_at DESC) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_aa_type ON agent_alerts(alert_type, created_at DESC);

-- View: active (unresolved) alerts
CREATE OR REPLACE VIEW v_active_alerts AS
SELECT aa.*, a.name as agent_name, a.model, bs.station_code
FROM agent_alerts aa
LEFT JOIN agents a ON a.id = aa.agent_id
LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
WHERE aa.resolved = FALSE
ORDER BY
    CASE aa.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
    aa.created_at DESC;

-- View: weekly agent performance summary
CREATE OR REPLACE VIEW v_agent_weekly_performance AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.model,
    bs.station_code,
    COALESCE(SUM(ads.total_tasks), 0) as week_total_tasks,
    COALESCE(SUM(ads.successful_tasks), 0) as week_successful,
    COALESCE(SUM(ads.failed_tasks), 0) as week_failed,
    COALESCE(AVG(ads.utilization_pct), 0) as avg_utilization,
    COALESCE(AVG(ads.error_rate_pct), 0) as avg_error_rate,
    COALESCE(AVG(ads.avg_duration_ms), 0) as avg_response_ms
FROM agents a
LEFT JOIN agent_daily_summary ads ON ads.agent_id = a.id
    AND ads.summary_date >= CURRENT_DATE - INTERVAL '7 days'
LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
WHERE a.status = 'active'
GROUP BY a.id, a.name, a.model, bs.station_code
ORDER BY week_total_tasks DESC;
