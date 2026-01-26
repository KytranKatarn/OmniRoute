-- Migration 064: Voice DNA System
-- Date: 2026-01-21
-- Purpose: Enhance voice caching for emotion-modulated synthesis (Phase 64)
-- Gives A.R.C.H.I.E. her unique voice integrated with Consciousness

-- ============================================================================
-- PHASE 64.2: Voice Table Enhancements
-- ============================================================================

-- Add new columns to voice_word_cache for emotion-aware caching
DO $$
BEGIN
    -- emotion_context: What emotion was used when generating
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'voice_word_cache' AND column_name = 'emotion_context'
    ) THEN
        ALTER TABLE voice_word_cache ADD COLUMN emotion_context VARCHAR(50);
    END IF;

    -- voice_parameters: JSON of speed, pitch, warmth used
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'voice_word_cache' AND column_name = 'voice_parameters'
    ) THEN
        ALTER TABLE voice_word_cache ADD COLUMN voice_parameters JSONB;
    END IF;

    -- duration_ms: How long generation took
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'voice_word_cache' AND column_name = 'duration_ms'
    ) THEN
        ALTER TABLE voice_word_cache ADD COLUMN duration_ms INTEGER;
    END IF;

    -- hit_count: Cache hit counter for optimization
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'voice_word_cache' AND column_name = 'hit_count'
    ) THEN
        ALTER TABLE voice_word_cache ADD COLUMN hit_count INTEGER DEFAULT 0;
    END IF;

    -- text_hash: SHA-256 hash for fast lookups
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'voice_word_cache' AND column_name = 'text_hash'
    ) THEN
        ALTER TABLE voice_word_cache ADD COLUMN text_hash VARCHAR(64);
    END IF;
END $$;

-- Create unique index on text_hash for fast cache lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_cache_hash
    ON voice_word_cache(text_hash)
    WHERE text_hash IS NOT NULL;

-- Index for emotion-based queries
CREATE INDEX IF NOT EXISTS idx_voice_cache_emotion
    ON voice_word_cache(emotion_context);

-- Index for cache optimization (most used phrases)
CREATE INDEX IF NOT EXISTS idx_voice_cache_hits
    ON voice_word_cache(hit_count DESC)
    WHERE hit_count > 0;

-- ============================================================================
-- User Voice Preferences
-- ============================================================================

CREATE TABLE IF NOT EXISTS voice_config (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) UNIQUE,
    voice_enabled BOOLEAN DEFAULT TRUE,
    auto_play BOOLEAN DEFAULT FALSE,
    volume DECIMAL(3,2) DEFAULT 0.80,
    preferred_speed DECIMAL(3,2) DEFAULT 1.00,
    preferred_emotion VARCHAR(50) DEFAULT 'neutral',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE voice_config IS 'User voice preferences for A.R.C.H.I.E. Voice DNA System (Phase 64)';
COMMENT ON COLUMN voice_config.voice_enabled IS 'Whether voice synthesis is enabled for this user';
COMMENT ON COLUMN voice_config.auto_play IS 'Auto-play voice responses without clicking Listen button';
COMMENT ON COLUMN voice_config.volume IS 'Playback volume 0.0-1.0';
COMMENT ON COLUMN voice_config.preferred_speed IS 'Speech speed multiplier 0.5-2.0';
COMMENT ON COLUMN voice_config.preferred_emotion IS 'Override emotion (or null for auto-detect)';

-- ============================================================================
-- Voice Generation Analytics
-- ============================================================================

CREATE TABLE IF NOT EXISTS voice_generation_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    text_length INTEGER,
    emotion VARCHAR(50),
    cached BOOLEAN,
    generation_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_log_user ON voice_generation_log(user_id);
CREATE INDEX IF NOT EXISTS idx_voice_log_date ON voice_generation_log(created_at);
CREATE INDEX IF NOT EXISTS idx_voice_log_cached ON voice_generation_log(cached);

COMMENT ON TABLE voice_generation_log IS 'Voice generation analytics for optimization (Phase 64)';

-- ============================================================================
-- Views for Analytics
-- ============================================================================

-- Voice cache statistics by emotion
CREATE OR REPLACE VIEW v_voice_cache_stats AS
SELECT
    emotion_context,
    COUNT(*) as cached_phrases,
    SUM(COALESCE(hit_count, 0)) as total_hits,
    AVG(COALESCE(hit_count, 0))::NUMERIC(10,2) as avg_hits_per_phrase,
    AVG(duration_ms)::INTEGER as avg_generation_ms
FROM voice_word_cache
WHERE text_hash IS NOT NULL
GROUP BY emotion_context
ORDER BY total_hits DESC;

COMMENT ON VIEW v_voice_cache_stats IS 'Voice cache statistics by emotion (Phase 64)';

-- Daily voice generation stats
CREATE OR REPLACE VIEW v_voice_daily_stats AS
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_generations,
    COUNT(*) FILTER (WHERE cached = TRUE) as cache_hits,
    COUNT(*) FILTER (WHERE cached = FALSE) as new_generations,
    ROUND(100.0 * COUNT(*) FILTER (WHERE cached = TRUE) / NULLIF(COUNT(*), 0), 1) as cache_hit_rate,
    AVG(generation_time_ms) FILTER (WHERE cached = FALSE)::INTEGER as avg_generation_ms,
    AVG(text_length)::INTEGER as avg_text_length
FROM voice_generation_log
GROUP BY DATE(created_at)
ORDER BY date DESC;

COMMENT ON VIEW v_voice_daily_stats IS 'Daily voice generation statistics (Phase 64)';

-- Top cached phrases (most reused)
CREATE OR REPLACE VIEW v_voice_top_cached AS
SELECT
    word as phrase_preview,
    emotion_context,
    hit_count,
    duration_ms as original_gen_time_ms
FROM voice_word_cache
WHERE text_hash IS NOT NULL
ORDER BY hit_count DESC
LIMIT 100;

COMMENT ON VIEW v_voice_top_cached IS 'Most frequently used cached voice phrases (Phase 64)';

-- ============================================================================
-- Functions
-- ============================================================================

-- Function to get voice config with defaults
CREATE OR REPLACE FUNCTION get_voice_config(p_user_id INTEGER)
RETURNS TABLE (
    voice_enabled BOOLEAN,
    auto_play BOOLEAN,
    volume DECIMAL(3,2),
    preferred_speed DECIMAL(3,2),
    preferred_emotion VARCHAR(50)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(vc.voice_enabled, TRUE),
        COALESCE(vc.auto_play, FALSE),
        COALESCE(vc.volume, 0.80),
        COALESCE(vc.preferred_speed, 1.00),
        vc.preferred_emotion
    FROM (SELECT 1) as dummy
    LEFT JOIN voice_config vc ON vc.user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_voice_config IS 'Get user voice config with defaults (Phase 64)';

-- Function to cleanup old cache entries (run periodically)
CREATE OR REPLACE FUNCTION cleanup_voice_cache(p_min_hits INTEGER DEFAULT 0, p_days_old INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM voice_word_cache
    WHERE text_hash IS NOT NULL
      AND hit_count <= p_min_hits
      AND (created_at IS NULL OR created_at < NOW() - (p_days_old || ' days')::INTERVAL);

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_voice_cache IS 'Remove unused cache entries older than N days (Phase 64)';

-- ============================================================================
-- Completion
-- ============================================================================

SELECT 'Migration 064 completed - Voice DNA System enabled (Phase 64)' as status;
