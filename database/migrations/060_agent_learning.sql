-- Migration 060: Agent Learning System
-- Date: 2026-01-21
-- Purpose: Enable agents to learn from Claude's work and track skill acquisition

-- Add learned_skills column to agents if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agents' AND column_name = 'learned_skills'
    ) THEN
        ALTER TABLE agents ADD COLUMN learned_skills JSONB DEFAULT '[]'::JSONB;
    END IF;
END $$;

-- Add learning_history column to agents if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agents' AND column_name = 'learning_history'
    ) THEN
        ALTER TABLE agents ADD COLUMN learning_history JSONB DEFAULT '[]'::JSONB;
    END IF;
END $$;

-- Agent learning log - tracks what agents learn from Claude
CREATE TABLE IF NOT EXISTS agent_learning_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    learned_from VARCHAR(50) DEFAULT 'claude',
    skill_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(50),
    knowledge_id INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL,
    confidence FLOAT DEFAULT 0.5,
    successful_uses INTEGER DEFAULT 0,
    failed_uses INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    context_summary TEXT,
    metadata JSONB DEFAULT '{}'::JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_learning_agent ON agent_learning_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_learning_skill ON agent_learning_log(skill_name);
CREATE INDEX IF NOT EXISTS idx_agent_learning_category ON agent_learning_log(skill_category);
CREATE INDEX IF NOT EXISTS idx_agent_learning_confidence ON agent_learning_log(confidence DESC);

-- Bridge interaction log - tracks ALL calls through archie_bridge
CREATE TABLE IF NOT EXISTS bridge_interaction_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    module_name VARCHAR(100),
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    intent_type VARCHAR(50),
    prompt_summary TEXT,
    response_summary TEXT,
    model_used VARCHAR(50),
    tokens_used INTEGER,
    cost_estimate DECIMAL(10, 6) DEFAULT 0,
    execution_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    escalated_to_claude BOOLEAN DEFAULT FALSE,
    tags TEXT[],
    learned_entry_id INTEGER,  -- Links to knowledge_base if learning occurred
    metadata JSONB DEFAULT '{}'::JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bridge_log_user ON bridge_interaction_log(user_id);
CREATE INDEX IF NOT EXISTS idx_bridge_log_module ON bridge_interaction_log(module_name);
CREATE INDEX IF NOT EXISTS idx_bridge_log_agent ON bridge_interaction_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_bridge_log_intent ON bridge_interaction_log(intent_type);
CREATE INDEX IF NOT EXISTS idx_bridge_log_created ON bridge_interaction_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bridge_log_escalated ON bridge_interaction_log(escalated_to_claude) WHERE escalated_to_claude = TRUE;

-- View: Agent skill summary
CREATE OR REPLACE VIEW v_agent_skills AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.role,
    a.department,
    COUNT(all.id) as total_skills_learned,
    COUNT(all.id) FILTER (WHERE all.confidence >= 0.8) as mastered_skills,
    COUNT(all.id) FILTER (WHERE all.confidence >= 0.5 AND all.confidence < 0.8) as developing_skills,
    COUNT(all.id) FILTER (WHERE all.confidence < 0.5) as learning_skills,
    COALESCE(SUM(all.successful_uses), 0) as total_successful_uses,
    ROUND(AVG(all.confidence)::numeric, 2) as avg_confidence,
    MAX(all.last_used_at) as last_skill_used
FROM agents a
LEFT JOIN agent_learning_log all ON a.id = all.agent_id
GROUP BY a.id, a.name, a.role, a.department;

-- View: Bridge learning analytics
CREATE OR REPLACE VIEW v_bridge_analytics AS
SELECT
    DATE(created_at) as date,
    module_name,
    intent_type,
    COUNT(*) as total_calls,
    COUNT(*) FILTER (WHERE success = TRUE) as successful_calls,
    COUNT(*) FILTER (WHERE escalated_to_claude = TRUE) as claude_escalations,
    ROUND(AVG(execution_time_ms)::numeric, 0) as avg_execution_ms,
    SUM(COALESCE(tokens_used, 0)) as total_tokens,
    SUM(COALESCE(cost_estimate, 0)) as total_cost,
    COUNT(DISTINCT agent_id) as agents_involved,
    COUNT(learned_entry_id) as learnings_created
FROM bridge_interaction_log
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at), module_name, intent_type
ORDER BY date DESC, total_calls DESC;

-- View: Claude escalation patterns (to reduce over time)
CREATE OR REPLACE VIEW v_escalation_patterns AS
SELECT
    intent_type,
    module_name,
    COUNT(*) as total_escalations,
    ROUND(AVG(execution_time_ms)::numeric, 0) as avg_execution_ms,
    SUM(COALESCE(cost_estimate, 0)) as total_cost,
    array_agg(DISTINCT skill_category) FILTER (WHERE skill_category IS NOT NULL) as related_skills
FROM bridge_interaction_log bil
LEFT JOIN agent_learning_log all ON bil.agent_id = all.agent_id
WHERE bil.escalated_to_claude = TRUE
  AND bil.created_at > NOW() - INTERVAL '30 days'
GROUP BY intent_type, module_name
ORDER BY total_escalations DESC;

-- Function: Log agent learning from Claude interaction
CREATE OR REPLACE FUNCTION log_agent_learning(
    p_agent_id INTEGER,
    p_skill_name VARCHAR(100),
    p_skill_category VARCHAR(50),
    p_knowledge_id INTEGER DEFAULT NULL,
    p_context_summary TEXT DEFAULT NULL,
    p_learned_from VARCHAR(50) DEFAULT 'claude',
    p_initial_confidence FLOAT DEFAULT 0.5,
    p_metadata JSONB DEFAULT '{}'::JSONB
) RETURNS INTEGER AS $$
DECLARE
    v_log_id INTEGER;
    v_existing_id INTEGER;
