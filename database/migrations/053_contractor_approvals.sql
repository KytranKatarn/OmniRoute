-- ============================================================================
-- MIGRATION: 053_contractor_approvals.sql
-- A.R.C.H.I.E. Contractor Permission System + Task Execution Tracking
-- Date: 2026-01-20
-- Purpose: Contractor approval workflow, task execution logging for HR/IAAE
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. CONTRACTOR APPROVAL REQUESTS TABLE
-- Requires Kytran/admin approval before using paid API contractors
-- ============================================================================
CREATE TABLE IF NOT EXISTS contractor_approval_requests (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    requested_by INTEGER REFERENCES users(id) ON DELETE SET NULL,

    -- Task details
    task_type VARCHAR(100) NOT NULL,
    task_description TEXT,
    module_source VARCHAR(100),

    -- Cost estimation
    estimated_tokens INTEGER,
    estimated_cost DECIMAL(10,4) DEFAULT 0.00,
    contractor_model VARCHAR(100),
    contractor_provider VARCHAR(50),

    -- Approval workflow
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied', 'expired', 'used')),
    priority VARCHAR(20) DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),

    -- Admin response
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP,
    denial_reason TEXT,

    -- Expiration (auto-expire stale requests)
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '24 hours'),

    -- Tracking
    actual_cost DECIMAL(10,4),
    execution_id UUID,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_contractor_approvals_status ON contractor_approval_requests(status);
CREATE INDEX idx_contractor_approvals_agent ON contractor_approval_requests(agent_id);
CREATE INDEX idx_contractor_approvals_pending ON contractor_approval_requests(status, created_at) WHERE status = 'pending';
CREATE INDEX idx_contractor_approvals_expires ON contractor_approval_requests(expires_at) WHERE status = 'pending';

-- ============================================================================
-- 2. ADD AUTO-APPROVAL THRESHOLD TO AGENTS
-- Small tasks under threshold can auto-approve (future A.R.C.H.I.E. budget)
-- ============================================================================
ALTER TABLE agents ADD COLUMN IF NOT EXISTS auto_approve_threshold DECIMAL(10,4) DEFAULT 0.00;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS contractor_usage_this_month DECIMAL(10,2) DEFAULT 0.00;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS contractor_budget_monthly DECIMAL(10,2) DEFAULT 50.00;

COMMENT ON COLUMN agents.auto_approve_threshold IS 'Cost threshold for auto-approving contractor usage (0 = requires approval)';
COMMENT ON COLUMN agents.contractor_usage_this_month IS 'Contractor API costs accumulated this month';
COMMENT ON COLUMN agents.contractor_budget_monthly IS 'Monthly budget limit for contractor API usage';

-- ============================================================================
-- 3. TASK EXECUTION LOG TABLE
-- Every task logged for HR monitoring and IAAE compliance
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_execution_log (
    id SERIAL PRIMARY KEY,
    execution_id UUID DEFAULT gen_random_uuid(),

    -- Agent info
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    agent_name VARCHAR(100),
    worker_type VARCHAR(20) CHECK (worker_type IN ('internal', 'contract')),

    -- Task classification
    task_type VARCHAR(100) NOT NULL,
    task_description TEXT,
    station_code VARCHAR(20),

    -- Module/source tracking
    module_source VARCHAR(100),
    mcp_tool VARCHAR(100),
    request_origin VARCHAR(50), -- 'platform', 'mcp', 'goose', 'api'

    -- Model/provider info
    model_used VARCHAR(100),
    provider VARCHAR(50),

    -- Usage metrics
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    cost DECIMAL(10,6) DEFAULT 0.00,
    duration_ms INTEGER,

    -- IAAE compliance
    iaae_compliant BOOLEAN DEFAULT TRUE,
    ethics_constraint_id INTEGER REFERENCES ethics_constraints(id),
    compliance_notes TEXT,

    -- Outcome
    success BOOLEAN NOT NULL,
    error_message TEXT,
    error_code VARCHAR(50),

    -- Attribution
    requested_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approval_id INTEGER REFERENCES contractor_approval_requests(id),

    -- Metadata
    request_metadata JSONB DEFAULT '{}'::jsonb,
    response_metadata JSONB DEFAULT '{}'::jsonb,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_task_execution_agent ON task_execution_log(agent_id);
CREATE INDEX idx_task_execution_worker_type ON task_execution_log(worker_type);
CREATE INDEX idx_task_execution_created ON task_execution_log(created_at DESC);
CREATE INDEX idx_task_execution_task_type ON task_execution_log(task_type);
CREATE INDEX idx_task_execution_module ON task_execution_log(module_source);
CREATE INDEX idx_task_execution_station ON task_execution_log(station_code);
CREATE INDEX idx_task_execution_success ON task_execution_log(success, created_at);
CREATE INDEX idx_task_execution_cost ON task_execution_log(cost) WHERE cost > 0;

-- ============================================================================
-- 4. CONTRACTOR BUDGET HISTORY
-- Track monthly contractor spending for budgeting
-- ============================================================================
CREATE TABLE IF NOT EXISTS contractor_budget_history (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    month_year VARCHAR(7) NOT NULL, -- 'YYYY-MM'
    total_requests INTEGER DEFAULT 0,
    approved_requests INTEGER DEFAULT 0,
    denied_requests INTEGER DEFAULT 0,
    total_cost DECIMAL(10,4) DEFAULT 0.00,
    budget_limit DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, month_year)
);

