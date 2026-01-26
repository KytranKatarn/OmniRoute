-- Migration 051: Local LLM Staffing Optimization
-- Date: 2026-01-20
-- Purpose:
--   1. Fix worker_type for all agents (internal vs contract)
--   2. Ensure all staff use local Ollama LLMs
--   3. Keep only 7 external API contractors
--   4. Update department assignments

BEGIN;

-- ============================================
-- PHASE 1: Fix Contract Workers (7 external API agents)
-- ============================================

-- The 7 Contract Workers should be worker_type='contract'
UPDATE agents SET worker_type = 'contract'
WHERE department = 'Contract Workers';

-- Ensure correct models for contractors
UPDATE agents SET model = 'gpt-4o' WHERE name = 'ChatGPT Contractor';
UPDATE agents SET model = 'claude-sonnet-4-20250514' WHERE name = 'Claude Contractor';
UPDATE agents SET model = 'gemini-pro' WHERE name = 'Gemini Contractor';
UPDATE agents SET model = 'copilot' WHERE name = 'CoPilot Contractor';
UPDATE agents SET model = 'deepseek-chat' WHERE name = 'Deepseek Contractor';
UPDATE agents SET model = 'grok-beta' WHERE name = 'Grok Contractor';
UPDATE agents SET model = 'pplx-online' WHERE name = 'Perplexity Contractor';

-- ============================================
-- PHASE 2: Fix ALL non-Contract Workers to be internal
-- ============================================

-- All agents NOT in Contract Workers department should be internal
UPDATE agents SET worker_type = 'internal'
WHERE department != 'Contract Workers'
AND worker_type != 'human';

-- ============================================
-- PHASE 3: Ensure correct local LLM models by department
-- ============================================

-- Engineering/Infrastructure/Security -> deepseek-coder-v2:16b (or deepseek-coder:33b for senior)
UPDATE agents SET model = 'deepseek-coder-v2:16b'
WHERE department IN ('Engineering', 'Infrastructure')
AND worker_type = 'internal'
AND model NOT IN ('deepseek-coder:33b', 'codellama:latest');

-- Security gets deepseek-coder:33b for complex analysis
UPDATE agents SET model = 'deepseek-coder:33b'
WHERE department = 'Security'
AND worker_type = 'internal';

-- Marketing/Creative -> dolphin3:latest
UPDATE agents SET model = 'dolphin3:latest'
WHERE department = 'Marketing'
AND worker_type = 'internal';

-- Healthcare/Wellness/Customer Support/Customer Success -> nous-hermes2
UPDATE agents SET model = 'nous-hermes2'
WHERE department IN ('Healthcare', 'Wellness', 'Customer Support', 'Customer Success')
AND worker_type = 'internal';

-- Finance/Legal/Compliance -> mixtral:8x7b
UPDATE agents SET model = 'mixtral:8x7b'
WHERE department IN ('Finance', 'Legal', 'Compliance')
AND worker_type = 'internal';

-- Documentation -> command-r:latest
UPDATE agents SET model = 'command-r:latest'
WHERE department = 'Documentation'
AND worker_type = 'internal';

-- Operations/Quality Assurance/Administration -> qwen2.5-coder:7b
UPDATE agents SET model = 'qwen2.5-coder:7b'
WHERE department IN ('Operations', 'Quality Assurance', 'Administration')
AND worker_type = 'internal';

-- Sales/Business Development -> mistral:latest
UPDATE agents SET model = 'mistral:latest'
WHERE department IN ('Sales', 'Business Development')
AND worker_type = 'internal';

-- Human Resources/General/Product -> llama3.1:8b
UPDATE agents SET model = 'llama3.1:8b'
WHERE department IN ('Human Resources', 'General', 'Product')
AND worker_type = 'internal';

-- Knowledge Management/Ethics & Governance -> deepseek-coder-v2:16b
UPDATE agents SET model = 'deepseek-coder-v2:16b'
WHERE department IN ('Knowledge Management', 'Ethics & Governance')
AND worker_type = 'internal';

-- Executive Leadership (A.R.C.H.I.E.) -> deepseek-coder-v2:16b
UPDATE agents SET model = 'deepseek-coder-v2:16b'
WHERE department = 'Executive Leadership'
AND worker_type = 'internal';

-- ============================================
-- PHASE 4: Set monthly_budget to 0 for all internal agents
-- (They use FREE local LLMs)
-- ============================================

UPDATE agents SET monthly_budget = 0
WHERE worker_type = 'internal';

-- Set appropriate budgets for contractors (external API costs)
UPDATE agents SET monthly_budget = 50
WHERE worker_type = 'contract';

-- ============================================
-- VERIFICATION QUERIES
-- ============================================

-- Show final agent distribution
-- SELECT worker_type, COUNT(*) as count FROM agents WHERE status = 'active' GROUP BY worker_type;

-- Show model distribution
-- SELECT model, worker_type, COUNT(*) as count FROM agents WHERE status = 'active' GROUP BY model, worker_type ORDER BY worker_type, count DESC;

COMMIT;

-- Log migration
INSERT INTO knowledge_base (title, content, knowledge_type, importance, source_type, tags)
VALUES (
    'Migration 051: Local LLM Staffing Optimization',
    'Migrated all staff agents to use local Ollama LLMs. Fixed worker_type classifications. Kept 7 external API contractors only.',
    'improvement',
    0.9,
    'migration',
    ARRAY['migration', 'staffing', 'llm', 'optimization']
);
