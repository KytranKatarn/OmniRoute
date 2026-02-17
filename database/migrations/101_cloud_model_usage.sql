-- Migration 101: Cloud Model Usage Tracking
-- Tracks per-request usage for Ollama Cloud API models (MiniMax M2.5, Qwen3-Coder-Next)
-- Provides weekly and daily summary views for monitoring

CREATE TABLE IF NOT EXISTS cloud_model_usage (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'ollama_cloud',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    response_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    session_id VARCHAR(100),
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    user_id INTEGER,
    task_type VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cloud_usage_model ON cloud_model_usage(model_name);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_created ON cloud_model_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_provider ON cloud_model_usage(provider);

-- Weekly summary view
CREATE OR REPLACE VIEW v_cloud_usage_weekly AS
SELECT
    model_name,
    provider,
    date_trunc('week', created_at) AS week_start,
    COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE success = TRUE) AS successful_requests,
    SUM(prompt_tokens) AS total_prompt_tokens,
    SUM(completion_tokens) AS total_completion_tokens,
    SUM(total_tokens) AS total_tokens,
    AVG(response_ms) FILTER (WHERE success = TRUE) AS avg_response_ms,
    MIN(created_at) AS first_request,
    MAX(created_at) AS last_request
FROM cloud_model_usage
GROUP BY model_name, provider, date_trunc('week', created_at)
ORDER BY week_start DESC, model_name;

-- Daily summary view
CREATE OR REPLACE VIEW v_cloud_usage_daily AS
SELECT
    model_name,
    provider,
    DATE(created_at) AS usage_date,
    COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE success = TRUE) AS successful_requests,
    SUM(total_tokens) AS total_tokens,
    AVG(response_ms) FILTER (WHERE success = TRUE) AS avg_response_ms
FROM cloud_model_usage
GROUP BY model_name, provider, DATE(created_at)
ORDER BY usage_date DESC, model_name;