CREATE INDEX idx_contractor_budget_agent ON contractor_budget_history(agent_id);
CREATE INDEX idx_contractor_budget_month ON contractor_budget_history(month_year);

-- ============================================================================
-- 5. VIEWS FOR HR DASHBOARD
-- ============================================================================

-- View: Team productivity by day
CREATE OR REPLACE VIEW v_team_productivity AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.first_name,
    a.last_name,
    a.worker_type,
    a.department,
    a.model,
    DATE(tel.created_at) as work_date,
    COUNT(*) as tasks_completed,
    COUNT(*) FILTER (WHERE tel.success = TRUE) as successful_tasks,
    COUNT(*) FILTER (WHERE tel.success = FALSE) as failed_tasks,
    SUM(tel.tokens_used) as total_tokens,
    SUM(tel.cost) as total_cost,
    AVG(tel.duration_ms) as avg_duration_ms,
    COUNT(DISTINCT tel.task_type) as task_types_handled
FROM task_execution_log tel
JOIN agents a ON tel.agent_id = a.id
WHERE tel.created_at > NOW() - INTERVAL '30 days'
GROUP BY a.id, a.name, a.first_name, a.last_name, a.worker_type, a.department, a.model, DATE(tel.created_at)
ORDER BY work_date DESC, tasks_completed DESC;

-- View: Internal vs Contractor usage summary
CREATE OR REPLACE VIEW v_worker_type_summary AS
SELECT
    worker_type,
    DATE(created_at) as work_date,
    COUNT(*) as task_count,
    SUM(tokens_used) as total_tokens,
    SUM(cost) as total_cost,
    AVG(duration_ms) as avg_duration_ms,
    COUNT(*) FILTER (WHERE success = TRUE) as success_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE success = TRUE) / NULLIF(COUNT(*), 0), 2) as success_rate
FROM task_execution_log
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY worker_type, DATE(created_at)
ORDER BY work_date DESC, worker_type;

-- View: Contractor approval queue
CREATE OR REPLACE VIEW v_contractor_approval_queue AS
SELECT
    car.id,
    car.status,
    car.priority,
    car.task_type,
    car.task_description,
    car.module_source,
    car.estimated_cost,
    car.contractor_model,
    car.contractor_provider,
    car.created_at,
    car.expires_at,
    car.expires_at < NOW() as is_expired,
    a.id as agent_id,
    a.name as agent_name,
    a.first_name,
    a.last_name,
    a.department,
    u.username as requested_by_username
FROM contractor_approval_requests car
JOIN agents a ON car.agent_id = a.id
LEFT JOIN users u ON car.requested_by = u.id
WHERE car.status = 'pending'
ORDER BY
    CASE car.priority
        WHEN 'urgent' THEN 1
        WHEN 'high' THEN 2
        WHEN 'normal' THEN 3
        WHEN 'low' THEN 4
    END,
    car.created_at ASC;

-- View: Monthly contractor spending by agent
CREATE OR REPLACE VIEW v_contractor_spending AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.first_name,
    a.last_name,
    a.department,
    a.contractor_budget_monthly as budget,
    a.contractor_usage_this_month as used,
    a.contractor_budget_monthly - a.contractor_usage_this_month as remaining,
    ROUND(100.0 * a.contractor_usage_this_month / NULLIF(a.contractor_budget_monthly, 0), 2) as usage_percent,
    CASE
        WHEN a.contractor_usage_this_month >= a.contractor_budget_monthly THEN 'exhausted'
        WHEN a.contractor_usage_this_month >= a.contractor_budget_monthly * 0.8 THEN 'warning'
        ELSE 'ok'
    END as budget_status
FROM agents a
WHERE a.worker_type = 'contract' AND a.status = 'active'
ORDER BY a.contractor_usage_this_month DESC;

-- View: Module usage statistics
CREATE OR REPLACE VIEW v_module_usage_stats AS
SELECT
    module_source,
    COUNT(*) as total_tasks,
    COUNT(DISTINCT agent_id) as agents_involved,
    SUM(tokens_used) as total_tokens,
    SUM(cost) as total_cost,
    AVG(duration_ms) as avg_duration_ms,
    ROUND(100.0 * COUNT(*) FILTER (WHERE success = TRUE) / NULLIF(COUNT(*), 0), 2) as success_rate,
    COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_tasks,
    COUNT(*) FILTER (WHERE worker_type = 'contract') as contractor_tasks
