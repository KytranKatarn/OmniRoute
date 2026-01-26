-- Token Usage Tracking and Budget Management Migration
-- Run this to add token tracking, cost monitoring, and budget warnings

-- 1. Create token_usage_log table
CREATE TABLE IF NOT EXISTS token_usage_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    provider VARCHAR(50) NOT NULL,  -- ollama, claude, openai, grok
    model VARCHAR(100) NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost DECIMAL(10, 6) NOT NULL DEFAULT 0.0,  -- Cost in USD
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_token_usage_agent ON token_usage_log(agent_id);
CREATE INDEX idx_token_usage_created ON token_usage_log(created_at);
CREATE INDEX idx_token_usage_provider ON token_usage_log(provider);

-- 2. Add budget and cost tracking columns to agents table
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS monthly_budget DECIMAL(10, 2),  -- Monthly budget in USD
    ADD COLUMN IF NOT EXISTS budget_alert_threshold DECIMAL(3, 2) DEFAULT 0.8,  -- Alert at 80% by default
    ADD COLUMN IF NOT EXISTS total_tokens_used BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_cost DECIMAL(10, 2) DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS last_used TIMESTAMP;

-- 3. Create budget_alerts table for tracking warnings
CREATE TABLE IF NOT EXISTS budget_alerts (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    alert_level VARCHAR(20) NOT NULL,  -- 'warning', 'critical'
    message TEXT NOT NULL,
    usage_percent DECIMAL(5, 2),
    monthly_cost DECIMAL(10, 2),
    monthly_budget DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT NOW(),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by INTEGER REFERENCES users(id),
    acknowledged_at TIMESTAMP
);

CREATE INDEX idx_budget_alerts_agent ON budget_alerts(agent_id);
CREATE INDEX idx_budget_alerts_level ON budget_alerts(alert_level);
CREATE INDEX idx_budget_alerts_acknowledged ON budget_alerts(acknowledged);

-- 4. Create cost_summary view for easy monitoring
CREATE OR REPLACE VIEW agent_cost_summary AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.tier,
    a.model,
    a.monthly_budget,
    a.total_cost as lifetime_cost,
    COALESCE(current_month.tokens, 0) as monthly_tokens,
    COALESCE(current_month.cost, 0) as monthly_cost,
    CASE
        WHEN a.monthly_budget IS NOT NULL AND a.monthly_budget > 0
        THEN ROUND((COALESCE(current_month.cost, 0) / a.monthly_budget * 100)::numeric, 2)
        ELSE 0
    END as budget_usage_percent,
    CASE
        WHEN a.monthly_budget IS NOT NULL AND COALESCE(current_month.cost, 0) >= a.monthly_budget
        THEN 'EXCEEDED'
        WHEN a.monthly_budget IS NOT NULL AND COALESCE(current_month.cost, 0) >= (a.monthly_budget * a.budget_alert_threshold)
        THEN 'WARNING'
        ELSE 'OK'
    END as budget_status
FROM agents a
LEFT JOIN (
    SELECT
        agent_id,
        SUM(tokens_used) as tokens,
        SUM(cost) as cost
    FROM token_usage_log
    WHERE created_at >= DATE_TRUNC('month', NOW())
    GROUP BY agent_id
) current_month ON a.id = current_month.agent_id;

-- 5. Add provider cost configuration table
CREATE TABLE IF NOT EXISTS provider_pricing (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,  -- claude, openai, grok, etc
    model VARCHAR(100) NOT NULL,
    input_cost_per_1m DECIMAL(10, 2) NOT NULL,  -- Cost per 1M input tokens
    output_cost_per_1m DECIMAL(10, 2) NOT NULL,  -- Cost per 1M output tokens
    effective_date DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    UNIQUE(provider, model, effective_date)
);

