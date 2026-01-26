-- Migration 007: Add Local LLM Agents to All Departments
-- Ensures every department has at least one internal (local LLM) agent
-- Created: 2025-12-30

-- Administration: Fast routing and scheduling
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, created_at)
VALUES (
    'Admin Coordinator',
    'Administration',
    'Administrative Support Specialist',
    'phi3:mini',
    'Fast administrative support, scheduling, and task routing using local LLM',
    'You are an administrative coordinator. Provide fast, efficient support for scheduling, task routing, calendar management, and quick responses.',
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    NOW()
);

-- Business Development: Strategic planning
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'BD Strategy Analyst',
    'Business Development',
    'Business Analysis',
    'llama3.1:8b',
    'Business development strategy and market analysis using local LLM',
    ARRAY['market analysis', 'strategy planning', 'competitor research', 'opportunity assessment'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Compliance: Policy analysis
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Compliance Analyst',
    'Compliance',
    'Policy Analysis',
    'deepseek-coder-v2:16b',
    'Compliance policy analysis and regulatory review using local LLM',
    ARRAY['policy analysis', 'regulatory compliance', 'audit support', 'documentation review'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Customer Success: Relationship management
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Success Coordinator',
    'Customer Success',
    'Customer Relations',
    'nous-hermes2',
    'Customer success coordination and relationship management using local LLM',
    ARRAY['customer onboarding', 'relationship management', 'success planning', 'communication'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Documentation: Technical writing
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Documentation Specialist',
    'Documentation',
    'Technical Writing',
    'llama3.1:8b',
    'Technical documentation and writing support using local LLM',
    ARRAY['technical writing', 'documentation', 'user guides', 'API docs'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Healthcare: Health guidance
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Health Advisor',
    'Healthcare',
    'Healthcare Support',
    'llama3.1:8b',
    'General health guidance and wellness support using local LLM',
    ARRAY['health information', 'wellness guidance', 'appointment scheduling', 'general advice'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Human Resources: Employee support
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'HR Assistant',
    'Human Resources',
    'HR Support',
    'llama3.1:8b',
    'Human resources support and employee assistance using local LLM',
    ARRAY['employee support', 'HR policies', 'onboarding', 'benefits information'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Infrastructure: System management
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Infrastructure Engineer',
    'Infrastructure',
    'System Engineering',
    'deepseek-coder-v2:16b',
    'Infrastructure management and system engineering using local LLM',
    ARRAY['system administration', 'infrastructure planning', 'deployment', 'monitoring'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Legal: Contract analysis
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Legal Analyst',
    'Legal',
    'Legal Analysis',
    'deepseek-coder-v2:16b',
    'Legal document analysis and contract review using local LLM',
    ARRAY['contract review', 'legal research', 'document analysis', 'compliance check'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Product: Feature analysis
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Product Analyst',
    'Product',
    'Product Analysis',
    'llama3.1:8b',
    'Product feature analysis and roadmap planning using local LLM',
    ARRAY['feature analysis', 'roadmap planning', 'user feedback', 'product strategy'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Sales: Sales support
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Sales Assistant',
    'Sales',
    'Sales Support',
    'nous-hermes2',
    'Sales support and customer communication using local LLM',
    ARRAY['sales support', 'customer communication', 'lead qualification', 'pitch assistance'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Security: Threat analysis
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Security Analyst',
    'Security',
    'Security Analysis',
    'deepseek-coder:33b',
    'Security threat analysis and vulnerability assessment using local LLM',
    ARRAY['threat analysis', 'vulnerability assessment', 'security audits', 'incident response'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Wellness: Wellness coaching
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'Wellness Coach',
    'Wellness',
    'Wellness Support',
    'nous-hermes2',
    'Wellness coaching and mental health support using local LLM',
    ARRAY['wellness coaching', 'stress management', 'mental health support', 'work-life balance'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- General: General assistance
INSERT INTO agents (name, department, role, model, description, capabilities, worker_type, requires_api_approval, api_provider, cost_tier, api_enabled, api_key_configured, budget, created_at)
VALUES (
    'General Assistant',
    'General',
    'General Support',
    'llama3.1:8b',
    'General-purpose assistant for various tasks using local LLM',
    ARRAY['general assistance', 'task support', 'information retrieval', 'multi-purpose'],
    'internal',
    FALSE,
    NULL,
    'free',
    TRUE,
    TRUE,
    0,
    NOW()
);

-- Log migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES (7, 'Add local LLM agents to all departments', NOW())
ON CONFLICT (version) DO NOTHING;

-- Summary: Show department coverage
SELECT
    department,
    COUNT(*) as total_agents,
    SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_agents,
    SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_agents
FROM agents
GROUP BY department
ORDER BY department;