FROM task_execution_log
WHERE created_at > NOW() - INTERVAL '30 days'
    AND module_source IS NOT NULL
GROUP BY module_source
ORDER BY total_tasks DESC;

-- ============================================================================
-- 6. FUNCTIONS FOR CONTRACTOR APPROVAL WORKFLOW
-- ============================================================================

-- Function: Request contractor approval
CREATE OR REPLACE FUNCTION request_contractor_approval(
    p_agent_id INTEGER,
    p_user_id INTEGER,
    p_task_type VARCHAR(100),
    p_task_description TEXT,
    p_module_source VARCHAR(100),
    p_estimated_cost DECIMAL(10,4),
    p_contractor_model VARCHAR(100),
    p_contractor_provider VARCHAR(50),
    p_priority VARCHAR(20) DEFAULT 'normal'
) RETURNS TABLE(
    approval_id INTEGER,
    status VARCHAR(20),
    auto_approved BOOLEAN,
    message TEXT
) AS $$
DECLARE
    v_threshold DECIMAL(10,4);
    v_approval_id INTEGER;
BEGIN
    -- Get agent's auto-approval threshold
    SELECT auto_approve_threshold INTO v_threshold
    FROM agents WHERE id = p_agent_id;

    -- Check if under auto-approval threshold
    IF p_estimated_cost <= COALESCE(v_threshold, 0) AND v_threshold > 0 THEN
        -- Auto-approve small requests
        INSERT INTO contractor_approval_requests (
            agent_id, requested_by, task_type, task_description,
            module_source, estimated_cost, contractor_model, contractor_provider,
            priority, status, approved_at
        ) VALUES (
            p_agent_id, p_user_id, p_task_type, p_task_description,
            p_module_source, p_estimated_cost, p_contractor_model, p_contractor_provider,
            p_priority, 'approved', NOW()
        ) RETURNING id INTO v_approval_id;

        RETURN QUERY SELECT
            v_approval_id,
            'approved'::VARCHAR(20),
            TRUE,
            'Auto-approved: cost under threshold'::TEXT;
    ELSE
        -- Require manual approval
        INSERT INTO contractor_approval_requests (
            agent_id, requested_by, task_type, task_description,
            module_source, estimated_cost, contractor_model, contractor_provider,
            priority, status
        ) VALUES (
            p_agent_id, p_user_id, p_task_type, p_task_description,
            p_module_source, p_estimated_cost, p_contractor_model, p_contractor_provider,
            p_priority, 'pending'
        ) RETURNING id INTO v_approval_id;

        -- Log to governance audit
        INSERT INTO governance_audit_log (
            event_type, event_category, agent_id, user_id, action,
            new_value, outcome
        ) VALUES (
            'contractor_approval_requested', 'contractor', p_agent_id, p_user_id, 'request',
            jsonb_build_object(
                'task_type', p_task_type,
                'estimated_cost', p_estimated_cost,
                'contractor', p_contractor_provider || '/' || p_contractor_model
            ),
            'pending'
        );

        RETURN QUERY SELECT
            v_approval_id,
            'pending'::VARCHAR(20),
            FALSE,
            'Awaiting admin approval'::TEXT;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function: Approve contractor request
