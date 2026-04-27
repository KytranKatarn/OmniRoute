-- Browser agent tables for archie_browser container (Sub-D #2352)
-- Run: docker exec -i archie_database psql -U archie -d archie < 169_browser_agent.sql

CREATE TABLE IF NOT EXISTS agent_browser_sessions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    platform VARCHAR(50) NOT NULL,
    username VARCHAR(255),
    password_encrypted TEXT,
    session_data_encrypted TEXT,
    session_expires_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'missing',
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agent_id, platform)
);

CREATE TABLE IF NOT EXISTS browser_task_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    skill VARCHAR(100) NOT NULL,
    platform VARCHAR(50),
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    error_message TEXT,
    screenshot_path TEXT,
    triggered_by VARCHAR(50),
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_browser_task_log_agent ON browser_task_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_browser_task_log_status ON browser_task_log(status);
CREATE INDEX IF NOT EXISTS idx_agent_browser_sessions_agent ON agent_browser_sessions(agent_id, platform);
