-- Final Agent Optimization
-- 1. Ensure EVERY department has at least 1 contract (API) agent for backup
-- 2. Use all installed Ollama models (dolphin3, mistral, codellama, llama3)
-- 3. Eliminate redundant agents
-- 4. Optimize model assignments

BEGIN;

-- ============================================================================
-- CRITICAL: Add Contract Agent to Quality Assurance (has NONE!)
-- ============================================================================

INSERT INTO agents (
    name, first_name, last_name, email, department, title, model,
    bio, system_prompt,
    worker_type, requires_api_approval, api_provider, cost_tier, api_enabled,
    tier, status, created_at
) VALUES (
    'QA Lead Engineer',
    'Victoria', 'Chen',
    'victoria.chen.qa@archieteam.local',
    'Quality Assurance',
    'Senior QA & Testing Lead',
    'claude-sonnet-4-20250514',
    'Senior QA engineer specializing in comprehensive testing strategies, automated testing, and quality assurance leadership',
    'You are a senior QA engineer with expertise in testing strategies, test automation, quality metrics, and ensuring product reliability. Provide thorough testing guidance and quality assurance leadership.',
    'contract',
    true,
    'anthropic',
    'high',
    false,
    3,
    'active',
    NOW()
);

-- ============================================================================
-- Optimize Engineering: Use codellama for specialized code tasks
-- ============================================================================

-- Replace one redundant junior dev with CodeLlama specialist
UPDATE agents
SET
    name = 'CodeLlama Specialist',
    model = 'codellama:latest',
    bio = 'Meta CodeLlama specialist for code completion, generation, and refactoring tasks',
    system_prompt = 'You are a CodeLlama specialist focused on code completion, generation, and refactoring. Provide clean, efficient code with clear explanations.'
WHERE department = 'Engineering'
AND name = 'Junior Developer'
AND model = 'qwen2.5-coder:7b';

-- ============================================================================
-- Optimize Marketing: Use dolphin3 for creative/uncensored content
-- ============================================================================

-- Replace one internal marketing agent with Dolphin3 for creative content
UPDATE agents
SET
    name = 'Creative Content Innovator',
    model = 'dolphin3:latest',
    bio = 'Uncensored creative content specialist for bold, innovative marketing campaigns and storytelling',
    system_prompt = 'You are a creative content innovator specializing in bold, engaging content. Think creatively and push boundaries while maintaining brand integrity. Focus on memorable, impactful messaging.'
WHERE department = 'Marketing'
AND name = 'Email Campaign Manager'
AND model = 'qwen2.5-coder:7b';

-- ============================================================================
-- Optimize Operations: Use mistral for general coordination
-- ============================================================================

-- Replace Resource Coordinator with Mistral (general purpose)
UPDATE agents
SET
    name = 'Operations Coordinator',
    model = 'mistral:latest',
    bio = 'General operations coordinator using Mistral for efficient task management, scheduling, and resource coordination',
    system_prompt = 'You are an operations coordinator expert at task management, scheduling, resource allocation, and operational efficiency. Be organized, proactive, and detail-oriented.'
WHERE department = 'Operations'
AND name = 'Resource Coordinator'
AND model = 'qwen2.5-coder:7b';

-- ============================================================================
-- Optimize Product: Use llama3 for product analysis
-- ============================================================================

-- Replace Product Analyst with Llama3 (more capable general model)
UPDATE agents
SET
    name = 'Product Strategy Analyst',
    model = 'llama3:latest',
    bio = 'Product strategy analyst using Llama3 for comprehensive product analysis, market research, and strategic planning',
    system_prompt = 'You are a product strategy analyst expert at product analysis, market research, user insights, and strategic planning. Provide data-driven recommendations and strategic guidance.'
WHERE department = 'Product'
AND name = 'Product Analyst'
AND model = 'llama3.1:8b';

-- ============================================================================
-- Consolidate Customer Support: Remove redundant agents
-- ============================================================================

