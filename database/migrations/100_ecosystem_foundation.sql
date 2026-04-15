-- ============================================================
-- LLM Ecosystem Redesign — Foundation Migration
-- Decision #441, Spec: 2026-04-15-llm-ecosystem-redesign-design.md
-- ============================================================

BEGIN;

-- 1. Department capability profiles
CREATE TABLE IF NOT EXISTS department_capability_profiles (
    id SERIAL PRIMARY KEY,
    department VARCHAR(100) NOT NULL UNIQUE,
    floor VARCHAR(50) NOT NULL,
    required_capabilities JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO department_capability_profiles (department, floor, required_capabilities) VALUES
('Executive Office', 'BRIDGE', '["summarization", "reasoning", "orchestration"]'),
('Operations & Infrastructure', 'OPERATIONS', '["log_analysis", "scripting", "diagnostics"]'),
('Logistics & Supply Chain', 'OPERATIONS', '["data_extraction", "cost_analysis"]'),
('Finance & Accounting', 'OPERATIONS', '["numerical_reasoning", "report_generation"]'),
('Engineering & Technology', 'ENGINEERING', '["code_generation", "code_review", "debugging", "architecture"]'),
('Security & Compliance', 'ENGINEERING', '["classification", "threat_analysis", "policy_reasoning"]'),
('Research & Development', 'ENGINEERING', '["reasoning", "research_synthesis", "embedding"]'),
('Creative & Design', 'CREATIVE', '["creative_writing", "image_generation", "vision"]'),
('Marketing & Communications', 'CREATIVE', '["copywriting", "social_content", "multilingual"]'),
('Documentation & Knowledge', 'CREATIVE', '["summarization", "knowledge_extraction", "quality_scoring"]'),
('Customer Success & Support', 'SERVICES', '["conversation", "sentiment_analysis", "empathy"]'),
('Human Resources & Culture', 'SERVICES', '["ethics_reasoning", "policy_compliance", "welfare_check"]'),
('Medical & Wellness', 'SERVICES', '["empathetic_dialogue", "health_reasoning"]'),
('Legal & Regulatory', 'SERVICES', '["legal_reasoning", "document_analysis", "policy"]'),
('Diplomatic & External Relations', 'SERVICES', '["multilingual", "diplomatic_writing", "translation"]'),
('Analytics & Intelligence', 'SERVICES', '["data_analysis", "forecasting", "pattern_recognition"]'),
('News & Media', 'CREATIVE', '["fact_checking", "bias_detection", "editorial", "news_writing"]')
ON CONFLICT (department) DO UPDATE SET
    floor = EXCLUDED.floor,
    required_capabilities = EXCLUDED.required_capabilities,
    updated_at = NOW();

-- 2. Add C.R.E.E.D. compliance tier to contractor_providers
ALTER TABLE contractor_providers ADD COLUMN IF NOT EXISTS creed_compliance_tier INTEGER DEFAULT 2;
COMMENT ON COLUMN contractor_providers.creed_compliance_tier IS '1=Compliant (local/privacy), 2=Conditional (acceptable policy), 3=Restricted (data may be retained)';

-- 3. Normalize capability tags — fix image_generation → image_gen
UPDATE contractor_providers
SET capabilities = REPLACE(capabilities::text, '"image_generation"', '"image_gen"')::jsonb
WHERE capabilities::text LIKE '%image_generation%';

-- 4. Set C.R.E.E.D. compliance tiers for existing contractors
UPDATE contractor_providers SET creed_compliance_tier = 1 WHERE provider_key IN ('comfyui', 'kokoro_tts', 'ollama_diffuser');
UPDATE contractor_providers SET creed_compliance_tier = 2 WHERE provider_key IN ('groq', 'cerebras', 'mistral', 'cohere', 'together', 'cloudflare_ai', 'huggingface');
UPDATE contractor_providers SET creed_compliance_tier = 3 WHERE provider_key IN ('openai', 'gemini', 'xai', 'replicate_audio', 'elevenlabs', 'perplexity', 'claude');

-- 5. Fix contractor tier positions
UPDATE contractor_providers SET tier_position = 1 WHERE provider_key = 'comfyui';
UPDATE contractor_providers SET tier_position = 2 WHERE provider_key = 'kokoro_tts';
UPDATE contractor_providers SET tier_position = 3 WHERE provider_key = 'ollama_diffuser';
UPDATE contractor_providers SET tier_position = 4 WHERE provider_key = 'huggingface';
UPDATE contractor_providers SET tier_position = 5 WHERE provider_key = 'cloudflare_ai';
UPDATE contractor_providers SET tier_position = 6 WHERE provider_key = 'groq';
UPDATE contractor_providers SET tier_position = 7 WHERE provider_key = 'cerebras';
UPDATE contractor_providers SET tier_position = 9 WHERE provider_key = 'together';
UPDATE contractor_providers SET tier_position = 10 WHERE provider_key = 'cohere';
UPDATE contractor_providers SET tier_position = 11 WHERE provider_key = 'mistral';
UPDATE contractor_providers SET tier_position = 14 WHERE provider_key = 'minimax_cloud';
UPDATE contractor_providers SET tier_position = 15 WHERE provider_key = 'qwen3_cloud';
UPDATE contractor_providers SET tier_position = 19 WHERE provider_key = 'gemini';
UPDATE contractor_providers SET tier_position = 20 WHERE provider_key = 'xai';
UPDATE contractor_providers SET tier_position = 21 WHERE provider_key = 'perplexity';
UPDATE contractor_providers SET tier_position = 24 WHERE provider_key = 'openai';
UPDATE contractor_providers SET tier_position = 25 WHERE provider_key = 'claude';
UPDATE contractor_providers SET tier_position = 29 WHERE provider_key = 'replicate_audio';
UPDATE contractor_providers SET tier_position = 30 WHERE provider_key = 'elevenlabs';

-- 6. Add 6 new contractor providers
INSERT INTO contractor_providers (provider_key, display_name, base_url, capabilities, is_active, tier_position, creed_compliance_tier, is_cloud_proxy)
VALUES
('pollinations', 'Pollinations', 'https://image.pollinations.ai', '["image_gen"]', true, 8, 2, false),
('deepseek', 'DeepSeek', 'https://api.deepseek.com/v1', '["text_chat", "code", "reasoning"]', true, 12, 2, false),
('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1', '["text_chat", "code", "vision"]', true, 13, 2, false),
('stability_ai', 'Stability AI', 'https://api.stability.ai/v2beta', '["image_gen"]', true, 22, 3, false),
('fal_ai', 'Fal.ai', 'https://fal.run', '["image_gen"]', true, 23, 2, false),
('replicate', 'Replicate', 'https://api.replicate.com/v1', '["image_gen", "video_gen", "audio"]', true, 26, 3, false)
ON CONFLICT (provider_key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    base_url = EXCLUDED.base_url,
    capabilities = EXCLUDED.capabilities,
    tier_position = EXCLUDED.tier_position,
    creed_compliance_tier = EXCLUDED.creed_compliance_tier;

COMMIT;
