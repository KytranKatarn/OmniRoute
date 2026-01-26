-- Migration 052: Optimize Staff with New Ollama Models
-- Date: 2026-01-20
-- Purpose: Leverage 5 new Ollama models for better task-LLM matching
-- New Models: starcoder2:7b, yi:34b, solar:10.7b, llama3.2:3b, qwen2.5:7b
--
-- Changes: 17 agents optimized for better performance

BEGIN;

-- ============================================
-- 1. starcoder2:7b - Code completion specialists (2 agents)
-- Size: 4.0 GB | Best for IDE-style code completion
-- ============================================

UPDATE agents SET model = 'starcoder2:7b'
WHERE name = 'CodeLlama Specialist' AND worker_type = 'internal';

UPDATE agents SET model = 'starcoder2:7b'
WHERE name = 'ChatGPT Code Specialist' AND worker_type = 'internal';

-- ============================================
-- 2. yi:34b - Complex reasoning (4 agents)
-- Size: 19 GB | Best for Legal, Finance, Compliance analysis
-- ============================================

UPDATE agents SET model = 'yi:34b'
WHERE name = 'Legal Advisor' AND worker_type = 'internal';

UPDATE agents SET model = 'yi:34b'
WHERE name = 'Data Privacy Officer' AND worker_type = 'internal';

UPDATE agents SET model = 'yi:34b'
WHERE name = 'Contracts & Proposals Specialist' AND worker_type = 'internal';

UPDATE agents SET model = 'yi:34b'
WHERE name = 'Tax Assistant' AND worker_type = 'internal';

-- ============================================
-- 3. solar:10.7b - Instruction following (4 agents)
-- Size: 6.1 GB | Best for Operations, Product, Project Mgmt
-- ============================================

UPDATE agents SET model = 'solar:10.7b'
WHERE name = 'Operations Lead' AND worker_type = 'internal';

UPDATE agents SET model = 'solar:10.7b'
WHERE name = 'Project Manager' AND worker_type = 'internal';

UPDATE agents SET model = 'solar:10.7b'
WHERE name = 'Product & Improvement Manager' AND worker_type = 'internal';

UPDATE agents SET model = 'solar:10.7b'
WHERE name = 'Shipping & Fulfillment Coordinator' AND worker_type = 'internal';

-- ============================================
-- 4. llama3.2:3b - Ultra-fast quick tasks (4 agents)
-- Size: 2.0 GB | Best for simple queries, fast responses
-- ============================================

UPDATE agents SET model = 'llama3.2:3b'
WHERE name = 'Receptionist' AND worker_type = 'internal';

UPDATE agents SET model = 'llama3.2:3b'
WHERE name = 'General Assistant' AND worker_type = 'internal';

UPDATE agents SET model = 'llama3.2:3b'
WHERE name = 'Grok General Assistant' AND worker_type = 'internal';

UPDATE agents SET model = 'llama3.2:3b'
WHERE name = 'Travel Coordinator' AND worker_type = 'internal';

-- ============================================
-- 5. qwen2.5:7b - Better general reasoning (3 agents)
-- Size: 4.5 GB | Upgrade from qwen2.5-coder:7b for non-code tasks
-- ============================================

UPDATE agents SET model = 'qwen2.5:7b'
WHERE name = 'QA Engineer' AND worker_type = 'internal';

UPDATE agents SET model = 'qwen2.5:7b'
WHERE name = 'QA Lead Engineer' AND worker_type = 'internal';

UPDATE agents SET model = 'qwen2.5:7b'
WHERE name = 'Executive Assistant' AND worker_type = 'internal';

COMMIT;

-- Log to knowledge base
INSERT INTO knowledge_base (title, content, knowledge_type, importance, source_type, tags)
VALUES (
    'Migration 052: Staff Optimization with New LLMs',
    'Optimized 17 agents with 5 new Ollama models:
    - starcoder2:7b (2 agents): Code completion for Engineering
    - yi:34b (4 agents): Complex reasoning for Legal/Finance/Compliance
    - solar:10.7b (4 agents): Instruction following for Operations/Product
    - llama3.2:3b (4 agents): Ultra-fast for quick tasks
    - qwen2.5:7b (3 agents): Better general reasoning for QA/Admin',
    'improvement',
    0.85,
    'migration',
    ARRAY['migration', 'staffing', 'llm', 'optimization', 'ollama']
);
