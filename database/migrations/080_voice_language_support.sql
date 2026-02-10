-- Migration 080: Voice Language Support
-- Adds language column to voice tables for multilingual TTS (French Quebecois, etc.)

ALTER TABLE voice_word_cache ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en';
ALTER TABLE agent_voice_profiles ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en';
ALTER TABLE voice_pregen_jobs ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en';
ALTER TABLE voice_generation_log ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en';

CREATE INDEX IF NOT EXISTS idx_voice_cache_language ON voice_word_cache(language);
