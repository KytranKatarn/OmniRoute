-- Migration 015: Conversation Sessions for Claude Code Memory (Phase 6)
-- Creates table to store Claude Code development session summaries

-- Create conversation_sessions table
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id SERIAL PRIMARY KEY,

    -- Session identification
    session_name VARCHAR(255) NOT NULL,
    session_id VARCHAR(255),  -- Claude session ID if available

    -- Git context (captured from hooks)
    git_branch VARCHAR(255),
    git_commit VARCHAR(100),
    working_directory TEXT,

    -- Timeline
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    compact_triggered_at TIMESTAMP,  -- When auto-compact occurred
    duration_seconds INTEGER,

    -- Conversation content
    full_transcript TEXT,  -- Full conversation text
    summary TEXT,  -- AI-generated summary
    key_insights JSONB DEFAULT '[]'::jsonb,  -- Extracted insights
    decisions_made JSONB DEFAULT '[]'::jsonb,  -- Key decisions
    code_patterns_learned JSONB DEFAULT '[]'::jsonb,  -- Code patterns identified

    -- Categorization
    primary_topic VARCHAR(100),  -- e.g., 'database', 'api', 'ui', 'deployment'
    phase VARCHAR(50),  -- e.g., 'Phase 5', 'Phase 6'
    tags TEXT[] DEFAULT '{}',

    -- Knowledge integration
    knowledge_entries_created INTEGER[] DEFAULT '{}',  -- IDs from knowledge_base
    improvements_created INTEGER[] DEFAULT '{}',  -- IDs from improvement_proposals
    mistakes_learned INTEGER[] DEFAULT '{}',  -- IDs from knowledge_base (type=mistake_learned)

    -- Quality metrics
    productivity_score DECIMAL(3,2),  -- 0.0-1.0 based on outcomes
    learning_value DECIMAL(3,2),  -- 0.0-1.0 how much was learned
    code_quality DECIMAL(3,2),  -- 0.0-1.0 quality of code produced

    -- Processing status
    processing_status VARCHAR(50) DEFAULT 'raw',  -- raw, processing, summarized, indexed
    processed_at TIMESTAMP,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_productivity_score CHECK (productivity_score IS NULL OR (productivity_score >= 0.0 AND productivity_score <= 1.0)),
    CONSTRAINT valid_learning_value CHECK (learning_value IS NULL OR (learning_value >= 0.0 AND learning_value <= 1.0)),
    CONSTRAINT valid_code_quality CHECK (code_quality IS NULL OR (code_quality >= 0.0 AND code_quality <= 1.0))
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_session_name ON conversation_sessions(session_name);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_git_branch ON conversation_sessions(git_branch);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_started_at ON conversation_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_primary_topic ON conversation_sessions(primary_topic);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_phase ON conversation_sessions(phase);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_tags_gin ON conversation_sessions USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_processing_status ON conversation_sessions(processing_status);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_knowledge_entries ON conversation_sessions USING GIN(knowledge_entries_created);

-- Create helper function to update updated_at
CREATE OR REPLACE FUNCTION update_conversation_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trigger_update_conversation_sessions_updated_at ON conversation_sessions;
CREATE TRIGGER trigger_update_conversation_sessions_updated_at
    BEFORE UPDATE ON conversation_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_sessions_updated_at();

-- Create view for active/recent sessions
CREATE OR REPLACE VIEW recent_conversation_sessions AS
SELECT
    id,
    session_name,
    git_branch,
    primary_topic,
    phase,
    started_at,
    ended_at,
    EXTRACT(EPOCH FROM (COALESCE(ended_at, NOW()) - started_at)) AS duration_seconds,
    processing_status,
    ARRAY_LENGTH(knowledge_entries_created, 1) AS knowledge_count,
    ARRAY_LENGTH(improvements_created, 1) AS improvements_count,
    ARRAY_LENGTH(mistakes_learned, 1) AS mistakes_count,
    productivity_score,
    learning_value
FROM conversation_sessions
WHERE started_at > NOW() - INTERVAL '30 days'
ORDER BY started_at DESC;

-- Create statistics view
CREATE OR REPLACE VIEW conversation_sessions_stats AS
SELECT
    COUNT(*) AS total_sessions,
    COUNT(*) FILTER (WHERE ended_at IS NOT NULL) AS completed_sessions,
    COUNT(*) FILTER (WHERE processing_status = 'summarized') AS summarized_sessions,
    COUNT(*) FILTER (WHERE processing_status = 'indexed') AS indexed_sessions,
    SUM(ARRAY_LENGTH(knowledge_entries_created, 1)) AS total_knowledge_created,
    SUM(ARRAY_LENGTH(improvements_created, 1)) AS total_improvements_created,
    SUM(ARRAY_LENGTH(mistakes_learned, 1)) AS total_mistakes_learned,
    AVG(productivity_score) AS avg_productivity,
    AVG(learning_value) AS avg_learning_value,
    AVG(code_quality) AS avg_code_quality,
    AVG(EXTRACT(EPOCH FROM (ended_at - started_at))) AS avg_duration_seconds
FROM conversation_sessions
WHERE ended_at IS NOT NULL;

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON conversation_sessions TO archie;
GRANT SELECT ON recent_conversation_sessions TO archie;
GRANT SELECT ON conversation_sessions_stats TO archie;
GRANT USAGE, SELECT ON SEQUENCE conversation_sessions_id_seq TO archie;

COMMENT ON TABLE conversation_sessions IS 'Phase 6: Stores Claude Code development session summaries and learnings';
COMMENT ON COLUMN conversation_sessions.full_transcript IS 'Complete conversation text for archival/search';
COMMENT ON COLUMN conversation_sessions.summary IS 'AI-generated summary of what was accomplished';
COMMENT ON COLUMN conversation_sessions.key_insights IS 'Array of key insights extracted: [{insight: "...", importance: 0.8}]';
COMMENT ON COLUMN conversation_sessions.knowledge_entries_created IS 'References to knowledge_base entries created during session';
COMMENT ON COLUMN conversation_sessions.productivity_score IS 'How productive the session was (0.0-1.0)';
COMMENT ON COLUMN conversation_sessions.learning_value IS 'How much new knowledge was gained (0.0-1.0)';
