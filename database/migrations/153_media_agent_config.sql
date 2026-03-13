-- Migration 153: Agent media configuration + gallery visibility
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS media_agent_config (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT FALSE,
    media_type VARCHAR(20) DEFAULT 'image',
    schedule_cron VARCHAR(50) DEFAULT '0 */4 * * *',
    default_prompt TEXT,
    default_negative TEXT DEFAULT '',
    default_params JSONB DEFAULT '{}',
    daily_cap INTEGER DEFAULT 10,
    last_generated_at TIMESTAMP,
    gallery_visibility VARCHAR(20) DEFAULT 'private',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE media_library
ADD COLUMN IF NOT EXISTS gallery_visibility VARCHAR(20) DEFAULT 'shared';

CREATE INDEX IF NOT EXISTS idx_media_agent_config_enabled
ON media_agent_config(enabled) WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_media_library_gallery_visibility
ON media_library(gallery_visibility);

CREATE INDEX IF NOT EXISTS idx_media_library_owner_type_agent
ON media_library(owner_type) WHERE owner_type = 'agent';
