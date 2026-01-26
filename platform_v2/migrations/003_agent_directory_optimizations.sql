-- ============================================================================
-- A.R.C.H.I.E. Platform - Agent Directory Optimizations
-- Migration: 003 - Database Performance & Multi-Tier Access
-- Created: 2025-12-31
-- Purpose: Optimize agent queries and prepare for multi-tier architecture
-- ============================================================================

-- ============================================================================
-- PERFORMANCE INDEXES
-- ============================================================================

-- Agent query performance indexes
CREATE INDEX IF NOT EXISTS idx_agents_department_status
    ON agents(department, status);

CREATE INDEX IF NOT EXISTS idx_agents_tier_status
    ON agents(tier, status);

CREATE INDEX IF NOT EXISTS idx_agents_total_cost
    ON agents(total_cost DESC);

CREATE INDEX IF NOT EXISTS idx_agents_last_used
    ON agents(last_used DESC NULLS LAST);

-- Multi-tenant access control indexes (for future visibility filtering)
CREATE INDEX IF NOT EXISTS idx_agents_visibility
    ON agents(status, worker_type, tier)
    WHERE status = 'active';

-- Search performance
CREATE INDEX IF NOT EXISTS idx_agents_search_name
    ON agents USING gin(to_tsvector('english',
        COALESCE(first_name, '') || ' ' ||
        COALESCE(last_name, '') || ' ' ||
        COALESCE(title, '') || ' ' ||
        COALESCE(department, '')));

-- ============================================================================
-- AGENT DIRECTORY VIEW
-- ============================================================================

CREATE OR REPLACE VIEW agent_directory_view AS
SELECT
    a.id,
    a.name,
    -- Full name for display
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) as full_name,
    a.first_name,
    a.last_name,
    a.email,
    a.title,
    a.department,
    a.bio,
    a.avatar_url,
    a.pronouns,
    a.tier,
    a.status,
    a.worker_type,
    a.model,
    a.system_prompt,
    a.capabilities,
    a.monthly_budget,
    a.total_cost,
    a.total_tokens_used,
    a.created_at,
    a.last_used,
    -- Agent type info
    at.name as agent_type,
    at.category as agent_category,
    at.icon as agent_icon,
    -- Computed fields
    ROUND(
        (a.total_cost / NULLIF(a.monthly_budget, 0)) * 100,
        2
    ) as budget_used_percent,
    -- Activity status based on last_used
    CASE
        WHEN a.last_used IS NULL THEN 'never-used'
        WHEN a.last_used > NOW() - INTERVAL '7 days' THEN 'active'
        WHEN a.last_used > NOW() - INTERVAL '30 days' THEN 'semi-active'
        ELSE 'inactive'
    END as activity_status,
    -- Budget status
    CASE
        WHEN a.monthly_budget IS NULL THEN 'no-budget'
        WHEN a.total_cost >= a.monthly_budget THEN 'over-budget'
        WHEN a.total_cost >= (a.monthly_budget * COALESCE(a.budget_alert_threshold, 0.8)) THEN 'near-limit'
        ELSE 'under-budget'
    END as budget_status
FROM agents a
LEFT JOIN agent_types at ON a.type_id = at.id
WHERE a.status = 'active';

-- ============================================================================
-- AGENT STATISTICS VIEW
-- ============================================================================

CREATE OR REPLACE VIEW agent_statistics_view AS
SELECT
    -- Overall statistics
    COUNT(*) as total_active_agents,
    COUNT(DISTINCT department) as total_departments,
    SUM(monthly_budget) as total_monthly_budget,
    SUM(total_cost) as total_cost_to_date,
    ROUND(AVG(total_cost), 2) as avg_cost_per_agent,

    -- Worker type breakdown
    COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_agents,
    COUNT(*) FILTER (WHERE worker_type = 'contract') as contract_agents,

    -- Tier breakdown
    COUNT(*) FILTER (WHERE tier = 1) as tier_1_agents,
    COUNT(*) FILTER (WHERE tier = 2) as tier_2_agents,
    COUNT(*) FILTER (WHERE tier = 3) as tier_3_agents,

    -- Activity breakdown
    COUNT(*) FILTER (WHERE last_used > NOW() - INTERVAL '7 days') as active_last_week,
    COUNT(*) FILTER (WHERE last_used > NOW() - INTERVAL '30 days') as active_last_month,
    COUNT(*) FILTER (WHERE last_used IS NULL) as never_used,

    -- Budget analysis
    COUNT(*) FILTER (WHERE total_cost >= monthly_budget) as over_budget_count,
    SUM(total_cost) FILTER (WHERE total_cost >= monthly_budget) as over_budget_total,

    -- API provider breakdown
    COUNT(*) FILTER (WHERE api_provider = 'anthropic') as anthropic_agents,
    COUNT(*) FILTER (WHERE api_provider = 'openai') as openai_agents,
    COUNT(*) FILTER (WHERE api_provider = 'x-ai') as xai_agents,
    COUNT(*) FILTER (WHERE api_provider IS NULL) as local_agents

