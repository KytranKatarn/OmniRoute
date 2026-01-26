-- ============================================================================
-- Migration 054: Goose Workflow Queue
-- Phase 55: Goose Orchestration
-- Date: 2026-01-21
-- ============================================================================

-- Workflow execution queue for Goose orchestration
CREATE TABLE IF NOT EXISTS workflow_queue (
    id SERIAL PRIMARY KEY,
    workflow_id UUID DEFAULT gen_random_uuid() UNIQUE,
    workflow_name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Workflow definition
    steps JSONB DEFAULT '[]',
    parameters JSONB DEFAULT '{}',
    current_step INTEGER DEFAULT 0,

    -- Execution status
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'paused')),
    progress_percent INTEGER DEFAULT 0,
    error_message TEXT,

    -- Timing
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    timeout_at TIMESTAMP,

    -- Metadata
    initiated_by VARCHAR(100), -- 'user:123', 'goose', 'webhook', 'schedule'
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Results
    output JSONB,
    execution_log JSONB DEFAULT '[]'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_workflow_queue_status ON workflow_queue(status);
CREATE INDEX IF NOT EXISTS idx_workflow_queue_created ON workflow_queue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_queue_name ON workflow_queue(workflow_name);
CREATE INDEX IF NOT EXISTS idx_workflow_queue_initiated ON workflow_queue(initiated_by);

-- Workflow templates (blueprints stored in database)
CREATE TABLE IF NOT EXISTS workflow_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    description TEXT,
    category VARCHAR(100) DEFAULT 'general',
    steps JSONB NOT NULL,
    default_parameters JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Scheduled workflows (cron-based triggers)
CREATE TABLE IF NOT EXISTS workflow_schedules (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES workflow_templates(id) ON DELETE CASCADE,
    cron_expression VARCHAR(100) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'UTC',
    is_enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    parameters JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Workflow execution steps (detailed step logging)
CREATE TABLE IF NOT EXISTS workflow_step_executions (
    id SERIAL PRIMARY KEY,
    workflow_id UUID REFERENCES workflow_queue(workflow_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    step_name VARCHAR(200),
    tool_name VARCHAR(100),
    input_params JSONB,
    output_result JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_step_exec_workflow ON workflow_step_executions(workflow_id);

-- View for workflow statistics
CREATE OR REPLACE VIEW v_workflow_stats AS
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_workflows,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE status = 'failed') as failed,
    COUNT(*) FILTER (WHERE status = 'running') as running,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration_seconds,
    SUM(retry_count) as total_retries
FROM workflow_queue
GROUP BY DATE(created_at);

-- Function to update workflow step
CREATE OR REPLACE FUNCTION update_workflow_step(
    p_workflow_id UUID,
    p_step_number INTEGER,
    p_status VARCHAR,
    p_output JSONB DEFAULT NULL,
    p_error TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    -- Update step execution
    UPDATE workflow_step_executions
    SET
        status = p_status,
        output_result = COALESCE(p_output, output_result),
        error_message = p_error,
        completed_at = CASE WHEN p_status IN ('completed', 'failed') THEN NOW() ELSE completed_at END,
        duration_ms = CASE WHEN p_status IN ('completed', 'failed')
            THEN EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
            ELSE duration_ms END
    WHERE workflow_id = p_workflow_id AND step_number = p_step_number;

    -- Update workflow current step
    UPDATE workflow_queue
    SET
        current_step = p_step_number,
        status = CASE
            WHEN p_status = 'failed' THEN 'failed'
            ELSE status
        END,
        error_message = CASE
            WHEN p_status = 'failed' THEN p_error
            ELSE error_message
        END
    WHERE workflow_id = p_workflow_id;
END;
$$ LANGUAGE plpgsql;

-- Function to complete workflow
CREATE OR REPLACE FUNCTION complete_workflow(
    p_workflow_id UUID,
    p_output JSONB DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE workflow_queue
    SET
        status = 'completed',
        completed_at = NOW(),
        output = p_output,
        progress_percent = 100
    WHERE workflow_id = p_workflow_id;
END;
$$ LANGUAGE plpgsql;

-- Insert sample workflow template
INSERT INTO workflow_templates (name, description, category, steps, default_parameters)
VALUES (
    'code_review_workflow',
    'Automated code review pipeline using local AI models',
    'development',
    '[
        {"name": "search_context", "tool": "search_knowledge", "params": {"query": "{{code_context}}", "types": ["code_snippet", "mistake_learned"]}},
        {"name": "analyze_code", "tool": "generate_code", "params": {"prompt": "Review this code for issues: {{code}}", "language": "{{language}}"}},
        {"name": "store_review", "tool": "store_memory", "params": {"content": "{{review_result}}", "memory_type": "code_snippet", "category": "code_review"}}
    ]'::JSONB,
    '{"language": "python", "code_context": "code review"}'::JSONB
) ON CONFLICT (name) DO NOTHING;

INSERT INTO workflow_templates (name, description, category, steps, default_parameters)
VALUES (
    'daily_health_check',
    'Daily system health check and reporting',
    'admin',
    '[
        {"name": "check_health", "tool": "health_check", "params": {}},
        {"name": "get_status", "tool": "get_system_status", "params": {}},
        {"name": "log_result", "tool": "log_audit_event", "params": {"action": "health_check", "resource": "system"}}
    ]'::JSONB,
    '{}'::JSONB
) ON CONFLICT (name) DO NOTHING;

COMMENT ON TABLE workflow_queue IS 'Goose orchestration workflow execution queue';
COMMENT ON TABLE workflow_templates IS 'Reusable workflow templates (blueprints)';
COMMENT ON TABLE workflow_schedules IS 'Scheduled workflow triggers';
