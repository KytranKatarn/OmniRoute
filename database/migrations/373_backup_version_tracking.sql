-- Migration 373: version tracking on backup_log
-- Every backup now records git context and who triggered it

ALTER TABLE backup_log
  ADD COLUMN IF NOT EXISTS git_commit      TEXT,
  ADD COLUMN IF NOT EXISTS git_branch      TEXT,
  ADD COLUMN IF NOT EXISTS platform_version TEXT,
  ADD COLUMN IF NOT EXISTS triggered_by    TEXT,
  ADD COLUMN IF NOT EXISTS proposal_id     INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS pr_number       INTEGER;

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_backup_log_git_commit   ON backup_log(git_commit);
CREATE INDEX IF NOT EXISTS idx_backup_log_triggered_by ON backup_log(triggered_by);
