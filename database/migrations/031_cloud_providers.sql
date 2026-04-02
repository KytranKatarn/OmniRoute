-- Phase 3: Cloud provider management
-- Idempotent: uses IF NOT EXISTS

CREATE TABLE IF NOT EXISTS cloud_providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    logo_url TEXT,
    headquarters_city VARCHAR(100),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    provider_type VARCHAR(20) DEFAULT 'cloud',
    api_endpoint TEXT,
    api_key_env_var VARCHAR(100),
    tier VARCHAR(30) DEFAULT 'free',
    capabilities JSONB DEFAULT '[]',
    models_available JSONB DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'active',
    monthly_budget DECIMAL(10,2) DEFAULT 0,
    monthly_usage DECIMAL(10,2) DEFAULT 0,
    usage_reset_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cloud_usage_log (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES cloud_providers(id),
    agent_id INTEGER REFERENCES agents(id),
    model_name VARCHAR(100),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    estimated_cost DECIMAL(10,6) DEFAULT 0,
    capability VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cloud_usage_log_provider ON cloud_usage_log(provider_id);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_log_created ON cloud_usage_log(created_at);

-- Seed known providers
INSERT INTO cloud_providers (name, headquarters_city, latitude, longitude, provider_type, api_key_env_var, tier, capabilities, models_available, status)
VALUES
    ('OpenAI', 'San Francisco', 37.7749, -122.4194, 'cloud', 'OPENAI_API_KEY', 'pay-as-you-go',
     '["chat","embedding","image_gen"]', '["gpt-4o","gpt-4o-mini","dall-e-3"]', 'active'),
    ('Anthropic', 'San Francisco', 37.7749, -122.4194, 'cloud', 'ANTHROPIC_API_KEY', 'pay-as-you-go',
     '["chat"]', '["claude-sonnet-4-20250514","claude-haiku-4-5-20251001"]', 'active'),
    ('Google AI', 'Mountain View', 37.3861, -122.0839, 'cloud', 'GOOGLE_AI_API_KEY', 'free',
     '["chat","embedding"]', '["gemini-2.0-flash"]', 'inactive'),
    ('Groq', 'Mountain View', 37.3861, -122.0839, 'cloud', 'GROQ_API_KEY', 'free',
     '["chat"]', '["llama-3.3-70b-versatile","mixtral-8x7b-32768"]', 'active')
ON CONFLICT DO NOTHING;
