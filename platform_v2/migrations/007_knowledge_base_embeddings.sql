-- Migration 007: Knowledge Base Semantic Search
-- Purpose: Add embedding support for semantic search in codebase knowledge
-- Author: A.R.C.H.I.E. Platform
-- Date: 2026-01-06

-- Add embedding column to archie_codebase_knowledge table
ALTER TABLE archie_codebase_knowledge
ADD COLUMN IF NOT EXISTS embedding JSONB;

-- Add index for faster embedding queries
CREATE INDEX IF NOT EXISTS idx_codebase_knowledge_embedding
ON archie_codebase_knowledge USING GIN (embedding);

-- last_updated column already exists, so we don't need updated_at

-- Comments for documentation
COMMENT ON COLUMN archie_codebase_knowledge.embedding IS 'JSONB array of embedding vectors for semantic search (768-dim from nomic-embed-text)';
