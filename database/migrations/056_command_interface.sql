-- Migration 056: A.R.C.H.I.E. Command Interface Tables
-- Date: 2026-01-21
-- Purpose: Support unified command interface (Phase 56-60)

-- Command execution log - tracks every command processed
CREATE TABLE IF NOT EXISTS archie_command_log (
    id SERIAL PRIMARY KEY,
    conversation_id UUID,
    user_id INTEGER REFERENCES users(id),
    raw_input TEXT NOT NULL,
    parsed_intent JSONB,
    intent_type VARCHAR(50),
    confidence DECIMAL(5,4),
    routed_to VARCHAR(100),
    agent_used VARCHAR(100),
    station VARCHAR(50),
    escalated_to_contractor BOOLEAN DEFAULT FALSE,
    contractor_id INTEGER REFERENCES agents(id),
    execution_result JSONB,
    success BOOLEAN,
    error_message TEXT,
    duration_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    cost DECIMAL(10,6) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Active command sessions (for multi-step commands and workflows)
CREATE TABLE IF NOT EXISTS archie_command_sessions (
    id SERIAL PRIMARY KEY,
    session_id UUID DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id),
    session_type VARCHAR(50) DEFAULT 'conversation', -- conversation, workflow, team_discussion
    state JSONB DEFAULT '{}',
    context JSONB DEFAULT '{}', -- conversation context, preferences
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'active', -- active, paused, completed, failed
    workflow_id UUID, -- link to workflow_queue if applicable
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '24 hours')
);

-- Complexity assessment for escalation decisions
CREATE TABLE IF NOT EXISTS archie_complexity_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(100) NOT NULL,
    pattern_type VARCHAR(50) NOT NULL, -- keyword, regex, semantic
    pattern_value TEXT NOT NULL,
    complexity_score INTEGER DEFAULT 5, -- 1-10 scale
    requires_contractor BOOLEAN DEFAULT FALSE,
    recommended_model VARCHAR(100),
    description TEXT,
    usage_count INTEGER DEFAULT 0,
    success_rate DECIMAL(5,4) DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Pre-populate complexity patterns for Claude escalation
INSERT INTO archie_complexity_patterns (pattern_name, pattern_type, pattern_value, complexity_score, requires_contractor, description) VALUES
-- High complexity - Requires Claude
('architecture_design', 'keyword', 'design.*architecture|microservices|system design', 9, TRUE, 'System architecture design'),
('multi_file_refactor', 'keyword', 'refactor.*across|rename.*everywhere|update all', 8, TRUE, 'Multi-file refactoring'),
('security_review', 'keyword', 'security review|vulnerability|penetration|audit', 9, TRUE, 'Security analysis'),
('complex_debug', 'keyword', 'race condition|memory leak|deadlock|intermittent', 8, TRUE, 'Complex debugging'),
('novel_implementation', 'keyword', 'implement.*like|real-time collaboration|complex algorithm', 8, TRUE, 'Novel implementations'),
('explicit_claude', 'keyword', 'claude|need help|escalate|contractor', 10, TRUE, 'Explicit Claude request'),

-- Medium complexity - Try local first
('code_generation', 'keyword', 'write.*function|create.*class|implement', 5, FALSE, 'Code generation'),
('bug_fix', 'keyword', 'fix.*bug|error|not working|broken', 5, FALSE, 'Bug fixes'),
('documentation', 'keyword', 'document|readme|comment|explain', 4, FALSE, 'Documentation'),
('test_writing', 'keyword', 'write.*test|test case|unit test', 5, FALSE, 'Test writing'),

