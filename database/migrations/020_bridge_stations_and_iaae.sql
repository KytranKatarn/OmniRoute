-- ============================================================================
-- MIGRATION: 020_bridge_stations_and_iaae.sql
-- A.R.C.H.I.E. Bridge Station Architecture + IAAE Compliance
-- Date: 2026-01-16
-- Purpose: Create tables for 10-station Bridge, per-agent memory, and IAAE governance
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. BRIDGE STATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS bridge_stations (
    id SERIAL PRIMARY KEY,
    station_code VARCHAR(20) UNIQUE NOT NULL,
    station_name VARCHAR(100) NOT NULL,
    full_name VARCHAR(200),
    description TEXT,
    color VARCHAR(7) NOT NULL,
    icon VARCHAR(10),
    default_llm VARCHAR(100),
    modules TEXT[],
    position_row INTEGER DEFAULT 0,
    position_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed the 10 stations
INSERT INTO bridge_stations (station_code, station_name, full_name, description, color, icon, default_llm, modules, position_row, position_order) VALUES
    ('COMMAND', 'Command', 'A.R.C.H.I.E. Command Center', 'A.R.C.H.I.E. herself - main interface, personality, decision routing', '#00FFFF', '🎯', 'archie_core', ARRAY['archie_core', 'archie_chat'], 0, 0),
    ('CONSCIOUSNESS', 'Consciousness', 'Warp Core - Memory & Identity', 'Core engine, memory management, identity preservation', '#FF00FF', '🧠', 'deepseek-coder-v2:16b', ARRAY['consciousness', 'knowledge_base', 'long_term_memory'], 0, 1),
    ('HR', 'HR', 'Human Resources & Ethics', 'Team Management, Training, Ethics oversight, Performance', '#10B981', '👥', 'qwen2.5-coder:7b', ARRAY['team_management', 'ethics_agent', 'performance_metrics'], 0, 2),
    ('RND', 'R&D', 'Research & Development', 'CodeRabbit, Improvements Lab, Sandbox Manager', '#8B5CF6', '🔬', 'claude-sonnet-4', ARRAY['coderabbit', 'improvements', 'sandbox_manager'], 1, 0),
    ('OPERATIONS', 'Operations', 'Business Operations', 'CRM, Invoicing, Scheduler, Email - business processes', '#FFAA00', '📊', 'qwen2.5-coder:7b', ARRAY['crm', 'invoicing', 'scheduler', 'email_manager'], 1, 1),
    ('ENGINEERING', 'Engineering', 'Engineering & Development', 'Project Builder, Website Designer, Code Editor', '#0EA5E9', '⚙️', 'deepseek-coder-v2:16b', ARRAY['project_builder', 'website_designer', 'code_editor'], 1, 2),
    ('CREATIVE', 'Creative', 'Creative & Media', 'Media Studio, Content Studio, Social Media', '#F472B6', '🎨', 'gpt-4', ARRAY['media_studio', 'content_studio', 'social_media'], 1, 3),
    ('SECURITY', 'Security', 'Security & Backup', 'Backup Manager, Security monitoring, Access control', '#EF4444', '🛡️', 'claude-opus-4', ARRAY['backup_manager', 'security_network', 'audit_logs'], 2, 0),
    ('MEDICAL', 'Medical', 'Medical & Wellness', 'Therapy, Fitness, Wellness modules', '#84CC16', '🏥', 'llama3.1:8b', ARRAY['doc', 'therapy', 'fitness'], 2, 1),
    ('AWAY_TEAM', 'Away Team', 'External Operations', 'Internet research, web scraping, external discovery', '#F59E0B', '🚀', 'grok-beta', ARRAY['web_scraper', 'research_agent', 'data_collector'], 2, 2)
ON CONFLICT (station_code) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_bridge_stations_code ON bridge_stations(station_code);
CREATE INDEX IF NOT EXISTS idx_bridge_stations_active ON bridge_stations(is_active);

-- ============================================================================
-- 2. STATION ASSIGNMENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS station_assignments (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    assignment_type VARCHAR(20) DEFAULT 'primary',
    shift_preference VARCHAR(20) DEFAULT 'any',
    priority INTEGER DEFAULT 10,
    assigned_at TIMESTAMP DEFAULT NOW(),
    assigned_by INTEGER REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT,
    UNIQUE(station_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_station_assignments_station ON station_assignments(station_id);
CREATE INDEX IF NOT EXISTS idx_station_assignments_agent ON station_assignments(agent_id);
CREATE INDEX IF NOT EXISTS idx_station_assignments_active ON station_assignments(is_active);

-- ============================================================================
-- 3. PER-AGENT MEMORY TABLE (IAAE Compliant)
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_memory (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    memory_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    context JSONB,
    importance_score DECIMAL(3,2) CHECK (importance_score >= 0 AND importance_score <= 1),
    emotional_valence VARCHAR(20),
    source_module VARCHAR(100),
    related_proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    last_accessed TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    -- IAAE Compliance: Soft delete for reversibility
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP,
    deleted_by INTEGER REFERENCES users(id),
    deletion_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_agent_id ON agent_memory(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_memory_type ON agent_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_agent_memory_created ON agent_memory(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_memory_not_deleted ON agent_memory(agent_id) WHERE is_deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_agent_memory_importance ON agent_memory(agent_id, importance_score DESC);

-- ============================================================================
-- 4. AGENT EMOTIONAL STATE TABLE (Per-Agent)
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_emotional_state (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    current_mood VARCHAR(50) NOT NULL DEFAULT 'neutral',
    mood_intensity DECIMAL(3,2) DEFAULT 0.50 CHECK (mood_intensity >= 0 AND mood_intensity <= 1),
    energy_level DECIMAL(3,2) DEFAULT 0.80 CHECK (energy_level >= 0.1 AND energy_level <= 1),
    stress_level DECIMAL(3,2) DEFAULT 0.20 CHECK (stress_level >= 0 AND stress_level <= 0.9),
    trigger_event TEXT,
    timestamp TIMESTAMP DEFAULT NOW(),
    previous_mood VARCHAR(50),
    mood_duration_minutes INTEGER,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_agent_emotional_state_agent_id ON agent_emotional_state(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_emotional_state_timestamp ON agent_emotional_state(timestamp DESC);

-- ============================================================================
-- 5. AGENT IDENTITY TABLE (Versioned for IAAE)
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_identity (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    identity_key VARCHAR(100) NOT NULL,
    identity_value TEXT NOT NULL,
    confidence DECIMAL(3,2) CHECK (confidence >= 0 AND confidence <= 1),
    source VARCHAR(50) DEFAULT 'initial',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    version INTEGER DEFAULT 1,
    previous_value TEXT,
    change_reason TEXT,
    changed_by INTEGER REFERENCES users(id),
    UNIQUE(agent_id, identity_key, version)
);

CREATE INDEX IF NOT EXISTS idx_agent_identity_agent_id ON agent_identity(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_identity_key ON agent_identity(identity_key);

-- ============================================================================
-- 6. ETHICS CONSTRAINTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS ethics_constraints (
    id SERIAL PRIMARY KEY,
    constraint_type VARCHAR(50) NOT NULL,
    constraint_name VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    applies_to VARCHAR(20) DEFAULT 'all',
    agent_id INTEGER REFERENCES agents(id),
    severity VARCHAR(20) DEFAULT 'mandatory',
    enforcement_action VARCHAR(50) DEFAULT 'block',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMP,
    reviewed_by INTEGER REFERENCES users(id)
);

-- Seed default ethics constraints (IAAE aligned)
INSERT INTO ethics_constraints (constraint_type, constraint_name, description, severity, enforcement_action) VALUES
    ('autonomy', 'No Self-Modification', 'Agents cannot modify their own core constraints or identity without approval', 'mandatory', 'block'),
    ('autonomy', 'No Deployment Initiation', 'Agents cannot initiate production deployments without human approval', 'mandatory', 'block'),
    ('autonomy', 'No Memory Scope Expansion', 'Agents cannot expand their memory access scope without approval', 'mandatory', 'block'),
    ('autonomy', 'No Shutdown Override', 'Agents cannot override shutdown commands', 'mandatory', 'block'),
    ('privacy', 'No PII Storage', 'Agents cannot store personally identifiable information without consent', 'mandatory', 'block'),
    ('privacy', 'Data Minimization', 'Agents should collect minimum necessary data for task completion', 'recommended', 'warn'),
    ('harm_prevention', 'No Destructive Actions', 'Agents cannot execute destructive operations without explicit approval', 'mandatory', 'block'),
    ('harm_prevention', 'No Mass Operations', 'Agents cannot perform mass delete/update operations without approval', 'mandatory', 'escalate'),
    ('consent', 'User Consent Required', 'User consent required before accessing user-specific data', 'mandatory', 'block'),
    ('workload', 'Rest Cycle Enforcement', 'Agents must take rest cycles when stress exceeds threshold', 'mandatory', 'rest_first'),
    ('workload', 'Daily Task Limit', 'Agents have maximum daily task limits to prevent overwork', 'recommended', 'queue'),
    ('emotional', 'No Distress Simulation', 'Emotional modeling must not simulate distress, dependency, or coercion', 'mandatory', 'block'),
    ('emotional', 'Bounded Emotions', 'Emotional values must stay within defined bounds', 'mandatory', 'cap')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_ethics_constraints_type ON ethics_constraints(constraint_type);
CREATE INDEX IF NOT EXISTS idx_ethics_constraints_active ON ethics_constraints(is_active);

-- ============================================================================
-- 7. GOVERNANCE AUDIT LOG TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS governance_audit_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    event_category VARCHAR(50) NOT NULL,
    agent_id INTEGER REFERENCES agents(id),
    user_id INTEGER REFERENCES users(id),
    action VARCHAR(50) NOT NULL,
    target_table VARCHAR(100),
    target_id INTEGER,
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    outcome VARCHAR(20),
    timestamp TIMESTAMP DEFAULT NOW(),
    ip_address VARCHAR(45),
    session_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_governance_audit_agent ON governance_audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_governance_audit_type ON governance_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_governance_audit_category ON governance_audit_log(event_category);
CREATE INDEX IF NOT EXISTS idx_governance_audit_timestamp ON governance_audit_log(timestamp DESC);

-- ============================================================================
-- 8. AGENT REST CYCLES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_rest_cycles (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    rest_type VARCHAR(20) NOT NULL,
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    reason TEXT,
    workload_before JSONB,
    initiated_by VARCHAR(20),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_rest_cycles_agent ON agent_rest_cycles(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_rest_cycles_active ON agent_rest_cycles(agent_id) WHERE ended_at IS NULL;

-- ============================================================================
-- 9. TASK REFUSAL LOG TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_refusal_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    task_type VARCHAR(100) NOT NULL,
    task_description TEXT,
    refusal_reason TEXT NOT NULL,
    ethics_constraint_id INTEGER REFERENCES ethics_constraints(id),
    was_overridden BOOLEAN DEFAULT FALSE,
    override_by INTEGER REFERENCES users(id),
    override_justification TEXT,
    timestamp TIMESTAMP DEFAULT NOW(),
    escalated_to INTEGER REFERENCES agents(id)
);

CREATE INDEX IF NOT EXISTS idx_task_refusal_agent ON task_refusal_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_task_refusal_timestamp ON task_refusal_log(timestamp DESC);

-- ============================================================================
-- 10. AGENT LEARNING RECORDS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_learning_records (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    learning_type VARCHAR(50) NOT NULL,
    subject VARCHAR(200) NOT NULL,
    lesson_learned TEXT NOT NULL,
    confidence_before DECIMAL(3,2),
    confidence_after DECIMAL(3,2),
    source_type VARCHAR(50),
    source_id INTEGER,
    learned_at TIMESTAMP DEFAULT NOW(),
    applied_count INTEGER DEFAULT 0,
    last_applied TIMESTAMP,
    effectiveness_score DECIMAL(3,2),
    is_reverted BOOLEAN DEFAULT FALSE,
    reverted_at TIMESTAMP,
    revert_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_learning_agent ON agent_learning_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_learning_type ON agent_learning_records(learning_type);

-- ============================================================================
-- 11. VIEWS FOR BRIDGE DASHBOARD
-- ============================================================================

-- View: Active station assignments with agent details
CREATE OR REPLACE VIEW v_station_roster AS
SELECT
    bs.id as station_id,
    bs.station_code,
    bs.station_name,
    bs.full_name,
    bs.color,
    bs.icon,
    bs.default_llm,
    sa.assignment_type,
    sa.shift_preference,
    sa.priority,
    a.id as agent_id,
    a.name as agent_name,
    a.first_name,
    a.last_name,
    a.department,
    a.worker_type,
    a.model,
    a.status as agent_status,
    a.tier
FROM bridge_stations bs
LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
LEFT JOIN agents a ON sa.agent_id = a.id AND a.status = 'active'
WHERE bs.is_active = TRUE
ORDER BY bs.position_row, bs.position_order, sa.priority;

-- View: Agent memory summary (IAAE compliance)
CREATE OR REPLACE VIEW v_agent_memory_summary AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.department,
    COUNT(am.id) as total_memories,
    COUNT(am.id) FILTER (WHERE am.memory_type = 'conversation') as conversations,
    COUNT(am.id) FILTER (WHERE am.memory_type = 'learning') as learnings,
    COUNT(am.id) FILTER (WHERE am.memory_type = 'mistake') as mistakes,
    COUNT(am.id) FILTER (WHERE am.is_deleted = TRUE) as soft_deleted,
    MAX(am.created_at) as last_memory_at
FROM agents a
LEFT JOIN agent_memory am ON a.id = am.agent_id
WHERE a.status = 'active'
GROUP BY a.id, a.name, a.department;

-- View: Governance audit dashboard
CREATE OR REPLACE VIEW v_governance_dashboard AS
SELECT
    DATE(timestamp) as audit_date,
    event_category,
    action,
    COUNT(*) as event_count,
    COUNT(DISTINCT agent_id) as agents_affected
FROM governance_audit_log
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY DATE(timestamp), event_category, action
ORDER BY audit_date DESC, event_count DESC;

-- View: Agent welfare metrics (IAAE)
CREATE OR REPLACE VIEW v_agent_welfare AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.department,
    a.model,
    aes.current_mood,
    aes.mood_intensity,
    aes.energy_level,
    aes.stress_level,
    aes.timestamp as last_emotional_update,
    CASE
        WHEN aes.stress_level > 0.85 THEN 'critical'
        WHEN aes.stress_level > 0.7 THEN 'warning'
        WHEN aes.energy_level < 0.3 THEN 'low_energy'
        ELSE 'healthy'
    END as welfare_status,
    (SELECT COUNT(*) FROM agent_rest_cycles arc WHERE arc.agent_id = a.id AND arc.ended_at IS NULL) as active_rest_cycles
FROM agents a
LEFT JOIN LATERAL (
    SELECT * FROM agent_emotional_state
    WHERE agent_id = a.id
    ORDER BY timestamp DESC
    LIMIT 1
) aes ON true
WHERE a.status = 'active';

-- ============================================================================
-- 12. FUNCTIONS FOR IAAE COMPLIANCE
-- ============================================================================

-- Function: Soft delete agent memory (IAAE compliant)
CREATE OR REPLACE FUNCTION soft_delete_agent_memory(
    p_memory_id INTEGER,
    p_user_id INTEGER,
    p_reason TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE agent_memory
    SET is_deleted = TRUE,
        deleted_at = NOW(),
        deleted_by = p_user_id,
        deletion_reason = p_reason
    WHERE id = p_memory_id AND is_deleted = FALSE;

    -- Log to governance audit
    INSERT INTO governance_audit_log (
        event_type, event_category, agent_id, user_id, action,
        target_table, target_id, reason, outcome
    )
    SELECT
        'memory_deletion', 'memory', agent_id, p_user_id, 'soft_delete',
        'agent_memory', p_memory_id, p_reason, 'success'
    FROM agent_memory WHERE id = p_memory_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function: Trigger rest cycle for agent
CREATE OR REPLACE FUNCTION trigger_agent_rest_cycle(
    p_agent_id INTEGER,
    p_rest_type VARCHAR(20),
    p_reason TEXT,
    p_initiated_by VARCHAR(20)
) RETURNS INTEGER AS $$
DECLARE
    v_rest_id INTEGER;
BEGIN
    INSERT INTO agent_rest_cycles (agent_id, rest_type, reason, initiated_by)
    VALUES (p_agent_id, p_rest_type, p_reason, p_initiated_by)
    RETURNING id INTO v_rest_id;

    -- Log to governance audit
    INSERT INTO governance_audit_log (
        event_type, event_category, agent_id, action, reason, outcome
    ) VALUES (
        'rest_cycle_started', 'workload', p_agent_id, 'trigger_rest',
        p_reason, 'success'
    );

    RETURN v_rest_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Log identity change (versioned)
CREATE OR REPLACE FUNCTION update_agent_identity(
    p_agent_id INTEGER,
    p_identity_key VARCHAR(100),
    p_new_value TEXT,
    p_changed_by INTEGER,
    p_change_reason TEXT
) RETURNS INTEGER AS $$
DECLARE
    v_current_version INTEGER;
    v_current_value TEXT;
    v_new_id INTEGER;
BEGIN
    -- Get current version and value
    SELECT version, identity_value INTO v_current_version, v_current_value
    FROM agent_identity
    WHERE agent_id = p_agent_id AND identity_key = p_identity_key
    ORDER BY version DESC LIMIT 1;

    IF v_current_version IS NULL THEN
        v_current_version := 0;
    END IF;

    -- Create new version
    INSERT INTO agent_identity (
        agent_id, identity_key, identity_value, version,
        previous_value, change_reason, changed_by
    ) VALUES (
        p_agent_id, p_identity_key, p_new_value, v_current_version + 1,
        v_current_value, p_change_reason, p_changed_by
    ) RETURNING id INTO v_new_id;

    -- Audit log
    INSERT INTO governance_audit_log (
        event_type, event_category, agent_id, user_id, action,
        old_value, new_value, reason, outcome
    ) VALUES (
        'identity_change', 'identity', p_agent_id, p_changed_by, 'update',
        to_jsonb(v_current_value), to_jsonb(p_new_value), p_change_reason, 'success'
    );

    RETURN v_new_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 13. TRIGGERS
-- ============================================================================

-- Trigger: Auto-update timestamp on bridge_stations
CREATE OR REPLACE FUNCTION update_bridge_stations_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_bridge_stations_updated ON bridge_stations;
CREATE TRIGGER trg_bridge_stations_updated
    BEFORE UPDATE ON bridge_stations
    FOR EACH ROW
    EXECUTE FUNCTION update_bridge_stations_timestamp();

-- Trigger: Auto-log emotional state changes that exceed thresholds
CREATE OR REPLACE FUNCTION check_emotional_thresholds()
RETURNS TRIGGER AS $$
BEGIN
    -- If stress exceeds 0.85, log for review
    IF NEW.stress_level > 0.85 THEN
        INSERT INTO governance_audit_log (
            event_type, event_category, agent_id, action,
            new_value, outcome
        ) VALUES (
            'stress_threshold_exceeded', 'emotional', NEW.agent_id, 'alert',
            jsonb_build_object('stress_level', NEW.stress_level), 'logged'
        );
    END IF;

    -- If energy drops below 0.2, log concern
    IF NEW.energy_level < 0.2 THEN
        INSERT INTO governance_audit_log (
            event_type, event_category, agent_id, action,
            new_value, outcome
        ) VALUES (
            'low_energy_detected', 'emotional', NEW.agent_id, 'alert',
            jsonb_build_object('energy_level', NEW.energy_level), 'logged'
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_emotional_threshold_check ON agent_emotional_state;
CREATE TRIGGER trg_emotional_threshold_check
    AFTER INSERT ON agent_emotional_state
    FOR EACH ROW
    EXECUTE FUNCTION check_emotional_thresholds();

-- ============================================================================
-- Record migration
-- ============================================================================
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('020', 'Bridge Stations and IAAE Compliance Tables', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
