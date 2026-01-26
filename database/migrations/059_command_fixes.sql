-- Migration 059: Command Interface Fixes
-- Date: 2026-01-21
-- Purpose: Ensure all required functions exist for command interface

-- Ensure assess_command_complexity function exists
CREATE OR REPLACE FUNCTION assess_command_complexity(
    p_command TEXT,
    p_intent_type VARCHAR(50) DEFAULT NULL
) RETURNS TABLE (
    complexity_score INTEGER,
    requires_contractor BOOLEAN,
    suggested_model VARCHAR(50),
    reasoning TEXT
) AS $$
DECLARE
    v_score INTEGER := 5;
    v_contractor BOOLEAN := FALSE;
    v_model VARCHAR(50) := 'deepseek-coder:33b';
    v_reason TEXT := 'Standard complexity';
BEGIN
    -- Check for high-complexity patterns
    IF p_command ~* 'refactor|redesign|architecture|implement.*system|migrate|full.*rewrite' THEN
        v_score := 9;
        v_contractor := TRUE;
        v_model := 'claude-sonnet-4';
        v_reason := 'Major architectural change detected';
    ELSIF p_command ~* 'fix.*bug|debug|error|issue|problem|broken' THEN
        v_score := 6;
        v_model := 'deepseek-coder:33b';
        v_reason := 'Bug fix or debugging task';
    ELSIF p_command ~* 'create.*proposal|improvement|suggest' THEN
        v_score := 4;
        v_model := 'llama3.2:3b';
        v_reason := 'Proposal or suggestion task';
    ELSIF p_command ~* 'explain|what is|how does|tell me' THEN
        v_score := 2;
        v_model := 'llama3.2:3b';
        v_reason := 'Information or explanation query';
    END IF;

    -- Check intent type overrides
    IF p_intent_type = 'contractor_request' THEN
        v_contractor := TRUE;
        v_model := 'claude-sonnet-4';
        v_reason := 'Explicit contractor request';
    ELSIF p_intent_type = 'code_task' AND v_score >= 7 THEN
        v_contractor := TRUE;
    END IF;

    RETURN QUERY SELECT v_score, v_contractor, v_model, v_reason;
END;
$$ LANGUAGE plpgsql;

-- Command execution analytics view
CREATE OR REPLACE VIEW v_command_analytics AS
SELECT
    DATE(created_at) as date,
    intent_type,
    COUNT(*) as total_commands,
    COUNT(*) FILTER (WHERE success = TRUE) as successful,
    COUNT(*) FILTER (WHERE success = FALSE) as failed,
    ROUND(AVG(duration_ms)::numeric, 2) as avg_duration_ms,
    COUNT(*) FILTER (WHERE escalated_to_contractor = TRUE) as escalated,
    SUM(COALESCE(tokens_used, 0)) as total_tokens
FROM archie_command_log
GROUP BY DATE(created_at), intent_type
ORDER BY date DESC, total_commands DESC;

-- Escalation analysis view
CREATE OR REPLACE VIEW v_escalation_analysis AS
SELECT
    intent_type,
    COUNT(*) as total_commands,
    COUNT(*) FILTER (WHERE escalated_to_contractor = TRUE) as escalated_count,
    ROUND(
        (COUNT(*) FILTER (WHERE escalated_to_contractor = TRUE)::float / COUNT(*) * 100)::numeric,
        1
    ) as escalation_rate,
    ROUND(AVG(confidence)::numeric, 2) as avg_confidence,
    ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)::numeric, 2) as success_rate
FROM archie_command_log
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY intent_type
ORDER BY total_commands DESC;

-- Module usage tracking
CREATE TABLE IF NOT EXISTS module_usage_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    module_name VARCHAR(100) NOT NULL,
    action VARCHAR(100),
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    duration_ms INTEGER,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_module_usage_module ON module_usage_log(module_name);
CREATE INDEX IF NOT EXISTS idx_module_usage_created ON module_usage_log(created_at DESC);

-- Module health view
CREATE OR REPLACE VIEW v_module_health AS
SELECT
    module_name,
    COUNT(*) as total_calls,
    COUNT(*) FILTER (WHERE success = TRUE) as successful_calls,
    ROUND(
        (COUNT(*) FILTER (WHERE success = TRUE)::float / COUNT(*) * 100)::numeric,
        1
    ) as success_rate,
    ROUND(AVG(duration_ms)::numeric, 0) as avg_duration_ms,
    MAX(created_at) as last_used,
    COUNT(DISTINCT DATE(created_at)) as days_active
FROM module_usage_log
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY module_name
ORDER BY total_calls DESC;

-- Error pattern tracking for learning
CREATE TABLE IF NOT EXISTS command_error_patterns (
    id SERIAL PRIMARY KEY,
    error_pattern TEXT NOT NULL,
    error_count INTEGER DEFAULT 1,
    last_occurrence TIMESTAMP DEFAULT NOW(),
    suggested_fix TEXT,
    auto_retry BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(error_pattern)
);

-- Function to log module usage
CREATE OR REPLACE FUNCTION log_module_usage(
    p_user_id INTEGER,
    p_module_name VARCHAR(100),
    p_action VARCHAR(100),
    p_success BOOLEAN,
    p_error_message TEXT DEFAULT NULL,
    p_duration_ms INTEGER DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::JSONB
) RETURNS INTEGER AS $$
DECLARE
    v_log_id INTEGER;
BEGIN
    INSERT INTO module_usage_log (
        user_id, module_name, action, success, error_message, duration_ms, metadata
    ) VALUES (
        p_user_id, p_module_name, p_action, p_success, p_error_message, p_duration_ms, p_metadata
    )
    RETURNING id INTO v_log_id;

    -- Track error patterns
    IF NOT p_success AND p_error_message IS NOT NULL THEN
        INSERT INTO command_error_patterns (error_pattern, suggested_fix, metadata)
        VALUES (
            LEFT(p_error_message, 500),
            NULL,
            jsonb_build_object('module', p_module_name, 'action', p_action)
        )
        ON CONFLICT (error_pattern) DO UPDATE SET
            error_count = command_error_patterns.error_count + 1,
            last_occurrence = NOW();
    END IF;

    RETURN v_log_id;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON FUNCTION assess_command_complexity IS 'Assess command complexity and suggest model/contractor';
COMMENT ON TABLE module_usage_log IS 'Track module usage for analytics and debugging';
COMMENT ON TABLE command_error_patterns IS 'Track recurring error patterns for auto-learning';

SELECT 'Migration 059 completed - Command interface fixes applied' as status;
