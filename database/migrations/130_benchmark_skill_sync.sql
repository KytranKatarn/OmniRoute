-- Migration 130: Benchmark → Skill Feedback Loop
-- Auto-adjusts agent_skills.proficiency_level from benchmark scores.
-- Part of Project #110 Phase 5: Benchmark-to-Skills Feedback Loop.

-- 1. Audit table — tracks every skill adjustment from benchmarks
CREATE TABLE IF NOT EXISTS benchmark_skill_updates (
    id SERIAL PRIMARY KEY,
    run_id INT NOT NULL REFERENCES action_benchmark_runs(id),
    agent_id INT NOT NULL REFERENCES agents(id),
    agent_name VARCHAR(100) NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    old_level INT,
    new_level INT NOT NULL,
    benchmark_score REAL NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bsu_agent ON benchmark_skill_updates(agent_id, skill_name);
CREATE INDEX IF NOT EXISTS idx_bsu_run ON benchmark_skill_updates(run_id);

-- 2. Capability-to-skill mapping (reference table)
CREATE TABLE IF NOT EXISTS capability_skill_map (
    capability VARCHAR(80) PRIMARY KEY,
    skill_name VARCHAR(100) NOT NULL
);

INSERT INTO capability_skill_map (capability, skill_name) VALUES
    ('code_analysis', 'code_analysis'),
    ('summarize', 'summarization'),
    ('embedding', 'data_processing'),
    ('translate', 'translation'),
    ('general', 'general_intelligence'),
    ('code_review', 'code_analysis'),
    ('writing', 'content_creation'),
    ('research', 'research'),
    ('classification', 'classification'),
    ('conversation', 'conversation'),
    ('planning', 'planning'),
    ('debugging', 'debugging'),
    ('testing', 'testing'),
    ('documentation', 'documentation')
ON CONFLICT (capability) DO NOTHING;
