-- GitHub Integration Tables
-- Version: 3.1.2
-- Date: 2025-12-31

-- Table for tracking GitHub repositories
CREATE TABLE IF NOT EXISTS github_repositories (
    id SERIAL PRIMARY KEY,
    repo_name VARCHAR(255) NOT NULL UNIQUE,
    repo_type VARCHAR(50) NOT NULL,  -- 'website', 'ai-agents', 'prompts', 'n8n'
    local_path TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'not_cloned',  -- 'not_cloned', 'cloned', 'error'
    indexed BOOLEAN DEFAULT FALSE,
    indexed_files INTEGER DEFAULT 0,
    cloned_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW(),
    last_pull TIMESTAMP,
    last_push TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table for knowledge base (indexed repository content)
CREATE TABLE IF NOT EXISTS knowledge_base (
    id SERIAL PRIMARY KEY,
    repo_type VARCHAR(50) NOT NULL,
    file_path TEXT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_extension VARCHAR(50),
    content TEXT,
    indexed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(repo_type, file_path)
);

-- Table for system settings (if doesn't exist)
CREATE TABLE IF NOT EXISTS system_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) NOT NULL UNIQUE,
    value TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_github_repos_type ON github_repositories(repo_type);
CREATE INDEX IF NOT EXISTS idx_github_repos_status ON github_repositories(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_repo_type ON knowledge_base(repo_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_indexed_at ON knowledge_base(indexed_at);
CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(key);

-- Insert default repositories
INSERT INTO github_repositories (repo_name, repo_type, local_path, status)
VALUES
    ('ashishpatel26/500-AI-Agents-Projects', 'ai-agents', '/mnt/archie_brain/learning_resources/500-AI-Agents-Projects', 'not_cloned'),
    ('x1xhlol/system-prompts-and-models-of-ai-tools', 'prompts', '/mnt/archie_brain/learning_resources/system-prompts-and-models-of-ai-tools', 'not_cloned'),
    ('Zie619/n8n-workflows', 'n8n', '/mnt/archie_brain/learning_resources/n8n-workflows', 'not_cloned')
ON CONFLICT (repo_name) DO NOTHING;

-- Add comment
COMMENT ON TABLE github_repositories IS 'Tracks GitHub repositories cloned and managed by A.R.C.H.I.E.';
COMMENT ON TABLE knowledge_base IS 'Stores indexed content from GitHub repositories for A.R.C.H.I.E.''s learning';
COMMENT ON TABLE system_settings IS 'Stores system-wide configuration settings';