-- Insert current pricing (as of Dec 2024)
INSERT INTO provider_pricing (provider, model, input_cost_per_1m, output_cost_per_1m, notes) VALUES
    -- Claude
    ('claude', 'claude-sonnet-4-20250514', 3.0, 15.0, 'Claude Sonnet 4 - balanced performance'),
    ('claude', 'claude-opus-4-20250514', 15.0, 75.0, 'Claude Opus 4 - highest capability'),

    -- OpenAI
    ('openai', 'gpt-4-turbo', 10.0, 30.0, 'GPT-4 Turbo - fast and capable'),
    ('openai', 'gpt-4', 30.0, 60.0, 'GPT-4 - original version'),
    ('openai', 'gpt-4o', 2.5, 10.0, 'GPT-4o - optimized model'),
    ('openai', 'gpt-3.5-turbo', 0.5, 1.5, 'GPT-3.5 Turbo - cost effective'),
    ('openai', 'o1-preview', 15.0, 60.0, 'OpenAI o1 - advanced reasoning'),

    -- Grok
    ('grok', 'grok-beta', 5.0, 15.0, 'Grok AI - general purpose'),
    ('grok', 'grok-vision-beta', 5.0, 15.0, 'Grok with vision capabilities'),

    -- Ollama (local - no cost)
    ('ollama', 'deepseek-coder-v2:16b', 0.0, 0.0, 'Local model - no API cost'),
    ('ollama', 'qwen2.5-coder:7b', 0.0, 0.0, 'Local model - no API cost'),
    ('ollama', 'deepseek-coder:33b', 0.0, 0.0, 'Local model - no API cost'),
    ('ollama', 'codellama:latest', 0.0, 0.0, 'Local model - no API cost')
ON CONFLICT (provider, model, effective_date) DO NOTHING;

-- 6. Create function to automatically log budget alerts
CREATE OR REPLACE FUNCTION log_budget_alert() RETURNS TRIGGER AS $$
BEGIN
    -- Check if we should log a budget alert
    IF NEW.monthly_budget IS NOT NULL AND NEW.total_cost >= (NEW.monthly_budget * NEW.budget_alert_threshold) THEN
        INSERT INTO budget_alerts (agent_id, alert_level, message, monthly_cost, monthly_budget)
        SELECT
            NEW.id,
            CASE WHEN monthly_cost >= NEW.monthly_budget THEN 'critical' ELSE 'warning' END,
            CASE WHEN monthly_cost >= NEW.monthly_budget
                THEN format('Agent %s has exceeded monthly budget: $%s / $%s', NEW.name, monthly_cost, NEW.monthly_budget)
                ELSE format('Agent %s approaching budget limit: $%s / $%s (%s%%)', NEW.name, monthly_cost, NEW.monthly_budget,
                     ROUND((monthly_cost / NEW.monthly_budget * 100)::numeric, 1))
            END,
            monthly_cost,
            NEW.monthly_budget
        FROM (
            SELECT COALESCE(SUM(cost), 0) as monthly_cost
            FROM token_usage_log
            WHERE agent_id = NEW.id
            AND created_at >= DATE_TRUNC('month', NOW())
        ) costs
        WHERE NOT EXISTS (
            -- Don't create duplicate alerts for the same period
            SELECT 1 FROM budget_alerts
            WHERE agent_id = NEW.id
            AND created_at >= DATE_TRUNC('month', NOW())
            AND acknowledged = FALSE
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agent_budget_check
    AFTER UPDATE OF total_cost ON agents
    FOR EACH ROW
    EXECUTE FUNCTION log_budget_alert();

COMMENT ON TABLE token_usage_log IS 'Tracks token usage and costs for each agent interaction';
COMMENT ON TABLE budget_alerts IS 'Stores budget warning and exceeded alerts for agents';
COMMENT ON VIEW agent_cost_summary IS 'Summary view of agent costs and budget status';
COMMENT ON TABLE provider_pricing IS 'Current pricing for external API providers';