CREATE OR REPLACE FUNCTION approve_contractor_request(
    p_approval_id INTEGER,
    p_admin_id INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    v_agent_id INTEGER;
BEGIN
    -- Update the request
    UPDATE contractor_approval_requests
    SET status = 'approved',
        approved_by = p_admin_id,
        approved_at = NOW(),
        updated_at = NOW()
    WHERE id = p_approval_id AND status = 'pending'
    RETURNING agent_id INTO v_agent_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Log to governance audit
    INSERT INTO governance_audit_log (
        event_type, event_category, agent_id, user_id, action,
        target_table, target_id, outcome
    ) VALUES (
        'contractor_approval_granted', 'contractor', v_agent_id, p_admin_id, 'approve',
        'contractor_approval_requests', p_approval_id, 'approved'
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function: Deny contractor request
CREATE OR REPLACE FUNCTION deny_contractor_request(
    p_approval_id INTEGER,
    p_admin_id INTEGER,
    p_reason TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_agent_id INTEGER;
BEGIN
    UPDATE contractor_approval_requests
    SET status = 'denied',
        approved_by = p_admin_id,
        approved_at = NOW(),
        denial_reason = p_reason,
        updated_at = NOW()
    WHERE id = p_approval_id AND status = 'pending'
    RETURNING agent_id INTO v_agent_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Log to governance audit
    INSERT INTO governance_audit_log (
        event_type, event_category, agent_id, user_id, action,
        target_table, target_id, reason, outcome
    ) VALUES (
        'contractor_approval_denied', 'contractor', v_agent_id, p_admin_id, 'deny',
        'contractor_approval_requests', p_approval_id, p_reason, 'denied'
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function: Log task execution
CREATE OR REPLACE FUNCTION log_task_execution(
    p_agent_id INTEGER,
    p_task_type VARCHAR(100),
    p_module_source VARCHAR(100),
    p_model_used VARCHAR(100),
    p_provider VARCHAR(50),
    p_tokens_used INTEGER,
    p_cost DECIMAL(10,6),
    p_duration_ms INTEGER,
    p_success BOOLEAN,
    p_user_id INTEGER DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL,
    p_station_code VARCHAR(20) DEFAULT NULL,
    p_mcp_tool VARCHAR(100) DEFAULT NULL,
    p_request_origin VARCHAR(50) DEFAULT 'platform'
) RETURNS UUID AS $$
DECLARE
    v_execution_id UUID;
    v_worker_type VARCHAR(20);
    v_agent_name VARCHAR(100);
BEGIN
    -- Get agent info
    SELECT worker_type, name INTO v_worker_type, v_agent_name
    FROM agents WHERE id = p_agent_id;

    -- Insert execution log
    INSERT INTO task_execution_log (
        agent_id, agent_name, worker_type, task_type, station_code,
        module_source, mcp_tool, request_origin, model_used, provider,
        tokens_used, cost, duration_ms, success, error_message,
        requested_by
    ) VALUES (
        p_agent_id, v_agent_name, v_worker_type, p_task_type, p_station_code,
        p_module_source, p_mcp_tool, p_request_origin, p_model_used, p_provider,
        p_tokens_used, p_cost, p_duration_ms, p_success, p_error_message,
        p_user_id
    ) RETURNING execution_id INTO v_execution_id;

    -- Update agent usage stats if contractor
    IF v_worker_type = 'contract' AND p_cost > 0 THEN
        UPDATE agents
        SET contractor_usage_this_month = contractor_usage_this_month + p_cost,
            total_cost = total_cost + p_cost,
            total_tokens_used = total_tokens_used + COALESCE(p_tokens_used, 0),
            last_used = NOW()
        WHERE id = p_agent_id;
    ELSIF p_cost = 0 THEN
        -- Update stats for internal agents too
        UPDATE agents
        SET total_tokens_used = total_tokens_used + COALESCE(p_tokens_used, 0),
            last_used = NOW()
        WHERE id = p_agent_id;
    END IF;

    RETURN v_execution_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Expire old pending requests
CREATE OR REPLACE FUNCTION expire_contractor_requests() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE contractor_approval_requests
    SET status = 'expired',
        updated_at = NOW()
    WHERE status = 'pending' AND expires_at < NOW();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Reset monthly contractor budgets (run monthly)
CREATE OR REPLACE FUNCTION reset_monthly_contractor_budgets() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
    v_month VARCHAR(7);
BEGIN
    v_month := TO_CHAR(NOW() - INTERVAL '1 month', 'YYYY-MM');

    -- Archive last month's spending
    INSERT INTO contractor_budget_history (agent_id, month_year, total_cost, budget_limit)
    SELECT
        id,
        v_month,
        contractor_usage_this_month,
        contractor_budget_monthly
    FROM agents
    WHERE worker_type = 'contract' AND contractor_usage_this_month > 0
    ON CONFLICT (agent_id, month_year) DO UPDATE
    SET total_cost = EXCLUDED.total_cost,
        updated_at = NOW();

    -- Reset monthly counters
    UPDATE agents
    SET contractor_usage_this_month = 0
    WHERE worker_type = 'contract';

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 7. TRIGGERS
-- ============================================================================

-- Trigger: Auto-update timestamp on contractor_approval_requests
CREATE OR REPLACE FUNCTION update_contractor_approval_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_contractor_approval_updated ON contractor_approval_requests;
CREATE TRIGGER trg_contractor_approval_updated
    BEFORE UPDATE ON contractor_approval_requests
    FOR EACH ROW
    EXECUTE FUNCTION update_contractor_approval_timestamp();

-- ============================================================================
-- 8. SEED DEFAULT CONTRACTOR BUDGETS
-- ============================================================================

-- Set contractor budgets for existing contractor agents
UPDATE agents
SET contractor_budget_monthly = 50.00,
    auto_approve_threshold = 0.00
WHERE worker_type = 'contract'
  AND contractor_budget_monthly IS NULL;

-- ============================================================================
-- Record migration
-- ============================================================================
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('053', 'Contractor Approval System and Task Execution Tracking', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