-- Low complexity - Always local
('simple_query', 'keyword', 'what is|how do|show me|list', 2, FALSE, 'Simple queries'),
('status_check', 'keyword', 'status|health|running|check', 2, FALSE, 'Status checks'),
('file_operation', 'keyword', 'read file|create file|edit|update', 3, FALSE, 'File operations'),
('team_operation', 'keyword', 'assign|move|schedule|roster', 3, FALSE, 'Team operations')
ON CONFLICT DO NOTHING;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_command_log_user ON archie_command_log(user_id);
CREATE INDEX IF NOT EXISTS idx_command_log_intent ON archie_command_log(intent_type);
CREATE INDEX IF NOT EXISTS idx_command_log_created ON archie_command_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_command_log_conversation ON archie_command_log(conversation_id);
CREATE INDEX IF NOT EXISTS idx_command_sessions_user ON archie_command_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_command_sessions_status ON archie_command_sessions(status);
-- Unique partial index for active sessions (required for ON CONFLICT)
CREATE UNIQUE INDEX IF NOT EXISTS idx_command_sessions_user_active
ON archie_command_sessions(user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_complexity_patterns_type ON archie_complexity_patterns(pattern_type);

-- View for command analytics
CREATE OR REPLACE VIEW v_command_analytics AS
SELECT
    DATE(created_at) as date,
    intent_type,
    COUNT(*) as total_commands,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN escalated_to_contractor THEN 1 ELSE 0 END) as escalated,
    AVG(duration_ms) as avg_duration_ms,
    SUM(tokens_used) as total_tokens,
    SUM(cost) as total_cost
FROM archie_command_log
GROUP BY DATE(created_at), intent_type;

-- View for escalation analysis
CREATE OR REPLACE VIEW v_escalation_analysis AS
SELECT
    intent_type,
    COUNT(*) as total,
    SUM(CASE WHEN escalated_to_contractor THEN 1 ELSE 0 END) as escalated,
    ROUND(100.0 * SUM(CASE WHEN escalated_to_contractor THEN 1 ELSE 0 END) / COUNT(*), 2) as escalation_rate,
    AVG(CASE WHEN NOT escalated_to_contractor THEN
        CASE WHEN success THEN 1.0 ELSE 0.0 END
    END) as local_success_rate,
    AVG(CASE WHEN escalated_to_contractor THEN
        CASE WHEN success THEN 1.0 ELSE 0.0 END
    END) as contractor_success_rate
FROM archie_command_log
GROUP BY intent_type;

-- Function to assess command complexity
CREATE OR REPLACE FUNCTION assess_command_complexity(input_text TEXT)
RETURNS TABLE (
    complexity_score INTEGER,
    requires_contractor BOOLEAN,
    matching_patterns TEXT[],
    recommended_action TEXT
) AS $$
DECLARE
    total_score INTEGER := 0;
    max_score INTEGER := 0;
    needs_contractor BOOLEAN := FALSE;
    patterns TEXT[] := ARRAY[]::TEXT[];
    pattern RECORD;
BEGIN
    FOR pattern IN
        SELECT p.pattern_name, p.pattern_value, p.complexity_score, p.requires_contractor
        FROM archie_complexity_patterns p
        WHERE p.pattern_type = 'keyword'
        AND input_text ~* p.pattern_value
    LOOP
        patterns := array_append(patterns, pattern.pattern_name);
        total_score := total_score + pattern.complexity_score;
        IF pattern.complexity_score > max_score THEN
            max_score := pattern.complexity_score;
        END IF;
        IF pattern.requires_contractor THEN
            needs_contractor := TRUE;
        END IF;
    END LOOP;

    -- Return results
    complexity_score := COALESCE(max_score, 3); -- Default medium
    requires_contractor := needs_contractor;
    matching_patterns := patterns;

    IF needs_contractor THEN
        recommended_action := 'escalate_to_contractor';
    ELSIF max_score >= 6 THEN
        recommended_action := 'use_powerful_local_model';
    ELSE
        recommended_action := 'use_fast_local_model';
    END IF;

    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON archie_command_log TO archie;
GRANT SELECT, INSERT, UPDATE, DELETE ON archie_command_sessions TO archie;
GRANT SELECT, UPDATE ON archie_complexity_patterns TO archie;
GRANT USAGE, SELECT ON SEQUENCE archie_command_log_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE archie_command_sessions_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE archie_complexity_patterns_id_seq TO archie;
GRANT SELECT ON v_command_analytics TO archie;
GRANT SELECT ON v_escalation_analysis TO archie;