FROM agents
WHERE status = 'active';

-- ============================================================================
-- DEPARTMENT SUMMARY VIEW
-- ============================================================================

CREATE OR REPLACE VIEW department_summary_view AS
SELECT
    department,
    COUNT(*) as agent_count,
    SUM(monthly_budget) as department_budget,
    SUM(total_cost) as department_cost,
    ROUND(AVG(total_cost), 2) as avg_agent_cost,
    COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_count,
    COUNT(*) FILTER (WHERE worker_type = 'contract') as contract_count,
    COUNT(*) FILTER (WHERE last_used > NOW() - INTERVAL '7 days') as active_count
FROM agents
WHERE status = 'active'
GROUP BY department
ORDER BY agent_count DESC, department;

-- ============================================================================
-- MULTI-TIER ACCESS PREPARATION
-- ============================================================================

-- Add visibility field to agents (for controlling public/dashboard/admin access)
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'internal';

COMMENT ON COLUMN agents.visibility IS
    'Access visibility: internal (admin only), dashboard (logged-in users), public (anyone), course (enrolled students)';

-- Add subscription tier to users table
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(20) DEFAULT 'free';

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}';

COMMENT ON COLUMN users.subscription_tier IS
    'Subscription level: free, basic, pro, enterprise';

COMMENT ON COLUMN users.google_id IS
    'Google OAuth ID for KytranEmpowerment@gmail.com integration';

-- ============================================================================
-- AGENT ACCESS POLICIES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_access_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    access_type VARCHAR(20) NOT NULL CHECK (access_type IN ('admin', 'user', 'student', 'public')),
    allowed_operations VARCHAR(50)[] DEFAULT ARRAY['view'],
    rate_limit_per_hour INTEGER DEFAULT 10,
    requires_subscription_tier VARCHAR(20),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, access_type)
);

