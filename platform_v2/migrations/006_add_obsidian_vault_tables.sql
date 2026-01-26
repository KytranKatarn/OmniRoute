-- Migration 006: Add Obsidian Vault Tables
-- Date: 2026-01-08
-- Purpose: Add database support for Obsidian vault integration
--
-- Tables Created:
-- 1. vault_links - Stores bidirectional wikilink relationships
-- 2. vault_sync_log - Tracks file system sync events
--
-- Columns Added to knowledge_base:
-- 1. title - Note title (extracted from frontmatter or filename)
-- 2. category - Note category (Core, Features, Development, etc.)
-- 3. created_at - Note creation timestamp
-- 4. updated_at - Last modification timestamp
-- 5. is_documentation - Flag for vault notes
-- 6. file_path - Local file system path
-- 7. frontmatter_metadata - YAML frontmatter as JSONB
-- 8. last_synced_at - Last sync timestamp

-- ============================================================================
-- EXTEND knowledge_base TABLE
-- ============================================================================

-- Add vault-specific columns to existing knowledge_base table
ALTER TABLE knowledge_base
ADD COLUMN IF NOT EXISTS title TEXT,
ADD COLUMN IF NOT EXISTS category VARCHAR(100),
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS is_documentation BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS file_path TEXT,
ADD COLUMN IF NOT EXISTS frontmatter_metadata JSONB,
ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP;

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_knowledge_base_title
    ON knowledge_base(title);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_category
    ON knowledge_base(category);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_is_doc
    ON knowledge_base(is_documentation);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_file_path
    ON knowledge_base(file_path);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_last_synced
    ON knowledge_base(last_synced_at DESC);

-- ============================================================================
-- CREATE vault_links TABLE
-- ============================================================================

-- Stores bidirectional relationships between vault notes
CREATE TABLE IF NOT EXISTS vault_links (
    id SERIAL PRIMARY KEY,
    source_note_id INTEGER NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    target_note_id INTEGER NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    link_text TEXT,
    link_type VARCHAR(20) DEFAULT 'wikilink',  -- wikilink, tag, embed
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_note_id, target_note_id, link_type)
);

-- Indexes for backlink queries
CREATE INDEX IF NOT EXISTS idx_vault_links_source
    ON vault_links(source_note_id);

CREATE INDEX IF NOT EXISTS idx_vault_links_target
    ON vault_links(target_note_id);

CREATE INDEX IF NOT EXISTS idx_vault_links_type
    ON vault_links(link_type);

-- Composite index for bidirectional queries
CREATE INDEX IF NOT EXISTS idx_vault_links_bidirectional
    ON vault_links(source_note_id, target_note_id);

-- ============================================================================
-- CREATE vault_sync_log TABLE
-- ============================================================================

-- Tracks all file system sync events for debugging and monitoring
CREATE TABLE IF NOT EXISTS vault_sync_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(20) NOT NULL,  -- CREATE, MODIFY, DELETE, MOVE
    file_path TEXT NOT NULL,
    note_id INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, success, error
    error_message TEXT,
    detected_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Indexes for monitoring and debugging
CREATE INDEX IF NOT EXISTS idx_vault_sync_status
    ON vault_sync_log(status);

CREATE INDEX IF NOT EXISTS idx_vault_sync_detected
    ON vault_sync_log(detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_vault_sync_event_type
    ON vault_sync_log(event_type);

CREATE INDEX IF NOT EXISTS idx_vault_sync_file_path
    ON vault_sync_log(file_path);

-- ============================================================================
-- DATA MIGRATION (Optional)
-- ============================================================================

-- Mark any existing documentation in knowledge_base
-- (Uncomment if you have existing docs to mark)
-- UPDATE knowledge_base
-- SET is_documentation = TRUE
-- WHERE category IN ('documentation', 'guide', 'reference');

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify tables created
DO $$
BEGIN
    RAISE NOTICE 'Migration 006 Complete:';
    RAISE NOTICE '  - knowledge_base extended with 8 new columns';
    RAISE NOTICE '  - vault_links table created';
    RAISE NOTICE '  - vault_sync_log table created';
    RAISE NOTICE '  - 13 indexes created for performance';
END $$;

-- Show current schema
SELECT
    'knowledge_base' as table_name,
    COUNT(*) as column_count
FROM information_schema.columns
WHERE table_name = 'knowledge_base'
UNION ALL
SELECT
    'vault_links',
    COUNT(*)
FROM information_schema.columns
WHERE table_name = 'vault_links'
UNION ALL
SELECT
    'vault_sync_log',
    COUNT(*)
FROM information_schema.columns
WHERE table_name = 'vault_sync_log';