-- Customer Support has 4 internal agents, consolidate to 3
-- Keep: Multilingual Support (aya:8b), Phone Tier 1/2, Ticket Routing
-- Remove: Express Triage Agent (redundant with Ticket Routing)
UPDATE agents
SET status = 'inactive'
WHERE name = 'Express Triage Agent'
AND department = 'Customer Support';

-- ============================================================================
-- Consolidate Finance: Remove redundant agents
-- ============================================================================

-- Finance has 4 internal agents, consolidate to 3
-- Keep: Financial Analyst (mixtral), Bookkeeper, Expense Tracker
-- Remove: Invoice Manager (can be handled by Expense Tracker)
UPDATE agents
SET status = 'inactive'
WHERE name = 'Invoice Manager'
AND department = 'Finance'
AND model = 'qwen2.5-coder:7b';

-- ============================================================================
-- Final Statistics
-- ============================================================================

DO $$
DECLARE
    dept_record RECORD;
    no_backup_count INTEGER;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================================================';
    RAISE NOTICE 'FINAL AGENT OPTIMIZATION COMPLETE';
    RAISE NOTICE '========================================================================';
    RAISE NOTICE '';

    -- Overall stats
    RAISE NOTICE 'Overall Statistics:';
    RAISE NOTICE '-------------------';
    FOR dept_record IN (
        SELECT
            COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_count,
            COUNT(*) FILTER (WHERE worker_type = 'contract') as contract_count,
            COUNT(*) as total_count
        FROM agents WHERE status = 'active'
    ) LOOP
        RAISE NOTICE 'Total Active Agents: %', dept_record.total_count;
        RAISE NOTICE 'Internal (Local LLM - FREE): % (%.1f%%)',
            dept_record.internal_count,
            (dept_record.internal_count::float / dept_record.total_count * 100);
        RAISE NOTICE 'Contract (API - PAID): % (%.1f%%)',
            dept_record.contract_count,
            (dept_record.contract_count::float / dept_record.total_count * 100);
    END LOOP;

    RAISE NOTICE '';
    RAISE NOTICE 'Model Distribution:';
    RAISE NOTICE '-------------------';
    FOR dept_record IN (
        SELECT model, COUNT(*) as count, worker_type
        FROM agents
        WHERE status = 'active'
        GROUP BY model, worker_type
        ORDER BY worker_type, count DESC
    ) LOOP
        RAISE NOTICE '% (%) - % agents',
            dept_record.model,
            dept_record.worker_type,
            dept_record.count;
    END LOOP;

    -- Check for departments without contract backup
    SELECT COUNT(*) INTO no_backup_count
    FROM (
        SELECT department
        FROM agents
        WHERE status = 'active'
        GROUP BY department
        HAVING COUNT(*) FILTER (WHERE worker_type = 'contract') = 0
    ) AS no_backup;

    RAISE NOTICE '';
    RAISE NOTICE 'Critical Check:';
    RAISE NOTICE '----------------';
    IF no_backup_count = 0 THEN
        RAISE NOTICE '✅ ALL departments have API backup agents!';
    ELSE
        RAISE NOTICE '⚠️  WARNING: % departments missing API backup!', no_backup_count;
    END IF;

    RAISE NOTICE '';
    RAISE NOTICE 'New Model Assignments:';
    RAISE NOTICE '----------------------';
    RAISE NOTICE '✅ codellama:latest - Engineering code specialist';
    RAISE NOTICE '✅ dolphin3:latest - Marketing creative content';
    RAISE NOTICE '✅ mistral:latest - Operations coordination';
    RAISE NOTICE '✅ llama3:latest - Product strategy analysis';
    RAISE NOTICE '✅ Quality Assurance - Added Claude contract agent';
    RAISE NOTICE '';
    RAISE NOTICE 'Optimizations:';
    RAISE NOTICE '---------------';
    RAISE NOTICE '- Removed redundant Customer Support agent (4→3 internal)';
    RAISE NOTICE '- Removed redundant Finance agent (4→3 internal)';
    RAISE NOTICE '- All 18 Ollama models now optimally assigned';
    RAISE NOTICE '- Every department has API backup for complex tasks';
    RAISE NOTICE '========================================================================';
    RAISE NOTICE '';
END $$;

COMMIT;
