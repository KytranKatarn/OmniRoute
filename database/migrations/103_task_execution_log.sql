-- ============================================================================
-- MIGRATION: 103_task_execution_log.sql
-- Project #91: Team Management Redesign — BridgeDispatcher HR Tracking
-- Date: 2026-02-17
-- Purpose: Create task_execution_log for tracking all AI work dispatched through BridgeDispatcher
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS task_execution_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    agent_name VARCHAR(100),
    module_id VARCHAR(100),
    capability VARCHAR(50) NOT NULL,
    model_used VARCHAR(100) NOT NULL,
    provider VARCHAR(50) DEFAULT 'ollama',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    station_code VARCHAR(20),
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    priority VARCHAR(20) DEFAULT 'normal',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tel_agent_id ON task_execution_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_tel_module_id ON task_execution_log(module_id);
CREATE INDEX IF NOT EXISTS idx_tel_created_at ON task_execution_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tel_capability ON task_execution_log(capability);
CREATE INDEX IF NOT EXISTS idx_tel_agent_date ON task_execution_log(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tel_success ON task_execution_log(success) WHERE success = FALSE;

-- View: Agent work summary (for HR dashboard)
CREATE OR REPLACE VIEW v_agent_work_summary AS
SELECT
    a.id AS agent_id,
    a.name AS agent_name,
    a.model AS default_model,
    bs.station_code,
    COUNT(tel.id) AS total_tasks,
    COUNT(tel.id) FILTER (WHERE tel.success = TRUE) AS successful_tasks,
    COUNT(tel.id) FILTER (WHERE tel.success = FALSE) AS failed_tasks,
    COALESCE(SUM(tel.duration_ms), 0) AS total_duration_ms,
    COALESCE(AVG(tel.duration_ms), 0)::INTEGER AS avg_duration_ms,
    COALESCE(SUM(tel.prompt_tokens + tel.completion_tokens), 0) AS total_tokens,
    MAX(tel.created_at) AS last_active
FROM agents a
LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
LEFT JOIN bridge_stations bs ON sa.station_id = bs.id
LEFT JOIN task_execution_log tel ON a.id = tel.agent_id
WHERE a.status = 'active'
GROUP BY a.id, a.name, a.model, bs.station_code;

-- View: Module dispatch summary (which agents serve which modules)
CREATE OR REPLACE VIEW v_module_dispatch_summary AS
SELECT
    tel.module_id,
    tel.agent_name,
    tel.capability,
    COUNT(*) AS task_count,
    COALESCE(AVG(tel.duration_ms), 0)::INTEGER AS avg_duration_ms,
    COUNT(*) FILTER (WHERE tel.success = TRUE)::FLOAT / NULLIF(COUNT(*), 0) AS success_rate,
    MAX(tel.created_at) AS last_dispatch
FROM task_execution_log tel
WHERE tel.created_at > NOW() - INTERVAL '24 hours'
GROUP BY tel.module_id, tel.agent_name, tel.capability;

COMMIT;
