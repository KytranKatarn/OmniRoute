-- Migration 006: Add Backup Tracking Columns to Improvement Proposals
-- Date: 2026-01-02
-- Purpose: Track automatic backups created before deploying improvements

-- Add backup tracking columns to improvement_proposals
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS backup_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS backup_created_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS deployment_started_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS health_check_passed BOOLEAN DEFAULT NULL,
ADD COLUMN IF NOT EXISTS health_check_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS rollback_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS rollback_reason TEXT,
ADD COLUMN IF NOT EXISTS executed_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS executed_by INTEGER REFERENCES users(id);

-- Add index for backup tracking
CREATE INDEX IF NOT EXISTS idx_proposals_backup ON improvement_proposals(backup_name) WHERE backup_name IS NOT NULL;

-- Add index for deployment tracking
CREATE INDEX IF NOT EXISTS idx_proposals_deployed ON improvement_proposals(deployed_at DESC) WHERE deployed_at IS NOT NULL;

-- Add comment
COMMENT ON COLUMN improvement_proposals.backup_name IS 'Name of the pre-deployment backup created automatically';
COMMENT ON COLUMN improvement_proposals.backup_created_at IS 'Timestamp when pre-deployment backup was created';
COMMENT ON COLUMN improvement_proposals.deployment_started_at IS 'Timestamp when deployment was initiated';
COMMENT ON COLUMN improvement_proposals.health_check_passed IS 'Result of post-deployment health checks';
COMMENT ON COLUMN improvement_proposals.health_check_at IS 'Timestamp when health checks were run';
COMMENT ON COLUMN improvement_proposals.rollback_at IS 'Timestamp when deployment was rolled back';
COMMENT ON COLUMN improvement_proposals.rollback_reason IS 'Reason for rollback';
COMMENT ON COLUMN improvement_proposals.executed_at IS 'Timestamp when improvement was executed';
COMMENT ON COLUMN improvement_proposals.executed_by IS 'User ID who executed the improvement';
