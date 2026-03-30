-- 060_monitoring_tables.sql
-- Monitoring integration: Nagios check state + alert history

CREATE TABLE IF NOT EXISTS monitoring_checks (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    check_type VARCHAR(16) NOT NULL DEFAULT 'service',
    status VARCHAR(16) NOT NULL DEFAULT 'unknown',
    output TEXT,
    last_check TIMESTAMP WITH TIME ZONE,
    next_check TIMESTAMP WITH TIME ZONE,
    attempts INTEGER DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(node_id, check_name)
);
CREATE INDEX IF NOT EXISTS idx_monitoring_checks_status ON monitoring_checks(status);
CREATE INDEX IF NOT EXISTS idx_monitoring_checks_node ON monitoring_checks(node_id);

CREATE TABLE IF NOT EXISTS monitoring_alerts (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    check_name VARCHAR(128) NOT NULL,
    old_status VARCHAR(16),
    new_status VARCHAR(16) NOT NULL,
    alerted_via VARCHAR(16) NOT NULL,
    message TEXT,
    alerted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    cooldown_until TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_node ON monitoring_alerts(node_id, check_name);
CREATE INDEX IF NOT EXISTS idx_monitoring_alerts_time ON monitoring_alerts(alerted_at DESC);
