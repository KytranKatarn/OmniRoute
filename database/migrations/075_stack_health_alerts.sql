-- ============================================================================
-- Migration 075: Stack Health Alerts
-- ============================================================================
-- Adds tables for container health monitoring, alerting, and webhooks
-- ============================================================================

-- Health alerts table
CREATE TABLE IF NOT EXISTS stack_health_alerts (
    id SERIAL PRIMARY KEY,
    stack_name VARCHAR(50) NOT NULL,
    container_name VARCHAR(100),
    alert_type VARCHAR(50) NOT NULL,  -- 'crash', 'restart_loop', 'unhealthy', 'resource_threshold'
    severity VARCHAR(20) DEFAULT 'warning',  -- 'info', 'warning', 'critical'
    message TEXT NOT NULL,
    details JSONB,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by INTEGER REFERENCES users(id),
    acknowledged_at TIMESTAMP,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Alert thresholds configuration
CREATE TABLE IF NOT EXISTS stack_health_config (
    id SERIAL PRIMARY KEY,
    stack_name VARCHAR(50),  -- NULL for global defaults
    metric_type VARCHAR(50) NOT NULL,  -- 'cpu', 'memory', 'restart_count'
    threshold_warning DECIMAL(10,2),
    threshold_critical DECIMAL(10,2),
    enabled BOOLEAN DEFAULT TRUE,
    cooldown_minutes INTEGER DEFAULT 15,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stack_name, metric_type)
);

-- Health alert webhooks (similar to backup_webhooks pattern)
CREATE TABLE IF NOT EXISTS health_alert_webhooks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    event_types TEXT[] DEFAULT ARRAY['container_crash', 'health_warning', 'health_critical'],
    stack_filter TEXT[],  -- NULL for all stacks
    active BOOLEAN DEFAULT TRUE,
    secret_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_triggered TIMESTAMP,
    last_status INTEGER,
    last_error TEXT
);

-- Container metrics history (for trend analysis, 7-day retention handled by cleanup job)
CREATE TABLE IF NOT EXISTS container_metrics_history (
    id SERIAL PRIMARY KEY,
    container_name VARCHAR(100) NOT NULL,
    stack_name VARCHAR(50),
    cpu_percent DECIMAL(5,2),
    mem_percent DECIMAL(5,2),
    mem_usage_mb INTEGER,
    restart_count INTEGER DEFAULT 0,
    health_status VARCHAR(20),  -- 'healthy', 'unhealthy', 'starting', 'none'
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_health_alerts_stack ON stack_health_alerts(stack_name);
CREATE INDEX IF NOT EXISTS idx_health_alerts_created ON stack_health_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_alerts_active ON stack_health_alerts(resolved, acknowledged) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS idx_metrics_container ON container_metrics_history(container_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_recorded ON container_metrics_history(recorded_at DESC);

-- Insert default global thresholds
INSERT INTO stack_health_config (stack_name, metric_type, threshold_warning, threshold_critical, cooldown_minutes)
VALUES
    (NULL, 'cpu', 80.0, 95.0, 15),
    (NULL, 'memory', 85.0, 95.0, 15),
    (NULL, 'restart_count', 3, 5, 30)
ON CONFLICT (stack_name, metric_type) DO NOTHING;

-- Add trigger to update updated_at on config changes
CREATE OR REPLACE FUNCTION update_health_config_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_health_config_updated ON stack_health_config;
CREATE TRIGGER trigger_health_config_updated
    BEFORE UPDATE ON stack_health_config
    FOR EACH ROW
    EXECUTE FUNCTION update_health_config_timestamp();

-- Comment on tables
COMMENT ON TABLE stack_health_alerts IS 'Health alerts for Docker stack containers';
COMMENT ON TABLE stack_health_config IS 'Configurable thresholds for health monitoring';
COMMENT ON TABLE health_alert_webhooks IS 'Webhook endpoints for health alert notifications';
COMMENT ON TABLE container_metrics_history IS 'Historical container metrics for trend analysis';
