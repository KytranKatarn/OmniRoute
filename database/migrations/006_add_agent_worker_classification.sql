-- Migration 006: Add Agent Worker Classification
-- Adds fields to distinguish internal (local LLM) vs contract (API-based) workers
-- Created: 2025-12-30

-- Add worker classification columns
ALTER TABLE agents ADD COLUMN IF NOT EXISTS worker_type VARCHAR(20) DEFAULT 'internal';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS requires_api_approval BOOLEAN DEFAULT FALSE;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS api_provider VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS cost_tier VARCHAR(20) DEFAULT 'free';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS api_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS api_key_configured BOOLEAN DEFAULT FALSE;

-- Add comments for documentation
COMMENT ON COLUMN agents.worker_type IS 'Classification: internal (local LLM) or contract (API-based)';
COMMENT ON COLUMN agents.requires_api_approval IS 'Whether agent requires explicit approval before API calls';
COMMENT ON COLUMN agents.api_provider IS 'API provider: anthropic, openai, x-ai, google, null for local';
COMMENT ON COLUMN agents.cost_tier IS 'Cost tier: free (local), low, medium, high (API)';
COMMENT ON COLUMN agents.api_enabled IS 'Whether API usage is enabled for this agent';
COMMENT ON COLUMN agents.api_key_configured IS 'Whether API key is configured for this provider';

-- Create index for worker_type queries
CREATE INDEX IF NOT EXISTS idx_agents_worker_type ON agents(worker_type);
CREATE INDEX IF NOT EXISTS idx_agents_api_provider ON agents(api_provider);

-- Set default values for existing agents based on their models
-- Mark Claude agents as contract workers (Anthropic)
UPDATE agents
SET
    worker_type = 'contract',
    requires_api_approval = TRUE,
    api_provider = 'anthropic',
    cost_tier = 'high',
    api_enabled = FALSE,
    api_key_configured = FALSE
WHERE model LIKE 'claude-%';

-- Mark GPT agents as contract workers (OpenAI)
UPDATE agents
SET
    worker_type = 'contract',
    requires_api_approval = TRUE,
    api_provider = 'openai',
    cost_tier = 'high',
    api_enabled = FALSE,
    api_key_configured = FALSE
WHERE model LIKE 'gpt-%';

-- Mark Grok agents as contract workers (X.AI)
UPDATE agents
SET
    worker_type = 'contract',
    requires_api_approval = TRUE,
    api_provider = 'x-ai',
    cost_tier = 'medium',
    api_enabled = FALSE,
    api_key_configured = FALSE
WHERE model LIKE 'grok-%';

-- Mark all local Ollama models as internal workers (free)
UPDATE agents
SET
    worker_type = 'internal',
    requires_api_approval = FALSE,
    api_provider = NULL,
    cost_tier = 'free',
    api_enabled = TRUE,
    api_key_configured = TRUE
WHERE model NOT LIKE 'claude-%'
  AND model NOT LIKE 'gpt-%'
  AND model NOT LIKE 'grok-%'
  AND model NOT LIKE 'gemini-%';

-- Log migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES (6, 'Add agent worker classification fields', NOW())
ON CONFLICT (version) DO NOTHING;

-- Summary query
SELECT
    worker_type,
    api_provider,
    cost_tier,
    COUNT(*) as agent_count
FROM agents
GROUP BY worker_type, api_provider, cost_tier
ORDER BY worker_type, api_provider;
