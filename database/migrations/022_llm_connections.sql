-- Migration 022: LLM Connections Monitor
-- Phase 27: Health monitoring for AI model connections
-- Created: January 16, 2026

-- ============================================================================
-- LLM CONNECTIONS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS llm_connections (
    id SERIAL PRIMARY KEY,

    -- Connection identity
    provider VARCHAR(50) NOT NULL,  -- ollama, claude, openai, grok, gemini, deepseek
    model_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),

    -- Connection details
    endpoint_url VARCHAR(500),
    api_key_configured BOOLEAN DEFAULT FALSE,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'unknown' CHECK (status IN ('online', 'offline', 'degraded', 'unknown')),
    last_check TIMESTAMP WITH TIME ZONE,
    last_success TIMESTAMP WITH TIME ZONE,
    last_failure TIMESTAMP WITH TIME ZONE,

    -- Performance metrics
    avg_latency_ms INTEGER,
    p95_latency_ms INTEGER,
    success_rate DECIMAL(5,2) DEFAULT 100.00,
    total_requests BIGINT DEFAULT 0,
    failed_requests BIGINT DEFAULT 0,

    -- Health check config
    health_check_enabled BOOLEAN DEFAULT TRUE,
    health_check_interval_seconds INTEGER DEFAULT 30,
    failure_threshold INTEGER DEFAULT 3,  -- Mark offline after N failures
    consecutive_failures INTEGER DEFAULT 0,

    -- Cost tracking
    cost_per_1k_input DECIMAL(10,6),
    cost_per_1k_output DECIMAL(10,6),

    -- Metadata
    capabilities JSONB DEFAULT '{}',  -- {vision: true, function_calling: true, etc}
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(provider, model_name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_llm_connections_provider ON llm_connections(provider);
CREATE INDEX IF NOT EXISTS idx_llm_connections_status ON llm_connections(status);
CREATE INDEX IF NOT EXISTS idx_llm_connections_last_check ON llm_connections(last_check DESC);

-- ============================================================================
-- LLM CONNECTION HISTORY (for graphs/trends)
-- ============================================================================

CREATE TABLE IF NOT EXISTS llm_connection_history (
    id SERIAL PRIMARY KEY,
    connection_id INTEGER REFERENCES llm_connections(id) ON DELETE CASCADE,

    check_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(20),
    latency_ms INTEGER,
    error_message TEXT,

    -- Partition by time for efficient queries
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_history_connection ON llm_connection_history(connection_id);
CREATE INDEX IF NOT EXISTS idx_llm_history_time ON llm_connection_history(check_time DESC);

-- ============================================================================
-- LLM ALERTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS llm_alerts (
    id SERIAL PRIMARY KEY,
    connection_id INTEGER REFERENCES llm_connections(id) ON DELETE CASCADE,

    alert_type VARCHAR(30) NOT NULL CHECK (alert_type IN ('offline', 'degraded', 'high_latency', 'error_rate', 'recovered')),
    severity VARCHAR(20) DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'critical')),

    message TEXT NOT NULL,
    details JSONB DEFAULT '{}',

    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by INTEGER,
    acknowledged_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_alerts_connection ON llm_alerts(connection_id);
CREATE INDEX IF NOT EXISTS idx_llm_alerts_unack ON llm_alerts(acknowledged) WHERE NOT acknowledged;

-- ============================================================================
-- VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW llm_status_summary AS
SELECT
    provider,
    COUNT(*) as total_models,
    COUNT(*) FILTER (WHERE status = 'online') as online,
    COUNT(*) FILTER (WHERE status = 'offline') as offline,
    COUNT(*) FILTER (WHERE status = 'degraded') as degraded,
    AVG(avg_latency_ms) as avg_latency,
    AVG(success_rate) as avg_success_rate
FROM llm_connections
GROUP BY provider;

CREATE OR REPLACE VIEW recent_llm_alerts AS
SELECT
    a.id,
    a.alert_type,
    a.severity,
    a.message,
    a.created_at,
    a.acknowledged,
    c.provider,
    c.model_name,
    c.display_name
FROM llm_alerts a
JOIN llm_connections c ON a.connection_id = c.id
WHERE a.created_at > NOW() - INTERVAL '24 hours'
ORDER BY a.created_at DESC;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Update connection status
CREATE OR REPLACE FUNCTION update_llm_status(
    p_provider VARCHAR,
    p_model VARCHAR,
    p_status VARCHAR,
    p_latency INTEGER DEFAULT NULL,
    p_error TEXT DEFAULT NULL
) RETURNS void AS $$
DECLARE
    v_connection_id INTEGER;
    v_prev_status VARCHAR;
    v_failures INTEGER;
BEGIN
    -- Get connection
    SELECT id, status, consecutive_failures
    INTO v_connection_id, v_prev_status, v_failures
    FROM llm_connections
    WHERE provider = p_provider AND model_name = p_model;

    IF v_connection_id IS NULL THEN
        RETURN;
    END IF;

    -- Update based on status
    IF p_status = 'online' THEN
        UPDATE llm_connections SET
            status = 'online',
            last_check = NOW(),
            last_success = NOW(),
            consecutive_failures = 0,
            avg_latency_ms = COALESCE((avg_latency_ms * 0.9 + p_latency * 0.1)::INTEGER, p_latency),
            total_requests = total_requests + 1,
            updated_at = NOW()
        WHERE id = v_connection_id;

        -- Create recovery alert if was offline
        IF v_prev_status = 'offline' THEN
            INSERT INTO llm_alerts (connection_id, alert_type, severity, message)
            VALUES (v_connection_id, 'recovered', 'info',
                    p_provider || '/' || p_model || ' is back online');
        END IF;
    ELSE
        -- Failure
        v_failures := v_failures + 1;

        UPDATE llm_connections SET
            last_check = NOW(),
            last_failure = NOW(),
            consecutive_failures = v_failures,
            failed_requests = failed_requests + 1,
            total_requests = total_requests + 1,
            status = CASE WHEN v_failures >= failure_threshold THEN 'offline' ELSE 'degraded' END,
            updated_at = NOW()
        WHERE id = v_connection_id;

        -- Create alert if crossing threshold
        IF v_failures = 3 THEN
            INSERT INTO llm_alerts (connection_id, alert_type, severity, message, details)
            VALUES (v_connection_id, 'offline', 'critical',
                    p_provider || '/' || p_model || ' is offline',
                    jsonb_build_object('error', p_error, 'failures', v_failures));
        END IF;
    END IF;

    -- Log to history
    INSERT INTO llm_connection_history (connection_id, status, latency_ms, error_message)
    VALUES (v_connection_id, p_status, p_latency, p_error);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SEED DATA: Known LLM Connections
-- ============================================================================

INSERT INTO llm_connections (provider, model_name, display_name, endpoint_url, capabilities, cost_per_1k_input, cost_per_1k_output)
VALUES
    -- Ollama (Local)
    ('ollama', 'deepseek-coder-v2:16b', 'DeepSeek Coder v2', 'http://localhost:11434',
     '{"coding": true, "local": true}', 0, 0),
    ('ollama', 'qwen2.5-coder:7b', 'Qwen 2.5 Coder', 'http://localhost:11434',
     '{"coding": true, "local": true}', 0, 0),
    ('ollama', 'llama3.2:latest', 'Llama 3.2', 'http://localhost:11434',
     '{"general": true, "local": true}', 0, 0),
    ('ollama', 'mistral:latest', 'Mistral', 'http://localhost:11434',
     '{"general": true, "local": true}', 0, 0),

    -- Claude (API)
    ('claude', 'claude-sonnet-4-20250514', 'Claude Sonnet 4', 'https://api.anthropic.com',
     '{"vision": true, "function_calling": true, "coding": true}', 0.003, 0.015),
    ('claude', 'claude-opus-4-20250514', 'Claude Opus 4', 'https://api.anthropic.com',
     '{"vision": true, "function_calling": true, "coding": true, "reasoning": true}', 0.015, 0.075),

    -- OpenAI (API)
    ('openai', 'gpt-4o', 'GPT-4o', 'https://api.openai.com',
     '{"vision": true, "function_calling": true}', 0.005, 0.015),
    ('openai', 'gpt-4o-mini', 'GPT-4o Mini', 'https://api.openai.com',
     '{"vision": true, "function_calling": true}', 0.00015, 0.0006),

    -- Grok (API)
    ('grok', 'grok-beta', 'Grok Beta', 'https://api.x.ai',
     '{"general": true}', 0.005, 0.015),

    -- Gemini (API)
    ('gemini', 'gemini-pro', 'Gemini Pro', 'https://generativelanguage.googleapis.com',
     '{"vision": true, "function_calling": true}', 0.00025, 0.0005)
ON CONFLICT (provider, model_name) DO NOTHING;

-- ============================================================================
-- DONE
-- ============================================================================
SELECT 'Migration 022: LLM Connections Monitor - COMPLETE' as status;
