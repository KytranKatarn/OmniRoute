-- Migration 106: External AI Providers
-- API key storage + cost tracking for OpenAI, Perplexity, xAI

CREATE TABLE IF NOT EXISTS external_api_keys (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL UNIQUE,
    api_key_encrypted TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    monthly_budget_usd NUMERIC(10,2) DEFAULT 10.00,
    current_month_cost_usd NUMERIC(10,2) DEFAULT 0.00,
    budget_reset_day INTEGER DEFAULT 1,
    last_reset_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE cloud_model_usage ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(10,6) DEFAULT 0;

CREATE OR REPLACE VIEW v_external_cost_summary AS
SELECT
    provider,
    date_trunc('day', created_at) as day,
    COUNT(*) as calls,
    SUM(cost_usd) as daily_cost,
    SUM(prompt_tokens) as total_prompt_tokens,
    SUM(completion_tokens) as total_completion_tokens
FROM cloud_model_usage
WHERE provider NOT IN ('ollama', 'ollama_cloud')
GROUP BY provider, date_trunc('day', created_at)
ORDER BY day DESC, provider;

INSERT INTO model_tier_configs (tier_name, provider, model_name, is_active, input_cost_per_1m, output_cost_per_1m, max_tokens)
VALUES
    ('openai', 'openai', 'gpt-4o-mini', TRUE, 0.15, 0.60, 16384),
    ('perplexity', 'perplexity', 'llama-3.1-sonar-small-128k-online', TRUE, 0.20, 0.20, 8192),
    ('grok', 'xai', 'grok-2', TRUE, 2.00, 10.00, 8192)
ON CONFLICT (tier_name) DO UPDATE SET
    provider = EXCLUDED.provider,
    model_name = EXCLUDED.model_name,
    input_cost_per_1m = EXCLUDED.input_cost_per_1m,
    output_cost_per_1m = EXCLUDED.output_cost_per_1m,
    is_active = EXCLUDED.is_active;
