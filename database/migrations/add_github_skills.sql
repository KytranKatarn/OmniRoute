-- Migration: Create github_skills table for skill pipeline
-- Project #187: GitHub Skill Pipeline — Auto-Pull, Analyze, Register, Adapt

CREATE TABLE IF NOT EXISTS github_skills (
    id              SERIAL PRIMARY KEY,
    kb_entry_id     INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL,
    repo_name       VARCHAR(255) NOT NULL,
    skill_name      VARCHAR(255) NOT NULL,
    description     TEXT,
    capabilities    JSONB DEFAULT '[]'::jsonb,
    quality_score   INTEGER CHECK (quality_score BETWEEN 1 AND 5),
    status          VARCHAR(30) DEFAULT 'discovered'
                    CHECK (status IN ('discovered', 'analyzing', 'analyzed', 'registered', 'adapted', 'archived')),
    original_repo   VARCHAR(255),
    adapted_from_id INTEGER REFERENCES github_skills(id) ON DELETE SET NULL,
    agent_ids       JSONB DEFAULT '[]'::jsonb,
    analysis        JSONB DEFAULT '{}'::jsonb,
    file_path       TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_github_skills_repo ON github_skills(repo_name);
CREATE INDEX IF NOT EXISTS idx_github_skills_status ON github_skills(status);
CREATE INDEX IF NOT EXISTS idx_github_skills_quality ON github_skills(quality_score);
CREATE UNIQUE INDEX IF NOT EXISTS idx_github_skills_repo_path ON github_skills(repo_name, file_path);

-- Seed existing skills from knowledge_base (discovered status)
INSERT INTO github_skills (kb_entry_id, repo_name, skill_name, description, file_path, status, created_at)
SELECT
    kb.id,
    kb.memory_metadata->>'repo',
    SPLIT_PART(kb.title, ': ', 2),
    LEFT(kb.content, 300),
    kb.file_path,
    'discovered',
    kb.created_at
FROM knowledge_base kb
WHERE kb.knowledge_type = 'github_file'
  AND kb.content IS NOT NULL AND kb.content != ''
  AND (
      kb.title ILIKE '%/skill%/README%'
      OR kb.title ILIKE '%/agent%/README%'
      OR kb.title ILIKE '%/plugin%/README%'
      OR kb.title ILIKE '%skill-creator%'
      OR kb.title ILIKE '%prompt-engineer%'
      OR kb.title ILIKE '%autonomy%'
      OR kb.title ILIKE '%anti-rationalization%'
      OR kb.title ILIKE '%context-engineering%'
      OR kb.title ILIKE '%writing-skills%'
  )
  AND kb.memory_metadata->>'repo' IS NOT NULL
ON CONFLICT (repo_name, file_path) DO NOTHING;
