-- Benchmark Model Assignment Pipeline
-- Stores per-model benchmark results by skill category for roster model updates.

CREATE TABLE IF NOT EXISTS agent_benchmark_results (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    model_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(50) NOT NULL,
    task_description TEXT,
    score DECIMAL(5,2),
    response_time_ms INTEGER,
    quality_rating DECIMAL(3,2),
    tokens_used INTEGER,
    benchmark_date TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_benchmark_skill_model
    ON agent_benchmark_results (skill_category, model_name);
CREATE INDEX IF NOT EXISTS idx_benchmark_agent
    ON agent_benchmark_results (agent_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_date
    ON agent_benchmark_results (benchmark_date);
