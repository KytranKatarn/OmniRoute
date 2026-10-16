-- Migration 023: Approvals Queue for GitHub Skills
-- Date: 2026-10-14
-- Purpose: Enable Department HQ APPROVALS tab sync for GitHub skill reviews

-- Create approvals_queue table
CREATE TABLE IF NOT EXISTS approvals_queue (
    id VARCHAR(50) PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id INTEGER NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('approve', 'reject')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    reason TEXT,
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL
);

-- Index for looking up pending approvals by source/resource
CREATE INDEX IF NOT EXISTS idx_approvals_queue_source_res ON approvals_queue(source, resource_type, resource_id) WHERE status = 'pending';

-- Index for reviewing by status
CREATE INDEX IF NOT EXISTS idx_approvals_queue_status ON approvals_queue(status) WHERE status IN ('pending', 'approved', 'rejected');

-- Add comment
COMMENT ON TABLE approvals_queue IS 'Queue of pending approvals from across the platform (GitHub skills, code health, etc.). Syncable between GitHub tab and Department HQ APPROVALS tab.';

-- Insert initial pending approvals for existing skills that need human review
-- (skills with status "analyzed" but not yet "registered" or "approved")
INSERT INTO approvals_queue (id, source, resource_type, resource_id, action, status, created_by)
SELECT
    'gh_skill_' || gs.id::text,
    'github_skills',
    'skill',
    gs.id,
    'approve',
    'pending',
    'system_initialization'
FROM github_skills gs
WHERE gs.status = 'analyzed'
ON CONFLICT (id) DO NOTHING;

COMMENT ON COLUMN approvals_queue.id IS 'Unique approval ID: gh_skill_<skill_id>';
COMMENT ON COLUMN approvals_queue.source IS 'Source module: github_skills, code_health, etc.';
COMMENT ON COLUMN approvals_queue.resource_type IS 'Type of resource being approved: skill, code_snippet, etc.';
COMMENT ON COLUMN approvals_queue.action IS 'Requested action: approve or reject';
COMMENT ON COLUMN approvals_queue.status IS 'Current status: pending, approved, or rejected';
COMMENT ON COLUMN approvals_queue.reason IS 'Human-readable reason for the approval/rejection';
COMMENT ON COLUMN approvals_queue.reviewed_by IS 'User or API key that performed the review';
COMMENT ON COLUMN approvals_queue.reviewed_at IS 'Timestamp when the review was performed';
