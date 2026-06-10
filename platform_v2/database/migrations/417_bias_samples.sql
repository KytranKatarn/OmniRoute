-- Bias sampling results — 10% inline fairness monitoring (Project #358 #3265)
CREATE TABLE IF NOT EXISTS bias_sample_results (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100),
    capability VARCHAR(100),
    model_used VARCHAR(100),
    prompt_snippet TEXT,
    response_snippet TEXT,
    bias_score DECIMAL(5,4),
    bias_band VARCHAR(20),
    rationale TEXT,
    confidence DECIMAL(5,4),
    creed_event_pushed BOOLEAN DEFAULT FALSE,
    sampled_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bias_samples_agent ON bias_sample_results(agent_name);
CREATE INDEX IF NOT EXISTS idx_bias_samples_band ON bias_sample_results(bias_band);
CREATE INDEX IF NOT EXISTS idx_bias_samples_sampled_at ON bias_sample_results(sampled_at);
