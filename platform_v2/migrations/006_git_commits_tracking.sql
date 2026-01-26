-- Migration 006: Git Commits Tracking
-- Purpose: Track Git commits from Cursor IDE for automatic workflow triggering
-- Author: A.R.C.H.I.E. Platform
-- Date: 2026-01-06

-- Create git_commits table
CREATE TABLE IF NOT EXISTS git_commits (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    commit_hash VARCHAR(40) UNIQUE NOT NULL,
    commit_message TEXT,
    author_name VARCHAR(255),
    author_email VARCHAR(255),
    branch_name VARCHAR(255) NOT NULL,
    committed_at TIMESTAMP NOT NULL,
    detected_at TIMESTAMP DEFAULT NOW(),
    workflow_triggered BOOLEAN DEFAULT FALSE,
    workflow_id VARCHAR(100),
    workflow_status VARCHAR(50), -- 'pending', 'running', 'completed', 'failed'
    workflow_completed_at TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_git_commits_proposal ON git_commits(proposal_id);
CREATE INDEX IF NOT EXISTS idx_git_commits_branch ON git_commits(branch_name);
CREATE INDEX IF NOT EXISTS idx_git_commits_hash ON git_commits(commit_hash);
CREATE INDEX IF NOT EXISTS idx_git_commits_workflow ON git_commits(workflow_triggered, workflow_status);
CREATE INDEX IF NOT EXISTS idx_git_commits_detected ON git_commits(detected_at DESC);

-- Add trigger to update improvement_proposals.last_commit_at
CREATE OR REPLACE FUNCTION update_proposal_last_commit()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE improvement_proposals
    SET last_commit_at = NEW.committed_at,
        updated_at = NOW()
    WHERE id = NEW.proposal_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_proposal_last_commit
    AFTER INSERT ON git_commits
    FOR EACH ROW
    EXECUTE FUNCTION update_proposal_last_commit();

-- Add last_commit_at column to improvement_proposals if not exists
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS last_commit_at TIMESTAMP;

-- Add index for last_commit_at
CREATE INDEX IF NOT EXISTS idx_proposals_last_commit ON improvement_proposals(last_commit_at DESC);

-- Comments for documentation
COMMENT ON TABLE git_commits IS 'Tracks Git commits from Cursor IDE sandbox branches';
COMMENT ON COLUMN git_commits.commit_hash IS 'Full Git commit SHA hash (40 chars)';
COMMENT ON COLUMN git_commits.workflow_triggered IS 'Whether automatic workflow was triggered for this commit';
COMMENT ON COLUMN git_commits.metadata IS 'Additional commit metadata (files changed, diff stats, etc.)';
