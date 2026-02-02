-- Security & Network Module Database Migration
-- Version: 072
-- Created: 2026-02-02
-- Description: Creates tables for IP access control, security events, scans, vulnerabilities, SSL monitoring

-- ============================================================================
-- IP ACCESS CONTROL
-- Stores blocked/allowed IPs with expiry support
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_ip_access (
    id SERIAL PRIMARY KEY,
    ip_address INET NOT NULL,
    access_type VARCHAR(20) NOT NULL CHECK (access_type IN ('block', 'allow', 'whitelist')),
    reason TEXT,
    source VARCHAR(50) DEFAULT 'manual',  -- manual, auto_block, import
    expires_at TIMESTAMP,  -- NULL means permanent
    is_active BOOLEAN DEFAULT TRUE,
    blocked_count INTEGER DEFAULT 0,
    last_seen_at TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ip_address)
);

CREATE INDEX IF NOT EXISTS idx_security_ip_access_ip ON security_ip_access(ip_address);
CREATE INDEX IF NOT EXISTS idx_security_ip_access_type ON security_ip_access(access_type);
CREATE INDEX IF NOT EXISTS idx_security_ip_access_active ON security_ip_access(is_active);
CREATE INDEX IF NOT EXISTS idx_security_ip_access_expires ON security_ip_access(expires_at) WHERE expires_at IS NOT NULL;

-- ============================================================================
-- SECURITY EVENTS
-- Tracks security-related events for threat detection
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,  -- brute_force, port_scan, unauthorized_access, malware, ddos
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    source_ip INET,
    target_ip INET,
    target_port INTEGER,
    description TEXT,
    raw_data JSONB,
    status VARCHAR(20) DEFAULT 'new' CHECK (status IN ('new', 'investigating', 'resolved', 'false_positive')),
    resolved_by INTEGER REFERENCES users(id),
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_events_type ON security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_security_events_status ON security_events(status);
CREATE INDEX IF NOT EXISTS idx_security_events_source_ip ON security_events(source_ip);
CREATE INDEX IF NOT EXISTS idx_security_events_created ON security_events(created_at);

