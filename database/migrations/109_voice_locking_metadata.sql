-- Migration 109: Voice locking audit metadata
-- Adds locked_at timestamp and locked_with_params to track when/how cache was locked

ALTER TABLE voice_word_cache
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS locked_with_params JSONB;

-- Backfill: set locked_at for already-locked entries to their last update time
UPDATE voice_word_cache
SET locked_at = COALESCE(last_used, NOW())
WHERE is_locked = TRUE AND locked_at IS NULL;

COMMENT ON COLUMN voice_word_cache.locked_at IS 'When this entry was locked (immutability timestamp)';
COMMENT ON COLUMN voice_word_cache.locked_with_params IS 'Voice parameters snapshot at lock time (speaker, speed, pitch, warmth, engine)';
