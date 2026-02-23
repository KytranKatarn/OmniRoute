-- 119_project_ideas.sql
-- Dev HQ Ideas Board — lightweight idea tracking with promote-to-project

BEGIN;

CREATE TABLE IF NOT EXISTS project_ideas (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) DEFAULT 'feature',
    priority INTEGER DEFAULT 5,
    status VARCHAR(50) DEFAULT 'new',
    tags TEXT[] DEFAULT '{}',
    promoted_to_project_id INTEGER REFERENCES unified_projects(id),
    metadata JSONB DEFAULT '{}',
    created_by_user_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ideas_status ON project_ideas(status);
CREATE INDEX IF NOT EXISTS idx_ideas_category ON project_ideas(category);

COMMIT;
