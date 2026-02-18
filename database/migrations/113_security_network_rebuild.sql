-- Migration 113: Security & Network Module Rebuild
-- 6 new tables for agent actions, recon scans, scan results,
-- camera events, DNS changes, and security reports.

BEGIN;

-- 1. Agent automation suggestions/actions
CREATE TABLE IF NOT EXISTS security_agent_actions (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(50) NOT NULL,       -- suggest, auto_execute
    category VARCHAR(50) NOT NULL,          -- dns, camera, scan, access, filters
    title VARCHAR(200) NOT NULL,
    description TEXT,
    reasoning TEXT,
    status VARCHAR(20) DEFAULT 'pending',   -- pending, approved, dismissed, executed, failed
    data JSONB,
    executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Argus scan history
CREATE TABLE IF NOT EXISTS security_recon_scans (
    id SERIAL PRIMARY KEY,
    module_name VARCHAR(100) NOT NULL,
    target VARCHAR(500) NOT NULL,
    options JSONB,
    status VARCHAR(20) DEFAULT 'running',   -- running, completed, failed
    results JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    triggered_by VARCHAR(50) DEFAULT 'user' -- user, agent, schedule
);

-- 3. Vulnerability scan results
CREATE TABLE IF NOT EXISTS security_scan_results (
    id SERIAL PRIMARY KEY,
    scanner VARCHAR(50) NOT NULL,           -- nmap, nikto, nuclei, zap, testssl
    target VARCHAR(500) NOT NULL,
    severity VARCHAR(20),                   -- critical, high, medium, low, info
    finding VARCHAR(500),
    details JSONB,
    scan_id INTEGER REFERENCES security_recon_scans(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. Camera motion events from HA
CREATE TABLE IF NOT EXISTS security_camera_events (
    id SERIAL PRIMARY KEY,
    camera_entity VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,        -- motion, doorbell, arm, disarm
    location VARCHAR(100),
    thumbnail_url TEXT,
    data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 5. DNS management audit trail
CREATE TABLE IF NOT EXISTS security_dns_changes (
    id SERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL,            -- adguard, hostinger
    action VARCHAR(50) NOT NULL,
    domain VARCHAR(500),
    details JSONB,
    changed_by VARCHAR(50) DEFAULT 'user',  -- user, agent
    created_at TIMESTAMP DEFAULT NOW()
);

-- 6. Generated security reports
CREATE TABLE IF NOT EXISTS security_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    date_range_start TIMESTAMP,
    date_range_end TIMESTAMP,
    content JSONB,
    format VARCHAR(10) DEFAULT 'json',      -- json, pdf, csv
    file_path TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_agent_actions_status ON security_agent_actions(status);
CREATE INDEX IF NOT EXISTS idx_agent_actions_category ON security_agent_actions(category);
CREATE INDEX IF NOT EXISTS idx_agent_actions_created ON security_agent_actions(created_at);
CREATE INDEX IF NOT EXISTS idx_recon_scans_status ON security_recon_scans(status);
CREATE INDEX IF NOT EXISTS idx_scan_results_severity ON security_scan_results(severity);
CREATE INDEX IF NOT EXISTS idx_camera_events_camera ON security_camera_events(camera_entity);
CREATE INDEX IF NOT EXISTS idx_camera_events_type ON security_camera_events(event_type);
CREATE INDEX IF NOT EXISTS idx_camera_events_created ON security_camera_events(created_at);
CREATE INDEX IF NOT EXISTS idx_dns_changes_source ON security_dns_changes(source);
CREATE INDEX IF NOT EXISTS idx_dns_changes_created ON security_dns_changes(created_at);

COMMIT;
