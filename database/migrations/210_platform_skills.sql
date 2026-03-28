BEGIN;
CREATE TABLE IF NOT EXISTS platform_skills (
    id SERIAL PRIMARY KEY,
    skill_name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    tier INTEGER NOT NULL,
    department VARCHAR(100),
    agent_director VARCHAR(50),
    capability VARCHAR(50),
    prompt_template TEXT NOT NULL,
    system_prompt TEXT DEFAULT '',
    requires_file BOOLEAN DEFAULT false,
    requires_context BOOLEAN DEFAULT false,
    source VARCHAR(20) DEFAULT 'platform',
    github_skill_id INTEGER,
    status VARCHAR(20) DEFAULT 'active',
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_platform_skills_tier ON platform_skills (tier);
CREATE INDEX IF NOT EXISTS idx_platform_skills_dept ON platform_skills (department);
CREATE INDEX IF NOT EXISTS idx_platform_skills_status ON platform_skills (status);
COMMIT;
