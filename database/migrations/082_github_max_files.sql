-- Migration 082: Add per-repo configurable file cap
-- Allows overriding the global MAX_FILES_PER_REPO default on a per-repository basis

ALTER TABLE github_repositories ADD COLUMN IF NOT EXISTS max_files INTEGER DEFAULT NULL;
COMMENT ON COLUMN github_repositories.max_files IS 'Per-repo file cap. NULL = global default (2000).';
