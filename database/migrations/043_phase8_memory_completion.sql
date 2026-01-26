-- Migration 043: Phase 8 Long-Term Memory Completion
-- Creates user_memory_preferences table and memory integration functions
-- Date: 2026-01-20

DO $$
BEGIN
    RAISE NOTICE 'Migration 043: Phase 8 Long-Term Memory Completion';
END $$;

-- =============================================================================
-- USER MEMORY PREFERENCES TABLE
-- Stores learned user preferences from conversations
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_memory_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,

    -- Preference categorization
    category VARCHAR(100) NOT NULL,  -- 'code_style', 'communication', 'tools', 'workflow', etc.
    preference_key VARCHAR(255) NOT NULL,  -- 'indentation', 'commit_style', 'framework', etc.
    preference_value TEXT NOT NULL,  -- The actual preference value

    -- Confidence tracking
    confidence DECIMAL(3,2) DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    times_confirmed INTEGER DEFAULT 1,
    times_contradicted INTEGER DEFAULT 0,

    -- Source tracking
    source_conversation_id INTEGER,  -- References conversation_sessions if available
    first_observed_at TIMESTAMP DEFAULT NOW(),
    last_confirmed_at TIMESTAMP DEFAULT NOW(),

    -- Metadata
    context JSONB,  -- Additional context about when preference was learned
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id, category, preference_key)
);

CREATE INDEX IF NOT EXISTS idx_user_prefs_user ON user_memory_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_user_prefs_category ON user_memory_preferences(category);
CREATE INDEX IF NOT EXISTS idx_user_prefs_active ON user_memory_preferences(is_active) WHERE is_active = TRUE;

-- =============================================================================
-- CONVERSATION MEMORY EXTRACTION TRACKING
-- Tracks which conversations have been processed for memory extraction
-- =============================================================================

