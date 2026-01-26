-- Migration 017: User Local Answer Preference (Phase 3 Week 2)
-- Enable per-user control of local answer generation for conservative testing
-- Date: 2026-01-10

-- ============================================================================
-- PART 1: Add User Preference Column
-- ============================================================================

-- Add enable_local_answers column to users table
ALTER TABLE users
ADD COLUMN IF NOT EXISTS enable_local_answers BOOLEAN DEFAULT FALSE;

-- Add preference metadata for future expansion
ALTER TABLE users
ADD COLUMN IF NOT EXISTS local_answer_preferences JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN users.enable_local_answers IS
'Enable local answer generation (Phase 3) - answers from knowledge base without LLM calls';

COMMENT ON COLUMN users.local_answer_preferences IS
'Additional preferences for local answers: threshold overrides, feedback settings, etc.';

-- ============================================================================
-- PART 2: Enable for Admin Users (Week 2 Testing)
-- ============================================================================

-- Enable local answers for admin users (is_admin = TRUE) for initial testing
UPDATE users
SET enable_local_answers = TRUE
WHERE is_admin = TRUE;

-- ============================================================================
-- PART 3: Add Feedback Tracking
-- ============================================================================

-- Track user feedback on local answers for quality monitoring
CREATE TABLE IF NOT EXISTS local_answer_feedback (
    id SERIAL PRIMARY KEY,
    query_hash VARCHAR(64) REFERENCES local_answer_savings(query_hash),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    was_helpful BOOLEAN NOT NULL,
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_local_feedback_hash
ON local_answer_feedback(query_hash);

CREATE INDEX IF NOT EXISTS idx_local_feedback_user
ON local_answer_feedback(user_id);

CREATE INDEX IF NOT EXISTS idx_local_feedback_helpful
ON local_answer_feedback(was_helpful);

COMMENT ON TABLE local_answer_feedback IS
'User feedback on local answer quality for Week 2+ monitoring';

-- ============================================================================
-- PART 4: Analytics Functions for Week 2 Monitoring
-- ============================================================================

-- Function: Get local answer accuracy rate
CREATE OR REPLACE FUNCTION get_local_answer_accuracy(days_back INTEGER DEFAULT 7)
RETURNS TABLE (
    total_answers BIGINT,
    feedback_count BIGINT,
    helpful_count BIGINT,
    unhelpful_count BIGINT,
    accuracy_rate NUMERIC,
    feedback_rate NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (SELECT COUNT(*) FROM local_answer_savings
         WHERE created_at > NOW() - (days_back || ' days')::INTERVAL)::BIGINT as total_answers,

        (SELECT COUNT(*) FROM local_answer_feedback f
         JOIN local_answer_savings s ON f.query_hash = s.query_hash
         WHERE s.created_at > NOW() - (days_back || ' days')::INTERVAL)::BIGINT as feedback_count,

        (SELECT COUNT(*) FROM local_answer_feedback f
         JOIN local_answer_savings s ON f.query_hash = s.query_hash
         WHERE s.created_at > NOW() - (days_back || ' days')::INTERVAL
           AND f.was_helpful = TRUE)::BIGINT as helpful_count,

        (SELECT COUNT(*) FROM local_answer_feedback f
         JOIN local_answer_savings s ON f.query_hash = s.query_hash
         WHERE s.created_at > NOW() - (days_back || ' days')::INTERVAL
           AND f.was_helpful = FALSE)::BIGINT as unhelpful_count,

        -- Accuracy rate (helpful / total_feedback)
        ROUND(
            (SELECT COUNT(*) FROM local_answer_feedback f
             JOIN local_answer_savings s ON f.query_hash = s.query_hash
             WHERE s.created_at > NOW() - (days_back || ' days')::INTERVAL
               AND f.was_helpful = TRUE)::NUMERIC /
            NULLIF((SELECT COUNT(*) FROM local_answer_feedback f
                    JOIN local_answer_savings s ON f.query_hash = s.query_hash
                    WHERE s.created_at > NOW() - (days_back || ' days')::INTERVAL), 0) * 100,
            2
        ) as accuracy_rate,

        -- Feedback rate (feedback / total_answers)
        ROUND(
            (SELECT COUNT(*) FROM local_answer_feedback f
             JOIN local_answer_savings s ON f.query_hash = s.query_hash
             WHERE s.created_at > NOW() - (days_back || ' days')::INTERVAL)::NUMERIC /
            NULLIF((SELECT COUNT(*) FROM local_answer_savings
                    WHERE created_at > NOW() - (days_back || ' days')::INTERVAL), 0) * 100,
            2
        ) as feedback_rate;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_local_answer_accuracy IS
'Get local answer accuracy and feedback metrics for Week 2 monitoring';

-- Function: Get per-user local answer stats
CREATE OR REPLACE FUNCTION get_user_local_answer_stats(days_back INTEGER DEFAULT 7)
RETURNS TABLE (
    user_id INTEGER,
    username VARCHAR,
    email VARCHAR,
    enable_local_answers BOOLEAN,
    total_local_answers BIGINT,
    cost_saved NUMERIC,
    feedback_given BIGINT,
    helpful_feedback BIGINT,
    accuracy_rate NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        u.id,
        u.username,
        u.email,
        u.enable_local_answers,
        COUNT(DISTINCT s.id)::BIGINT as total_local_answers,
        ROUND(SUM(s.estimated_cost_saved)::numeric, 4) as cost_saved,
        COUNT(DISTINCT f.id)::BIGINT as feedback_given,
        COUNT(DISTINCT CASE WHEN f.was_helpful THEN f.id END)::BIGINT as helpful_feedback,
        ROUND(
            COUNT(DISTINCT CASE WHEN f.was_helpful THEN f.id END)::NUMERIC /
            NULLIF(COUNT(DISTINCT f.id), 0) * 100,
            2
        ) as accuracy_rate
    FROM users u
    LEFT JOIN local_answer_savings s ON s.user_id = u.id
        AND s.created_at > NOW() - (days_back || ' days')::INTERVAL
    LEFT JOIN local_answer_feedback f ON f.user_id = u.id
        AND EXISTS (
            SELECT 1 FROM local_answer_savings s2
            WHERE s2.query_hash = f.query_hash
              AND s2.created_at > NOW() - (days_back || ' days')::INTERVAL
        )
    GROUP BY u.id, u.username, u.email, u.enable_local_answers
    HAVING COUNT(DISTINCT s.id) > 0 OR u.enable_local_answers = TRUE
    ORDER BY total_local_answers DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_user_local_answer_stats IS
'Get per-user statistics for local answer usage and accuracy';

-- ============================================================================
-- PART 5: View for Week 2 Monitoring Dashboard
-- ============================================================================

CREATE OR REPLACE VIEW week_2_monitoring AS
SELECT
    DATE(s.created_at) as date,
    COUNT(*) as local_answers,
    COUNT(DISTINCT s.user_id) as unique_users,
    AVG(s.confidence_score) as avg_confidence,
    SUM(s.estimated_cost_saved) as cost_saved,
    COUNT(f.id) as feedback_count,
    COUNT(CASE WHEN f.was_helpful THEN 1 END) as helpful_count,
    COUNT(CASE WHEN NOT f.was_helpful THEN 1 END) as unhelpful_count,
    ROUND(
        COUNT(CASE WHEN f.was_helpful THEN 1 END)::NUMERIC /
        NULLIF(COUNT(f.id), 0) * 100,
        2
    ) as accuracy_pct
FROM local_answer_savings s
LEFT JOIN local_answer_feedback f ON f.query_hash = s.query_hash
WHERE s.created_at > NOW() - INTERVAL '14 days'
GROUP BY DATE(s.created_at)
ORDER BY date DESC;

COMMENT ON VIEW week_2_monitoring IS
'Daily monitoring view for Phase 3 Week 2 conservative testing';

-- ============================================================================
-- PART 6: Sample Queries for Week 2 Monitoring
-- ============================================================================

-- Test query 1: Get accuracy metrics
-- SELECT * FROM get_local_answer_accuracy(7);

-- Test query 2: Get per-user stats
-- SELECT * FROM get_user_local_answer_stats(7);

-- Test query 3: View daily monitoring
-- SELECT * FROM week_2_monitoring LIMIT 7;

-- Test query 4: Check which users have local answers enabled
-- SELECT id, username, email, role_id, enable_local_answers
-- FROM users WHERE enable_local_answers = TRUE;

-- ============================================================================
-- Migration Complete
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'users' AND column_name = 'enable_local_answers') THEN
        RAISE NOTICE 'Migration 017: User preference column added successfully';
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_name = 'local_answer_feedback') THEN
        RAISE NOTICE 'Migration 017: Feedback tracking table created successfully';
    END IF;

    RAISE NOTICE 'Migration 017: User Local Answer Preference - COMPLETE';
    RAISE NOTICE 'Week 2 Testing: Enabled for admin users (role_id = 1)';
END $$;
