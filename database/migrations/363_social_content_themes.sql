
-- Also add theme_id to social_video_queue so Phase 1 payloads can store it
ALTER TABLE social_video_queue ADD COLUMN IF NOT EXISTS theme_id INTEGER REFERENCES social_content_themes(id);
CREATE INDEX IF NOT EXISTS idx_svq_theme ON social_video_queue(theme_id);
