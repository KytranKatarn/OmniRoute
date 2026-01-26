-- Migration 071: System Operations Module
-- Tables for metrics history and operation auditing
-- Date: 2026-01-22

-- ============================================================================
-- 1. System Metrics History (for real-time graphs)
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_metrics_history (
    id SERIAL PRIMARY KEY,
    metric_type VARCHAR(50) NOT NULL,  -- 'cpu', 'memory', 'disk', 'network', 'gpu'
    value DECIMAL(10, 2) NOT NULL,
    details JSONB,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient time-range queries
CREATE INDEX IF NOT EXISTS idx_metrics_history_type_time
    ON system_metrics_history(metric_type, recorded_at DESC);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_metrics_history_recorded
    ON system_metrics_history(recorded_at);

COMMENT ON TABLE system_metrics_history IS 'Historical system metrics for real-time graphing';

-- ============================================================================
-- 2. System Operations Audit Log
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_operations_audit (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR(100) NOT NULL,  -- 'process_kill', 'service_restart', 'docker_action', 'disk_mount'
    target VARCHAR(255) NOT NULL,        -- PID, service name, container ID, device path
    details JSONB,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    ip_address VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sysops_audit_user ON system_operations_audit(user_id);
CREATE INDEX IF NOT EXISTS idx_sysops_audit_type ON system_operations_audit(action_type);
CREATE INDEX IF NOT EXISTS idx_sysops_audit_created ON system_operations_audit(created_at DESC);

COMMENT ON TABLE system_operations_audit IS 'Audit log for all system operations actions';

-- ============================================================================
-- 3. System Alert Thresholds Configuration
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_alerts_config (
    id SERIAL PRIMARY KEY,
    metric_type VARCHAR(50) NOT NULL UNIQUE,
    threshold_warning DECIMAL(10,2),
    threshold_critical DECIMAL(10,2),
    enabled BOOLEAN DEFAULT TRUE,
    notify_email BOOLEAN DEFAULT FALSE,
    notify_webhook BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE system_alerts_config IS 'Alert threshold configuration for system metrics';

-- Insert default alert thresholds
INSERT INTO system_alerts_config (metric_type, threshold_warning, threshold_critical)
VALUES
    ('cpu', 75.0, 90.0),
    ('memory', 80.0, 95.0),
    ('disk', 80.0, 90.0),
    ('gpu', 85.0, 95.0)
ON CONFLICT (metric_type) DO NOTHING;

-- ============================================================================
-- 4. Cleanup Function (run daily via cron or scheduler)
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_old_system_metrics()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Delete metrics older than 7 days
    DELETE FROM system_metrics_history
    WHERE recorded_at < NOW() - INTERVAL '7 days';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_system_metrics IS 'Cleanup metrics older than 7 days';

-- ============================================================================
-- 5. View for Recent Audit Activity
-- ============================================================================

CREATE OR REPLACE VIEW v_recent_system_operations AS
SELECT
    soa.id,
    soa.action_type,
    soa.target,
    soa.success,
    soa.error_message,
    soa.ip_address,
    soa.created_at,
    u.username,
    soa.details
FROM system_operations_audit soa
LEFT JOIN users u ON soa.user_id = u.id
WHERE soa.created_at > NOW() - INTERVAL '24 hours'
ORDER BY soa.created_at DESC;

COMMENT ON VIEW v_recent_system_operations IS 'Recent system operations from the last 24 hours';

-- ============================================================================
-- 6. Grant Permissions
-- ============================================================================

GRANT SELECT, INSERT ON system_metrics_history TO archie;
GRANT SELECT, INSERT ON system_operations_audit TO archie;
GRANT SELECT, INSERT, UPDATE ON system_alerts_config TO archie;
GRANT USAGE, SELECT ON SEQUENCE system_metrics_history_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE system_operations_audit_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE system_alerts_config_id_seq TO archie;
GRANT SELECT ON v_recent_system_operations TO archie;

-- ============================================================================
-- Done
-- ============================================================================

SELECT 'Migration 071: System Operations complete' as status;
