-- Migration 078: Agent Voice Profiles & Pre-generation System
-- Date: 2026-02-10
-- Purpose: Per-agent voice profiles, pre-generation job tracking, agent_id on cache

-- ============================================================================
-- Agent Voice Profiles
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_voice_profiles (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    profile_name VARCHAR(100) NOT NULL,
    speaker VARCHAR(100) NOT NULL DEFAULT 'Ana Florence',
    speed DECIMAL(3,2) NOT NULL DEFAULT 1.00,
    pitch_shift DECIMAL(3,2) NOT NULL DEFAULT 1.00,
    warmth DECIMAL(3,2) NOT NULL DEFAULT 0.80,
    default_emotion VARCHAR(50) DEFAULT 'neutral',
    emotion_overrides JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id),
    UNIQUE(agent_id)
);

COMMENT ON TABLE agent_voice_profiles IS 'Per-agent voice identity profiles (Phase 78)';

-- ============================================================================
-- Add agent_id to voice_word_cache for per-agent caching
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'voice_word_cache' AND column_name = 'agent_id'
    ) THEN
        ALTER TABLE voice_word_cache ADD COLUMN agent_id INTEGER REFERENCES agents(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_voice_cache_agent ON voice_word_cache(agent_id);

-- ============================================================================
-- Pre-generation Job Tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS voice_pregen_jobs (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id),
    status VARCHAR(20) DEFAULT 'pending',
    job_type VARCHAR(20) NOT NULL,
    total_words INTEGER DEFAULT 0,
    completed_words INTEGER DEFAULT 0,
    failed_words INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    error_message TEXT
);

COMMENT ON TABLE voice_pregen_jobs IS 'Voice pre-generation job tracking (Phase 78)';

CREATE INDEX IF NOT EXISTS idx_pregen_status ON voice_pregen_jobs(status);

-- ============================================================================
-- Completion
-- ============================================================================

SELECT 'Migration 078 completed - Agent voice profiles & pre-generation' as status;
