-- Migration 035: Language preference persistence
ALTER TABLE users ADD COLUMN IF NOT EXISTS language_preference VARCHAR(8) DEFAULT 'en';
COMMENT ON COLUMN users.language_preference IS 'ISO language code: en, fr, es, pt, de, zh, ar, he';
