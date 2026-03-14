-- Migration 157: Link social posts to Media Studio assets
-- Idempotent: safe to run multiple times

ALTER TABLE social_posts
ADD COLUMN IF NOT EXISTS media_library_id INTEGER REFERENCES media_library(id);

CREATE INDEX IF NOT EXISTS idx_social_posts_media_library
ON social_posts(media_library_id) WHERE media_library_id IS NOT NULL;
