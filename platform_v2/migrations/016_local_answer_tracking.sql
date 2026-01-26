-- Migration 016: Local Answer Tracking (Phase 3)
-- Track cost savings from local answer generation
-- Date: 2026-01-10

-- ============================================================================
-- PART 1: Local Answer Savings Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS local_answer_savings (
    id SERIAL PRIMARY KEY,
    query_hash VARCHAR(64) UNIQUE NOT NULL,  -- SHA256 hash for deduplication
    query_preview TEXT,                       -- First 100 chars of query
    knowledge_ids INTEGER[],                  -- Which knowledge entries were used
    confidence_score DECIMAL(3,2),            -- 0.0-1.0 confidence
    strategy VARCHAR(20),                     -- 'direct' | 'synthesize'
    estimated_tokens_saved INTEGER,           -- Tokens that would have been used
    estimated_cost_saved DECIMAL(10,4),       -- Cost saved in dollars
    would_have_used_model VARCHAR(100),       -- Model that would have been called
    would_have_used_provider VARCHAR(50),     -- Provider (anthropic, openai, etc)
    created_at TIMESTAMP DEFAULT NOW(),
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);

-- Indexes for local_answer_savings
CREATE INDEX IF NOT EXISTS idx_local_savings_date
ON local_answer_savings(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_local_savings_user
ON local_answer_savings(user_id);

CREATE INDEX IF NOT EXISTS idx_local_savings_strategy
ON local_answer_savings(strategy);

COMMENT ON TABLE local_answer_savings IS
'Tracks queries answered locally without external LLM calls for cost savings analytics';

-- ============================================================================
-- PART 2: Knowledge Base Usage Tracking
-- ============================================================================

-- Add local usage tracking columns to knowledge_base
ALTER TABLE knowledge_base
ADD COLUMN IF NOT EXISTS times_used_locally INTEGER DEFAULT 0;

ALTER TABLE knowledge_base
ADD COLUMN IF NOT EXISTS estimated_cost_saved DECIMAL(10,4) DEFAULT 0.0;

-- Index for top knowledge by value
CREATE INDEX IF NOT EXISTS idx_kb_local_usage
ON knowledge_base(times_used_locally DESC, estimated_cost_saved DESC);

COMMENT ON COLUMN knowledge_base.times_used_locally IS
'Number of times this entry was used to answer queries locally without LLM';

COMMENT ON COLUMN knowledge_base.estimated_cost_saved IS
'Total estimated cost savings from using this entry for local answers';

-- ============================================================================
-- PART 3: Analytics Views
-- ============================================================================

-- View: Local answer statistics
CREATE OR REPLACE VIEW local_answer_statistics AS
SELECT
    DATE_TRUNC('day', created_at) as date,
    COUNT(*) as local_answers,
    SUM(estimated_tokens_saved) as total_tokens_saved,
    SUM(estimated_cost_saved) as total_cost_saved,
    AVG(confidence_score) as avg_confidence,
    COUNT(DISTINCT user_id) as unique_users,
    COUNT(CASE WHEN strategy = 'direct' THEN 1 END) as direct_answers,
    COUNT(CASE WHEN strategy = 'synthesize' THEN 1 END) as synthesized_answers
FROM local_answer_savings
GROUP BY DATE_TRUNC('day', created_at)
ORDER BY date DESC;

COMMENT ON VIEW local_answer_statistics IS
'Daily statistics for local answer generation and cost savings';

-- View: Top knowledge entries by cost savings
CREATE OR REPLACE VIEW top_knowledge_by_savings AS
SELECT
    id,
    knowledge_type,
    title,
    category,
    times_used_locally,
    ROUND(estimated_cost_saved::numeric, 2) as cost_saved,
    importance_score,
    created_at
FROM knowledge_base
WHERE times_used_locally > 0
ORDER BY estimated_cost_saved DESC, times_used_locally DESC
LIMIT 50;

COMMENT ON VIEW top_knowledge_by_savings IS
'Top 50 knowledge entries ranked by cost savings from local answers';

-- ============================================================================
-- PART 4: Helper Functions
-- ============================================================================

-- Function: Get cost savings report
CREATE OR REPLACE FUNCTION get_cost_savings_report(days_back INTEGER DEFAULT 30)
RETURNS TABLE (
    total_local_answers BIGINT,
    total_tokens_saved BIGINT,
    total_cost_saved NUMERIC,
    avg_confidence NUMERIC,
    unique_users_count BIGINT,
    direct_answers_count BIGINT,
    synthesized_answers_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT as total_local_answers,
        SUM(estimated_tokens_saved)::BIGINT as total_tokens_saved,
        ROUND(SUM(estimated_cost_saved)::numeric, 2) as total_cost_saved,
        ROUND(AVG(confidence_score)::numeric, 2) as avg_confidence,
        COUNT(DISTINCT user_id)::BIGINT as unique_users_count,
        COUNT(CASE WHEN strategy = 'direct' THEN 1 END)::BIGINT as direct_answers_count,
        COUNT(CASE WHEN strategy = 'synthesize' THEN 1 END)::BIGINT as synthesized_answers_count
    FROM local_answer_savings
    WHERE created_at > NOW() - (days_back || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_cost_savings_report IS
'Get comprehensive cost savings report for specified number of days';

-- Function: Get savings rate (local vs LLM calls)
CREATE OR REPLACE FUNCTION get_savings_rate(days_back INTEGER DEFAULT 30)
RETURNS TABLE (
    local_answers BIGINT,
    llm_calls BIGINT,
    local_percentage NUMERIC,
    cost_saved NUMERIC,
    cost_spent NUMERIC,
    savings_percentage NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (SELECT COUNT(*) FROM local_answer_savings
         WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::BIGINT as local_answers,
        (SELECT COUNT(*) FROM token_usage_log
         WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::BIGINT as llm_calls,
        ROUND(
            (SELECT COUNT(*) FROM local_answer_savings
             WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::NUMERIC /
            NULLIF((SELECT COUNT(*) FROM local_answer_savings
                    WHERE created_at > NOW() - (days_back || ' days')::INTERVAL) +
                   (SELECT COUNT(*) FROM token_usage_log
                    WHERE created_at > NOW() - (days_back || ' days')::INTERVAL), 0) * 100,
            2
        ) as local_percentage,
        ROUND((SELECT SUM(estimated_cost_saved) FROM local_answer_savings
               WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::numeric, 2) as cost_saved,
        ROUND((SELECT SUM(cost) FROM token_usage_log
               WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::numeric, 2) as cost_spent,
        ROUND(
            (SELECT SUM(estimated_cost_saved) FROM local_answer_savings
             WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::NUMERIC /
            NULLIF((SELECT SUM(estimated_cost_saved) FROM local_answer_savings
                    WHERE created_at > NOW() - (days_back || ' days')::INTERVAL) +
                   (SELECT SUM(cost) FROM token_usage_log
                    WHERE created_at > NOW() - (days_back || ' days')::INTERVAL), 0) * 100,
            2
        ) as savings_percentage;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_savings_rate IS
'Calculate savings rate: local answers vs LLM calls';

-- ============================================================================
-- PART 5: Sample Queries for Testing
-- ============================================================================

-- Test query 1: Get today's savings
-- SELECT * FROM local_answer_statistics WHERE date = CURRENT_DATE;

-- Test query 2: Get 30-day report
-- SELECT * FROM get_cost_savings_report(30);

-- Test query 3: Get savings rate
-- SELECT * FROM get_savings_rate(30);

-- Test query 4: Top knowledge by savings
-- SELECT * FROM top_knowledge_by_savings LIMIT 10;

-- ============================================================================
-- Migration Complete
-- ============================================================================

-- Verify tables
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'local_answer_savings') THEN
        RAISE NOTICE 'Migration 016: local_answer_savings table created successfully';
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'knowledge_base' AND column_name = 'times_used_locally') THEN
        RAISE NOTICE 'Migration 016: knowledge_base tracking columns added successfully';
    END IF;

    RAISE NOTICE 'Migration 016: Local Answer Tracking - COMPLETE';
END $$;
