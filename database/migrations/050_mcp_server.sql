-- ============================================================================
-- Migration 050: MCP Server Tables
-- Phase 50: AI Integration Hub - Model Context Protocol Server
-- ============================================================================

-- MCP API Keys for authentication
CREATE TABLE IF NOT EXISTS mcp_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) NOT NULL,
    key_prefix VARCHAR(10) NOT NULL,  -- First 8 chars for identification
    name VARCHAR(100) NOT NULL,
    description TEXT,
    permissions JSONB DEFAULT '["read"]',  -- ["read", "write", "admin"]
    allowed_tools JSONB DEFAULT '[]',  -- Empty = all tools, or specific tool names
    rate_limit_per_minute INTEGER DEFAULT 60,
    rate_limit_per_hour INTEGER DEFAULT 1000,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Index for fast key lookup
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_hash ON mcp_api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_prefix ON mcp_api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_mcp_api_keys_user ON mcp_api_keys(user_id);

-- MCP Tool Usage Log for audit and analytics
CREATE TABLE IF NOT EXISTS mcp_tool_usage (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER REFERENCES mcp_api_keys(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    session_id VARCHAR(100),
    tool_name VARCHAR(100) NOT NULL,
    tool_category VARCHAR(50),
    input_params JSONB,
    output_summary TEXT,
    output_size_bytes INTEGER,
    execution_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_code VARCHAR(50),
    error_message TEXT,
    client_info JSONB,  -- User agent, IP, etc.
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for usage queries
CREATE INDEX IF NOT EXISTS idx_mcp_tool_usage_key ON mcp_tool_usage(api_key_id);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_usage_tool ON mcp_tool_usage(tool_name);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_usage_created ON mcp_tool_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_usage_session ON mcp_tool_usage(session_id);

-- MCP Tool Definitions (allows dynamic tool registration)
CREATE TABLE IF NOT EXISTS mcp_tool_definitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    category VARCHAR(50) NOT NULL,  -- knowledge, creation, business, admin, etc.
    display_name VARCHAR(150),
    description TEXT NOT NULL,
    input_schema JSONB NOT NULL,  -- JSON Schema for input validation
    output_schema JSONB,  -- Expected output schema
    endpoint_path VARCHAR(255),  -- Internal API endpoint to call
    http_method VARCHAR(10) DEFAULT 'POST',
    handler_function VARCHAR(255),  -- Python function path if not using HTTP
    is_enabled BOOLEAN DEFAULT TRUE,
    requires_auth BOOLEAN DEFAULT TRUE,
    required_permissions JSONB DEFAULT '["read"]',
    rate_limit_override INTEGER,  -- Override default rate limit
    timeout_ms INTEGER DEFAULT 30000,
    cache_ttl_seconds INTEGER DEFAULT 0,  -- 0 = no caching
    examples JSONB DEFAULT '[]',  -- Example inputs/outputs for documentation
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_definitions_category ON mcp_tool_definitions(category);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_definitions_enabled ON mcp_tool_definitions(is_enabled);

-- MCP Sessions for tracking conversations
CREATE TABLE IF NOT EXISTS mcp_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) UNIQUE NOT NULL,
    api_key_id INTEGER REFERENCES mcp_api_keys(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    client_name VARCHAR(100),  -- e.g., "claude-code", "custom-agent"
    client_version VARCHAR(50),
    started_at TIMESTAMP DEFAULT NOW(),
    last_activity_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    tool_calls_count INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mcp_sessions_session_id ON mcp_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_mcp_sessions_api_key ON mcp_sessions(api_key_id);

-- Rate limiting tracking
CREATE TABLE IF NOT EXISTS mcp_rate_limits (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER REFERENCES mcp_api_keys(id) ON DELETE CASCADE,
    window_start TIMESTAMP NOT NULL,
    window_type VARCHAR(10) NOT NULL,  -- 'minute' or 'hour'
    request_count INTEGER DEFAULT 1,
    UNIQUE(api_key_id, window_start, window_type)
);

CREATE INDEX IF NOT EXISTS idx_mcp_rate_limits_key_window ON mcp_rate_limits(api_key_id, window_start);

-- ============================================================================
-- Helper Functions
-- ============================================================================

-- Function to check rate limit
CREATE OR REPLACE FUNCTION check_mcp_rate_limit(
    p_api_key_id INTEGER,
    p_limit_per_minute INTEGER,
    p_limit_per_hour INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    minute_count INTEGER;
    hour_count INTEGER;
    minute_start TIMESTAMP;
    hour_start TIMESTAMP;
BEGIN
    minute_start := date_trunc('minute', NOW());
    hour_start := date_trunc('hour', NOW());

    -- Check minute limit
    SELECT COALESCE(SUM(request_count), 0) INTO minute_count
    FROM mcp_rate_limits
    WHERE api_key_id = p_api_key_id
      AND window_type = 'minute'
      AND window_start = minute_start;

    IF minute_count >= p_limit_per_minute THEN
        RETURN FALSE;
    END IF;

    -- Check hour limit
    SELECT COALESCE(SUM(request_count), 0) INTO hour_count
    FROM mcp_rate_limits
    WHERE api_key_id = p_api_key_id
      AND window_type = 'hour'
      AND window_start = hour_start;

    IF hour_count >= p_limit_per_hour THEN
        RETURN FALSE;
    END IF;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to increment rate limit counter
CREATE OR REPLACE FUNCTION increment_mcp_rate_limit(p_api_key_id INTEGER)
RETURNS VOID AS $$
BEGIN
    -- Increment minute counter
    INSERT INTO mcp_rate_limits (api_key_id, window_start, window_type, request_count)
    VALUES (p_api_key_id, date_trunc('minute', NOW()), 'minute', 1)
    ON CONFLICT (api_key_id, window_start, window_type)
    DO UPDATE SET request_count = mcp_rate_limits.request_count + 1;

    -- Increment hour counter
    INSERT INTO mcp_rate_limits (api_key_id, window_start, window_type, request_count)
    VALUES (p_api_key_id, date_trunc('hour', NOW()), 'hour', 1)
    ON CONFLICT (api_key_id, window_start, window_type)
    DO UPDATE SET request_count = mcp_rate_limits.request_count + 1;

    -- Cleanup old rate limit records (older than 2 hours)
    DELETE FROM mcp_rate_limits WHERE window_start < NOW() - INTERVAL '2 hours';
END;
$$ LANGUAGE plpgsql;

-- Function to generate API key statistics
CREATE OR REPLACE FUNCTION get_mcp_api_key_stats(p_api_key_id INTEGER)
RETURNS TABLE (
    total_calls BIGINT,
    successful_calls BIGINT,
    failed_calls BIGINT,
    avg_execution_time_ms NUMERIC,
    most_used_tool VARCHAR,
    last_used TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT as total_calls,
        COUNT(*) FILTER (WHERE success = TRUE)::BIGINT as successful_calls,
        COUNT(*) FILTER (WHERE success = FALSE)::BIGINT as failed_calls,
        ROUND(AVG(execution_time_ms)::NUMERIC, 2) as avg_execution_time_ms,
        (SELECT tool_name FROM mcp_tool_usage WHERE api_key_id = p_api_key_id
         GROUP BY tool_name ORDER BY COUNT(*) DESC LIMIT 1) as most_used_tool,
        MAX(created_at) as last_used
    FROM mcp_tool_usage
    WHERE api_key_id = p_api_key_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Views
-- ============================================================================

-- View for MCP dashboard statistics
CREATE OR REPLACE VIEW v_mcp_stats AS
SELECT
    (SELECT COUNT(*) FROM mcp_api_keys WHERE is_active = TRUE) as active_api_keys,
    (SELECT COUNT(*) FROM mcp_tool_definitions WHERE is_enabled = TRUE) as enabled_tools,
    (SELECT COUNT(*) FROM mcp_sessions WHERE ended_at IS NULL
     AND last_activity_at > NOW() - INTERVAL '1 hour') as active_sessions,
    (SELECT COUNT(*) FROM mcp_tool_usage WHERE created_at > NOW() - INTERVAL '24 hours') as calls_24h,
    (SELECT COUNT(*) FROM mcp_tool_usage WHERE created_at > NOW() - INTERVAL '1 hour') as calls_1h,
    (SELECT ROUND(AVG(execution_time_ms)::NUMERIC, 2) FROM mcp_tool_usage
     WHERE created_at > NOW() - INTERVAL '1 hour') as avg_response_time_ms,
    (SELECT COUNT(*) FILTER (WHERE success = FALSE) * 100.0 / NULLIF(COUNT(*), 0)
     FROM mcp_tool_usage WHERE created_at > NOW() - INTERVAL '24 hours') as error_rate_24h;

-- View for tool usage breakdown
CREATE OR REPLACE VIEW v_mcp_tool_usage_summary AS
SELECT
    tool_name,
    tool_category,
    COUNT(*) as total_calls,
    COUNT(*) FILTER (WHERE success = TRUE) as successful_calls,
    ROUND(AVG(execution_time_ms)::NUMERIC, 2) as avg_time_ms,
    MAX(created_at) as last_called
FROM mcp_tool_usage
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY tool_name, tool_category
ORDER BY total_calls DESC;

-- ============================================================================
-- Insert Default Tool Definitions
-- ============================================================================

-- Knowledge & Memory Tools
INSERT INTO mcp_tool_definitions (name, category, display_name, description, input_schema, endpoint_path, http_method) VALUES
('search_knowledge', 'knowledge', 'Search Knowledge Base',
 'Search the unified knowledge base for relevant information, code snippets, and documentation.',
 '{"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}, "limit": {"type": "integer", "default": 10}, "types": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]}',
 '/tools/consciousness/api/knowledge/search', 'GET'),

('store_memory', 'knowledge', 'Store Memory',
 'Store information in long-term memory for future recall.',
 '{"type": "object", "properties": {"content": {"type": "string"}, "memory_type": {"type": "string", "enum": ["fact", "preference", "pattern", "decision"]}, "importance": {"type": "number", "minimum": 0, "maximum": 1}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["content"]}',
 '/tools/consciousness/api/memory', 'POST'),

('get_preferences', 'knowledge', 'Get User Preferences',
 'Retrieve learned user preferences and settings.',
 '{"type": "object", "properties": {"category": {"type": "string"}, "user_id": {"type": "integer"}}}',
 '/tools/consciousness/api/memory/preferences', 'GET')
ON CONFLICT (name) DO NOTHING;

-- Creation Tools
INSERT INTO mcp_tool_definitions (name, category, display_name, description, input_schema, endpoint_path, http_method) VALUES
('list_projects', 'creation', 'List Projects',
 'List all projects in Project Builder.',
 '{"type": "object", "properties": {"status": {"type": "string"}, "limit": {"type": "integer", "default": 20}}}',
 '/tools/project-builder/api/projects', 'GET'),

('create_project', 'creation', 'Create Project',
 'Create a new project in Project Builder.',
 '{"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "template": {"type": "string"}, "tech_stack": {"type": "object"}}, "required": ["name"]}',
 '/tools/project-builder/api/projects', 'POST'),

('import_figma', 'creation', 'Import Figma Design',
 'Import a design from Figma and parse it for code generation.',
 '{"type": "object", "properties": {"file_key": {"type": "string"}, "node_id": {"type": "string"}}, "required": ["file_key"]}',
 '/tools/figma/api/parse', 'POST')
ON CONFLICT (name) DO NOTHING;

-- Business Tools
INSERT INTO mcp_tool_definitions (name, category, display_name, description, input_schema, endpoint_path, http_method) VALUES
('create_invoice', 'business', 'Create Invoice',
 'Create a new invoice for a customer.',
 '{"type": "object", "properties": {"customer_id": {"type": "integer"}, "items": {"type": "array"}, "due_date": {"type": "string", "format": "date"}}, "required": ["customer_id", "items"]}',
 '/tools/invoicing/api/invoices', 'POST'),

('send_email', 'business', 'Send Email',
 'Send an email via the Email Manager.',
 '{"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "template_id": {"type": "integer"}}, "required": ["to", "subject", "body"]}',
 '/tools/email-manager/api/send', 'POST'),

('get_crm_contacts', 'business', 'Get CRM Contacts',
 'Search and retrieve contacts from CRM.',
 '{"type": "object", "properties": {"query": {"type": "string"}, "segment": {"type": "string"}, "limit": {"type": "integer", "default": 50}}}',
 '/tools/crm/api/contacts', 'GET')
ON CONFLICT (name) DO NOTHING;

-- Admin Tools
INSERT INTO mcp_tool_definitions (name, category, display_name, description, input_schema, endpoint_path, http_method) VALUES
('get_system_status', 'admin', 'Get System Status',
 'Get the current status of all A.R.C.H.I.E. modules and services.',
 '{"type": "object", "properties": {}}',
 '/api/modules/health', 'GET'),

('assign_agent', 'admin', 'Assign Agent',
 'Assign an AI agent to a station or task.',
 '{"type": "object", "properties": {"agent_id": {"type": "integer"}, "station_id": {"type": "integer"}, "task_description": {"type": "string"}}, "required": ["agent_id"]}',
 '/tools/team-management/api/stations/drag-drop', 'POST'),

('run_backup', 'admin', 'Run Backup',
 'Trigger a system backup.',
 '{"type": "object", "properties": {"components": {"type": "array", "items": {"type": "string"}}, "description": {"type": "string"}}}',
 '/tools/backup-manager/api/backup', 'POST')
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- Create default admin API key (for testing)
-- ============================================================================
-- Note: In production, generate keys through the UI
-- This creates a test key with hash of 'archie-mcp-test-key-2026'
INSERT INTO mcp_api_keys (user_id, key_hash, key_prefix, name, description, permissions)
SELECT
    1,  -- Admin user
    encode(sha256('archie-mcp-test-key-2026'::bytea), 'hex'),
    'archie-m',
    'Development Test Key',
    'Default API key for development and testing. Replace in production.',
    '["read", "write", "admin"]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM mcp_api_keys WHERE name = 'Development Test Key');

COMMIT;
