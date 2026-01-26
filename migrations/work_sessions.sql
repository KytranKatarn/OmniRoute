-- Work Sessions - Active Context Tracking
-- A.R.C.H.I.E. Platform v5.24.0
-- Phase 65.1: Session Context System
-- Created: 2026-01-25

BEGIN;

-- ============================================================================
-- WORK SESSIONS TABLE
-- Tracks what's being actively worked on across Claude CLI and ARCHIE
-- ============================================================================

CREATE TABLE IF NOT EXISTS work_sessions (
    id SERIAL PRIMARY KEY,

    -- What's being worked on
    project_id INTEGER REFERENCES unified_projects(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES unified_tasks(id) ON DELETE SET NULL,

    -- Who/what is working
    session_type VARCHAR(50) NOT NULL,  -- 'claude_cli', 'archie_web', 'agent', 'api'
    session_id VARCHAR(255),            -- Claude session ID, browser session, or agent ID
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,

    -- Session state
    status VARCHAR(20) DEFAULT 'active',  -- 'active', 'paused', 'completed'
    focus_description TEXT,               -- "Building auth module", "Fixing bug #123"

    -- Context data
    current_file VARCHAR(500),            -- File being worked on
    current_branch VARCHAR(100),          -- Git branch
    work_notes TEXT,                      -- Running notes during session
    context JSONB DEFAULT '{}',           -- Additional context (tags, related items, etc.)

    -- Timestamps
    started_at TIMESTAMP DEFAULT NOW(),
    last_activity TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,

    -- Summary on completion
    summary TEXT,                         -- What was accomplished
    files_modified JSONB DEFAULT '[]',    -- List of files touched
    decisions_made JSONB DEFAULT '[]'     -- Key decisions during session
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_work_sessions_project ON work_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_work_sessions_status ON work_sessions(status);
CREATE INDEX IF NOT EXISTS idx_work_sessions_session_id ON work_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_work_sessions_active ON work_sessions(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_work_sessions_recent ON work_sessions(last_activity DESC);

-- ============================================================================
-- WORK NOTES TABLE
-- Quick notes during work sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS work_notes (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES work_sessions(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES unified_projects(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES unified_tasks(id) ON DELETE SET NULL,

    note_type VARCHAR(50) DEFAULT 'general',  -- 'general', 'decision', 'blocker', 'idea', 'todo'
    content TEXT NOT NULL,

    -- Who added it
    added_by_user_id INTEGER REFERENCES users(id),
    added_by_agent_id INTEGER REFERENCES agents(id),
    added_by_session VARCHAR(255),  -- Claude session ID

    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_work_notes_session ON work_notes(session_id);
CREATE INDEX IF NOT EXISTS idx_work_notes_project ON work_notes(project_id);
CREATE INDEX IF NOT EXISTS idx_work_notes_type ON work_notes(note_type);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Get active work session for a session ID
CREATE OR REPLACE FUNCTION get_active_work_session(p_session_id VARCHAR)
RETURNS TABLE (
    session_id INTEGER,
    project_id INTEGER,
    project_name VARCHAR,
    project_slug VARCHAR,
    task_id INTEGER,
    task_title VARCHAR,
    focus_description TEXT,
    current_file VARCHAR,
    started_at TIMESTAMP,
    last_activity TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ws.id as session_id,
        ws.project_id,
        p.name as project_name,
        p.slug as project_slug,
        ws.task_id,
        t.title as task_title,
        ws.focus_description,
        ws.current_file,
        ws.started_at,
        ws.last_activity
    FROM work_sessions ws
    LEFT JOIN unified_projects p ON ws.project_id = p.id
    LEFT JOIN unified_tasks t ON ws.task_id = t.id
    WHERE ws.session_id = p_session_id
      AND ws.status = 'active'
    ORDER BY ws.last_activity DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Update last activity timestamp
CREATE OR REPLACE FUNCTION touch_work_session(p_session_id VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE work_sessions
    SET last_activity = NOW()
    WHERE session_id = p_session_id AND status = 'active';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- TRIGGER: Auto-update last_activity
-- ============================================================================

CREATE OR REPLACE FUNCTION update_session_activity()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_activity = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_work_session_activity ON work_sessions;
CREATE TRIGGER update_work_session_activity
    BEFORE UPDATE ON work_sessions
    FOR EACH ROW EXECUTE FUNCTION update_session_activity();

-- ============================================================================
-- LOG THIS MIGRATION
-- ============================================================================

INSERT INTO archie_config_history (
    config_type, config_path, change_type, change_reason, impact_assessment
) VALUES (
    'database',
    'work_sessions, work_notes',
    'created',
    'Phase 65.1: Session Context System for tracking active work across Claude CLI and ARCHIE',
    'Enables persistent work context, shared between CLI and web UI'
);

COMMIT;

-- Verification
SELECT 'work_sessions' as table_name, COUNT(*) as rows FROM work_sessions
UNION ALL
SELECT 'work_notes', COUNT(*) FROM work_notes;
