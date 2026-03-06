-- Migration 129: Agent Action Benchmarks
-- Adds benchmark infrastructure for testing agent performance on station actions.
-- Part of Project #110: Agent Action Benchmarks.

-- 1. Add test_config to station_actions (benchmark test definition)
ALTER TABLE station_actions ADD COLUMN IF NOT EXISTS test_config JSONB DEFAULT NULL;

-- 2. Benchmark run tracking
CREATE TABLE IF NOT EXISTS action_benchmark_runs (
    id SERIAL PRIMARY KEY,
    action_key VARCHAR(80) NOT NULL,
    station_code VARCHAR(20) NOT NULL,
    test_config JSONB NOT NULL DEFAULT '{}',
    total_agents INT DEFAULT 0,
    completed_agents INT DEFAULT 0,
    failed_agents INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_by INT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_action
    ON action_benchmark_runs(action_key, started_at DESC);

-- 3. Individual agent benchmark results
CREATE TABLE IF NOT EXISTS action_benchmark_results (
    id SERIAL PRIMARY KEY,
    run_id INT NOT NULL REFERENCES action_benchmark_runs(id) ON DELETE CASCADE,
    agent_id INT NOT NULL REFERENCES agents(id),
    agent_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200),
    model_used VARCHAR(100),
    provider VARCHAR(50) DEFAULT 'ollama',
    duration_ms INT DEFAULT 0,
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    response_preview TEXT,
    score REAL DEFAULT 0.0,
    rank INT,
    tested_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_benchmark_results_run
    ON action_benchmark_results(run_id, score DESC);

-- 4. Seed test_config for existing 7 actions
-- Dev Pipeline (ENGINEERING): 3 actions
UPDATE station_actions SET test_config = '{
    "capability": "code_analysis",
    "prompt": "Analyze this Python function for bugs, style issues, and improvements:\n\ndef add(a, b):\n    return a + b",
    "system_prompt": "You are a code reviewer. List issues briefly. Be concise.",
    "description": "Scan trivial function for issues"
}'::jsonb
WHERE action_key = 'dev_pipeline.scan.batch';

UPDATE station_actions SET test_config = '{
    "capability": "code_analysis",
    "prompt": "Review this Python function for correctness and suggest improvements:\n\ndef factorial(n):\n    if n == 0: return 1\n    return n * factorial(n-1)",
    "system_prompt": "You are a code reviewer. List issues briefly. Be concise.",
    "description": "Scan single file function"
}'::jsonb
WHERE action_key = 'dev_pipeline.scan.run';

UPDATE station_actions SET test_config = '{
    "capability": "code_analysis",
    "prompt": "Write a simple pytest test for this function:\n\ndef greet(name):\n    return f\"Hello, {name}!\"",
    "system_prompt": "You are a test engineer. Write one pytest function. Be concise.",
    "description": "Generate simple test case"
}'::jsonb
WHERE action_key = 'dev_pipeline.sandbox.run';

-- Consciousness (ANALYTICS): 4 actions
UPDATE station_actions SET test_config = '{
    "capability": "summarize",
    "prompt": "Analyze this knowledge entry and extract key topics, entities, and a one-sentence summary:\n\nFlask is a micro web framework written in Python. It is classified as a microframework because it does not require particular tools or libraries.",
    "system_prompt": "You are a knowledge analyst. Extract topics, entities, and summary. Be concise.",
    "description": "Analyze short knowledge entry"
}'::jsonb
WHERE action_key = 'consciousness.analysis.start';

UPDATE station_actions SET test_config = '{
    "capability": "embedding",
    "prompt": "Generate a semantic summary suitable for vector embedding:\n\nDocker containers package applications with their dependencies, ensuring consistent deployment across environments.",
    "system_prompt": "Summarize the text in one dense sentence capturing all key concepts.",
    "description": "Prepare text for embedding"
}'::jsonb
WHERE action_key = 'consciousness.embeddings.generate';

UPDATE station_actions SET test_config = '{
    "capability": "code_analysis",
    "prompt": "Analyze this code file summary and categorize it:\n\nFile: app.py\nLanguage: Python\nImports: flask, os, logging\nFunctions: create_app, register_blueprints\nClasses: none",
    "system_prompt": "You are a code indexer. Categorize the file type and purpose in one sentence.",
    "description": "Classify code file metadata"
}'::jsonb
WHERE action_key = 'consciousness.github.reindex';

UPDATE station_actions SET test_config = '{
    "capability": "translate",
    "prompt": "Translate to French: The system is operating normally. All services are online.",
    "system_prompt": "You are a translator. Translate the given text accurately. Output only the translation.",
    "description": "Translate short system text"
}'::jsonb
WHERE action_key = 'consciousness.translate.generate';
