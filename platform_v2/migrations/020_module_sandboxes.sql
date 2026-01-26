-- Migration: 020_module_sandboxes.sql
-- Purpose: Per-module sandbox tracking and configuration
-- Date: 2026-01-13
-- Part of: CodeRabbit + Improvements Lab + Sandbox Integration

-- ==========================================================================
-- MODULE SANDBOXES TABLE
-- Tracks individual module sandbox instances
-- ==========================================================================
CREATE TABLE IF NOT EXISTS module_sandboxes (
    id SERIAL PRIMARY KEY,
    module_id VARCHAR(100) NOT NULL,              -- coderabbit, improvements, ai_bridge, etc.
    sandbox_type VARCHAR(50) DEFAULT 'schema',    -- schema (lightweight) or docker (full isolation)
    schema_name VARCHAR(100),                     -- e.g., sandbox_coderabbit
    container_name VARCHAR(100),                  -- e.g., archie_sandbox_coderabbit
    port INTEGER,                                 -- e.g., 3101
    status VARCHAR(50) DEFAULT 'inactive',        -- inactive, starting, active, testing, stopping
    current_proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    last_test_at TIMESTAMP,

    -- Test results summary
    total_tests_run INTEGER DEFAULT 0,
    tests_passed INTEGER DEFAULT 0,
    tests_failed INTEGER DEFAULT 0,

    -- Constraints
    UNIQUE(module_id)
);

-- Index for quick status lookups
CREATE INDEX IF NOT EXISTS idx_module_sandboxes_status ON module_sandboxes(status);
CREATE INDEX IF NOT EXISTS idx_module_sandboxes_module ON module_sandboxes(module_id);

-- ==========================================================================
-- SANDBOX CONFIGURATION TABLE
-- Global and per-module sandbox settings
-- ==========================================================================
CREATE TABLE IF NOT EXISTS sandbox_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(100) NOT NULL,
    config_value JSONB NOT NULL,
    module_id VARCHAR(100),                       -- NULL = global setting
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER REFERENCES users(id),

    UNIQUE(config_key, module_id)
);

-- ==========================================================================
-- INSERT DEFAULT MODULE SANDBOX RECORDS
-- ==========================================================================
INSERT INTO module_sandboxes (module_id, sandbox_type, schema_name, container_name, port, status)
VALUES
    ('coderabbit', 'schema', 'sandbox_coderabbit', 'archie_sandbox_coderabbit', 3101, 'inactive'),
    ('improvements', 'schema', 'sandbox_improvements', 'archie_sandbox_improvements', 3102, 'inactive'),
    ('ai_bridge', 'docker', 'sandbox_ai_bridge', 'archie_sandbox_ai_bridge', 3103, 'inactive'),
    ('platform', 'docker', 'sandbox_platform', 'archie_sandbox_platform', 3104, 'inactive'),
    ('admin', 'schema', 'sandbox_admin', 'archie_sandbox_admin', 3105, 'inactive'),
    ('consciousness', 'schema', 'sandbox_consciousness', 'archie_sandbox_consciousness', 3106, 'inactive')
ON CONFLICT (module_id) DO NOTHING;

-- ==========================================================================
-- INSERT DEFAULT CONFIGURATION
-- ==========================================================================
INSERT INTO sandbox_config (config_key, config_value, module_id, description)
VALUES
    -- Global settings
    ('default_sandbox_type', '"schema"', NULL, 'Default sandbox type for new modules'),
    ('auto_cleanup_hours', '24', NULL, 'Auto-destroy sandboxes after this many hours of inactivity'),
    ('max_concurrent_sandboxes', '5', NULL, 'Maximum number of active sandboxes at once'),
    ('test_timeout_seconds', '300', NULL, 'Maximum time for test suite to complete'),
    ('auto_test_on_proposal', 'true', NULL, 'Automatically run tests when proposal enters sandbox'),
    ('notify_on_complete', 'true', NULL, 'Send notification when sandbox tests complete'),

    -- Module-specific overrides
    ('sandbox_type', '"docker"', 'ai_bridge', 'AI Bridge requires full Docker isolation'),
    ('sandbox_type', '"docker"', 'platform', 'Full platform changes require Docker isolation'),
    ('test_timeout_seconds', '600', 'platform', 'Platform tests need longer timeout'),
    ('test_timeout_seconds', '120', 'coderabbit', 'CodeRabbit tests are quick')
ON CONFLICT (config_key, module_id) DO NOTHING;

-- ==========================================================================
-- SANDBOX TEST HISTORY TABLE (extends existing sandbox_test_results)
-- Links test results to module sandboxes
-- ==========================================================================
ALTER TABLE sandbox_test_results
ADD COLUMN IF NOT EXISTS module_sandbox_id INTEGER REFERENCES module_sandboxes(id);

-- ==========================================================================
-- FUNCTION: Get sandbox config value with module override
-- ==========================================================================
CREATE OR REPLACE FUNCTION get_sandbox_config(p_key VARCHAR, p_module VARCHAR DEFAULT NULL)
RETURNS JSONB AS $$
DECLARE
    v_value JSONB;
BEGIN
    -- First try module-specific config
    IF p_module IS NOT NULL THEN
        SELECT config_value INTO v_value
        FROM sandbox_config
        WHERE config_key = p_key AND module_id = p_module;

        IF v_value IS NOT NULL THEN
            RETURN v_value;
        END IF;
    END IF;

    -- Fall back to global config
    SELECT config_value INTO v_value
    FROM sandbox_config
    WHERE config_key = p_key AND module_id IS NULL;

    RETURN v_value;
END;
$$ LANGUAGE plpgsql;

-- ==========================================================================
-- VIEW: Active sandboxes with current proposals
-- ==========================================================================
CREATE OR REPLACE VIEW v_active_sandboxes AS
SELECT
    ms.id,
    ms.module_id,
    ms.sandbox_type,
    ms.schema_name,
    ms.container_name,
    ms.port,
    ms.status,
    ms.current_proposal_id,
    ip.title AS proposal_title,
    ip.category AS proposal_category,
    ip.priority AS proposal_priority,
    ms.total_tests_run,
    ms.tests_passed,
    ms.tests_failed,
    ms.last_used_at,
    ms.last_test_at,
    CASE
        WHEN ms.status = 'active' THEN 'http://localhost:' || ms.port || '/sandbox/dashboard'
        ELSE NULL
    END AS access_url
FROM module_sandboxes ms
LEFT JOIN improvement_proposals ip ON ms.current_proposal_id = ip.id
ORDER BY ms.port;

COMMENT ON TABLE module_sandboxes IS 'Per-module sandbox instances for isolated testing';
COMMENT ON TABLE sandbox_config IS 'Global and per-module sandbox configuration settings';
COMMENT ON VIEW v_active_sandboxes IS 'Active sandboxes with their current proposal details';
