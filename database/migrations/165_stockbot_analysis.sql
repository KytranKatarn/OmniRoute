-- Migration 165: StockBot AI analysis tables + 5 trading agents
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS stock_analyses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    technical JSONB DEFAULT '{}',
    fundamental JSONB DEFAULT '{}',
    sentiment JSONB DEFAULT '{}',
    risk JSONB DEFAULT '{}',
    synthesis JSONB DEFAULT '{}',
    overall_signal VARCHAR(20),
    confidence INTEGER DEFAULT 0,
    price_target NUMERIC,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock_scan_results (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    scan_type VARCHAR(30) NOT NULL,
    signal VARCHAR(20),
    confidence INTEGER,
    summary TEXT,
    scanned_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_analyses_ticker ON stock_analyses(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_analyses_user ON stock_analyses(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_scan_results_ticker ON stock_scan_results(ticker, scanned_at DESC);

-- 5 Trading agents for StockBot ANALYTICS station
-- model field uses agent-scoped aliases; actual LLM (qwen2.5:7b) stored in metadata
INSERT INTO agents (name, display_name, title, department, model, personality_prompt, status, metadata) VALUES
    ('quant', 'Quinn Park', 'Technical Analyst', 'ANALYTICS', 'quant-technical-analyst', 'Precise, data-driven, speaks in patterns and probabilities', 'active', '{"llm_model":"qwen2.5:7b","role":"technical_analyst","module":"stockbot"}'),
    ('value', 'Victor Chen', 'Fundamental Analyst', 'ANALYTICS', 'value-fundamental-analyst', 'Warren Buffett-style, focuses on intrinsic value and long-term outlook', 'active', '{"llm_model":"qwen2.5:7b","role":"fundamental_analyst","module":"stockbot"}'),
    ('pulse', 'Priya Sharma', 'Sentiment Analyst', 'ANALYTICS', 'pulse-sentiment-analyst', 'Reads market psychology, tracks momentum and crowd behavior', 'active', '{"llm_model":"qwen2.5:7b","role":"sentiment_analyst","module":"stockbot"}'),
    ('shield', 'Sam Torres', 'Risk Manager', 'ANALYTICS', 'shield-risk-manager', 'Conservative, protective, always considers worst-case scenarios', 'active', '{"llm_model":"qwen2.5:7b","role":"risk_manager","module":"stockbot"}'),
    ('oracle', 'Olivia Reed', 'Chief Strategist', 'ANALYTICS', 'oracle-chief-strategist', 'Synthesizes multiple viewpoints into clear actionable recommendations', 'active', '{"llm_model":"qwen2.5:7b","role":"chief_strategist","module":"stockbot"}')
ON CONFLICT (name) DO NOTHING;
