-- Migration 068: Deployment Packages & Migration Support
-- Phase 31.1: System Migration & Distributed Backup
-- Date: 2026-01-21

-- ============================================================================
-- DEPLOYMENT PACKAGES TABLE
-- Self-contained archives for deploying ARCHIE on new machines
-- ============================================================================

CREATE TABLE IF NOT EXISTS deployment_packages (
    id SERIAL PRIMARY KEY,
    package_name VARCHAR(255) UNIQUE NOT NULL,
    version_tag VARCHAR(50),
    description TEXT,
    backup_source VARCHAR(255),  -- Source backup name if created from backup
    file_path VARCHAR(500),
    file_size BIGINT,
    checksum VARCHAR(64),  -- SHA256 checksum
    components JSONB DEFAULT '[]'::jsonb,  -- List of included components
    target_platform VARCHAR(50) DEFAULT 'linux',  -- linux, docker, all
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    download_count INTEGER DEFAULT 0,
    last_downloaded_at TIMESTAMP
);

-- ============================================================================
-- BACKUP TARGETS TABLE
-- For node backup sync (push/pull/mirror)
-- ============================================================================

CREATE TABLE IF NOT EXISTS backup_targets (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    target_type VARCHAR(20) NOT NULL,  -- push, pull, mirror
    target_path VARCHAR(500) DEFAULT '/backups',
    enabled BOOLEAN DEFAULT TRUE,
    sync_frequency VARCHAR(20) DEFAULT 'daily',  -- hourly, daily, weekly, manual
    retention_days INTEGER DEFAULT 30,
    last_sync_at TIMESTAMP,
    last_sync_status VARCHAR(20),  -- success, failed, in_progress
    last_sync_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- MIGRATION HISTORY TABLE
-- Track system migrations between machines
-- ============================================================================

CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    source_host VARCHAR(255),
    target_host VARCHAR(255),
    target_node_id INTEGER REFERENCES remote_nodes(id),
    backup_name VARCHAR(255),
    package_name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'pending',  -- pending, transferring, deploying, verifying, completed, failed
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    transfer_duration_ms INTEGER,
    deploy_duration_ms INTEGER,
    error_message TEXT,
    verification_result JSONB,
    created_by INTEGER REFERENCES users(id)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_deployment_packages_version ON deployment_packages(version_tag);
CREATE INDEX IF NOT EXISTS idx_deployment_packages_created ON deployment_packages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_targets_node ON backup_targets(node_id);
CREATE INDEX IF NOT EXISTS idx_backup_targets_enabled ON backup_targets(enabled) WHERE enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_migration_history_status ON migration_history(status);
CREATE INDEX IF NOT EXISTS idx_migration_history_target ON migration_history(target_host);

-- ============================================================================
-- HELPFUL VIEWS
-- ============================================================================

-- Active backup targets with node info
CREATE OR REPLACE VIEW v_active_backup_targets AS
SELECT
    bt.id,
    bt.target_type,
    bt.target_path,
    bt.sync_frequency,
    bt.retention_days,
    bt.last_sync_at,
    bt.last_sync_status,
    rn.node_id,
    rn.node_name,
    rn.vpn_ip,
    rn.status as node_status
FROM backup_targets bt
JOIN remote_nodes rn ON bt.node_id = rn.id
WHERE bt.enabled = TRUE
  AND rn.approval_status = 'approved';

-- Recent migrations summary
CREATE OR REPLACE VIEW v_migration_summary AS
SELECT
    mh.id,
    mh.source_host,
    mh.target_host,
    mh.status,
    mh.started_at,
    mh.completed_at,
    mh.transfer_duration_ms,
    mh.deploy_duration_ms,
    CASE
        WHEN mh.completed_at IS NOT NULL
        THEN EXTRACT(EPOCH FROM (mh.completed_at - mh.started_at))::INTEGER
        ELSE NULL
    END as total_duration_seconds,
    rn.node_name as target_node_name,
    u.username as initiated_by
FROM migration_history mh
LEFT JOIN remote_nodes rn ON mh.target_node_id = rn.id
LEFT JOIN users u ON mh.created_by = u.id
ORDER BY mh.started_at DESC;

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Get latest deployment package
CREATE OR REPLACE FUNCTION get_latest_deployment_package()
RETURNS TABLE(
    package_name VARCHAR,
    version_tag VARCHAR,
    file_size BIGINT,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT dp.package_name, dp.version_tag, dp.file_size, dp.created_at
    FROM deployment_packages dp
    ORDER BY dp.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Increment download count
CREATE OR REPLACE FUNCTION increment_package_downloads(p_package_name VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE deployment_packages
    SET download_count = download_count + 1,
        last_downloaded_at = NOW()
    WHERE package_name = p_package_name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SAMPLE DATA / DEFAULTS
-- ============================================================================

-- None needed - tables are ready for use

COMMENT ON TABLE deployment_packages IS 'Self-contained ARCHIE deployment archives for system migration';
COMMENT ON TABLE backup_targets IS 'Node backup sync configuration (push/pull/mirror)';
COMMENT ON TABLE migration_history IS 'History of system migrations between machines';
