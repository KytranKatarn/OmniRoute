-- Migration 175: Add AI analysis columns to google_email_cache
-- Supports email intelligence features ported from legacy email manager

ALTER TABLE google_email_cache ADD COLUMN IF NOT EXISTS ai_sentiment VARCHAR(20);
ALTER TABLE google_email_cache ADD COLUMN IF NOT EXISTS ai_priority VARCHAR(20);
ALTER TABLE google_email_cache ADD COLUMN IF NOT EXISTS ai_category VARCHAR(50);
ALTER TABLE google_email_cache ADD COLUMN IF NOT EXISTS ai_summary TEXT;
ALTER TABLE google_email_cache ADD COLUMN IF NOT EXISTS ai_analyzed_at TIMESTAMP;
ALTER TABLE google_email_cache ADD COLUMN IF NOT EXISTS filed_to_kb BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN google_email_cache.ai_sentiment IS 'AI-detected sentiment: positive, neutral, negative, urgent';
COMMENT ON COLUMN google_email_cache.ai_priority IS 'AI-assigned priority: low, medium, high, critical';
COMMENT ON COLUMN google_email_cache.ai_category IS 'AI category: business, personal, newsletter, notification, spam, support';
COMMENT ON COLUMN google_email_cache.ai_summary IS 'AI-generated one-line summary';
