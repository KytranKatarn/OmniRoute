-- Migration 091: Voice cache immutability
-- Adds is_locked flag to voice_word_cache to prevent overwrites after pre-generation.
-- Locked entries preserve their audio + voice_parameters permanently.

ALTER TABLE voice_word_cache ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE;

-- Index for quickly filtering locked entries
CREATE INDEX IF NOT EXISTS idx_voice_cache_locked ON voice_word_cache (is_locked) WHERE is_locked = TRUE;

COMMENT ON COLUMN voice_word_cache.is_locked IS 'When TRUE, audio and voice_parameters cannot be overwritten by new synthesis. Set by pre-gen jobs to preserve voice consistency.';
