-- Migration 079: Kokoro-82M Dual-Engine TTS Support
-- Adds engine tracking columns to voice tables for dual-engine (Kokoro + XTTS v2) support

-- Add engine tracking to voice_word_cache
ALTER TABLE voice_word_cache ADD COLUMN IF NOT EXISTS engine VARCHAR(20) DEFAULT 'xtts_v2';
CREATE INDEX IF NOT EXISTS idx_voice_cache_engine ON voice_word_cache(engine);

-- Add engine + voice_blend to agent_voice_profiles
-- DEFAULT 'xtts_v2' so existing profiles stay on their original engine
ALTER TABLE agent_voice_profiles ADD COLUMN IF NOT EXISTS engine VARCHAR(20) DEFAULT 'xtts_v2';
ALTER TABLE agent_voice_profiles ADD COLUMN IF NOT EXISTS voice_blend VARCHAR(200);

-- Track engine in generation log and pregen jobs
ALTER TABLE voice_generation_log ADD COLUMN IF NOT EXISTS engine VARCHAR(20);
ALTER TABLE voice_pregen_jobs ADD COLUMN IF NOT EXISTS engine VARCHAR(20) DEFAULT 'kokoro';
