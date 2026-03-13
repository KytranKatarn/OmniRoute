-- Migration 150: Audio voice samples + provider seeding
-- Adds voice_sample column to agents for XTTS v2 voice cloning
-- Seeds audio capabilities into contractor_providers

ALTER TABLE agents ADD COLUMN IF NOT EXISTS voice_sample VARCHAR(500);
COMMENT ON COLUMN agents.voice_sample IS 'Path to custom XTTS voice clone sample (6s WAV/MP3)';

-- Seed audio providers (stubbed — no real API keys yet)
INSERT INTO contractor_providers (provider_key, display_name, base_url, capabilities, is_active)
VALUES
    ('elevenlabs', 'ElevenLabs', 'https://api.elevenlabs.io', '["audio_sfx"]'::jsonb, false),
    ('stability_audio', 'Stability Audio', 'https://api.stability.ai', '["audio_music", "audio_sfx"]'::jsonb, false),
    ('replicate_audio', 'Replicate Audio', 'https://api.replicate.com', '["audio_music", "audio_sfx"]'::jsonb, false)
ON CONFLICT (provider_key) DO UPDATE
    SET capabilities = EXCLUDED.capabilities || contractor_providers.capabilities;
