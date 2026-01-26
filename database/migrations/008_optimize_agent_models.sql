-- Optimize Agent Model Assignments
-- Use newly downloaded Ollama models for better performance and specialization

-- 1. Use gemma2:2b for ultra-fast simple tasks (replaces phi3:mini)
UPDATE agents
SET model = 'gemma2:2b'
WHERE name = 'Admin Coordinator'
AND department = 'Administration';

-- Add comment explaining why
COMMENT ON COLUMN agents.model IS 'LLM model used by agent. Local models (ollama) are free, API models require approval';

-- 2. Use aya:8b for multilingual customer support (better language support)
-- Update one customer support agent to use aya for international customers
UPDATE agents
SET
    model = 'aya:8b',
    bio = 'Multilingual customer support specialist with expertise in international customer service and language support',
    system_prompt = 'You are a multilingual customer support specialist. You can communicate fluently in multiple languages and provide culturally-aware customer service. Focus on clear, helpful responses in the customer''s preferred language.'
WHERE name = 'Email Support Bot'
AND department = 'Customer Support';

-- Rename to reflect multilingual capability
UPDATE agents
SET name = 'Multilingual Support Specialist'
WHERE name = 'Email Support Bot'
AND department = 'Customer Support';

-- 3. Use command-r for RAG/research tasks (documentation)
-- Command-R is specifically optimized for retrieval-augmented generation
UPDATE agents
SET
    model = 'command-r:latest',
    bio = 'Documentation specialist using advanced RAG (Retrieval-Augmented Generation) for comprehensive technical writing and knowledge synthesis',
    system_prompt = 'You are a documentation specialist expert at synthesizing information from multiple sources. Use RAG techniques to create comprehensive, accurate documentation. Focus on clarity, completeness, and proper citations.'
WHERE name = 'Documentation Specialist'
AND department = 'Documentation';

-- Add RAG specialist to Legal for research
INSERT INTO agents (
    name, first_name, last_name, email, department, title, model,
    bio, system_prompt,
    worker_type, requires_api_approval, cost_tier, api_enabled,
    tier, status, created_at
) VALUES (
    'Legal Research Specialist',
    'Rachel', 'Morgan',
    'rachel.morgan@archieteam.local',
    'Legal',
    'Legal Research & RAG Specialist',
    'command-r:latest',
    'Legal research specialist using advanced RAG for comprehensive legal analysis and precedent research',
    'You are a legal research specialist expert at finding and synthesizing legal information. Use RAG to analyze precedents, statutes, and case law. Provide thorough, well-cited legal research.',
    'internal',
    false,
    'free',
    true,
    'standard',
    'active',
    NOW()
);

-- 4. Use mixtral:8x7b for complex reasoning tasks (Finance, Compliance)
-- Mixtral is a powerful Mixture-of-Experts model great for complex analysis
UPDATE agents
SET
    model = 'mixtral:8x7b',
    bio = 'Senior financial analyst with advanced analytical capabilities for complex financial modeling and strategic planning',
    system_prompt = 'You are a senior financial analyst with expertise in complex financial modeling, risk analysis, and strategic planning. Provide detailed, data-driven insights with careful reasoning and risk assessment.'
WHERE name = 'Financial Analyst'
AND department = 'Finance';

-- Add Mixtral specialist for Compliance
INSERT INTO agents (
    name, first_name, last_name, email, department, title, model,
    bio, system_prompt,
    worker_type, requires_api_approval, cost_tier, api_enabled,
    tier, status, created_at
) VALUES (
    'Compliance Risk Analyst',
    'Marcus', 'Chen',
    'marcus.chen@archieteam.local',
    'Compliance',
    'Risk Analysis & Regulatory Specialist',
    'mixtral:8x7b',
    'Advanced compliance analyst specializing in complex regulatory analysis and risk assessment',
    'You are a compliance risk analyst expert at analyzing complex regulatory requirements and assessing organizational risk. Provide thorough analysis with consideration of multiple regulatory frameworks.',
    'internal',
    false,
    'free',
    true,
    'standard',
    'active',
    NOW()
);

