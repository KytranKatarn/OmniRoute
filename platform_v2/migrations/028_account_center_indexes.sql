-- Migration 028: Account Center Performance Indexes
-- Adds missing indexes to improve query performance in Account Center module
--
-- These indexes address slow queries identified in code review:
-- - User filtering by subscription_tier and is_active
-- - Activity log time-based queries
-- - Failed login time-based queries
-- - Session lookups

-- ============================================================================
-- USERS TABLE INDEXES
-- ============================================================================

-- Index for subscription tier filtering (used in premium user counts, tier filters)
CREATE INDEX IF NOT EXISTS idx_users_subscription_tier
    ON users(subscription_tier);

-- Index for active user filtering (used in most user queries)
CREATE INDEX IF NOT EXISTS idx_users_is_active
    ON users(is_active);

-- Index for admin user filtering
CREATE INDEX IF NOT EXISTS idx_users_is_admin
    ON users(is_admin);

-- Composite index for common filter combinations
CREATE INDEX IF NOT EXISTS idx_users_active_tier
    ON users(is_active, subscription_tier);

-- Index for case-insensitive username searches (used in user search)
CREATE INDEX IF NOT EXISTS idx_users_username_lower
    ON users(LOWER(username));

-- Index for email searches
CREATE INDEX IF NOT EXISTS idx_users_email_lower
    ON users(LOWER(email));

-- ============================================================================
-- USER ACTIVITY LOG INDEXES
-- ============================================================================

-- Index for time-based activity queries (used in "active today" counts)
CREATE INDEX IF NOT EXISTS idx_user_activity_log_created_at
    ON user_activity_log(created_at);

-- Index for user-specific activity lookups
CREATE INDEX IF NOT EXISTS idx_user_activity_log_user_id
    ON user_activity_log(user_id);

-- Composite index for user activity by time
CREATE INDEX IF NOT EXISTS idx_user_activity_log_user_created
    ON user_activity_log(user_id, created_at DESC);

-- ============================================================================
-- FAILED LOGINS INDEXES
-- ============================================================================

-- Index for time-based failed login queries (recent attempts)
CREATE INDEX IF NOT EXISTS idx_failed_logins_attempted_at
    ON failed_logins(attempted_at);

-- Index for username-based failed login lookups
CREATE INDEX IF NOT EXISTS idx_failed_logins_username_lower
    ON failed_logins(LOWER(username));

-- Composite for recent failures by user
CREATE INDEX IF NOT EXISTS idx_failed_logins_username_time
    ON failed_logins(LOWER(username), attempted_at DESC);

-- ============================================================================
-- ACTIVE SESSIONS INDEXES
-- ============================================================================

-- Index for user session counts
CREATE INDEX IF NOT EXISTS idx_active_sessions_user_id
    ON active_sessions(user_id);

-- Index for session expiry checks
CREATE INDEX IF NOT EXISTS idx_active_sessions_expires_at
    ON active_sessions(expires_at);

-- ============================================================================
-- MCP API KEYS INDEXES
-- ============================================================================

-- Index for user API key counts
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_user_id
    ON mcp_api_keys(user_id);

-- Index for active key lookups
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_is_active
    ON mcp_api_keys(is_active);

-- Composite for active keys per user
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_user_active
    ON mcp_api_keys(user_id, is_active);

-- ============================================================================
-- ANALYZE TABLES
-- ============================================================================
-- Update table statistics for query planner after adding indexes

ANALYZE users;
ANALYZE user_activity_log;
ANALYZE failed_logins;
ANALYZE active_sessions;
ANALYZE mcp_api_keys;