-- ============================================================================
-- SECURITY SCANS
-- Tracks all security scan operations (nmap, nikto, nuclei, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_scans (
    id SERIAL PRIMARY KEY,
    scan_id VARCHAR(100) UNIQUE NOT NULL,  -- nmap_20240202_120000
    scan_type VARCHAR(30) NOT NULL,  -- nmap, nikto, nuclei, zap, ssl
    target VARCHAR(500) NOT NULL,
    scan_profile VARCHAR(50),  -- quick, full, vuln, spider, active
    status VARCHAR(20) DEFAULT 'running' CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    output_file VARCHAR(500),
    findings_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    medium_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    error_message TEXT,
    started_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_scans_scan_id ON security_scans(scan_id);
CREATE INDEX IF NOT EXISTS idx_security_scans_type ON security_scans(scan_type);
CREATE INDEX IF NOT EXISTS idx_security_scans_status ON security_scans(status);
CREATE INDEX IF NOT EXISTS idx_security_scans_target ON security_scans(target);
CREATE INDEX IF NOT EXISTS idx_security_scans_created ON security_scans(created_at);

-- ============================================================================
-- SECURITY VULNERABILITIES
-- Stores findings from security scans
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_vulnerabilities (
    id SERIAL PRIMARY KEY,
    scan_id INTEGER REFERENCES security_scans(id) ON DELETE CASCADE,
    vuln_id VARCHAR(100),  -- CVE-2024-1234, WASC-01, etc.
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    cvss_score DECIMAL(3,1),
    affected_url VARCHAR(1000),
    affected_component VARCHAR(500),
    evidence TEXT,
    remediation TEXT,
    reference_urls JSONB,  -- Array of URLs
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'fixed', 'accepted_risk', 'false_positive')),
    fixed_at TIMESTAMP,
    fixed_by INTEGER REFERENCES users(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_vuln_scan ON security_vulnerabilities(scan_id);
CREATE INDEX IF NOT EXISTS idx_security_vuln_severity ON security_vulnerabilities(severity);
CREATE INDEX IF NOT EXISTS idx_security_vuln_status ON security_vulnerabilities(status);
CREATE INDEX IF NOT EXISTS idx_security_vuln_vuln_id ON security_vulnerabilities(vuln_id);

-- ============================================================================
-- SSL CERTIFICATE MONITORS
-- Tracks SSL certificates for monitored domains
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_ssl_monitors (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    port INTEGER DEFAULT 443,
    issuer VARCHAR(500),
    subject VARCHAR(500),
    serial_number VARCHAR(100),
    valid_from TIMESTAMP,
    valid_until TIMESTAMP,
    days_until_expiry INTEGER,
    fingerprint_sha256 VARCHAR(100),
    protocol_version VARCHAR(20),
    cipher_suite VARCHAR(200),
    key_type VARCHAR(20),
    key_size INTEGER,
    grade VARCHAR(5),  -- A+, A, B, C, D, F
    vulnerabilities JSONB,  -- Array of vulns like BEAST, POODLE, etc.
    last_checked_at TIMESTAMP,
    check_interval_hours INTEGER DEFAULT 24,
    alert_days_before INTEGER DEFAULT 30,
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_ssl_domain ON security_ssl_monitors(domain);
CREATE INDEX IF NOT EXISTS idx_security_ssl_expiry ON security_ssl_monitors(valid_until);
CREATE INDEX IF NOT EXISTS idx_security_ssl_active ON security_ssl_monitors(is_active);

-- ============================================================================
-- SECURITY TOOL CONFIGS
-- Stores credentials and configs for external security tools
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_tool_configs (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100),
    host VARCHAR(255),
    port INTEGER,
    username VARCHAR(100),
    password_encrypted TEXT,  -- Encrypted password
    api_key_encrypted TEXT,   -- Encrypted API key
    additional_config JSONB,
    is_enabled BOOLEAN DEFAULT TRUE,
    last_connected_at TIMESTAMP,
    connection_status VARCHAR(20) DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Insert default tool configs
INSERT INTO security_tool_configs (tool_name, display_name, host, port)
VALUES
    ('adguard', 'AdGuard Home', 'network_adguard', 80),
    ('ntopng', 'ntopng', 'network_ntopng', 3000),
    ('nagios', 'Nagios', 'monitoring_nagios', 80),
    ('zap', 'OWASP ZAP', 'security_zap', 8090)
ON CONFLICT (tool_name) DO NOTHING;

-- ============================================================================
-- AUTO-BLOCK SETTINGS
-- Configuration for automatic threat blocking
-- ============================================================================

CREATE TABLE IF NOT EXISTS security_auto_block_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(50) NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Insert default auto-block settings
INSERT INTO security_auto_block_settings (setting_key, setting_value, description)
VALUES
    ('enabled', 'true', 'Enable automatic threat blocking'),
    ('failed_login_threshold', '5', 'Number of failed logins before auto-block'),
    ('failed_login_window_minutes', '15', 'Time window for failed login counting'),
    ('block_duration_hours', '24', 'How long to block IPs'),
    ('whitelist_ips', '["127.0.0.1", "192.168.1.1"]', 'IPs that should never be blocked (JSON array)')
ON CONFLICT (setting_key) DO NOTHING;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to check if an IP should be blocked based on failed logins
CREATE OR REPLACE FUNCTION check_auto_block_threshold(check_ip INET)
RETURNS BOOLEAN AS $$
DECLARE
    threshold INTEGER;
    window_minutes INTEGER;
    failure_count INTEGER;
    is_whitelisted BOOLEAN;
    whitelist_json JSONB;
BEGIN
    -- Get settings
    SELECT setting_value::INTEGER INTO threshold
    FROM security_auto_block_settings WHERE setting_key = 'failed_login_threshold';

    SELECT setting_value::INTEGER INTO window_minutes
    FROM security_auto_block_settings WHERE setting_key = 'failed_login_window_minutes';

    SELECT setting_value::JSONB INTO whitelist_json
    FROM security_auto_block_settings WHERE setting_key = 'whitelist_ips';

    -- Check whitelist
    IF whitelist_json IS NOT NULL AND whitelist_json ? check_ip::TEXT THEN
        RETURN FALSE;
    END IF;

    -- Count failures
    SELECT COUNT(*) INTO failure_count
    FROM audit_log
    WHERE action = 'login_failed'
      AND details->>'ip' = check_ip::TEXT
      AND created_at > NOW() - (window_minutes || ' minutes')::INTERVAL;

    RETURN failure_count >= COALESCE(threshold, 5);
END;
$$ LANGUAGE plpgsql;

-- Function to clean up expired IP blocks
CREATE OR REPLACE FUNCTION cleanup_expired_ip_blocks()
RETURNS INTEGER AS $$
DECLARE
    cleaned_count INTEGER;
BEGIN
    UPDATE security_ip_access
    SET is_active = FALSE
    WHERE expires_at IS NOT NULL
      AND expires_at < NOW()
      AND is_active = TRUE;

    GET DIAGNOSTICS cleaned_count = ROW_COUNT;
    RETURN cleaned_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- MIGRATION TRACKING
-- ============================================================================

INSERT INTO knowledge_base (category, title, content, knowledge_type, tags)
VALUES (
    'database',
    'Migration 072: Security Network Tables',
    'Created tables for security module: security_ip_access, security_events, security_scans, security_vulnerabilities, security_ssl_monitors, security_tool_configs, security_auto_block_settings',
    'system_info',
    ARRAY['migration', 'security', 'database']
) ON CONFLICT DO NOTHING;
