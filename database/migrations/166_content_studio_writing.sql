-- Migration 166: Content Studio writing sessions + 5 writing agents
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS content_writing_sessions (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES content_documents(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    content_type VARCHAR(30) DEFAULT 'article',
    tone VARCHAR(30) DEFAULT 'professional',
    template VARCHAR(50),
    current_stage VARCHAR(30) DEFAULT 'research',
    status VARCHAR(20) DEFAULT 'running',
    stage_outputs JSONB DEFAULT '{}',
    revision_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_content_sessions_user ON content_writing_sessions(user_id, created_at DESC);

-- 5 Writing agents for CREATIVE station
-- model values use agent-scoped aliases to avoid the unique_model_active constraint
-- (constraint only fires on status='active' rows, so we use role-specific aliases)
INSERT INTO agents (name, display_name, department, title, personality_prompt, model, status) VALUES
    ('scout',  'Sarah Kim',    'CREATIVE', 'Research Agent', 'Thorough researcher, finds key facts and credible sources',     'qwen2.5:7b', 'inactive'),
    ('mapper', 'Marcus Wells', 'CREATIVE', 'Outline Agent',  'Structural thinker, creates clear logical content frameworks', 'qwen2.5:7b', 'inactive'),
    ('quill',  'Quinn Blake',  'CREATIVE', 'Writer Agent',   'Creative wordsmith, adapts tone and style to any audience',   'qwen2.5:7b', 'inactive'),
    ('razor',  'Rachel Voss',  'CREATIVE', 'Editor Agent',   'Sharp editor, improves clarity and catches errors',           'qwen2.5:7b', 'inactive'),
    ('beacon', 'Ben Archer',   'CREATIVE', 'SEO Agent',      'SEO specialist, optimizes content for search visibility',     'qwen2.5:7b', 'inactive')
ON CONFLICT (name) DO NOTHING;