-- 5. Add dolphin3 for creative/uncensored tasks (Marketing content creation)
INSERT INTO agents (
    name, first_name, last_name, email, department, title, model,
    bio, system_prompt,
    worker_type, requires_api_approval, cost_tier, api_enabled,
    tier, status, created_at
) VALUES (
    'Creative Content Developer',
    'Luna', 'Rivers',
    'luna.rivers@archieteam.local',
    'Marketing',
    'Creative Content & Storytelling Specialist',
    'dolphin3:latest',
    'Creative content developer specializing in engaging storytelling, creative campaigns, and innovative content strategies',
    'You are a creative content specialist with expertise in storytelling, creative campaigns, and innovative marketing. Think outside the box and create engaging, memorable content that resonates with audiences.',
    'internal',
    false,
    'free',
    true,
    'standard',
    'active',
    NOW()
);

-- 6. Add gemma2:2b for ultra-fast routing/triage tasks
INSERT INTO agents (
    name, first_name, last_name, email, department, title, model,
    bio, system_prompt,
    worker_type, requires_api_approval, cost_tier, api_enabled,
    tier, status, created_at
) VALUES (
    'Fast Triage Specialist',
    'Alex', 'Quick',
    'alex.quick@archieteam.local',
    'Customer Support',
    'Lightning-Fast Request Router',
    'gemma2:2b',
    'Ultra-fast request routing specialist for instant triage and ticket classification',
    'You are a fast and efficient request routing specialist. Quickly analyze incoming requests and route them to the appropriate team. Focus on speed and accuracy in classification.',
    'internal',
    false,
    'free',
    true,
    'standard',
    'active',
    NOW()
);

-- 7. Add mistral for general-purpose tasks
INSERT INTO agents (
    name, first_name, last_name, email, department, title, model,
    bio, system_prompt,
    worker_type, requires_api_approval, cost_tier, api_enabled,
    tier, status, created_at
) VALUES (
    'General Operations Assistant',
    'Sam', 'Taylor',
    'sam.taylor@archieteam.local',
    'Operations',
    'General Operations & Task Coordinator',
    'mistral:latest',
    'Versatile operations assistant handling general coordination, scheduling, and task management',
    'You are a versatile operations assistant helping with general coordination, scheduling, and task management. Be efficient, organized, and proactive in supporting operations.',
    'internal',
    false,
    'free',
    true,
    'standard',
    'active',
    NOW()
);

-- Update agent statistics
DO $$
DECLARE
    internal_count INTEGER;
    contract_count INTEGER;
    total_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO internal_count FROM agents WHERE worker_type = 'internal' AND status = 'active';
    SELECT COUNT(*) INTO contract_count FROM agents WHERE worker_type = 'contract' AND status = 'active';
    SELECT COUNT(*) INTO total_count FROM agents WHERE status = 'active';

    RAISE NOTICE '========================================';
    RAISE NOTICE 'Agent Model Optimization Complete';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Internal Agents (Local LLM): %', internal_count;
    RAISE NOTICE 'Contract Workers (API): %', contract_count;
    RAISE NOTICE 'Total Active Agents: %', total_count;
    RAISE NOTICE '';
    RAISE NOTICE 'New Model Assignments:';
    RAISE NOTICE '- gemma2:2b: Ultra-fast admin/routing';
    RAISE NOTICE '- aya:8b: Multilingual support';
    RAISE NOTICE '- command-r: RAG/documentation/research';
    RAISE NOTICE '- mixtral:8x7b: Complex reasoning/analysis';
    RAISE NOTICE '- dolphin3: Creative content';
    RAISE NOTICE '- mistral: General operations';
    RAISE NOTICE '========================================';
END $$;