CREATE TABLE IF NOT EXISTS memory_extraction_log (
    id SERIAL PRIMARY KEY,

    -- Source reference
    source_type VARCHAR(50) NOT NULL,  -- 'conversation_session', 'knowledge_base', 'hook_capture'
    source_id INTEGER NOT NULL,

    -- Extraction results
    memories_created INTEGER DEFAULT 0,
    preferences_learned INTEGER DEFAULT 0,
    embeddings_generated INTEGER DEFAULT 0,

    -- Processing info
    processed_at TIMESTAMP DEFAULT NOW(),
    processing_duration_ms INTEGER,
    processor_version VARCHAR(20) DEFAULT '1.0',

    -- Error tracking
    error_message TEXT,
    status VARCHAR(20) DEFAULT 'completed',  -- 'completed', 'partial', 'failed'

    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_extraction_source ON memory_extraction_log(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memory_extraction_status ON memory_extraction_log(status);

-- =============================================================================
-- MEMORY SCHEDULED TASKS TABLE
-- Tracks scheduled memory maintenance tasks
-- =============================================================================

CREATE TABLE IF NOT EXISTS memory_scheduled_tasks (
    id SERIAL PRIMARY KEY,

    task_name VARCHAR(100) UNIQUE NOT NULL,
    task_type VARCHAR(50) NOT NULL,  -- 'decay', 'consolidation', 'cleanup', 'embedding_generation'

    -- Schedule
    cron_expression VARCHAR(100),  -- e.g., '0 3 * * *' for 3am daily
    interval_minutes INTEGER,  -- Alternative to cron

    -- Execution tracking
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    last_run_duration_ms INTEGER,
    last_run_status VARCHAR(20),
    last_run_result JSONB,

    -- Configuration
    config JSONB,  -- Task-specific configuration
    is_enabled BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Insert default scheduled tasks
INSERT INTO memory_scheduled_tasks (task_name, task_type, interval_minutes, config, is_enabled)
VALUES
    ('daily_memory_decay', 'decay', 1440, '{"min_age_hours": 24}', TRUE),
    ('hourly_embedding_generation', 'embedding_generation', 60, '{"batch_size": 50}', TRUE),
    ('weekly_memory_consolidation', 'consolidation', 10080, '{"similarity_threshold": 0.85}', TRUE),
    ('daily_low_importance_cleanup', 'cleanup', 1440, '{"min_importance": 0.1, "min_age_days": 90}', TRUE)
ON CONFLICT (task_name) DO NOTHING;

-- =============================================================================
-- FUNCTIONS FOR MEMORY INTEGRATION
-- =============================================================================

-- Function to learn a preference from conversation
CREATE OR REPLACE FUNCTION learn_preference(
    p_user_id INTEGER,
    p_category VARCHAR(100),
    p_key VARCHAR(255),
    p_value TEXT,
    p_confidence DECIMAL DEFAULT 0.6,
    p_context JSONB DEFAULT NULL
)
RETURNS INTEGER AS $$
DECLARE
    result_id INTEGER;
BEGIN
    INSERT INTO user_memory_preferences
        (user_id, category, preference_key, preference_value, confidence, context)
    VALUES
        (p_user_id, p_category, p_key, p_value, p_confidence, p_context)
    ON CONFLICT (user_id, category, preference_key) DO UPDATE SET
        -- If same value, increase confidence
        confidence = CASE
            WHEN user_memory_preferences.preference_value = EXCLUDED.preference_value
            THEN LEAST(1.0, user_memory_preferences.confidence + 0.1)
            -- If different value, decrease confidence and maybe update
            WHEN EXCLUDED.confidence > user_memory_preferences.confidence
            THEN EXCLUDED.confidence
            ELSE user_memory_preferences.confidence - 0.1
        END,
        preference_value = CASE
            WHEN EXCLUDED.confidence > user_memory_preferences.confidence
            THEN EXCLUDED.preference_value
            ELSE user_memory_preferences.preference_value
        END,
        times_confirmed = CASE
            WHEN user_memory_preferences.preference_value = EXCLUDED.preference_value
            THEN user_memory_preferences.times_confirmed + 1
            ELSE user_memory_preferences.times_confirmed
        END,
        times_contradicted = CASE
            WHEN user_memory_preferences.preference_value != EXCLUDED.preference_value
            THEN user_memory_preferences.times_contradicted + 1
            ELSE user_memory_preferences.times_contradicted
        END,
        last_confirmed_at = CASE
            WHEN user_memory_preferences.preference_value = EXCLUDED.preference_value
            THEN NOW()
            ELSE user_memory_preferences.last_confirmed_at
        END,
        context = COALESCE(EXCLUDED.context, user_memory_preferences.context),
        updated_at = NOW()
    RETURNING id INTO result_id;

    RETURN result_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get user preferences for context
CREATE OR REPLACE FUNCTION get_user_preferences(
    p_user_id INTEGER,
    p_category VARCHAR(100) DEFAULT NULL,
    p_min_confidence DECIMAL DEFAULT 0.5
)
RETURNS TABLE (
    category VARCHAR(100),
    preference_key VARCHAR(255),
    preference_value TEXT,
    confidence DECIMAL,
    times_confirmed INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ump.category,
        ump.preference_key,
        ump.preference_value,
        ump.confidence,
        ump.times_confirmed
    FROM user_memory_preferences ump
    WHERE ump.user_id = p_user_id
      AND ump.is_active = TRUE
      AND ump.confidence >= p_min_confidence
      AND (p_category IS NULL OR ump.category = p_category)
    ORDER BY ump.confidence DESC, ump.times_confirmed DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to process memory extraction from conversation
CREATE OR REPLACE FUNCTION extract_memories_from_text(
    p_content TEXT,
    p_user_id INTEGER DEFAULT NULL,
    p_source_type VARCHAR(50) DEFAULT 'conversation',
    p_importance DECIMAL DEFAULT 0.7
)
RETURNS INTEGER AS $$
DECLARE
    memory_id INTEGER;
    words_count INTEGER;
    has_code BOOLEAN;
    has_error BOOLEAN;
    memory_type VARCHAR(50);
    category VARCHAR(100);
BEGIN
    -- Analyze content
    words_count := array_length(regexp_split_to_array(p_content, '\s+'), 1);
    has_code := p_content ~ '```|`[^`]+`|def |function |class |import |from ';
    has_error := p_content ~* 'error|exception|failed|traceback|bug|fix';

    -- Determine memory type and category
    IF has_error THEN
        memory_type := 'problem_solution';
        category := 'troubleshooting';
    ELSIF has_code THEN
        memory_type := 'technical';
        category := 'code_pattern';
    ELSIF words_count > 500 THEN
        memory_type := 'procedure';
        category := 'workflow';
    ELSE
        memory_type := 'observation';
        category := 'general';
    END IF;

    -- Store in long_term_memory
    INSERT INTO long_term_memory
        (user_id, memory_type, category, content, importance_score, source_module, tags)
    VALUES
        (p_user_id, memory_type, category,
         LEFT(p_content, 10000),  -- Limit content size
         p_importance,
         p_source_type,
         ARRAY[memory_type, category, p_source_type])
    RETURNING id INTO memory_id;

    RETURN memory_id;
END;
$$ LANGUAGE plpgsql;

-- Function to run scheduled memory tasks
CREATE OR REPLACE FUNCTION run_memory_maintenance()
RETURNS TABLE (
    task_name VARCHAR(100),
    status VARCHAR(20),
    records_affected INTEGER
) AS $$
DECLARE
    decay_count INTEGER := 0;
    cleanup_count INTEGER := 0;
BEGIN
    -- Run memory decay
    SELECT apply_memory_decay() INTO decay_count;

    -- Run low-importance cleanup (older than 90 days, importance < 0.15, access_count < 2)
    DELETE FROM long_term_memory
    WHERE created_at < NOW() - INTERVAL '90 days'
      AND importance_score < 0.15
      AND (access_count IS NULL OR access_count < 2)
      AND (decay_immunity IS NULL OR decay_immunity = FALSE);
    GET DIAGNOSTICS cleanup_count = ROW_COUNT;

    -- Update scheduled task records
    UPDATE memory_scheduled_tasks
    SET last_run_at = NOW(),
        last_run_status = 'completed',
        last_run_result = jsonb_build_object('decay_count', decay_count, 'cleanup_count', cleanup_count)
    WHERE task_name IN ('daily_memory_decay', 'daily_low_importance_cleanup');

    RETURN QUERY
    SELECT 'memory_decay'::VARCHAR(100), 'completed'::VARCHAR(20), decay_count
    UNION ALL
    SELECT 'memory_cleanup'::VARCHAR(100), 'completed'::VARCHAR(20), cleanup_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VIEW FOR MEMORY DASHBOARD
-- =============================================================================

CREATE OR REPLACE VIEW v_memory_system_stats AS
SELECT
    (SELECT COUNT(*) FROM long_term_memory) as total_long_term_memories,
    (SELECT COUNT(*) FROM long_term_memory WHERE created_at > NOW() - INTERVAL '24 hours') as memories_last_24h,
    (SELECT COUNT(*) FROM memory_embeddings) as total_embeddings,
    (SELECT COUNT(*) FROM memory_collections) as total_collections,
    (SELECT COUNT(*) FROM memory_associations) as total_associations,
    (SELECT COUNT(*) FROM user_memory_preferences WHERE is_active = TRUE) as active_preferences,
    (SELECT COUNT(*) FROM knowledge_base WHERE entry_type = 'conversation_memory') as conversation_memories,
    (SELECT AVG(importance_score)::DECIMAL(3,2) FROM long_term_memory) as avg_importance,
    (SELECT MAX(last_run_at) FROM memory_scheduled_tasks WHERE task_type = 'decay') as last_decay_run;

-- =============================================================================
-- COMPLETION
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration 043 Complete: Phase 8 Long-Term Memory';
    RAISE NOTICE '  - user_memory_preferences table created';
    RAISE NOTICE '  - memory_extraction_log table created';
    RAISE NOTICE '  - memory_scheduled_tasks table created with 4 default tasks';
    RAISE NOTICE '  - learn_preference() function created';
    RAISE NOTICE '  - get_user_preferences() function created';
    RAISE NOTICE '  - extract_memories_from_text() function created';
    RAISE NOTICE '  - run_memory_maintenance() function created';
    RAISE NOTICE '  - v_memory_system_stats view created';
END $$;
