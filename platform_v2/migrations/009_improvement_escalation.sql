-- ============================================================================
-- Migration 009: Improvement Escalation & Retry Tracking
-- Date: 2026-01-02
-- Purpose: Add retry tracking and contractor escalation support for improvements
-- ============================================================================

-- Add retry and escalation tracking columns
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS assigned_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS escalated_to_contractor BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMP;

-- Create index for finding proposals by agent
CREATE INDEX IF NOT EXISTS idx_proposals_assigned_agent ON improvement_proposals(assigned_agent_id);

-- Create index for finding escalated proposals
CREATE INDEX IF NOT EXISTS idx_proposals_escalated ON improvement_proposals(escalated_to_contractor, escalated_at DESC);

-- Comments for documentation
COMMENT ON COLUMN improvement_proposals.retry_count IS 'Number of retry attempts (escalates to contractor at 3)';
COMMENT ON COLUMN improvement_proposals.assigned_agent_id IS 'Agent currently assigned to this proposal';
COMMENT ON COLUMN improvement_proposals.escalated_to_contractor IS 'Whether this has been escalated to paid contractor';
COMMENT ON COLUMN improvement_proposals.escalated_at IS 'When this was escalated to contractor';
COMMENT ON COLUMN improvement_proposals.last_retry_at IS 'Last retry attempt timestamp';
