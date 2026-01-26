-- ============================================================================
-- Migration 005: Improvement Workflow Enhancement
-- Date: 2026-01-01
-- Purpose: Add team assignment, sandbox, deployment tracking, and notifications
-- ============================================================================

-- Start transaction
BEGIN;

-- ============================================================================
-- NOTIFICATIONS TABLE (Required for escalation workflow)
-- ============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL, -- 'task_assigned', 'task_escalated', 'task_completed', 'system_alert', etc.
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    read_at TIMESTAMP,
    metadata JSONB,
    priority VARCHAR(20) DEFAULT 'normal', -- 'low', 'normal', 'high', 'urgent'
    action_url VARCHAR(255), -- Optional link to related resource
    CONSTRAINT valid_priority CHECK (priority IN ('low', 'normal', 'high', 'urgent'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);

-- ============================================================================
-- IMPROVEMENT TEAM ASSIGNMENTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS improvement_team_assignments (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL, -- 'lead', 'developer', 'reviewer', 'tester'
    assigned_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(30) DEFAULT 'assigned', -- 'assigned', 'in_progress', 'completed', 'blocked'
    notes TEXT,
    assigned_by INTEGER REFERENCES users(id), -- Who assigned this agent
    work_log JSONB, -- Track work done by this agent
    UNIQUE(proposal_id, agent_id),
    CONSTRAINT valid_assignment_status CHECK (status IN ('assigned', 'in_progress', 'completed', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_team_assignments_proposal ON improvement_team_assignments(proposal_id);
CREATE INDEX IF NOT EXISTS idx_team_assignments_agent ON improvement_team_assignments(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_team_assignments_status ON improvement_team_assignments(status);

-- ============================================================================
-- SANDBOX INSTANCES
-- ============================================================================

CREATE TABLE IF NOT EXISTS sandbox_instances (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    sandbox_type VARCHAR(20) NOT NULL, -- 'docker_container' or 'schema_separation'
    container_id VARCHAR(100), -- Docker container ID if applicable
    schema_name VARCHAR(50), -- Schema name if schema separation
    status VARCHAR(30) DEFAULT 'creating', -- 'creating', 'ready', 'testing', 'destroyed'
    created_at TIMESTAMP DEFAULT NOW(),
    destroyed_at TIMESTAMP,
    test_results JSONB, -- Results from sandbox testing
    backup_ref VARCHAR(255), -- Reference to pre-deployment backup
    metadata JSONB, -- Additional sandbox configuration
    created_by INTEGER REFERENCES users(id),
    error_log TEXT, -- Capture any errors during sandbox lifecycle
    CONSTRAINT valid_sandbox_type CHECK (sandbox_type IN ('docker_container', 'schema_separation')),
    CONSTRAINT valid_sandbox_status CHECK (status IN ('creating', 'ready', 'testing', 'destroyed', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_sandbox_proposal ON sandbox_instances(proposal_id, status);
CREATE INDEX IF NOT EXISTS idx_sandbox_status ON sandbox_instances(status);
CREATE INDEX IF NOT EXISTS idx_sandbox_created ON sandbox_instances(created_at DESC);

-- ============================================================================
-- DEPLOYMENT HISTORY TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS improvement_deployments (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    deployed_by INTEGER REFERENCES users(id),
    backup_name VARCHAR(255) NOT NULL, -- Reference to backup created before deployment
    sandbox_id INTEGER REFERENCES sandbox_instances(id),
    deployment_type VARCHAR(30) NOT NULL, -- 'manual', 'auto_low_risk', 'auto_approved'
    status VARCHAR(30) DEFAULT 'deploying', -- 'deploying', 'deployed', 'failed', 'rolled_back'
    deployed_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP, -- When deployment finished (success or failure)
    rolled_back_at TIMESTAMP,
    rollback_reason TEXT,
    health_check_passed BOOLEAN,
    deployment_log TEXT, -- Detailed log of deployment steps
    pre_deployment_checks JSONB, -- Results of pre-deployment validation
    post_deployment_metrics JSONB, -- Performance metrics after deployment
    CONSTRAINT valid_deployment_type CHECK (deployment_type IN ('manual', 'auto_low_risk', 'auto_approved')),
    CONSTRAINT valid_deployment_status CHECK (status IN ('deploying', 'deployed', 'failed', 'rolled_back'))
);

CREATE INDEX IF NOT EXISTS idx_deployments_proposal ON improvement_deployments(proposal_id);
CREATE INDEX IF NOT EXISTS idx_deployments_status ON improvement_deployments(status);
CREATE INDEX IF NOT EXISTS idx_deployments_date ON improvement_deployments(deployed_at DESC);

-- ============================================================================
-- WORKFLOW STATE TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS improvement_workflow_states (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    from_status VARCHAR(50),
    to_status VARCHAR(50) NOT NULL,
    changed_by INTEGER REFERENCES users(id),
    changed_at TIMESTAMP DEFAULT NOW(),
    reason TEXT, -- Why the status changed
    automated BOOLEAN DEFAULT false, -- Was this an automated transition?
    metadata JSONB, -- Additional context about the transition
    duration_seconds INTEGER, -- Time spent in previous status (calculated field)
    workflow_step VARCHAR(100) -- What step in the workflow this represents
);

CREATE INDEX IF NOT EXISTS idx_workflow_states_proposal ON improvement_workflow_states(proposal_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_workflow_states_automated ON improvement_workflow_states(automated);
CREATE INDEX IF NOT EXISTS idx_workflow_states_date ON improvement_workflow_states(changed_at DESC);

-- ============================================================================
-- ALTER EXISTING improvement_proposals TABLE
-- ============================================================================

-- Add new columns for enhanced workflow
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS team_assigned_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS team_size INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS required_skills TEXT[],
ADD COLUMN IF NOT EXISTS complexity VARCHAR(20) DEFAULT 'medium',
ADD COLUMN IF NOT EXISTS auto_deployed BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS sandbox_tested BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS last_health_check TIMESTAMP,
ADD COLUMN IF NOT EXISTS code_diff TEXT; -- Stores diff for preview

-- Add constraint for complexity
ALTER TABLE improvement_proposals
DROP CONSTRAINT IF EXISTS valid_complexity;

ALTER TABLE improvement_proposals
ADD CONSTRAINT valid_complexity CHECK (complexity IN ('low', 'medium', 'high'));

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_proposals_complexity ON improvement_proposals(complexity);
CREATE INDEX IF NOT EXISTS idx_proposals_team_assigned ON improvement_proposals(team_assigned_at);
CREATE INDEX IF NOT EXISTS idx_proposals_sandbox_tested ON improvement_proposals(sandbox_tested);

-- ============================================================================
-- CREATE VIEWS FOR COMMON QUERIES
-- ============================================================================

-- View: Active proposals with team assignments
CREATE OR REPLACE VIEW active_proposals_with_teams AS
SELECT
    p.id,
    p.title,
    p.category,
    p.priority,
    p.status,
    p.complexity,
    p.team_size,
    p.proposed_at,
    p.team_assigned_at,
    COUNT(DISTINCT ta.agent_id) as assigned_agents,
    COUNT(DISTINCT ta.agent_id) FILTER (WHERE ta.status = 'completed') as completed_agents,
    json_agg(
        json_build_object(
            'agent_id', a.id,
            'agent_name', a.name,
            'role', ta.role,
            'status', ta.status
        ) ORDER BY ta.assigned_at
    ) FILTER (WHERE ta.agent_id IS NOT NULL) as team_members
FROM improvement_proposals p
LEFT JOIN improvement_team_assignments ta ON p.id = ta.proposal_id
LEFT JOIN agents a ON ta.agent_id = a.id
WHERE p.status NOT IN ('archived', 'completed', 'rejected')
GROUP BY p.id;

-- View: Deployment success metrics
CREATE OR REPLACE VIEW deployment_metrics AS
SELECT
    DATE(deployed_at) as deployment_date,
    COUNT(*) as total_deployments,
    COUNT(*) FILTER (WHERE status = 'deployed') as successful,
    COUNT(*) FILTER (WHERE status = 'failed') as failed,
    COUNT(*) FILTER (WHERE status = 'rolled_back') as rolled_back,
    COUNT(*) FILTER (WHERE deployment_type = 'auto_low_risk') as automated,
    AVG(EXTRACT(EPOCH FROM (completed_at - deployed_at))/60) FILTER (WHERE completed_at IS NOT NULL) as avg_duration_minutes
FROM improvement_deployments
GROUP BY DATE(deployed_at)
ORDER BY deployment_date DESC;

-- ============================================================================
-- FUNCTIONS FOR AUTOMATION
-- ============================================================================

-- Function: Auto-detect stuck proposals and escalate them
CREATE OR REPLACE FUNCTION auto_escalate_stuck_proposals()
RETURNS TABLE(proposal_id INTEGER, hours_stuck NUMERIC)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH stuck AS (
        SELECT
            id,
            EXTRACT(EPOCH FROM (NOW() - proposed_at))/3600 as hours
        FROM improvement_proposals
        WHERE status IN ('pending', 'pending_approval', 'proposed')
        AND proposed_at < NOW() - INTERVAL '48 hours'
        AND status != 'escalated'
    )
    UPDATE improvement_proposals p
    SET
        status = 'escalated',
        escalated_at = NOW(),
        notes = COALESCE(notes || E'\n\n', '') ||
                '[AUTO-ESCALATED] Stuck in pending for ' || ROUND(s.hours::numeric, 1) || ' hours. Auto-escalated by system.'
    FROM stuck s
    WHERE p.id = s.id
    RETURNING p.id, s.hours;
END;
$$;

-- Function: Calculate proposal complexity based on category and scope
CREATE OR REPLACE FUNCTION calculate_proposal_complexity(
    p_category VARCHAR,
    p_description TEXT
)
RETURNS VARCHAR
LANGUAGE plpgsql
AS $$
DECLARE
    v_complexity VARCHAR;
    v_desc_length INTEGER;
BEGIN
    v_desc_length := LENGTH(p_description);

    -- High complexity categories
    IF p_category IN ('security', 'performance', 'architecture', 'database') THEN
        v_complexity := 'high';
    -- Medium complexity categories
    ELSIF p_category IN ('ui', 'api', 'integration', 'backend', 'frontend') THEN
        v_complexity := 'medium';
    -- Low complexity categories
    ELSE
        v_complexity := 'low';
    END IF;

    -- Adjust based on description length (proxy for scope)
    IF v_desc_length > 500 AND v_complexity = 'low' THEN
        v_complexity := 'medium';
    ELSIF v_desc_length > 1000 AND v_complexity = 'medium' THEN
        v_complexity := 'high';
    END IF;

    RETURN v_complexity;
END;
$$;

-- Function: Track workflow state changes (trigger)
CREATE OR REPLACE FUNCTION track_workflow_state_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_duration INTEGER;
BEGIN
    -- Only track if status actually changed
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        -- Calculate duration in previous state
        SELECT EXTRACT(EPOCH FROM (NOW() - changed_at))::INTEGER
        INTO v_duration
        FROM improvement_workflow_states
        WHERE proposal_id = NEW.id
        ORDER BY changed_at DESC
        LIMIT 1;

        -- Insert workflow state record
        INSERT INTO improvement_workflow_states (
            proposal_id,
            from_status,
            to_status,
            changed_by,
            changed_at,
            automated,
            duration_seconds
        ) VALUES (
            NEW.id,
            OLD.status,
            NEW.status,
            COALESCE(NEW.updated_by, NEW.proposed_by),
            NOW(),
            false, -- Can be updated by automation
            v_duration
        );
    END IF;

    RETURN NEW;
END;
$$;

-- Create trigger for workflow state tracking
DROP TRIGGER IF EXISTS trigger_track_workflow_state ON improvement_proposals;
CREATE TRIGGER trigger_track_workflow_state
    AFTER UPDATE ON improvement_proposals
    FOR EACH ROW
    EXECUTE FUNCTION track_workflow_state_change();

-- ============================================================================
-- INITIAL DATA / SEED DATA
-- ============================================================================

-- Insert default notification types documentation (for reference)
COMMENT ON TABLE notifications IS 'User notifications for tasks, alerts, and system messages. Types: task_assigned, task_escalated, task_completed, system_alert, deployment_success, deployment_failed, team_assigned, sandbox_ready';

COMMENT ON TABLE improvement_team_assignments IS 'Tracks which agents are assigned to which improvement proposals and their progress';

COMMENT ON TABLE sandbox_instances IS 'Tracks sandbox environments created for testing improvements before production deployment';

COMMENT ON TABLE improvement_deployments IS 'Complete audit trail of all improvement deployments with backup references and rollback capability';

COMMENT ON TABLE improvement_workflow_states IS 'Historical tracking of all status changes for improvement proposals, enabling workflow analytics';

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Commit transaction
COMMIT;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 005 completed successfully';
    RAISE NOTICE '   - Created notifications table';
    RAISE NOTICE '   - Created improvement_team_assignments table';
    RAISE NOTICE '   - Created sandbox_instances table';
    RAISE NOTICE '   - Created improvement_deployments table';
    RAISE NOTICE '   - Created improvement_workflow_states table';
    RAISE NOTICE '   - Added 8 new columns to improvement_proposals';
    RAISE NOTICE '   - Created 2 views for analytics';
    RAISE NOTICE '   - Created 3 automation functions';
    RAISE NOTICE '   - Created workflow state tracking trigger';
    RAISE NOTICE '';
    RAISE NOTICE '🎯 Next Steps:';
    RAISE NOTICE '   1. Verify migration: SELECT COUNT(*) FROM notifications;';
    RAISE NOTICE '   2. Test escalation: Test improvements escalation button';
    RAISE NOTICE '   3. Implement team assignment engine';
END $$;
