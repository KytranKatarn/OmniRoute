-- Migration 084: Persistent collaboration sessions
-- Replaces in-memory session storage with DB-backed persistence
-- Sessions survive container restarts and are fully auditable

CREATE TABLE IF NOT EXISTS collaboration_sessions (
    id SERIAL PRIMARY KEY,
    session_uuid UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id),
    topic TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'paused', 'completed', 'stopped', 'error')),
    current_turn INTEGER DEFAULT 0,
    max_turns INTEGER DEFAULT 10,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS collaboration_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES collaboration_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'archie', 'claude', 'system')),
    content TEXT NOT NULL,
    turn INTEGER NOT NULL DEFAULT 0,
    model_used VARCHAR(100),
    tokens_used INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collab_sessions_user ON collaboration_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_collab_sessions_status ON collaboration_sessions(status);
CREATE INDEX IF NOT EXISTS idx_collab_sessions_created ON collaboration_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collab_messages_session ON collaboration_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_collab_messages_turn ON collaboration_messages(session_id, turn);

COMMENT ON TABLE collaboration_sessions IS 'DB-backed AI-to-AI collaboration sessions (ARCHIE + Claude)';
COMMENT ON TABLE collaboration_messages IS 'Individual messages within collaboration sessions';
