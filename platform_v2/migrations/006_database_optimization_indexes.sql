--
-- Database Optimization - Index Creation
-- Adds performance indexes to frequently queried tables
--
-- Purpose:
-- - Improve query performance on common lookups
-- - Speed up JOIN operations
-- - Optimize filtering and sorting
-- - Reduce full table scans
--
-- Author: A.R.C.H.I.E. Platform
-- Date: 2026-01-07
--

-- ===========================================================================
-- USER & AUTHENTICATION INDEXES
-- ===========================================================================

-- Users table - frequently queried by username, email, status
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_users_status ON users(is_active, role);
CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_tier) WHERE is_active = TRUE;

-- User sessions - frequently queried by user_id and expiry
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id, expires_at) WHERE is_valid = TRUE;
CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(session_token) WHERE is_valid = TRUE;

-- ===========================================================================
-- AGENT SYSTEM INDEXES
-- ===========================================================================

-- Agents - frequently filtered by status, type, department
CREATE INDEX IF NOT EXISTS idx_agents_status_type ON agents(status, worker_type);
CREATE INDEX IF NOT EXISTS idx_agents_department ON agents(department, status);
CREATE INDEX IF NOT EXISTS idx_agents_tier ON agents(tier, status);
CREATE INDEX IF NOT EXISTS idx_agents_visibility ON agents(visibility);

-- Agent skills - frequently joined with agents
CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_id, proficiency_level);
CREATE INDEX IF NOT EXISTS idx_agent_skills_skill ON agent_skills(skill_name, proficiency_level);

