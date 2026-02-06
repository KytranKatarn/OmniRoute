-- Phase 82: ARCHIE Consciousness Intelligence Upgrade Schema Migration
-- Run: docker exec -i archie_database psql -U archie -d archie < scripts/phase82_schema_migration.sql
--
-- This migration adds:
-- 1. Vector embedding column for semantic search (pgvector)
-- 2. AI analysis JSONB storage
-- 3. Full-text search vector with auto-update trigger
-- 4. Knowledge relationships table
-- 5. Processing log table
-- 6. API usage tracking table

-- Ensure pgvector is installed
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. Modify knowledge_base table for embeddings and AI analysis
-- ============================================================================

-- Add embedding column (768 dimensions for nomic-embed-text)
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP;

-- Add AI analysis storage
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS ai_analysis JSONB;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS analysis_version INTEGER DEFAULT 0;

-- Add full-text search vector
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Create vector similarity index (ivfflat for faster approximate search)
-- Note: lists=100 is good for ~10K+ entries, adjust as collection grows
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_kb_embedding') THEN
        -- First check if there are enough entries with embeddings
        -- ivfflat requires some training data, but we can create it empty and it'll work
        CREATE INDEX idx_kb_embedding ON knowledge_base
            USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    END IF;
END $$;

-- Create GIN index for full-text search
CREATE INDEX IF NOT EXISTS idx_kb_search ON knowledge_base USING gin(search_vector);

-- Create index for analysis version tracking
CREATE INDEX IF NOT EXISTS idx_kb_analysis_version ON knowledge_base(analysis_version);

-- Create index for embedding timestamp
CREATE INDEX IF NOT EXISTS idx_kb_embedding_generated ON knowledge_base(embedding_generated_at);

-- ============================================================================
-- 2. Create trigger for automatic search_vector updates
-- ============================================================================

-- Function to update search_vector on insert/update
CREATE OR REPLACE FUNCTION update_knowledge_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS trig_kb_search_vector ON knowledge_base;

-- Create trigger
CREATE TRIGGER trig_kb_search_vector
    BEFORE INSERT OR UPDATE OF title, content, tags
    ON knowledge_base
    FOR EACH ROW
    EXECUTE FUNCTION update_knowledge_search_vector();

-- Backfill search_vector for existing entries (run once)
UPDATE knowledge_base SET search_vector =
    setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(content, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(array_to_string(tags, ' '), '')), 'C')
WHERE search_vector IS NULL;

-- ============================================================================
-- 3. Create knowledge_relationships table
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_relationships (
    id SERIAL PRIMARY KEY,
    from_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    to_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,
    strength FLOAT DEFAULT 0.5 CHECK (strength >= 0 AND strength <= 1),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system',
    UNIQUE(from_id, to_id, relationship_type)
);

-- Add comment documenting relationship types
COMMENT ON TABLE knowledge_relationships IS 'Knowledge graph relationships with 15 types:
- related_to: General conceptual relation
- part_of: Component/parent relationship
- uses: Depends on or utilizes
- extends: Builds upon or enhances
- implements: Realizes a concept/pattern
- solves: Addresses a problem
- causes: Leads to or triggers
- contradicts: Conflicts with
- supersedes: Replaces older knowledge
- prerequisite_of: Must understand first
- alternative_to: Different approach to same goal
- learned_from: Source attribution
- similar_to: Semantically close
- example_of: Concrete instance
- applies_to: Relevant context/domain';

-- Indexes for efficient graph traversal
CREATE INDEX IF NOT EXISTS idx_kr_from ON knowledge_relationships(from_id);
CREATE INDEX IF NOT EXISTS idx_kr_to ON knowledge_relationships(to_id);
CREATE INDEX IF NOT EXISTS idx_kr_type ON knowledge_relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_kr_strength ON knowledge_relationships(strength) WHERE strength > 0.5;

-- ============================================================================
-- 4. Create knowledge_processing_log table
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_processing_log (
    id SERIAL PRIMARY KEY,
    batch_id UUID NOT NULL,
    source_type VARCHAR(50),           -- 'conversation', 'github', 'claude_hook'
    source_id VARCHAR(255),            -- File path or ID
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed', 'skipped'
    knowledge_ids INTEGER[],           -- IDs of created knowledge entries
    relationships_created INTEGER DEFAULT 0,
    cards_created INTEGER DEFAULT 0,
    tokens_used INTEGER,
    embedding_tokens INTEGER,
    processing_time_ms INTEGER,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Indexes for processing log queries
CREATE INDEX IF NOT EXISTS idx_kpl_batch ON knowledge_processing_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_kpl_status ON knowledge_processing_log(status);
CREATE INDEX IF NOT EXISTS idx_kpl_source ON knowledge_processing_log(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_kpl_created ON knowledge_processing_log(created_at);

-- ============================================================================
-- 5. Create api_usage_daily table for cost tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS api_usage_daily (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE DEFAULT CURRENT_DATE,
    claude_input_tokens INTEGER DEFAULT 0,
    claude_output_tokens INTEGER DEFAULT 0,
    claude_requests INTEGER DEFAULT 0,
    ollama_embedding_tokens INTEGER DEFAULT 0,
    ollama_embedding_requests INTEGER DEFAULT 0,
    estimated_cost_usd DECIMAL(10, 4) DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for date lookups
CREATE INDEX IF NOT EXISTS idx_aud_date ON api_usage_daily(date);

-- ============================================================================
-- 6. Verify migration
-- ============================================================================

-- Show new columns in knowledge_base
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'knowledge_base'
AND column_name IN ('embedding', 'embedding_generated_at', 'ai_analysis', 'analysis_version', 'search_vector')
ORDER BY column_name;

-- Show new tables
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('knowledge_relationships', 'knowledge_processing_log', 'api_usage_daily')
ORDER BY table_name;

-- Show index counts
SELECT
    (SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'knowledge_base' AND indexname LIKE 'idx_kb_%') as kb_indexes,
    (SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'knowledge_relationships') as kr_indexes,
    (SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'knowledge_processing_log') as kpl_indexes;
