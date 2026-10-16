-- Migration 022: Add Review Tracking Columns to GitHub Skills
-- Date: 2026-10-14
-- Purpose: Enable skill review/approval workflow in Consciousness GitHub tab

-- Add review tracking columns to github_skills
ALTER TABLE github_skills
ADD COLUMN IF NOT EXISTS review_reason TEXT,
ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(100);

-- Add index for reviewing by status
CREATE INDEX IF NOT EXISTS idx_github_skills_review_status ON github_skills(status) WHERE status IN ('approved', 'rejected');

-- Add comments
COMMENT ON COLUMN github_skills.review_reason IS 'Reason for skill approval or rejection';
COMMENT ON COLUMN github_skills.reviewed_at IS 'Timestamp when skill was approved/rejected';
COMMENT ON COLUMN github_skills.reviewed_by IS 'User or API key that performed the review';
