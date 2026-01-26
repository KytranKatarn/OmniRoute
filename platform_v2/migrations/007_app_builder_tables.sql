--
-- App Builder Database Schema
-- Tables for GPT-Pilot style application generation
--
-- Purpose:
-- - Track application projects from planning to deployment
-- - Store all generated files and code
-- - Maintain chat history for clarification and iteration
-- - Log all execution steps for debugging and rollback
--
-- Author: A.R.C.H.I.E. Platform
-- Date: 2026-01-07
--

-- ===========================================================================
-- APP BUILDER PROJECTS
-- ===========================================================================

CREATE TABLE IF NOT EXISTS app_builder_projects (
    id SERIAL PRIMARY KEY,

    -- Ownership
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by INTEGER REFERENCES users(id),

    -- Project Identity
    name VARCHAR(255) NOT NULL,
    description TEXT,
    project_type VARCHAR(50) DEFAULT 'web_app', -- web_app, api, cli, mobile, desktop

    -- Planning Phase
    user_prompt TEXT NOT NULL, -- Original natural language request
    clarification_questions JSONB, -- Questions asked during planning
    clarification_answers JSONB, -- User answers
    project_plan JSONB, -- Detailed implementation plan
    plan_approved BOOLEAN DEFAULT FALSE,
    plan_approved_at TIMESTAMP,

    -- Technology Stack
    tech_stack JSONB, -- {backend: 'flask', frontend: 'react', database: 'postgresql', ...}
    dependencies JSONB, -- {python: ['flask', 'sqlalchemy'], javascript: ['react', 'axios']}

    -- Generation Status
    status VARCHAR(50) DEFAULT 'planning', -- planning, generating, testing, deploying, completed, failed, cancelled
    progress INTEGER DEFAULT 0, -- 0-100%
    current_step VARCHAR(100), -- Current generation step

    -- File Management
    total_files INTEGER DEFAULT 0,
    total_lines INTEGER DEFAULT 0,
    file_tree JSONB, -- Directory structure

    -- Git Integration
    git_repo_path VARCHAR(500), -- Path to Git repository
    git_initialized BOOLEAN DEFAULT FALSE,
    git_commit_count INTEGER DEFAULT 0,

    -- Sandbox Environment
    docker_container_id VARCHAR(100), -- Docker container for isolation
    sandbox_active BOOLEAN DEFAULT FALSE,
    sandbox_port INTEGER, -- Exposed port for testing
    sandbox_url VARCHAR(500), -- URL to access running app

    -- Testing
    tests_generated BOOLEAN DEFAULT FALSE,
    tests_passed BOOLEAN DEFAULT FALSE,
    test_results JSONB,
    syntax_errors JSONB, -- Array of syntax errors found

    -- Deployment
    deployed BOOLEAN DEFAULT FALSE,
    deployed_at TIMESTAMP,
    deployment_url VARCHAR(500),
    deployment_platform VARCHAR(50), -- vercel, railway, docker, heroku, aws
    deployment_config JSONB,

    -- Metadata
    tags TEXT[],
    is_public BOOLEAN DEFAULT FALSE, -- Share in gallery?
    is_template BOOLEAN DEFAULT FALSE, -- Use as template?

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP, -- When generation started
    completed_at TIMESTAMP, -- When generation completed

    -- Constraints
    CONSTRAINT app_builder_projects_name_user_unique UNIQUE(user_id, name)
);

