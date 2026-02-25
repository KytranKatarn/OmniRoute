-- Migration 117: Media Studio — capabilities column + media tables
-- Idempotent: safe to re-run

-- 1. Add capabilities JSONB column to contractor_providers
ALTER TABLE contractor_providers
ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '["text_chat"]';

-- 2. Seed capabilities for existing providers
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'minimax_cloud' AND (capabilities IS NULL OR capabilities = '["text_chat"]');
UPDATE contractor_providers SET capabilities = '["text_chat", "code"]' WHERE provider_key = 'qwen3_cloud';
UPDATE contractor_providers SET capabilities = '["text_chat", "code"]' WHERE provider_key = 'groq';
UPDATE contractor_providers SET capabilities = '["text_chat", "vision", "image_gen", "audio_tts"]' WHERE provider_key = 'gemini';
UPDATE contractor_providers SET capabilities = '["text_chat", "vision", "image_gen", "audio_tts", "code"]' WHERE provider_key = 'openai';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'cerebras';
UPDATE contractor_providers SET capabilities = '["text_chat", "code"]' WHERE provider_key = 'mistral';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'cohere';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'together';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'perplexity';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'xai';
UPDATE contractor_providers SET capabilities = '["text_chat"]' WHERE provider_key = 'claude';

-- 3. Media assets table
CREATE TABLE IF NOT EXISTS media_assets (
    id SERIAL PRIMARY KEY,
    asset_type VARCHAR(20) NOT NULL,
    title VARCHAR(255),
    prompt TEXT NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT,
    mime_type VARCHAR(100),
    provider_key VARCHAR(50) NOT NULL,
    model_used VARCHAR(100),
    cost_usd DECIMAL(10,6) DEFAULT 0,
    generation_params JSONB DEFAULT '{}',
    is_profile_image BOOLEAN DEFAULT FALSE,
    agent_id INTEGER REFERENCES agents(id),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_assets_type ON media_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_media_assets_created_by ON media_assets(created_by);
CREATE INDEX IF NOT EXISTS idx_media_assets_agent ON media_assets(agent_id) WHERE agent_id IS NOT NULL;

-- 4. Media generation queue
CREATE TABLE IF NOT EXISTS media_generation_queue (
    id SERIAL PRIMARY KEY,
    request_type VARCHAR(20) NOT NULL,
    prompt TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'pending',
    provider_key VARCHAR(50),
    model_used VARCHAR(100),
    assigned_agent_id INTEGER REFERENCES agents(id),
    result_asset_id INTEGER REFERENCES media_assets(id),
    error_message TEXT,
    requested_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_queue_status ON media_generation_queue(status);
CREATE INDEX IF NOT EXISTS idx_media_queue_requested_by ON media_generation_queue(requested_by);
