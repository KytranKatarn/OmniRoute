-- ============================================================================
-- Migration 007: Sandbox Testing Enhancement
-- Date: 2026-01-01
-- Purpose: Add TEST status workflow and sandbox testing infrastructure
-- ============================================================================

-- Add new columns to improvement_proposals for sandbox testing
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS test_status VARCHAR(50),  -- 'pending', 'running', 'passed', 'failed'
ADD COLUMN IF NOT EXISTS test_started_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS test_completed_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS test_duration_seconds INTEGER,
ADD COLUMN IF NOT EXISTS test_results_summary JSONB,
ADD COLUMN IF NOT EXISTS sandbox_type VARCHAR(30),  -- 'docker_container', 'schema_separation', 'none'
ADD COLUMN IF NOT EXISTS sandbox_created_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS sandbox_destroyed_at TIMESTAMP;

-- Add new columns to sandbox_instances for enhanced tracking
ALTER TABLE sandbox_instances
ADD COLUMN IF NOT EXISTS sandbox_url VARCHAR(255),  -- URL if accessible
ADD COLUMN IF NOT EXISTS resource_usage JSONB,  -- CPU, memory, disk usage
ADD COLUMN IF NOT EXISTS test_suite_results JSONB,  -- Results from each test suite
ADD COLUMN IF NOT EXISTS health_check_status VARCHAR(30),  -- 'healthy', 'unhealthy', 'unknown'
ADD COLUMN IF NOT EXISTS health_check_last_run TIMESTAMP;

-- Table: Sandbox Test Suites
-- Defines different test suites that can be run in sandboxes
CREATE TABLE IF NOT EXISTS sandbox_test_suites (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    test_type VARCHAR(50),  -- 'unit', 'integration', 'e2e', 'performance', 'security'
    test_command TEXT,  -- Command to run the test suite
    timeout_seconds INTEGER DEFAULT 300,
    required BOOLEAN DEFAULT FALSE,  -- Must pass for approval
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table: Sandbox Test Results
-- Stores individual test results from sandbox executions
CREATE TABLE IF NOT EXISTS sandbox_test_results (
    id SERIAL PRIMARY KEY,
    sandbox_id INTEGER REFERENCES sandbox_instances(id) ON DELETE CASCADE,
    test_suite_id INTEGER REFERENCES sandbox_test_suites(id),
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    test_name VARCHAR(255),
    status VARCHAR(30),  -- 'passed', 'failed', 'skipped', 'error'
    duration_ms INTEGER,
    error_message TEXT,
    stack_trace TEXT,
    output TEXT,
    metadata JSONB,
    executed_at TIMESTAMP DEFAULT NOW()
);

-- Table: Sandbox Health Checks
-- Tracks health check results for sandboxes
CREATE TABLE IF NOT EXISTS sandbox_health_checks (
    id SERIAL PRIMARY KEY,
    sandbox_id INTEGER REFERENCES sandbox_instances(id) ON DELETE CASCADE,
    check_type VARCHAR(50),  -- 'http', 'database', 'service', 'resource'
    status VARCHAR(30),  -- 'healthy', 'unhealthy', 'degraded'
    response_time_ms INTEGER,
    details JSONB,
    checked_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_proposals_test_status ON improvement_proposals(test_status, test_started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sandbox_instances_status ON sandbox_instances(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_results_sandbox ON sandbox_test_results(sandbox_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_results_proposal ON sandbox_test_results(proposal_id, status);
CREATE INDEX IF NOT EXISTS idx_health_checks_sandbox ON sandbox_health_checks(sandbox_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_suites_enabled ON sandbox_test_suites(enabled, test_type);

-- Insert default test suites
INSERT INTO sandbox_test_suites (name, description, test_type, test_command, timeout_seconds, required, enabled)
VALUES
    ('Python Syntax Check', 'Validate Python syntax for all .py files', 'unit', 'python -m py_compile', 60, TRUE, TRUE),
    ('Unit Tests', 'Run pytest unit tests', 'unit', 'pytest tests/unit -v', 300, TRUE, TRUE),
    ('Integration Tests', 'Run pytest integration tests', 'integration', 'pytest tests/integration -v', 600, FALSE, TRUE),
    ('Security Scan', 'Run security vulnerability scan', 'security', 'bandit -r . -f json', 300, TRUE, TRUE)
ON CONFLICT DO NOTHING;

-- Add comments for documentation
COMMENT ON TABLE sandbox_test_suites IS 'Defines test suites that can be run in sandboxes';
COMMENT ON TABLE sandbox_test_results IS 'Stores individual test results from sandbox executions';
COMMENT ON TABLE sandbox_health_checks IS 'Tracks health check results for running sandboxes';
COMMENT ON COLUMN improvement_proposals.test_status IS 'Current testing status: pending, running, passed, failed';
COMMENT ON COLUMN improvement_proposals.test_results_summary IS 'Summary of all test results in JSON format';
COMMENT ON COLUMN sandbox_instances.test_suite_results IS 'Results from each test suite execution';

-- Update existing sandbox_instances to have default status
UPDATE sandbox_instances SET status = 'destroyed' WHERE status IS NULL;
UPDATE sandbox_instances SET sandbox_type = 'schema_separation' WHERE sandbox_type IS NULL;

-- View: Active Sandboxes with Test Status
CREATE OR REPLACE VIEW active_sandboxes_view AS
SELECT
    si.id as sandbox_id,
    si.proposal_id,
    p.title as proposal_title,
    p.test_status,
    si.sandbox_type,
    si.status as sandbox_status,
    si.created_at,
    si.health_check_status,
    (
        SELECT COUNT(*)
        FROM sandbox_test_results str
        WHERE str.sandbox_id = si.id AND str.status = 'passed'
    ) as tests_passed,
    (
        SELECT COUNT(*)
        FROM sandbox_test_results str
        WHERE str.sandbox_id = si.id AND str.status = 'failed'
    ) as tests_failed,
    (
        SELECT COUNT(*)
        FROM sandbox_test_results str
        WHERE str.sandbox_id = si.id
    ) as total_tests
FROM sandbox_instances si
JOIN improvement_proposals p ON si.proposal_id = p.id
WHERE si.status IN ('creating', 'ready', 'testing')
ORDER BY si.created_at DESC;

COMMENT ON VIEW active_sandboxes_view IS 'Shows all active sandboxes with their test status';