-- Agent executions - frequently filtered by date and status
CREATE INDEX IF NOT EXISTS idx_agent_executions_agent ON agent_executions(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_executions_status ON agent_executions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_executions_user ON agent_executions(user_id, created_at DESC);

-- Agent call queue - frequently ordered by priority and creation time
CREATE INDEX IF NOT EXISTS idx_agent_call_queue_priority ON agent_call_queue(priority DESC, created_at ASC) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_agent_call_queue_assigned ON agent_call_queue(assigned_agent_id, status);

-- ===========================================================================
-- IMPROVEMENT WORKFLOW INDEXES
-- ===========================================================================

-- Improvement proposals - frequently filtered by status, priority, category
CREATE INDEX IF NOT EXISTS idx_improvement_proposals_status ON improvement_proposals(status, priority DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_improvement_proposals_category ON improvement_proposals(category, status);
CREATE INDEX IF NOT EXISTS idx_improvement_proposals_priority ON improvement_proposals(priority DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_improvement_proposals_created_by ON improvement_proposals(created_by, status);
CREATE INDEX IF NOT EXISTS idx_improvement_proposals_risk ON improvement_proposals(risk_level, status);

-- Team assignments - frequently joined with proposals and agents
CREATE INDEX IF NOT EXISTS idx_improvement_team_assignments_proposal ON improvement_team_assignments(proposal_id, status);
CREATE INDEX IF NOT EXISTS idx_improvement_team_assignments_agent ON improvement_team_assignments(agent_id, status);

-- Deployments - frequently queried by proposal and date
CREATE INDEX IF NOT EXISTS idx_improvement_deployments_proposal ON improvement_deployments(proposal_id, deployed_at DESC);
CREATE INDEX IF NOT EXISTS idx_improvement_deployments_status ON improvement_deployments(status, deployed_at DESC);

-- Workflow states - audit trail queries
CREATE INDEX IF NOT EXISTS idx_improvement_workflow_states_proposal ON improvement_workflow_states(proposal_id, changed_at DESC);

-- ===========================================================================
-- KNOWLEDGE & MEMORY INDEXES
-- ===========================================================================

-- Knowledge base - frequently searched by tags and embeddings
CREATE INDEX IF NOT EXISTS idx_knowledge_base_tags ON knowledge_base USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_type ON knowledge_base(content_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_source ON knowledge_base(source_type, source_id);

-- Embeddings - vector similarity searches (if using pgvector)
-- CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_vector ON knowledge_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Long-term memory - frequently queried by importance and recency
CREATE INDEX IF NOT EXISTS idx_long_term_memory_type ON long_term_memory(memory_type, importance DESC);
CREATE INDEX IF NOT EXISTS idx_long_term_memory_tags ON long_term_memory USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_long_term_memory_importance ON long_term_memory(importance DESC, created_at DESC);

-- Short-term memory - frequently queried by session
CREATE INDEX IF NOT EXISTS idx_short_term_memory_session ON short_term_memory(session_id, created_at DESC);

-- ===========================================================================
-- BUSINESS & SAAS INDEXES
-- ===========================================================================

-- Subscriptions - frequently queried by user and status
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status, end_date);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tier ON subscriptions(tier, status);

-- Payments - frequently queried by user and date
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_subscription ON payments(subscription_id, created_at DESC);

-- Usage metrics - time-series queries
CREATE INDEX IF NOT EXISTS idx_usage_metrics_user_date ON usage_metrics(user_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_usage_metrics_feature ON usage_metrics(feature_name, date DESC);

-- ===========================================================================
-- PROJECTS & WEBSITES INDEXES
-- ===========================================================================

-- App builder projects - frequently queried by user and status
CREATE INDEX IF NOT EXISTS idx_app_builder_projects_user ON app_builder_projects(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_projects_status ON app_builder_projects(status, created_at DESC);

-- Website builder projects - same pattern
CREATE INDEX IF NOT EXISTS idx_website_builder_projects_user ON website_builder_projects(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_website_builder_projects_status ON website_builder_projects(status, created_at DESC);

-- ===========================================================================
-- SYSTEM MANAGEMENT INDEXES
-- ===========================================================================

-- Audit log - time-series queries by user and action
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);

-- Backups - frequently queried by status and creation date
CREATE INDEX IF NOT EXISTS idx_backups_status ON backups(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backups_type ON backups(backup_type, created_at DESC);

-- Notifications - frequently queried by user and read status
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread ON notifications(user_id, created_at DESC) WHERE read = FALSE;
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at DESC);

-- API keys - frequently queried by key hash and user
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash) WHERE is_active = TRUE;

-- ===========================================================================
-- INTEGRATION & EXTERNAL SERVICES INDEXES
-- ===========================================================================

-- GitHub integration - frequently queried by user and repo
CREATE INDEX IF NOT EXISTS idx_github_repos_user ON github_repos(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_github_commits_repo ON github_commits(repo_id, committed_at DESC);

-- Git branches - frequently queried by proposal
CREATE INDEX IF NOT EXISTS idx_git_branches_proposal ON sandbox_branches(proposal_id, status);

-- Git commits - frequently queried by proposal and branch
CREATE INDEX IF NOT EXISTS idx_git_commits_proposal ON git_commits(proposal_id, committed_at DESC);
CREATE INDEX IF NOT EXISTS idx_git_commits_branch ON git_commits(branch_name, committed_at DESC);

-- ===========================================================================
-- COMPOSITE INDEXES FOR COMMON QUERIES
-- ===========================================================================

-- Improvement proposals with team and deployment info
CREATE INDEX IF NOT EXISTS idx_proposals_workflow ON improvement_proposals(status, priority, risk_level, created_at DESC);

-- Agent availability and assignment
CREATE INDEX IF NOT EXISTS idx_agents_available ON agents(status, worker_type, tier) WHERE status = 'active';

-- Active user sessions
CREATE INDEX IF NOT EXISTS idx_active_sessions ON user_sessions(user_id, expires_at) WHERE is_valid = TRUE AND expires_at > NOW();

-- Pending notifications
CREATE INDEX IF NOT EXISTS idx_pending_notifications ON notifications(user_id, created_at DESC) WHERE read = FALSE AND deleted = FALSE;

-- ===========================================================================
-- PARTIAL INDEXES FOR PERFORMANCE
-- ===========================================================================

-- Only index active/relevant records
CREATE INDEX IF NOT EXISTS idx_active_proposals ON improvement_proposals(id, created_at DESC) WHERE status NOT IN ('completed', 'rejected', 'archived');
CREATE INDEX IF NOT EXISTS idx_active_agents ON agents(id, name) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_active_subscriptions ON subscriptions(user_id, tier) WHERE status = 'active';

-- ===========================================================================
-- GIN INDEXES FOR JSONB/ARRAY COLUMNS
-- ===========================================================================

-- JSONB columns frequently queried
CREATE INDEX IF NOT EXISTS idx_agents_capabilities_gin ON agents USING GIN(capabilities);
CREATE INDEX IF NOT EXISTS idx_knowledge_metadata_gin ON knowledge_base USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_improvement_plan_steps_gin ON improvement_proposals USING GIN(plan_steps) WHERE plan_steps IS NOT NULL;

-- Array columns
CREATE INDEX IF NOT EXISTS idx_improvement_required_skills_gin ON improvement_proposals USING GIN(required_skills) WHERE required_skills IS NOT NULL;

-- ===========================================================================
-- ANALYZE TABLES FOR QUERY PLANNER
-- ===========================================================================

-- Update statistics for better query planning
ANALYZE users;
ANALYZE agents;
ANALYZE agent_executions;
ANALYZE improvement_proposals;
ANALYZE knowledge_base;
ANALYZE subscriptions;
ANALYZE audit_log;
ANALYZE notifications;

-- ===========================================================================
-- INDEX MAINTENANCE NOTES
-- ===========================================================================

-- To monitor index usage:
-- SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
-- FROM pg_stat_user_indexes
-- WHERE schemaname = 'public'
-- ORDER BY idx_scan ASC;

-- To find unused indexes:
-- SELECT schemaname, tablename, indexname
-- FROM pg_stat_user_indexes
-- WHERE idx_scan = 0 AND schemaname = 'public';

-- To check index bloat:
-- SELECT schemaname, tablename, indexname, pg_size_pretty(pg_relation_size(indexrelid)) AS size
-- FROM pg_stat_user_indexes
-- WHERE schemaname = 'public'
-- ORDER BY pg_relation_size(indexrelid) DESC;

-- ===========================================================================
-- COMPLETION SUMMARY
-- ===========================================================================

DO $$
DECLARE
    index_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND indexname LIKE 'idx_%';

    RAISE NOTICE '✅ Database Optimization Complete';
    RAISE NOTICE '   Total indexes created/verified: %', index_count;
    RAISE NOTICE '   Tables analyzed for query planning';
    RAISE NOTICE '   Performance indexes ready for production';
END $$;
