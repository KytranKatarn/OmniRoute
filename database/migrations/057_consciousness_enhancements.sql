-- Migration 057: Consciousness Module Enhancements
-- Date: 2026-01-21
-- Purpose: Support Save to Consciousness, GitHub Learning Integration

-- Add embedding tracking columns to knowledge_base
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS has_embedding BOOLEAN DEFAULT FALSE;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP;

-- Add file_path column if not exists (for GitHub files)
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS file_path TEXT;

-- Add is_code and is_documentation flags
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS is_code BOOLEAN DEFAULT FALSE;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS is_documentation BOOLEAN DEFAULT FALSE;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS file_extension VARCHAR(20);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_kb_has_embedding ON knowledge_base(has_embedding) WHERE has_embedding = TRUE;
CREATE INDEX IF NOT EXISTS idx_kb_source_type ON knowledge_base(source_type);
CREATE INDEX IF NOT EXISTS idx_kb_github_selective ON knowledge_base(importance_score DESC)
    WHERE source_type = 'github_selective';
CREATE INDEX IF NOT EXISTS idx_kb_file_path ON knowledge_base(file_path) WHERE file_path IS NOT NULL;

-- Create unique partial index for github_selective file paths (for upsert)
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_github_selective_path
    ON knowledge_base(file_path) WHERE source_type = 'github_selective';

-- Update existing github_file entries to have proper type weighting info
UPDATE knowledge_base
SET is_code = TRUE
WHERE knowledge_type = 'github_file'
  AND file_extension IN ('.py', '.js', '.ts', '.go', '.rs', '.java', '.c', '.cpp', '.h');

UPDATE knowledge_base
SET is_documentation = TRUE
WHERE knowledge_type = 'github_file'
  AND file_extension IN ('.md', '.txt', '.rst', '.adoc');

-- Add comment for documentation
COMMENT ON COLUMN knowledge_base.has_embedding IS 'Whether this entry has a semantic embedding for vector search';
COMMENT ON COLUMN knowledge_base.embedding_generated_at IS 'When the embedding was generated';
COMMENT ON COLUMN knowledge_base.file_path IS 'Full path for GitHub files (owner/repo/path)';
COMMENT ON COLUMN knowledge_base.is_code IS 'Whether this is a code file';
COMMENT ON COLUMN knowledge_base.is_documentation IS 'Whether this is documentation';
