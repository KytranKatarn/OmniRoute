-- Migration 154: Media edits table + versioning columns
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS media_edits (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES media_library(id),
    edit_type VARCHAR(30) NOT NULL,
    params JSONB DEFAULT '{}',
    mask_path VARCHAR(500),
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    result_id INTEGER REFERENCES media_library(id),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL
);

ALTER TABLE media_library
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES media_library(id);

CREATE INDEX IF NOT EXISTS idx_media_edits_source ON media_edits(source_id);
CREATE INDEX IF NOT EXISTS idx_media_edits_status ON media_edits(status);
CREATE INDEX IF NOT EXISTS idx_media_edits_owner ON media_edits(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_library_parent ON media_library(parent_id);
