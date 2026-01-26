-- Migration 012: Unify Knowledge Schema
-- Date: 2026-01-09
-- Purpose: Create unified knowledge architecture for A.R.C.H.I.E.'s Brain
--
-- This migration extends knowledge_base to support multiple knowledge types:
-- - vault_note: Curated Obsidian documentation
-- - conversation_memory: Auto-learned from conversations
-- - code_snippet: Extracted code patterns
-- - github_file: Indexed repository files
-- - improvement: Tracked code changes & fixes
-- - mistake_learned: Documented errors to prevent repetition

-- ============================================================================
-- STEP 1: Add knowledge_type column and supporting fields
-- ============================================================================

-- Add knowledge_type to differentiate between different knowledge sources
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS knowledge_type VARCHAR(50);

-- Add metadata columns for unified schema
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS memory_metadata JSONB;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS importance_score DECIMAL(3,2) DEFAULT 0.5;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS access_count INTEGER DEFAULT 0;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMP;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS source_type VARCHAR(50);
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS source_id VARCHAR(255);

-- ============================================================================
-- STEP 2: Set knowledge_type for existing data
-- ============================================================================

-- Mark existing Obsidian vault notes
UPDATE knowledge_base
SET knowledge_type = 'vault_note',
    source_type = 'obsidian',
    importance_score = 0.95  -- Vault notes are high priority
WHERE is_documentation = TRUE
  AND knowledge_type IS NULL;

-- Mark existing GitHub indexed files
UPDATE knowledge_base
SET knowledge_type = 'github_file',
    source_type = 'github',
    source_id = CONCAT(repo_type, ':', file_path),
    importance_score = 0.6  -- GitHub files medium priority
WHERE repo_type IS NOT NULL
  AND knowledge_type IS NULL;

-- Mark remaining entries as conversation_memory (fallback)
UPDATE knowledge_base
SET knowledge_type = 'conversation_memory',
    source_type = 'legacy',
    importance_score = 0.5
WHERE knowledge_type IS NULL;

-- ============================================================================
-- STEP 3: Create indexes for performance
-- ============================================================================

-- Index on knowledge_type for fast filtering
CREATE INDEX IF NOT EXISTS idx_kb_type
    ON knowledge_base(knowledge_type);

-- Composite index on importance + created_at for ranking
CREATE INDEX IF NOT EXISTS idx_kb_importance
    ON knowledge_base(importance_score DESC, created_at DESC);

-- Index on source type and ID for lookups
CREATE INDEX IF NOT EXISTS idx_kb_source
    ON knowledge_base(source_type, source_id);

-- Index on last_accessed for lifecycle management
CREATE INDEX IF NOT EXISTS idx_kb_accessed
    ON knowledge_base(last_accessed DESC NULLS LAST);

-- ============================================================================
-- STEP 4: Add constraint (only after setting types)
-- ============================================================================

-- Note: We use ON CONFLICT DO NOTHING in future inserts to handle duplicates
-- Don't add UNIQUE constraint yet as it might conflict with existing data
-- Will add after cleanup in next migration

-- ============================================================================
-- STEP 5: Create helper function to update access tracking
-- ============================================================================

CREATE OR REPLACE FUNCTION update_knowledge_access(knowledge_id INTEGER)
RETURNS void AS $$
BEGIN
    UPDATE knowledge_base
    SET access_count = COALESCE(access_count, 0) + 1,
        last_accessed = NOW()
    WHERE id = knowledge_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- STEP 6: Create helper function to calculate importance score
-- ============================================================================

CREATE OR REPLACE FUNCTION calculate_importance_score(
    p_knowledge_type VARCHAR,
    p_access_count INTEGER,
    p_created_at TIMESTAMP
)
RETURNS DECIMAL(3,2) AS $$
DECLARE
    base_score DECIMAL(3,2);
    age_days INTEGER;
    access_boost DECIMAL(3,2);
    final_score DECIMAL(3,2);
BEGIN
    -- Base scores by type
    base_score := CASE p_knowledge_type
        WHEN 'vault_note' THEN 0.95
        WHEN 'mistake_learned' THEN 0.95
        WHEN 'improvement' THEN 0.90
        WHEN 'code_snippet' THEN 0.80
        WHEN 'github_file' THEN 0.60
        WHEN 'conversation_memory' THEN 0.50
        ELSE 0.50
    END;

    -- Age factor (reduce importance for old unused memories)
    age_days := EXTRACT(DAY FROM NOW() - p_created_at);

    -- Access count boost (frequently accessed = more important)
    access_boost := LEAST(0.20, p_access_count * 0.02);

    -- Calculate final score
    final_score := base_score + access_boost;

    -- Age penalty for conversation_memory only (vault notes never age out)
    IF p_knowledge_type = 'conversation_memory' AND age_days > 180 THEN
        final_score := final_score * 0.7;  -- 30% penalty for old memories
    END IF;

    -- Clamp to 0.0-1.0 range
    final_score := GREATEST(0.0, LEAST(1.0, final_score));

    RETURN final_score;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- STEP 7: Update existing importance scores
-- ============================================================================

UPDATE knowledge_base
SET importance_score = calculate_importance_score(
    knowledge_type,
    COALESCE(access_count, 0),
    created_at
)
WHERE importance_score IS NULL OR importance_score = 0.5;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    vault_count INTEGER;
    github_count INTEGER;
    memory_count INTEGER;
    total_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO vault_count FROM knowledge_base WHERE knowledge_type = 'vault_note';
    SELECT COUNT(*) INTO github_count FROM knowledge_base WHERE knowledge_type = 'github_file';
    SELECT COUNT(*) INTO memory_count FROM knowledge_base WHERE knowledge_type = 'conversation_memory';
    SELECT COUNT(*) INTO total_count FROM knowledge_base;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Migration 012 - Unified Knowledge Schema Complete';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Total entries: %', total_count;
    RAISE NOTICE '  - Vault notes: %', vault_count;
    RAISE NOTICE '  - GitHub files: %', github_count;
    RAISE NOTICE '  - Conversation memories: %', memory_count;
    RAISE NOTICE '';
    RAISE NOTICE 'New columns added:';
    RAISE NOTICE '  - knowledge_type (categorization)';
    RAISE NOTICE '  - memory_metadata (JSONB)';
    RAISE NOTICE '  - importance_score (0.0-1.0)';
    RAISE NOTICE '  - access_count (usage tracking)';
    RAISE NOTICE '  - last_accessed (timestamp)';
    RAISE NOTICE '  - source_type, source_id (origin tracking)';
    RAISE NOTICE '';
    RAISE NOTICE 'Indexes created: 4';
    RAISE NOTICE 'Helper functions created: 2';
    RAISE NOTICE '=================================================';
END $$;

-- Show sample data from each type
SELECT
    knowledge_type,
    COUNT(*) as count,
    ROUND(AVG(importance_score)::numeric, 2) as avg_importance,
    MAX(created_at) as latest_entry
FROM knowledge_base
GROUP BY knowledge_type
ORDER BY count DESC;
