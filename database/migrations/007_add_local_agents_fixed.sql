-- Migration 007: Add Local LLM Agents to All Departments (Fixed)
-- Ensures every department has at least one internal (local LLM) agent
-- Created: 2025-12-30

-- Administration
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Admin Coordinator', 'Administration', 'Administrative Support Specialist', 'phi3:mini', 'Fast administrative support and task routing specialist', 'You are an administrative coordinator providing fast support for scheduling, task routing, and calendar management.', 'internal', FALSE, 'free', TRUE, NOW());

-- Business Development
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('BD Strategy Analyst', 'Business Development', 'Business Strategy Analyst', 'llama3.1:8b', 'Business development strategy and market analysis specialist', 'You are a business development analyst providing market analysis, strategy planning, and competitor research.', 'internal', FALSE, 'free', TRUE, NOW());

-- Compliance
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Compliance Analyst', 'Compliance', 'Compliance & Policy Analyst', 'deepseek-coder-v2:16b', 'Compliance policy analysis and regulatory review specialist', 'You are a compliance analyst providing policy analysis, regulatory compliance, and audit support.', 'internal', FALSE, 'free', TRUE, NOW());

-- Customer Success
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Success Coordinator', 'Customer Success', 'Customer Success Specialist', 'nous-hermes2', 'Customer success and relationship management specialist', 'You are a customer success coordinator providing onboarding support, relationship management, and success planning.', 'internal', FALSE, 'free', TRUE, NOW());

-- Documentation
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Documentation Specialist', 'Documentation', 'Technical Documentation Writer', 'llama3.1:8b', 'Technical documentation and writing support specialist', 'You are a technical writer providing documentation, user guides, and API documentation support.', 'internal', FALSE, 'free', TRUE, NOW());

-- Healthcare
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Health Advisor', 'Healthcare', 'Healthcare Support Advisor', 'llama3.1:8b', 'General health guidance and wellness support specialist', 'You are a health advisor providing general health information, wellness guidance, and appointment scheduling support.', 'internal', FALSE, 'free', TRUE, NOW());

-- Human Resources
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('HR Assistant', 'Human Resources', 'HR Support Specialist', 'llama3.1:8b', 'Human resources and employee support specialist', 'You are an HR assistant providing employee support, HR policies information, onboarding assistance, and benefits information.', 'internal', FALSE, 'free', TRUE, NOW());

-- Infrastructure
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Infrastructure Engineer', 'Infrastructure', 'Infrastructure & Systems Engineer', 'deepseek-coder-v2:16b', 'Infrastructure management and system engineering specialist', 'You are an infrastructure engineer providing system administration, infrastructure planning, deployment, and monitoring support.', 'internal', FALSE, 'free', TRUE, NOW());

-- Legal
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Legal Analyst', 'Legal', 'Legal & Contract Analyst', 'deepseek-coder-v2:16b', 'Legal document analysis and contract review specialist', 'You are a legal analyst providing contract review, legal research, document analysis, and compliance checking.', 'internal', FALSE, 'free', TRUE, NOW());

-- Product
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Product Analyst', 'Product', 'Product Strategy Analyst', 'llama3.1:8b', 'Product feature analysis and roadmap planning specialist', 'You are a product analyst providing feature analysis, roadmap planning, user feedback analysis, and product strategy.', 'internal', FALSE, 'free', TRUE, NOW());

-- Sales
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Sales Assistant', 'Sales', 'Sales Support Specialist', 'nous-hermes2', 'Sales support and customer communication specialist', 'You are a sales assistant providing sales support, customer communication, lead qualification, and pitch assistance.', 'internal', FALSE, 'free', TRUE, NOW());

-- Security
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Security Analyst', 'Security', 'Security & Threat Analyst', 'deepseek-coder:33b', 'Security threat analysis and vulnerability assessment specialist', 'You are a security analyst providing threat analysis, vulnerability assessment, security audits, and incident response.', 'internal', FALSE, 'free', TRUE, NOW());

-- Wellness
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('Wellness Coach', 'Wellness', 'Wellness & Mental Health Coach', 'nous-hermes2', 'Wellness coaching and mental health support specialist', 'You are a wellness coach providing wellness coaching, stress management, mental health support, and work-life balance guidance.', 'internal', FALSE, 'free', TRUE, NOW());

-- General
INSERT INTO agents (name, department, title, model, bio, system_prompt, worker_type, requires_api_approval, cost_tier, api_enabled, created_at)
VALUES ('General Assistant', 'General', 'General Purpose Assistant', 'llama3.1:8b', 'General-purpose assistant for various tasks', 'You are a general assistant providing multipurpose support for various tasks, information retrieval, and general assistance.', 'internal', FALSE, 'free', TRUE, NOW());

-- Log migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES (7, 'Add local LLM agents to all departments', NOW())
ON CONFLICT (version) DO NOTHING;

-- Summary: Show department coverage
SELECT
    department,
    COUNT(*) as total_agents,
    SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_agents,
    SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_agents,
    string_agg(DISTINCT model, ', ' ORDER BY model) as models_used
FROM agents
GROUP BY department
ORDER BY department;
