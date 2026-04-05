-- 154_project_knowledge_links.sql
-- Project-Knowledge linking, bridge job project tracking, task agent assignment

-- Junction table for many-to-many project <-> knowledge
CREATE TABLE IF NOT EXISTS project_knowledge_links (
    id SERIAL PRIMARY KEY,
    project_id INT NOT NULL REFERENCES unified_projects(id) ON DELETE CASCADE,
    knowledge_id INT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    link_type VARCHAR(20) NOT NULL DEFAULT 'auto',
    confidence DECIMAL(3,2),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, knowledge_id)
);

CREATE INDEX IF NOT EXISTS idx_pkl_project ON project_knowledge_links(project_id);
CREATE INDEX IF NOT EXISTS idx_pkl_knowledge ON project_knowledge_links(knowledge_id);
CREATE INDEX IF NOT EXISTS idx_pkl_link_type ON project_knowledge_links(link_type);

-- Project embeddings (768-dim, same as knowledge_base)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'unified_projects' AND column_name = 'embedding'
    ) THEN
        ALTER TABLE unified_projects ADD COLUMN embedding vector(768);
    END IF;
END $$;

-- Bridge jobs -> project tracking
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'bridge_jobs' AND column_name = 'project_id'
    ) THEN
        ALTER TABLE bridge_jobs ADD COLUMN project_id INT REFERENCES unified_projects(id);
        CREATE INDEX idx_bridge_jobs_project ON bridge_jobs(project_id);
    END IF;
END $$;

-- Task -> agent assignment
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'unified_tasks' AND column_name = 'assigned_agent'
    ) THEN
        ALTER TABLE unified_tasks ADD COLUMN assigned_agent INT REFERENCES agents(id);
        CREATE INDEX idx_unified_tasks_agent ON unified_tasks(assigned_agent);
    END IF;
END $$;
