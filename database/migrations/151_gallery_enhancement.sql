-- Migration 151: Gallery Enhancement — tags, collections, smart collections, embeddings
-- Adds 5 tables + prompt_embedding column on media_library

-- ─── Tags ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS media_tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    tag_type VARCHAR(20) NOT NULL DEFAULT 'user',
    created_by INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_media_tags_type ON media_tags (tag_type);

CREATE TABLE IF NOT EXISTS media_tag_map (
    id SERIAL PRIMARY KEY,
    media_id INTEGER NOT NULL REFERENCES media_library(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES media_tags(id) ON DELETE CASCADE,
    UNIQUE (media_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_media_tag_map_media ON media_tag_map (media_id);
CREATE INDEX IF NOT EXISTS idx_media_tag_map_tag ON media_tag_map (tag_id);

-- ─── Collections ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS media_collections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER,
    is_shared BOOLEAN DEFAULT false,
    cover_media_id INTEGER REFERENCES media_library(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_media_collections_owner
    ON media_collections (owner_type, owner_id);

CREATE TABLE IF NOT EXISTS media_collection_items (
    id SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES media_collections(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media_library(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0,
    added_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (collection_id, media_id)
);
CREATE INDEX IF NOT EXISTS idx_media_collection_items_coll
    ON media_collection_items (collection_id, sort_order);

-- ─── Smart Collections ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS media_smart_collections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER,
    filters JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_media_smart_collections_owner
    ON media_smart_collections (owner_type, owner_id);

-- ─── Prompt Embedding ────────────────────────────────────────────────

DO $$
BEGIN
    -- Try pgvector first
    CREATE EXTENSION IF NOT EXISTS vector;
    ALTER TABLE media_library ADD COLUMN IF NOT EXISTS prompt_embedding VECTOR(768);
    CREATE INDEX IF NOT EXISTS idx_media_library_prompt_emb
        ON media_library USING ivfflat (prompt_embedding vector_cosine_ops) WITH (lists = 10);
    RAISE NOTICE 'pgvector enabled — VECTOR(768) column added';
EXCEPTION WHEN OTHERS THEN
    -- Fallback to JSONB
    ALTER TABLE media_library ADD COLUMN IF NOT EXISTS prompt_embedding JSONB;
    RAISE NOTICE 'pgvector not available — using JSONB fallback for embeddings';
END $$;
