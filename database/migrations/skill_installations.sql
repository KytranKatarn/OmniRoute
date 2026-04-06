-- Skill installations tracking — one row per skill per target
-- Tracks install, test, and adaptation state independently per target
CREATE TABLE IF NOT EXISTS skill_installations (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES github_skills(id) ON DELETE CASCADE,
    target VARCHAR(30) NOT NULL,
    install_path TEXT NOT NULL,
    normalized_content TEXT,

    -- Structural validation
    struct_valid BOOLEAN,
    struct_errors JSONB DEFAULT '[]'::jsonb,

    -- Dry-run testing
    dry_run_passed BOOLEAN,
    dry_run_prompt TEXT,
    dry_run_output TEXT,
    dry_run_assertions JSONB DEFAULT '{}'::jsonb,

    -- Adaptation
    adapted BOOLEAN DEFAULT FALSE,
    adapted_content TEXT,
    adapted_at TIMESTAMP,

    -- Timestamps
    installed_at TIMESTAMP DEFAULT NOW(),
    tested_at TIMESTAMP,

    CONSTRAINT uq_skill_target UNIQUE(skill_id, target)
);

CREATE INDEX IF NOT EXISTS idx_skill_installations_target ON skill_installations(target);
CREATE INDEX IF NOT EXISTS idx_skill_installations_tested ON skill_installations(dry_run_passed) WHERE dry_run_passed IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_skill_installations_untested ON skill_installations(id) WHERE struct_valid IS NULL;
