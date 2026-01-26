-- Enhanced Knowledge Base with Tagging System
-- Version: 3.1.3
-- Date: 2025-12-31

-- Add tagging columns to knowledge_base
ALTER TABLE knowledge_base
ADD COLUMN IF NOT EXISTS tags TEXT[],
ADD COLUMN IF NOT EXISTS primary_category VARCHAR(100),
ADD COLUMN IF NOT EXISTS sub_category VARCHAR(100),
ADD COLUMN IF NOT EXISTS language VARCHAR(50),
ADD COLUMN IF NOT EXISTS complexity VARCHAR(20),
ADD COLUMN IF NOT EXISTS file_size INTEGER,
ADD COLUMN IF NOT EXISTS line_count INTEGER,
ADD COLUMN IF NOT EXISTS is_code BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS is_documentation BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS is_configuration BOOLEAN DEFAULT FALSE;

-- Create tags table for available tag definitions
CREATE TABLE IF NOT EXISTS knowledge_tags (
    id SERIAL PRIMARY KEY,
    tag_name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexed tags for fast searching
CREATE INDEX IF NOT EXISTS idx_knowledge_base_tags ON knowledge_base USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_category ON knowledge_base(primary_category);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_language ON knowledge_base(language);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_is_code ON knowledge_base(is_code);

-- Insert predefined tag categories
INSERT INTO knowledge_tags (tag_name, category, description, color) VALUES
    -- Automation Tags
    ('automation', 'Automation', 'Workflow automation and task scheduling', '#00FF00'),
    ('n8n-workflow', 'Automation', 'n8n workflow definitions', '#00FF88'),
    ('workflow-template', 'Automation', 'Reusable workflow templates', '#00FFAA'),
    ('api-integration', 'Automation', 'API integration workflows', '#00FFCC'),

    -- AI Agent Tags
    ('ai-agent', 'AI Agents', 'AI agent implementations', '#FF00FF'),
    ('agent-architecture', 'AI Agents', 'Agent design patterns', '#FF00CC'),
    ('agent-example', 'AI Agents', 'Working agent examples', '#FF0088'),
    ('multi-agent', 'AI Agents', 'Multi-agent systems', '#FF0044'),

    -- Script Tags
    ('python-script', 'Scripts', 'Python executable scripts', '#FFFF00'),
    ('bash-script', 'Scripts', 'Bash/shell scripts', '#FFFF44'),
    ('automation-script', 'Scripts', 'Task automation scripts', '#FFFF88'),
    ('utility-script', 'Scripts', 'Utility and helper scripts', '#FFFFCC'),

    -- Prompt Tags
    ('system-prompt', 'Prompts', 'System prompts for LLMs', '#00FFFF'),
    ('prompt-template', 'Prompts', 'Reusable prompt templates', '#00FFCC'),
    ('prompt-engineering', 'Prompts', 'Prompt engineering techniques', '#00FF88'),
    ('few-shot-example', 'Prompts', 'Few-shot learning examples', '#00FF44'),

    -- Code Tags
    ('python-code', 'Code', 'Python source code', '#FF8800'),
    ('javascript-code', 'Code', 'JavaScript source code', '#FF8844'),
    ('tutorial', 'Code', 'Tutorial and learning code', '#FF8888'),
    ('example', 'Code', 'Code examples', '#FF88CC'),
    ('library', 'Code', 'Reusable library code', '#FF88FF'),
    ('utility', 'Code', 'Utility functions', '#CC88FF'),

    -- Documentation Tags
    ('documentation', 'Documentation', 'Technical documentation', '#8888FF'),
    ('readme', 'Documentation', 'README files', '#8844FF'),
    ('api-docs', 'Documentation', 'API documentation', '#8800FF'),
    ('guide', 'Documentation', 'How-to guides', '#4400FF'),

    -- Configuration Tags
    ('config', 'Configuration', 'Configuration files', '#888888'),
    ('json-config', 'Configuration', 'JSON configuration', '#888844'),
    ('yaml-config', 'Configuration', 'YAML configuration', '#888800'),
    ('env-config', 'Configuration', 'Environment configuration', '#444400'),

    -- Complexity Tags
    ('beginner', 'Complexity', 'Beginner-level content', '#00FF00'),
    ('intermediate', 'Complexity', 'Intermediate-level content', '#FFFF00'),
    ('advanced', 'Complexity', 'Advanced-level content', '#FF8800'),
    ('expert', 'Complexity', 'Expert-level content', '#FF0000'),

    -- Data Science Tags
    ('data-science', 'Data Science', 'Data science code', '#0088FF'),
    ('machine-learning', 'Data Science', 'ML algorithms', '#0044FF'),
    ('data-analysis', 'Data Science', 'Data analysis scripts', '#0000FF'),
    ('visualization', 'Data Science', 'Data visualization', '#4400FF')
ON CONFLICT (tag_name) DO NOTHING;

-- Create function to auto-categorize content
CREATE OR REPLACE FUNCTION auto_categorize_content()
RETURNS TRIGGER AS $$
BEGIN
    -- Determine if it's code
    NEW.is_code := NEW.file_extension IN ('.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.rb');

    -- Determine if it's documentation
    NEW.is_documentation := NEW.file_extension IN ('.md', '.txt', '.rst', '.adoc') OR
                            LOWER(NEW.file_name) LIKE '%readme%' OR
                            LOWER(NEW.file_name) LIKE '%doc%';

    -- Determine if it's configuration
    NEW.is_configuration := NEW.file_extension IN ('.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.env');

    -- Set language
    NEW.language := CASE NEW.file_extension
        WHEN '.py' THEN 'Python'
        WHEN '.js' THEN 'JavaScript'
        WHEN '.ts' THEN 'TypeScript'
        WHEN '.java' THEN 'Java'
        WHEN '.cpp' THEN 'C++'
        WHEN '.c' THEN 'C'
        WHEN '.go' THEN 'Go'
        WHEN '.rs' THEN 'Rust'
        WHEN '.rb' THEN 'Ruby'
        WHEN '.sh' THEN 'Bash'
        WHEN '.json' THEN 'JSON'
        WHEN '.yaml' THEN 'YAML'
        WHEN '.yml' THEN 'YAML'
        ELSE 'Unknown'
    END;

    -- Count lines and size
    NEW.line_count := array_length(string_to_array(NEW.content, E'\n'), 1);
    NEW.file_size := length(NEW.content);

    -- Auto-tag based on content and file type
    NEW.tags := ARRAY[]::TEXT[];

    -- Add language tag
    IF NEW.file_extension = '.py' THEN
        NEW.tags := array_append(NEW.tags, 'python-code');
    ELSIF NEW.file_extension IN ('.js', '.ts') THEN
        NEW.tags := array_append(NEW.tags, 'javascript-code');
    END IF;

    -- Add script tag
    IF NEW.file_extension IN ('.py', '.sh') THEN
        NEW.tags := array_append(NEW.tags, 'python-script');
    END IF;

    -- Add documentation tag
    IF NEW.is_documentation THEN
        NEW.tags := array_append(NEW.tags, 'documentation');
        IF LOWER(NEW.file_name) LIKE '%readme%' THEN
            NEW.tags := array_append(NEW.tags, 'readme');
        END IF;
    END IF;

    -- Add configuration tag
    IF NEW.is_configuration THEN
        NEW.tags := array_append(NEW.tags, 'config');
        IF NEW.file_extension = '.json' THEN
            NEW.tags := array_append(NEW.tags, 'json-config');
        ELSIF NEW.file_extension IN ('.yaml', '.yml') THEN
            NEW.tags := array_append(NEW.tags, 'yaml-config');
        END IF;
    END IF;

    -- Add repo-specific tags
    IF NEW.repo_type = 'ai-agents' THEN
        NEW.tags := array_append(NEW.tags, 'ai-agent');
        NEW.tags := array_append(NEW.tags, 'agent-example');
        NEW.primary_category := 'AI Agents';
    ELSIF NEW.repo_type = 'prompts' THEN
        NEW.tags := array_append(NEW.tags, 'system-prompt');
        NEW.tags := array_append(NEW.tags, 'prompt-template');
        NEW.primary_category := 'Prompts';
    ELSIF NEW.repo_type = 'n8n' THEN
        NEW.tags := array_append(NEW.tags, 'automation');
        NEW.tags := array_append(NEW.tags, 'n8n-workflow');
        NEW.tags := array_append(NEW.tags, 'workflow-template');
        NEW.primary_category := 'Automation';
    ELSIF NEW.repo_type LIKE '%python%' THEN
        NEW.tags := array_append(NEW.tags, 'python-code');
        NEW.tags := array_append(NEW.tags, 'tutorial');
        NEW.tags := array_append(NEW.tags, 'example');
        NEW.primary_category := 'Code';
    END IF;

    -- Determine complexity by line count
    IF NEW.line_count < 50 THEN
        NEW.complexity := 'beginner';
        NEW.tags := array_append(NEW.tags, 'beginner');
    ELSIF NEW.line_count < 200 THEN
        NEW.complexity := 'intermediate';
        NEW.tags := array_append(NEW.tags, 'intermediate');
    ELSIF NEW.line_count < 500 THEN
        NEW.complexity := 'advanced';
        NEW.tags := array_append(NEW.tags, 'advanced');
    ELSE
        NEW.complexity := 'expert';
        NEW.tags := array_append(NEW.tags, 'expert');
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for auto-categorization
DROP TRIGGER IF EXISTS trigger_auto_categorize ON knowledge_base;
CREATE TRIGGER trigger_auto_categorize
    BEFORE INSERT OR UPDATE ON knowledge_base
    FOR EACH ROW
    EXECUTE FUNCTION auto_categorize_content();

-- Create view for easy tag searching
CREATE OR REPLACE VIEW knowledge_by_tags AS
SELECT
    kb.id,
    kb.repo_type,
    kb.file_name,
    kb.file_path,
    kb.primary_category,
    kb.sub_category,
    kb.language,
    kb.complexity,
    kb.tags,
    kb.line_count,
    kb.file_size,
    kb.indexed_at
FROM knowledge_base kb
ORDER BY kb.indexed_at DESC;

-- Add comment
COMMENT ON TABLE knowledge_tags IS 'Defines available tags and their categories for knowledge base content';
COMMENT ON FUNCTION auto_categorize_content() IS 'Automatically categorizes and tags content based on file type, content, and repository type';
COMMENT ON VIEW knowledge_by_tags IS 'Simplified view of knowledge base with tagging information';

SELECT 'Enhanced knowledge tagging system created successfully!' AS status;
