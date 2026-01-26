-- Migration 013: Add proposal_id column to code_issues table
-- This enables bidirectional tracking between CodeRabbit issues and Improvements Lab proposals
-- Date: 2026-01-15

-- Add proposal_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'code_issues' AND column_name = 'proposal_id'
    ) THEN
        ALTER TABLE code_issues
        ADD COLUMN proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL;

        RAISE NOTICE 'Added proposal_id column to code_issues table';
    ELSE
        RAISE NOTICE 'proposal_id column already exists';
    END IF;
END $$;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_code_issues_proposal_id ON code_issues(proposal_id);

-- Add index on status for filtering
CREATE INDEX IF NOT EXISTS idx_code_issues_status ON code_issues(status);

-- Verify the column was added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'code_issues' AND column_name = 'proposal_id';