CREATE INDEX IF NOT EXISTS idx_agent_access_policies_agent
    ON agent_access_policies(agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_access_policies_type
    ON agent_access_policies(access_type);

COMMENT ON TABLE agent_access_policies IS
    'Controls which users can access which agents and what operations they can perform';

-- ============================================================================
-- AGENT USAGE TRACKING (for billing and analytics)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id),
    agent_id INTEGER REFERENCES agents(id),
    usage_type VARCHAR(50) NOT NULL,
    tokens_used INTEGER,
    cost DECIMAL(10,4),
    duration_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_user_date
    ON agent_usage_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_usage_logs_agent_date
    ON agent_usage_logs(agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_usage_logs_date
    ON agent_usage_logs(created_at DESC);

COMMENT ON TABLE agent_usage_logs IS
    'Tracks all agent usage for billing, analytics, and rate limiting';

-- ============================================================================
-- COURSES TABLE (for Study Platform)
-- ============================================================================

CREATE TABLE IF NOT EXISTS courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    long_description TEXT,
    category VARCHAR(100),
    difficulty VARCHAR(20) CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    price DECIMAL(10,2),
    is_subscription BOOLEAN DEFAULT false,
    assigned_agents INTEGER[] DEFAULT ARRAY[]::INTEGER[],
    thumbnail_url VARCHAR(500),
    duration_hours INTEGER,
    is_published BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_courses_published
    ON courses(is_published, category);

CREATE INDEX IF NOT EXISTS idx_courses_slug
    ON courses(slug);

COMMENT ON TABLE courses IS
    'Courses offered on study.kytranempowerment.com';

-- ============================================================================
-- COURSE ENROLLMENTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS course_enrollments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id),
    course_id UUID REFERENCES courses(id),
    enrolled_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    access_level VARCHAR(20) DEFAULT 'basic',
    progress JSONB DEFAULT '{}',
    completed BOOLEAN DEFAULT false,
    completed_at TIMESTAMP,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    review TEXT,
    metadata JSONB DEFAULT '{}',
    UNIQUE(user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_user
    ON course_enrollments(user_id, enrolled_at DESC);

CREATE INDEX IF NOT EXISTS idx_enrollments_course
    ON course_enrollments(course_id, enrolled_at DESC);

CREATE INDEX IF NOT EXISTS idx_enrollments_active
    ON course_enrollments(user_id)
    WHERE completed = false AND (expires_at IS NULL OR expires_at > NOW());

-- ============================================================================
-- TRIGGERS FOR UPDATED_AT
-- ============================================================================

-- Courses updated_at trigger
DROP TRIGGER IF EXISTS update_courses_updated_at ON courses;
CREATE TRIGGER update_courses_updated_at
    BEFORE UPDATE ON courses
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Agent access policies updated_at trigger
DROP TRIGGER IF EXISTS update_agent_access_policies_updated_at ON agent_access_policies;
CREATE TRIGGER update_agent_access_policies_updated_at
    BEFORE UPDATE ON agent_access_policies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- HELPFUL FUNCTIONS
-- ============================================================================

-- Function to get agent directory with filters
CREATE OR REPLACE FUNCTION get_filtered_agent_directory(
    p_department VARCHAR DEFAULT NULL,
    p_tier INTEGER DEFAULT NULL,
    p_worker_type VARCHAR DEFAULT NULL,
    p_activity_status VARCHAR DEFAULT NULL,
    p_search VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    id INTEGER,
    full_name TEXT,
    email VARCHAR,
    title VARCHAR,
    department VARCHAR,
    tier INTEGER,
    worker_type VARCHAR,
    activity_status TEXT,
    budget_status TEXT,
    total_cost NUMERIC,
    monthly_budget NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        adv.id,
        adv.full_name,
        adv.email,
        adv.title,
        adv.department,
        adv.tier,
        adv.worker_type,
        adv.activity_status,
        adv.budget_status,
        adv.total_cost,
        adv.monthly_budget
    FROM agent_directory_view adv
    WHERE
        (p_department IS NULL OR adv.department = p_department) AND
        (p_tier IS NULL OR adv.tier = p_tier) AND
        (p_worker_type IS NULL OR adv.worker_type = p_worker_type) AND
        (p_activity_status IS NULL OR adv.activity_status = p_activity_status) AND
        (p_search IS NULL OR
            adv.full_name ILIKE '%' || p_search || '%' OR
            adv.email ILIKE '%' || p_search || '%' OR
            adv.title ILIKE '%' || p_search || '%' OR
            adv.department ILIKE '%' || p_search || '%')
    ORDER BY adv.department, adv.full_name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SAMPLE DATA FOR TESTING
-- ============================================================================

-- Set visibility for existing agents (default to 'internal' for now)
UPDATE agents SET visibility = 'internal' WHERE visibility IS NULL;

-- Sample access policy (allow all users to view tier 1 agents)
INSERT INTO agent_access_policies (agent_id, access_type, allowed_operations, rate_limit_per_hour)
SELECT
    id,
    'user',
    ARRAY['view', 'chat'],
    20
FROM agents
WHERE tier = 1 AND status = 'active'
ON CONFLICT (agent_id, access_type) DO NOTHING;

-- ============================================================================
-- MIGRATION LOGGING
-- ============================================================================

-- Ensure schema_migrations table exists
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(10) PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP DEFAULT NOW()
);

-- Log this migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('003', 'Agent Directory Optimizations & Multi-Tier Access', NOW())
ON CONFLICT (version) DO UPDATE
    SET applied_at = NOW();

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Migration 003 - Agent Directory Optimizations completed successfully';
    RAISE NOTICE '📊 Created views: agent_directory_view, agent_statistics_view, department_summary_view';
    RAISE NOTICE '🔍 Added %s performance indexes', 7;
    RAISE NOTICE '🔐 Created agent_access_policies table for multi-tier access';
    RAISE NOTICE '📚 Created courses and course_enrollments tables';
    RAISE NOTICE '📈 Created agent_usage_logs table for tracking';
END $$;