BEGIN
    -- Check if agent already has this skill
    SELECT id INTO v_existing_id
    FROM agent_learning_log
    WHERE agent_id = p_agent_id AND skill_name = p_skill_name;

    IF v_existing_id IS NOT NULL THEN
        -- Update existing skill with increased confidence
        UPDATE agent_learning_log
        SET confidence = LEAST(confidence + 0.1, 1.0),
            successful_uses = successful_uses + 1,
            last_used_at = NOW(),
            metadata = metadata || p_metadata
        WHERE id = v_existing_id
        RETURNING id INTO v_log_id;
    ELSE
        -- Create new skill entry
        INSERT INTO agent_learning_log (
            agent_id, learned_from, skill_name, skill_category,
            knowledge_id, confidence, context_summary, metadata
        ) VALUES (
            p_agent_id, p_learned_from, p_skill_name, p_skill_category,
            p_knowledge_id, p_initial_confidence, p_context_summary, p_metadata
        )
        RETURNING id INTO v_log_id;

        -- Update agent's learned_skills array
        UPDATE agents
        SET learned_skills = COALESCE(learned_skills, '[]'::JSONB) ||
            jsonb_build_object(
                'skill', p_skill_name,
                'category', p_skill_category,
                'learned_at', NOW(),
                'from', p_learned_from
            )
        WHERE id = p_agent_id;
    END IF;

    RETURN v_log_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Log bridge interaction with auto-learning
CREATE OR REPLACE FUNCTION log_bridge_interaction(
    p_user_id INTEGER,
    p_module_name VARCHAR(100),
    p_agent_id INTEGER DEFAULT NULL,
    p_intent_type VARCHAR(50) DEFAULT NULL,
    p_prompt_summary TEXT DEFAULT NULL,
    p_response_summary TEXT DEFAULT NULL,
    p_model_used VARCHAR(50) DEFAULT NULL,
    p_tokens_used INTEGER DEFAULT 0,
    p_cost_estimate DECIMAL(10, 6) DEFAULT 0,
    p_execution_time_ms INTEGER DEFAULT NULL,
    p_success BOOLEAN DEFAULT TRUE,
    p_error_message TEXT DEFAULT NULL,
    p_escalated_to_claude BOOLEAN DEFAULT FALSE,
    p_tags TEXT[] DEFAULT '{}',
    p_metadata JSONB DEFAULT '{}'::JSONB
) RETURNS INTEGER AS $$
DECLARE
    v_log_id INTEGER;
BEGIN
    INSERT INTO bridge_interaction_log (
        user_id, module_name, agent_id, intent_type,
        prompt_summary, response_summary, model_used,
        tokens_used, cost_estimate, execution_time_ms,
        success, error_message, escalated_to_claude,
        tags, metadata
    ) VALUES (
        p_user_id, p_module_name, p_agent_id, p_intent_type,
        p_prompt_summary, p_response_summary, p_model_used,
        p_tokens_used, p_cost_estimate, p_execution_time_ms,
        p_success, p_error_message, p_escalated_to_claude,
        p_tags, p_metadata
    )
    RETURNING id INTO v_log_id;

    -- Auto-update user session time
    IF p_user_id IS NOT NULL THEN
        PERFORM update_user_session_time(p_user_id);
    END IF;

    RETURN v_log_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Update agent skill confidence based on usage
CREATE OR REPLACE FUNCTION update_skill_confidence(
    p_agent_id INTEGER,
    p_skill_name VARCHAR(100),
    p_success BOOLEAN
) RETURNS VOID AS $$
BEGIN
    IF p_success THEN
        UPDATE agent_learning_log
        SET confidence = LEAST(confidence + 0.05, 1.0),
            successful_uses = successful_uses + 1,
            last_used_at = NOW()
        WHERE agent_id = p_agent_id AND skill_name = p_skill_name;
    ELSE
        UPDATE agent_learning_log
        SET confidence = GREATEST(confidence - 0.1, 0.0),
            failed_uses = failed_uses + 1,
            last_used_at = NOW()
        WHERE agent_id = p_agent_id AND skill_name = p_skill_name;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function: Get best agent for a skill
CREATE OR REPLACE FUNCTION get_best_agent_for_skill(
    p_skill_name VARCHAR(100),
    p_min_confidence FLOAT DEFAULT 0.6
) RETURNS TABLE (
    agent_id INTEGER,
    agent_name VARCHAR,
    confidence FLOAT,
    successful_uses INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        all.agent_id,
        a.name as agent_name,
        all.confidence,
        all.successful_uses
    FROM agent_learning_log all
    JOIN agents a ON all.agent_id = a.id
    WHERE all.skill_name ILIKE '%' || p_skill_name || '%'
      AND all.confidence >= p_min_confidence
      AND a.is_active = TRUE
    ORDER BY all.confidence DESC, all.successful_uses DESC
    LIMIT 5;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE agent_learning_log IS 'Tracks skills learned by agents from Claude interactions';
COMMENT ON TABLE bridge_interaction_log IS 'Comprehensive log of all archie_bridge calls';
COMMENT ON FUNCTION log_agent_learning IS 'Log a new skill learned by an agent';
COMMENT ON FUNCTION log_bridge_interaction IS 'Log a bridge interaction with auto-learning';
COMMENT ON FUNCTION get_best_agent_for_skill IS 'Find the most qualified agent for a specific skill';

SELECT 'Migration 060 completed - Agent learning system ready' as status;
