-- Migration 083: Orchestration Engine tables
-- Supports the AI orchestration system where ARCHIE routes, delegates, and tracks work

CREATE TABLE IF NOT EXISTS orchestration_sessions (
    id SERIAL PRIMARY KEY,
    session_id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id),
    conversation_id TEXT,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'completed', 'failed', 'cancelled')),
    total_steps INTEGER DEFAULT 0,
    total_duration_ms INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS orchestration_steps (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES orchestration_sessions(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_type VARCHAR(50) NOT NULL CHECK (step_type IN (
        'intent_parse', 'route_decision', 'agent_select',
        'iaae_check', 'welfare_check', 'gpu_check', 'execute', 'fallback'
    )),
    step_data JSONB NOT NULL DEFAULT '{}',
    agent_id INTEGER REFERENCES agents(id),
    model_used VARCHAR(100),
    duration_ms INTEGER DEFAULT 0,
    success BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_orch_sessions_user ON orchestration_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_orch_sessions_status ON orchestration_sessions(status);
CREATE INDEX IF NOT EXISTS idx_orch_sessions_created ON orchestration_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orch_steps_session ON orchestration_steps(session_id);
CREATE INDEX IF NOT EXISTS idx_orch_steps_type ON orchestration_steps(step_type);

COMMENT ON TABLE orchestration_sessions IS 'Tracks each orchestrated request through the AI pipeline';
COMMENT ON TABLE orchestration_steps IS 'Individual steps in each orchestration (intent, routing, agent selection, execution)';
