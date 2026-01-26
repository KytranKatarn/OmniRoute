-- Migration 021: Improvement Deployment Tracking Enhancement
-- Purpose: Add additional columns to improvement_deployments for Phase 23 workflow
-- Date: 2026-01-16
-- Phase: 23 - Sandbox System Completion
-- Note: The improvement_deployments table already exists from migration 005
--       This migration adds columns for enhanced tracking

-- ============================================================================
-- ADD MISSING COLUMNS TO IMPROVEMENT_DEPLOYMENTS
-- ============================================================================

-- Add module tracking
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS module_id VARCHAR(100);

-- Add post-deployment backup reference
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS backup_id_post VARCHAR(255);

-- Add auto-rollback flag
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS auto_rolled_back BOOLEAN DEFAULT FALSE;

-- Add files changed tracking
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS files_changed TEXT[];

-- Add deployment duration
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS deployment_duration_ms INTEGER;

-- Add health check details
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS health_check_details JSONB;

-- Add health check timestamp
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS health_check_at TIMESTAMP;

-- Add notes field
ALTER TABLE improvement_deployments
    ADD COLUMN IF NOT EXISTS notes TEXT;

-- Create index on module_id
CREATE INDEX IF NOT EXISTS idx_imp_deployments_module ON improvement_deployments(module_id);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View for recent improvement deployments with proposal info
CREATE OR REPLACE VIEW v_recent_improvement_deployments AS
SELECT
    d.id,
    d.proposal_id,
    ip.title as proposal_title,
    d.module_id,
    d.deployed_by,
    u.username as deployed_by_name,
    d.deployed_at,
    d.deployment_type as deployment_method,
    d.status,
    d.health_check_passed,
    d.auto_rolled_back,
    d.backup_name as backup_id_pre,
    d.files_changed,
    d.deployment_duration_ms
FROM improvement_deployments d
LEFT JOIN improvement_proposals ip ON d.proposal_id = ip.id
LEFT JOIN users u ON d.deployed_by = u.id
ORDER BY d.deployed_at DESC;

-- View for improvement deployment statistics by module
CREATE OR REPLACE VIEW v_improvement_deployment_stats AS
SELECT
    module_id,
    COUNT(*) as total_deployments,
    COUNT(CASE WHEN status = 'deployed' THEN 1 END) as successful,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
    COUNT(CASE WHEN status = 'rolled_back' THEN 1 END) as rolled_back,
    AVG(deployment_duration_ms) as avg_duration_ms,
    MAX(deployed_at) as last_deployment
FROM improvement_deployments
GROUP BY module_id;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON COLUMN improvement_deployments.module_id IS 'Module that was deployed (coderabbit, improvements, platform, etc.)';
COMMENT ON COLUMN improvement_deployments.backup_id_post IS 'Backup created after successful deployment';
COMMENT ON COLUMN improvement_deployments.auto_rolled_back IS 'TRUE if system automatically rolled back due to failed health checks';
COMMENT ON COLUMN improvement_deployments.files_changed IS 'Array of file paths that were modified';
COMMENT ON COLUMN improvement_deployments.deployment_duration_ms IS 'Total deployment time in milliseconds';
COMMENT ON COLUMN improvement_deployments.health_check_details IS 'Detailed health check results as JSON';
COMMENT ON COLUMN improvement_deployments.health_check_at IS 'When health checks were performed';
