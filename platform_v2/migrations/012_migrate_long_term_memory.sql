-- Migration 012b: Migrate long_term_memory to knowledge_base
-- Date: 2026-01-09
-- Purpose: Consolidate conversation memories into unified knowledge architecture
--
-- This migration copies all entries from long_term_memory table into knowledge_base
-- with knowledge_type='conversation_memory', preserving all metadata, importance
-- scores, and access patterns.

-- ============================================================================
-- STEP 1: Verify long_term_memory table exists
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = 'long_term_memory'
    ) THEN
        RAISE NOTICE 'long_term_memory table does not exist - skipping migration';
        RETURN;
    END IF;

    RAISE NOTICE 'Found long_term_memory table - proceeding with migration...';
END $$;

-- ============================================================================
-- STEP 2: Copy long_term_memory entries to knowledge_base
-- ============================================================================

INSERT INTO knowledge_base (
    knowledge_type,
    title,
    content,
    category,
    tags,
    memory_metadata,
    importance_score,
    access_count,
    last_accessed,
    source_type,
    source_id,
    created_at,
    updated_at,
    indexed_at
)
SELECT
    'conversation_memory'::VARCHAR(50),
    COALESCE(memory_type, 'Memory')::TEXT,  -- Use memory_type as title
    content::TEXT,
    category::VARCHAR(100),
    tags::TEXT[],
    metadata::JSONB,  -- Store original LTM metadata
    COALESCE(importance_score, 0.5)::DECIMAL(3,2),
    COALESCE(access_count, 0)::INTEGER,
    last_accessed::TIMESTAMP,
    'consciousness'::VARCHAR(50),
    'ltm_' || id::text,  -- Prefix with 'ltm_' to identify source
    COALESCE(created_at, NOW())::TIMESTAMP,
    COALESCE(created_at, NOW())::TIMESTAMP,
    NOW()::TIMESTAMP
FROM long_term_memory
WHERE NOT EXISTS (
    -- Avoid duplicates if migration already run
    SELECT 1 FROM knowledge_base kb
    WHERE kb.source_type = 'consciousness'
      AND kb.source_id = 'ltm_' || long_term_memory.id::text
)
ORDER BY created_at DESC;  -- Newest first

-- ============================================================================
-- STEP 3: Update importance scores for migrated memories
-- ============================================================================

-- Recalculate importance based on age and access patterns
UPDATE knowledge_base
SET importance_score = calculate_importance_score(
    knowledge_type,
    access_count,
    created_at
)
WHERE source_type = 'consciousness'
  AND source_id LIKE 'ltm_%';

-- ============================================================================
-- STEP 4: Create mapping table for backward compatibility (optional)
-- ============================================================================

-- This allows old code referencing long_term_memory IDs to still work
CREATE TABLE IF NOT EXISTS ltm_kb_mapping (
    ltm_id INTEGER PRIMARY KEY,
    kb_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    migrated_at TIMESTAMP DEFAULT NOW()
);

-- Populate mapping
INSERT INTO ltm_kb_mapping (ltm_id, kb_id)
SELECT
    CAST(REPLACE(source_id, 'ltm_', '') AS INTEGER),
    id
FROM knowledge_base
WHERE source_type = 'consciousness'
  AND source_id LIKE 'ltm_%'
ON CONFLICT (ltm_id) DO NOTHING;

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_ltm_mapping_kb
    ON ltm_kb_mapping(kb_id);

-- ============================================================================
-- STEP 5: Verify migration completeness
-- ============================================================================

DO $$
DECLARE
    ltm_count INTEGER;
    kb_migrated_count INTEGER;
    mapping_count INTEGER;
BEGIN
    -- Count original long_term_memory entries
    SELECT COUNT(*) INTO ltm_count
    FROM long_term_memory;

    -- Count migrated entries in knowledge_base
    SELECT COUNT(*) INTO kb_migrated_count
    FROM knowledge_base
    WHERE source_type = 'consciousness'
      AND source_id LIKE 'ltm_%';

    -- Count mapping entries
    SELECT COUNT(*) INTO mapping_count
    FROM ltm_kb_mapping;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Migration 012b - long_term_memory → knowledge_base';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Original long_term_memory entries: %', ltm_count;
    RAISE NOTICE 'Migrated to knowledge_base: %', kb_migrated_count;
    RAISE NOTICE 'Mapping entries created: %', mapping_count;
    RAISE NOTICE '';

    IF ltm_count = kb_migrated_count THEN
        RAISE NOTICE '✅ Migration SUCCESSFUL - All entries migrated';
    ELSE
        RAISE WARNING '⚠️  Migration INCOMPLETE - % entries missing', (ltm_count - kb_migrated_count);
    END IF;

    RAISE NOTICE '=================================================';
END $$;

-- ============================================================================
-- STEP 6: Show sample migrated data
-- ============================================================================

SELECT
    'Sample Migrated Memories' as info,
    kb.id,
    kb.title,
    kb.category,
    kb.importance_score,
    kb.access_count,
    kb.created_at,
    kb.source_id as original_ltm_id
FROM knowledge_base kb
WHERE kb.source_type = 'consciousness'
  AND kb.source_id LIKE 'ltm_%'
ORDER BY kb.importance_score DESC, kb.created_at DESC
LIMIT 10;

-- ============================================================================
-- STEP 7: Show memory type distribution
-- ============================================================================

SELECT
    title as memory_type,
    COUNT(*) as count,
    ROUND(AVG(importance_score)::numeric, 2) as avg_importance,
    MAX(access_count) as max_access_count
FROM knowledge_base
WHERE source_type = 'consciousness'
GROUP BY title
ORDER BY count DESC
LIMIT 15;

-- ============================================================================
-- NOTES FOR ADMIN
-- ============================================================================

-- 1. The long_term_memory table is NOT dropped by this migration
--    You can manually drop it after verifying everything works:
--    DROP TABLE long_term_memory CASCADE;
--
-- 2. Old code using long_term_memory can be updated to use knowledge_base:
--    SELECT * FROM knowledge_base WHERE knowledge_type = 'conversation_memory'
--
-- 3. The ltm_kb_mapping table allows old code to lookup KB IDs from LTM IDs:
--    SELECT kb_id FROM ltm_kb_mapping WHERE ltm_id = <old_id>
--
-- 4. Future conversation memories should INSERT directly into knowledge_base:
--    INSERT INTO knowledge_base (knowledge_type, ...) VALUES ('conversation_memory', ...)
