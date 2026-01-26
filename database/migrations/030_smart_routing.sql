-- Migration 030: Smart LLM Routing System
-- Date: 2026-01-19
-- Purpose: Add tables for intelligent model routing (Local → Sonnet → Opus)

-- =============================================================================
-- TASK ROUTING RULES TABLE
-- Defines which model tier to use for different task types
-- =============================================================================

CREATE TABLE IF NOT EXISTS task_routing_rules (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    complexity_threshold INTEGER DEFAULT 5,          -- 1-10 scale
    preferred_tier VARCHAR(20) NOT NULL,             -- 'local', 'haiku', 'sonnet', 'opus'
    fallback_tier VARCHAR(20),
    max_context_tokens INTEGER DEFAULT 8000,
    require_reset_on_escalate BOOLEAN DEFAULT TRUE,
    claude_as_judge BOOLEAN DEFAULT FALSE,
    judge_prompt TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed default routing rules
INSERT INTO task_routing_rules (task_type, description, complexity_threshold, preferred_tier, fallback_tier, claude_as_judge) VALUES
('format', 'Code formatting, linting, style fixes', 3, 'local', 'haiku', false),
('rewrite', 'Rewrite/refactor text or code', 4, 'local', 'sonnet', true),
('summarize', 'Summarize documents or code', 3, 'local', 'haiku', false),
('code_simple', 'Simple coding tasks, bug fixes', 5, 'sonnet', 'sonnet', false),
('code_complex', 'Complex multi-file coding', 7, 'sonnet', 'opus', false),
('refactor', 'Code refactoring', 6, 'sonnet', 'opus', false),
('architecture', 'System design, architecture decisions', 8, 'opus', 'opus', false),
('debug_simple', 'Simple debugging', 5, 'sonnet', 'sonnet', false),
('debug_hard', 'Complex debugging, race conditions', 8, 'opus', 'opus', false),
('review', 'Code review, PR review', 5, 'sonnet', 'sonnet', true),
('test_scaffold', 'Generate test scaffolding', 3, 'haiku', 'sonnet', false),
('documentation', 'Write documentation', 4, 'local', 'sonnet', true),
('sql', 'SQL queries and optimization', 5, 'sonnet', 'sonnet', false),
('api_design', 'API endpoint design', 6, 'sonnet', 'opus', false),
('security_audit', 'Security analysis', 7, 'opus', 'opus', false)
ON CONFLICT (task_type) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_task_routing_rules_type ON task_routing_rules(task_type);
CREATE INDEX IF NOT EXISTS idx_task_routing_rules_tier ON task_routing_rules(preferred_tier);
CREATE INDEX IF NOT EXISTS idx_task_routing_rules_active ON task_routing_rules(is_active) WHERE is_active = TRUE;

-- =============================================================================
-- TASK EXECUTIONS TABLE
-- Tracks every task execution with model tier, cost, and outcome
-- =============================================================================

CREATE TABLE IF NOT EXISTS task_executions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    task_type VARCHAR(100),
    task_description TEXT,

    -- Model selection
    initial_tier VARCHAR(20),
    model_tier_used VARCHAR(20),
    model_name VARCHAR(100),
    provider VARCHAR(50),

    -- Escalation tracking
    escalated BOOLEAN DEFAULT FALSE,
    escalation_count INTEGER DEFAULT 0,
    escalation_reason TEXT,
    failure_count INTEGER DEFAULT 0,

    -- Context management
    context_tokens INTEGER,
    was_reset_before BOOLEAN DEFAULT FALSE,

    -- Claude-as-Judge pattern
    claude_as_judge_used BOOLEAN DEFAULT FALSE,
    local_draft_tokens INTEGER,
    judge_tokens INTEGER,

    -- Cost tracking
    total_tokens INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost DECIMAL(10,6) DEFAULT 0,

    -- Outcome
    outcome VARCHAR(20) DEFAULT 'pending',  -- 'success', 'failed', 'escalated', 'pending'
    error_message TEXT,

    -- Timing
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_ms INTEGER,

    -- Metadata
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_task_executions_agent ON task_executions(agent_id);
CREATE INDEX IF NOT EXISTS idx_task_executions_tier ON task_executions(model_tier_used);
CREATE INDEX IF NOT EXISTS idx_task_executions_outcome ON task_executions(outcome);
CREATE INDEX IF NOT EXISTS idx_task_executions_started ON task_executions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_executions_type ON task_executions(task_type);
CREATE INDEX IF NOT EXISTS idx_task_executions_escalated ON task_executions(escalated) WHERE escalated = TRUE;

-- =============================================================================
-- ADD ROUTING COLUMNS TO AGENTS TABLE
-- =============================================================================

ALTER TABLE agents ADD COLUMN IF NOT EXISTS default_model_tier VARCHAR(20) DEFAULT 'sonnet';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_opus_percentage DECIMAL(3,2) DEFAULT 0.15;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS auto_escalate BOOLEAN DEFAULT TRUE;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS escalation_failure_threshold INTEGER DEFAULT 3;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS opus_usage_this_month DECIMAL(5,2) DEFAULT 0;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS total_tasks_this_month INTEGER DEFAULT 0;

-- =============================================================================
-- MODEL TIER DEFINITIONS TABLE
-- Maps tier names to actual model configurations
-- =============================================================================

CREATE TABLE IF NOT EXISTS model_tier_configs (
    id SERIAL PRIMARY KEY,
    tier_name VARCHAR(20) NOT NULL UNIQUE,
    display_name VARCHAR(50),
    provider VARCHAR(50) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    fallback_model VARCHAR(100),
    input_cost_per_1m DECIMAL(10,4) DEFAULT 0,
    output_cost_per_1m DECIMAL(10,4) DEFAULT 0,
    max_tokens INTEGER DEFAULT 4096,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 50,  -- Lower = tried first
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed model tier configurations
INSERT INTO model_tier_configs (tier_name, display_name, provider, model_name, input_cost_per_1m, output_cost_per_1m, priority) VALUES
('local', 'Local LLM (Ollama)', 'ollama', 'deepseek-coder-v2:16b', 0, 0, 10),
('haiku', 'Claude Haiku', 'claude', 'claude-3-haiku-20240307', 0.25, 1.25, 20),
('sonnet', 'Claude Sonnet', 'claude', 'claude-sonnet-4-20250514', 3.00, 15.00, 30),
('opus', 'Claude Opus', 'claude', 'claude-opus-4-20250514', 15.00, 75.00, 40)
ON CONFLICT (tier_name) DO UPDATE SET
    model_name = EXCLUDED.model_name,
    input_cost_per_1m = EXCLUDED.input_cost_per_1m,
    output_cost_per_1m = EXCLUDED.output_cost_per_1m;

-- =============================================================================
-- VIEWS FOR ANALYTICS
-- =============================================================================

-- Model usage summary by tier
CREATE OR REPLACE VIEW v_model_usage_summary AS
SELECT
    model_tier_used as tier,
    COUNT(*) as total_tasks,
    COUNT(*) FILTER (WHERE outcome = 'success') as successful_tasks,
    COUNT(*) FILTER (WHERE escalated = TRUE) as escalated_tasks,
    ROUND(AVG(cost)::numeric, 4) as avg_cost,
    SUM(cost) as total_cost,
    SUM(total_tokens) as total_tokens,
    ROUND(AVG(duration_ms)::numeric, 0) as avg_duration_ms
FROM task_executions
WHERE started_at >= NOW() - INTERVAL '30 days'
GROUP BY model_tier_used
ORDER BY total_tasks DESC;

-- Agent routing performance
CREATE OR REPLACE VIEW v_agent_routing_performance AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.default_model_tier,
    a.max_opus_percentage,
    COUNT(te.id) as total_tasks,
    COUNT(te.id) FILTER (WHERE te.model_tier_used = 'opus') as opus_tasks,
    CASE
        WHEN COUNT(te.id) > 0
        THEN ROUND((COUNT(te.id) FILTER (WHERE te.model_tier_used = 'opus')::numeric / COUNT(te.id) * 100), 2)
        ELSE 0
    END as opus_percentage,
    COUNT(te.id) FILTER (WHERE te.escalated = TRUE) as escalations,
    ROUND(AVG(te.cost)::numeric, 4) as avg_cost_per_task,
    SUM(te.cost) as total_cost_30d
FROM agents a
LEFT JOIN task_executions te ON a.id = te.agent_id
    AND te.started_at >= NOW() - INTERVAL '30 days'
GROUP BY a.id, a.name, a.default_model_tier, a.max_opus_percentage
ORDER BY total_tasks DESC;

-- Cost savings analysis
CREATE OR REPLACE VIEW v_routing_cost_savings AS
SELECT
    DATE_TRUNC('day', started_at) as date,
    COUNT(*) FILTER (WHERE model_tier_used = 'local') as local_tasks,
    COUNT(*) FILTER (WHERE claude_as_judge_used = TRUE) as judge_pattern_tasks,
    COUNT(*) FILTER (WHERE model_tier_used = 'opus') as opus_tasks,
    SUM(cost) as actual_cost,
    -- Estimate what it would have cost if all tasks used Opus
    SUM(total_tokens) * 0.000045 as estimated_opus_cost,  -- Rough estimate
    SUM(total_tokens) * 0.000045 - SUM(cost) as estimated_savings
FROM task_executions
WHERE started_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', started_at)
ORDER BY date DESC;

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Function to get recommended model for a task
CREATE OR REPLACE FUNCTION get_recommended_model(
    p_task_type VARCHAR(100),
    p_complexity INTEGER DEFAULT 5,
    p_agent_id INTEGER DEFAULT NULL,
    p_failure_count INTEGER DEFAULT 0
) RETURNS TABLE (
    tier VARCHAR(20),
    provider VARCHAR(50),
    model_name VARCHAR(100),
    should_escalate BOOLEAN,
    use_claude_as_judge BOOLEAN
) AS $$
DECLARE
    v_rule RECORD;
    v_agent RECORD;
    v_tier VARCHAR(20);
BEGIN
    -- Get routing rule for task type
    SELECT * INTO v_rule FROM task_routing_rules
    WHERE task_type = p_task_type AND is_active = TRUE;

    -- Default to sonnet if no rule found
    IF v_rule IS NULL THEN
        v_tier := 'sonnet';
    ELSE
        v_tier := v_rule.preferred_tier;

        -- Check if complexity exceeds threshold -> use fallback
        IF p_complexity > v_rule.complexity_threshold AND v_rule.fallback_tier IS NOT NULL THEN
            v_tier := v_rule.fallback_tier;
        END IF;
    END IF;

    -- Check if should escalate based on failures
    IF p_failure_count >= 3 AND v_tier != 'opus' THEN
        -- Escalate tier
        IF v_tier = 'local' THEN v_tier := 'sonnet';
        ELSIF v_tier = 'haiku' THEN v_tier := 'sonnet';
        ELSIF v_tier = 'sonnet' THEN v_tier := 'opus';
        END IF;
    END IF;

    -- Check agent's opus limit
    IF p_agent_id IS NOT NULL AND v_tier = 'opus' THEN
        SELECT * INTO v_agent FROM agents WHERE id = p_agent_id;
        IF v_agent.opus_usage_this_month >= v_agent.max_opus_percentage * 100 THEN
            v_tier := 'sonnet';  -- Downgrade if over limit
        END IF;
    END IF;

    -- Get model config for tier
    RETURN QUERY
    SELECT
        mtc.tier_name,
        mtc.provider,
        mtc.model_name,
        (p_failure_count >= 3) as should_escalate,
        COALESCE(v_rule.claude_as_judge, FALSE)
    FROM model_tier_configs mtc
    WHERE mtc.tier_name = v_tier AND mtc.is_active = TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to track task execution
CREATE OR REPLACE FUNCTION track_task_execution(
    p_agent_id INTEGER,
    p_task_type VARCHAR(100),
    p_tier VARCHAR(20),
    p_model VARCHAR(100),
    p_provider VARCHAR(50),
    p_outcome VARCHAR(20),
    p_tokens INTEGER,
    p_cost DECIMAL(10,6),
    p_escalated BOOLEAN DEFAULT FALSE
) RETURNS INTEGER AS $$
DECLARE
    v_execution_id INTEGER;
BEGIN
    -- Insert execution record
    INSERT INTO task_executions (
        agent_id, task_type, model_tier_used, model_name, provider,
        outcome, total_tokens, cost, escalated
    ) VALUES (
        p_agent_id, p_task_type, p_tier, p_model, p_provider,
        p_outcome, p_tokens, p_cost, p_escalated
    ) RETURNING id INTO v_execution_id;

    -- Update agent stats
    IF p_agent_id IS NOT NULL THEN
        UPDATE agents SET
            total_tasks_this_month = total_tasks_this_month + 1,
            opus_usage_this_month = CASE
                WHEN p_tier = 'opus'
                THEN opus_usage_this_month + 1
                ELSE opus_usage_this_month
            END
        WHERE id = p_agent_id;
    END IF;

    RETURN v_execution_id;
END;
$$ LANGUAGE plpgsql;

-- Reset monthly counters (call monthly via cron/scheduler)
CREATE OR REPLACE FUNCTION reset_monthly_routing_stats() RETURNS VOID AS $$
BEGIN
    UPDATE agents SET
        opus_usage_this_month = 0,
        total_tasks_this_month = 0;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- GRANTS
-- =============================================================================

GRANT SELECT, INSERT, UPDATE ON task_routing_rules TO archie;
GRANT SELECT, INSERT, UPDATE ON task_executions TO archie;
GRANT SELECT, INSERT, UPDATE ON model_tier_configs TO archie;
GRANT USAGE, SELECT ON SEQUENCE task_routing_rules_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE task_executions_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE model_tier_configs_id_seq TO archie;

-- Done
SELECT 'Migration 030: Smart LLM Routing System - COMPLETE' as status;