-- Indexes for app_builder_projects
CREATE INDEX IF NOT EXISTS idx_app_builder_projects_user ON app_builder_projects(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_projects_status ON app_builder_projects(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_projects_type ON app_builder_projects(project_type, status);
CREATE INDEX IF NOT EXISTS idx_app_builder_projects_tags ON app_builder_projects USING GIN(tags);

-- ===========================================================================
-- APP BUILDER FILES
-- ===========================================================================

CREATE TABLE IF NOT EXISTS app_builder_files (
    id SERIAL PRIMARY KEY,

    -- Project Association
    project_id INTEGER NOT NULL REFERENCES app_builder_projects(id) ON DELETE CASCADE,

    -- File Identity
    file_path VARCHAR(1000) NOT NULL, -- Relative path from project root
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50), -- python, javascript, html, css, sql, markdown, json, yaml

    -- Content
    content TEXT NOT NULL,
    content_hash VARCHAR(64), -- SHA256 hash for deduplication
    size_bytes INTEGER,
    line_count INTEGER,

    -- Generation Metadata
    generated_by VARCHAR(100), -- Agent that generated this file
    generation_method VARCHAR(50), -- llm, template, scaffold, manual
    generation_prompt TEXT, -- Prompt used to generate this file

    -- Version Control
    version INTEGER DEFAULT 1,
    previous_version_id INTEGER REFERENCES app_builder_files(id),
    is_latest BOOLEAN DEFAULT TRUE,

    -- Status
    status VARCHAR(50) DEFAULT 'generated', -- generated, validated, tested, deployed
    has_syntax_errors BOOLEAN DEFAULT FALSE,
    syntax_errors JSONB,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT app_builder_files_project_path_unique UNIQUE(project_id, file_path, version)
);

-- Indexes for app_builder_files
CREATE INDEX IF NOT EXISTS idx_app_builder_files_project ON app_builder_files(project_id, is_latest);
CREATE INDEX IF NOT EXISTS idx_app_builder_files_type ON app_builder_files(file_type, project_id);
CREATE INDEX IF NOT EXISTS idx_app_builder_files_status ON app_builder_files(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_files_hash ON app_builder_files(content_hash);

-- ===========================================================================
-- APP BUILDER CHAT HISTORY
-- ===========================================================================

CREATE TABLE IF NOT EXISTS app_builder_chat_history (
    id SERIAL PRIMARY KEY,

    -- Project Association
    project_id INTEGER NOT NULL REFERENCES app_builder_projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Message
    role VARCHAR(20) NOT NULL, -- user, assistant, system
    message TEXT NOT NULL,
    message_type VARCHAR(50), -- clarification, suggestion, error, progress, completion

    -- Context
    step VARCHAR(100), -- planning, generating, testing, deploying
    agent VARCHAR(100), -- clarification_agent, code_generator, test_runner

    -- Metadata
    metadata JSONB, -- Additional context (code snippets, file references, etc.)
    tokens_used INTEGER, -- LLM tokens consumed

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for app_builder_chat_history
CREATE INDEX IF NOT EXISTS idx_app_builder_chat_project ON app_builder_chat_history(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_chat_user ON app_builder_chat_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_chat_role ON app_builder_chat_history(role, created_at DESC);

-- ===========================================================================
-- APP BUILDER EXECUTION LOGS
-- ===========================================================================

CREATE TABLE IF NOT EXISTS app_builder_execution_logs (
    id SERIAL PRIMARY KEY,

    -- Project Association
    project_id INTEGER NOT NULL REFERENCES app_builder_projects(id) ON DELETE CASCADE,

    -- Execution Step
    step_name VARCHAR(200) NOT NULL, -- 'generate_backend', 'run_tests', 'deploy_to_vercel'
    step_type VARCHAR(50), -- planning, generation, validation, testing, deployment
    agent VARCHAR(100), -- Agent executing this step

    -- Status
    status VARCHAR(50) NOT NULL, -- running, completed, failed, skipped
    progress INTEGER DEFAULT 0, -- 0-100%

    -- Execution Details
    command TEXT, -- Command executed (if applicable)
    stdout TEXT, -- Standard output
    stderr TEXT, -- Standard error
    exit_code INTEGER, -- Process exit code

    -- Timing
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_ms INTEGER, -- Milliseconds

    -- Results
    success BOOLEAN,
    error_message TEXT,
    error_details JSONB,
    output_data JSONB, -- Structured output data

    -- Files Affected
    files_created TEXT[], -- Array of file paths created
    files_modified TEXT[], -- Array of file paths modified
    files_deleted TEXT[], -- Array of file paths deleted

    -- Metadata
    metadata JSONB,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for app_builder_execution_logs
CREATE INDEX IF NOT EXISTS idx_app_builder_logs_project ON app_builder_execution_logs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_logs_status ON app_builder_execution_logs(status, step_type);
CREATE INDEX IF NOT EXISTS idx_app_builder_logs_agent ON app_builder_execution_logs(agent, created_at DESC);

-- ===========================================================================
-- APP BUILDER TEMPLATES
-- ===========================================================================

CREATE TABLE IF NOT EXISTS app_builder_templates (
    id SERIAL PRIMARY KEY,

    -- Template Identity
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(100), -- api, web_app, cli, mobile, dashboard

    -- Template Definition
    tech_stack JSONB NOT NULL, -- Technology stack
    file_structure JSONB NOT NULL, -- Directory and file structure
    dependencies JSONB, -- Package dependencies

    -- Template Files
    template_files JSONB, -- Array of {path, content_template, variables}
    scaffold_steps JSONB, -- Steps to scaffold the project

    -- Usage
    usage_count INTEGER DEFAULT 0,
    is_official BOOLEAN DEFAULT FALSE, -- Official A.R.C.H.I.E. template?
    is_public BOOLEAN DEFAULT TRUE,

    -- Source
    source_project_id INTEGER REFERENCES app_builder_projects(id), -- If created from existing project
    created_by INTEGER REFERENCES users(id),

    -- Metadata
    tags TEXT[],
    difficulty VARCHAR(20), -- beginner, intermediate, advanced
    estimated_time_minutes INTEGER,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for app_builder_templates
CREATE INDEX IF NOT EXISTS idx_app_builder_templates_category ON app_builder_templates(category, is_public);
CREATE INDEX IF NOT EXISTS idx_app_builder_templates_tags ON app_builder_templates USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_app_builder_templates_usage ON app_builder_templates(usage_count DESC);

-- ===========================================================================
-- APP BUILDER DEPLOYMENTS
-- ===========================================================================

CREATE TABLE IF NOT EXISTS app_builder_deployments (
    id SERIAL PRIMARY KEY,

    -- Project Association
    project_id INTEGER NOT NULL REFERENCES app_builder_projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Deployment Details
    deployment_platform VARCHAR(50) NOT NULL, -- vercel, railway, docker, heroku, aws
    deployment_url VARCHAR(500),
    deployment_id VARCHAR(255), -- Platform-specific deployment ID

    -- Configuration
    environment VARCHAR(50) DEFAULT 'production', -- production, staging, preview
    config JSONB, -- Platform-specific configuration
    env_vars JSONB, -- Environment variables (encrypted)

    -- Build Information
    build_command TEXT,
    build_output TEXT,
    build_duration_seconds INTEGER,
    build_success BOOLEAN,

    -- Status
    status VARCHAR(50) DEFAULT 'pending', -- pending, building, deploying, active, failed, stopped
    health_status VARCHAR(50), -- healthy, unhealthy, unknown
    last_health_check TIMESTAMP,

    -- Metadata
    git_commit_hash VARCHAR(40),
    deployed_files_count INTEGER,
    deployment_size_mb DECIMAL(10, 2),

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    deployed_at TIMESTAMP,
    stopped_at TIMESTAMP,

    -- Constraints
    CONSTRAINT app_builder_deployments_project_env_unique UNIQUE(project_id, environment)
);

-- Indexes for app_builder_deployments
CREATE INDEX IF NOT EXISTS idx_app_builder_deployments_project ON app_builder_deployments(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_deployments_user ON app_builder_deployments(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_builder_deployments_status ON app_builder_deployments(status, deployment_platform);

-- ===========================================================================
-- TRIGGERS FOR UPDATED_AT
-- ===========================================================================

CREATE OR REPLACE FUNCTION update_app_builder_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER app_builder_projects_updated_at
    BEFORE UPDATE ON app_builder_projects
    FOR EACH ROW
    EXECUTE FUNCTION update_app_builder_updated_at();

CREATE TRIGGER app_builder_files_updated_at
    BEFORE UPDATE ON app_builder_files
    FOR EACH ROW
    EXECUTE FUNCTION update_app_builder_updated_at();

CREATE TRIGGER app_builder_templates_updated_at
    BEFORE UPDATE ON app_builder_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_app_builder_updated_at();

-- ===========================================================================
-- COMPLETION SUMMARY
-- ===========================================================================

DO $$
DECLARE
    table_count INTEGER;
    index_count INTEGER;
BEGIN
    -- Count created tables
    SELECT COUNT(*) INTO table_count
    FROM pg_tables
    WHERE schemaname = 'public'
    AND tablename LIKE 'app_builder_%';

    -- Count created indexes
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND indexname LIKE 'idx_app_builder_%';

    RAISE NOTICE '✅ App Builder Database Schema Created';
    RAISE NOTICE '   Tables: %', table_count;
    RAISE NOTICE '   Indexes: %', index_count;
    RAISE NOTICE '   Ready for Phase 2 implementation';
END $$;
