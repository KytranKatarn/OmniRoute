-- Migration 116: Dynamic Contractor Providers
-- Single source of truth for all external AI provider metadata.
-- Replaces hardcoded PROVIDER_CONFIGS, PROVIDER_MODELS, PROVIDER_RATE_LIMITS.

-- Add account_tier column to external_api_keys if missing
ALTER TABLE external_api_keys ADD COLUMN IF NOT EXISTS account_tier VARCHAR(30) DEFAULT 'free';

CREATE TABLE IF NOT EXISTS contractor_providers (
    id SERIAL PRIMARY KEY,
    provider_key VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    base_url TEXT NOT NULL,
    default_model VARCHAR(100),
    auth_method VARCHAR(20) DEFAULT 'api_key',
    auth_env_var VARCHAR(100),
    is_cloud_proxy BOOLEAN DEFAULT FALSE,
    tier_position INTEGER DEFAULT 99,
    models JSONB DEFAULT '[]',
    rate_limits JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed 12 providers
INSERT INTO contractor_providers (provider_key, display_name, base_url, default_model, auth_method, auth_env_var, is_cloud_proxy, tier_position, models, rate_limits, is_active)
VALUES
    -- 1. MiniMax Cloud (Ollama cloud proxy)
    ('minimax_cloud', 'MiniMax Cloud', 'ollama_cloud_proxy', 'minimax-m2.5', 'env_var', 'OLLAMA_API_KEY', TRUE, 3,
     '[{"name": "minimax-m2.5", "max_tokens": 8192, "cost_per_1k": {"input": 0.0, "output": 0.0}}]'::jsonb,
     '{"free": {"session_limit": 50, "weekly_limit": 7000}, "pro": {"session_limit": 500, "weekly_limit": 50000}, "enterprise": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     TRUE),

    -- 2. Qwen3 Cloud (Ollama cloud proxy)
    ('qwen3_cloud', 'Qwen3 Cloud', 'ollama_cloud_proxy', 'qwen3-coder-next', 'env_var', 'OLLAMA_API_KEY', TRUE, 4,
     '[{"name": "qwen3-coder-next", "max_tokens": 32768, "cost_per_1k": {"input": 0.0, "output": 0.0}}]'::jsonb,
     '{"free": {"session_limit": 50, "weekly_limit": 7000}, "pro": {"session_limit": 500, "weekly_limit": 50000}, "enterprise": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     TRUE),

    -- 3. OpenAI
    ('openai', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4o-mini', 'api_key', 'OPENAI_API_KEY', FALSE, 5,
     '[{"name": "gpt-4o-mini", "max_tokens": 16384, "cost_per_1k": {"input": 0.00015, "output": 0.0006}}, {"name": "gpt-4o", "max_tokens": 16384, "cost_per_1k": {"input": 0.0025, "output": 0.01}}]'::jsonb,
     '{"free": {"session_limit": 20, "weekly_limit": 500}, "pay_as_you_go": {"session_limit": null, "weekly_limit": null}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 4. Perplexity
    ('perplexity', 'Perplexity', 'https://api.perplexity.ai', 'llama-3.1-sonar-small-128k-online', 'api_key', 'PERPLEXITY_API_KEY', FALSE, 6,
     '[{"name": "llama-3.1-sonar-small-128k-online", "max_tokens": 8192, "cost_per_1k": {"input": 0.0002, "output": 0.0002}}]'::jsonb,
     '{"free": {"session_limit": 10, "weekly_limit": 200}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 5. xAI (Grok)
    ('xai', 'xAI (Grok)', 'https://api.x.ai/v1', 'grok-2', 'api_key', 'XAI_API_KEY', FALSE, 7,
     '[{"name": "grok-2", "max_tokens": 8192, "cost_per_1k": {"input": 0.002, "output": 0.01}}]'::jsonb,
     '{"free": {"session_limit": 25, "weekly_limit": 1500}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 6. Groq
    ('groq', 'Groq', 'https://api.groq.com/openai/v1', 'llama-3.3-70b-versatile', 'api_key', 'GROQ_API_KEY', FALSE, 8,
     '[{"name": "llama-3.3-70b-versatile", "max_tokens": 32768, "cost_per_1k": {"input": 0.00059, "output": 0.00079}}, {"name": "llama-3.1-8b-instant", "max_tokens": 8192, "cost_per_1k": {"input": 0.00005, "output": 0.00008}}]'::jsonb,
     '{"free": {"session_limit": 30, "weekly_limit": 14400}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 7. Google Gemini
    ('gemini', 'Google Gemini', 'https://generativelanguage.googleapis.com/v1beta/openai', 'gemini-2.0-flash', 'api_key', 'GEMINI_API_KEY', FALSE, 9,
     '[{"name": "gemini-2.0-flash", "max_tokens": 8192, "cost_per_1k": {"input": 0.0, "output": 0.0}}, {"name": "gemini-2.5-flash", "max_tokens": 65536, "cost_per_1k": {"input": 0.0, "output": 0.0}}]'::jsonb,
     '{"free": {"session_limit": 15, "weekly_limit": 1500}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 8. Cerebras
    ('cerebras', 'Cerebras', 'https://api.cerebras.ai/v1', 'llama3.1-8b', 'api_key', 'CEREBRAS_API_KEY', FALSE, 10,
     '[{"name": "llama3.1-8b", "max_tokens": 8192, "cost_per_1k": {"input": 0.0001, "output": 0.0001}}, {"name": "qwen-3-235b-a22b-instruct-2507", "max_tokens": 8192, "cost_per_1k": {"input": 0.001, "output": 0.001}}]'::jsonb,
     '{"free": {"session_limit": 30, "weekly_limit": 8400}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 9. Mistral AI
    ('mistral', 'Mistral AI', 'https://api.mistral.ai/v1', 'mistral-small-latest', 'api_key', 'MISTRAL_API_KEY', FALSE, 11,
     '[{"name": "mistral-small-latest", "max_tokens": 8192, "cost_per_1k": {"input": 0.0001, "output": 0.0003}}, {"name": "mistral-large-latest", "max_tokens": 8192, "cost_per_1k": {"input": 0.002, "output": 0.006}}]'::jsonb,
     '{"free": {"session_limit": 20, "weekly_limit": 2000}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 10. Cohere
    ('cohere', 'Cohere', 'https://api.cohere.com/compatibility/v1', 'command-a-03-2025', 'api_key', 'COHERE_API_KEY', FALSE, 12,
     '[{"name": "command-a-03-2025", "max_tokens": 4096, "cost_per_1k": {"input": 0.0025, "output": 0.01}}, {"name": "command-r-08-2024", "max_tokens": 4096, "cost_per_1k": {"input": 0.00015, "output": 0.0006}}]'::jsonb,
     '{"free": {"session_limit": 20, "weekly_limit": 1000}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 11. Together AI
    ('together', 'Together AI', 'https://api.together.xyz/v1', 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'api_key', 'TOGETHER_API_KEY', FALSE, 13,
     '[{"name": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "max_tokens": 8192, "cost_per_1k": {"input": 0.00088, "output": 0.00088}}]'::jsonb,
     '{"free": {"session_limit": 20, "weekly_limit": 1000}, "pro": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE),

    -- 12. Anthropic Claude
    ('claude', 'Anthropic Claude', 'http://localhost:7682/v1', 'claude-sonnet-4-20250514', 'api_key', 'ANTHROPIC_API_KEY', FALSE, 14,
     '[{"name": "claude-sonnet-4-20250514", "max_tokens": 8192, "cost_per_1k": {"input": 0.003, "output": 0.015}}, {"name": "claude-haiku-4-20250414", "max_tokens": 8192, "cost_per_1k": {"input": 0.0008, "output": 0.004}}]'::jsonb,
     '{"free": {"session_limit": 10, "weekly_limit": 200}, "max": {"session_limit": null, "weekly_limit": null}}'::jsonb,
     FALSE)
ON CONFLICT (provider_key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    base_url = EXCLUDED.base_url,
    default_model = EXCLUDED.default_model,
    auth_method = EXCLUDED.auth_method,
    auth_env_var = EXCLUDED.auth_env_var,
    is_cloud_proxy = EXCLUDED.is_cloud_proxy,
    tier_position = EXCLUDED.tier_position,
    models = EXCLUDED.models,
    rate_limits = EXCLUDED.rate_limits,
    updated_at = NOW();
