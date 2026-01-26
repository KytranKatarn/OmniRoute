-- Migration 058: User Session Time Tracking
-- Date: 2026-01-21
-- Purpose: Track cumulative time users spend interacting with A.R.C.H.I.E.

-- User session time tracking table
CREATE TABLE IF NOT EXISTS user_session_time (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_date DATE NOT NULL,
    total_minutes INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    last_message_at TIMESTAMP,
    first_message_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, session_date)
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_user_session_time_user ON user_session_time(user_id);
CREATE INDEX IF NOT EXISTS idx_user_session_time_date ON user_session_time(session_date DESC);

-- Cumulative stats view
CREATE OR REPLACE VIEW v_user_cumulative_time AS
SELECT
    user_id,
    SUM(total_minutes) as lifetime_minutes,
    SUM(message_count) as lifetime_messages,
    COUNT(DISTINCT session_date) as days_active,
    MIN(first_message_at) as first_interaction,
    MAX(last_message_at) as last_interaction,
    ROUND(SUM(total_minutes)::numeric / 60, 1) as lifetime_hours
FROM user_session_time
GROUP BY user_id;

-- Conversation consolidation tracking
CREATE TABLE IF NOT EXISTS conversation_consolidation_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    consolidation_hour TIMESTAMP NOT NULL,
    messages_consolidated INTEGER DEFAULT 0,
    knowledge_entry_id INTEGER REFERENCES knowledge_base(id),
    tags TEXT[],
    embedding_generated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, consolidation_hour)
);

CREATE INDEX IF NOT EXISTS idx_consolidation_hour ON conversation_consolidation_log(consolidation_hour DESC);

-- Scheduler task log
CREATE TABLE IF NOT EXISTS consciousness_scheduler_log (
    id SERIAL PRIMARY KEY,
    task_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'running', -- running, success, failed
    result_summary JSONB,
    error_message TEXT,
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_scheduler_log_task ON consciousness_scheduler_log(task_name, started_at DESC);

-- Function to update session time on each message
CREATE OR REPLACE FUNCTION update_user_session_time(
    p_user_id INTEGER,
    p_timestamp TIMESTAMP DEFAULT NOW()
) RETURNS void AS $$
DECLARE
    v_date DATE := p_timestamp::date;
    v_last_message TIMESTAMP;
    v_minutes_to_add INTEGER := 0;
BEGIN
    -- Get last message time for this user today
    SELECT last_message_at INTO v_last_message
    FROM user_session_time
    WHERE user_id = p_user_id AND session_date = v_date;

    -- Calculate minutes since last message (max 30 min gap counts)
    IF v_last_message IS NOT NULL THEN
        v_minutes_to_add := LEAST(
            EXTRACT(EPOCH FROM (p_timestamp - v_last_message)) / 60,
            30  -- Cap at 30 minutes per gap
        )::INTEGER;
    END IF;

    -- Upsert session time
    INSERT INTO user_session_time (user_id, session_date, total_minutes, message_count, first_message_at, last_message_at)
    VALUES (p_user_id, v_date, v_minutes_to_add, 1, p_timestamp, p_timestamp)
    ON CONFLICT (user_id, session_date) DO UPDATE SET
        total_minutes = user_session_time.total_minutes + v_minutes_to_add,
        message_count = user_session_time.message_count + 1,
        last_message_at = p_timestamp,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE user_session_time IS 'Track cumulative time users spend with A.R.C.H.I.E.';
COMMENT ON TABLE conversation_consolidation_log IS 'Log of hourly conversation consolidations';
COMMENT ON TABLE consciousness_scheduler_log IS 'Log of all scheduled consciousness tasks';
COMMENT ON FUNCTION update_user_session_time IS 'Call on each message to track session time';

SELECT 'Migration 058 completed - Time tracking tables created' as status;
