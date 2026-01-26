-- Unified Project & Documentation System Migration
-- A.R.C.H.I.E. Platform v5.24.0
-- Created: 2026-01-25
--
-- This migration creates the unified project tracking system that integrates:
-- - Project and task management
-- - Team collaboration (users + agents)
-- - A.R.C.H.I.E.'s consciousness/self-awareness
-- - Documentation versioning

BEGIN;

-- ============================================================================
-- CORE PROJECT TABLES
-- ============================================================================

-- Unified project tracking (replaces scattered blueprint_phases)
CREATE TABLE IF NOT EXISTS unified_projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'planning',
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),
    project_type VARCHAR(50), -- 'feature', 'bugfix', 'infrastructure', 'documentation', 'research'
    parent_project_id INTEGER REFERENCES unified_projects(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    tags VARCHAR(100)[] DEFAULT '{}',
    start_date TIMESTAMP,
    target_date TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_by_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL
);

-- Unified task system (consolidates blueprint_tasks, improvement_proposals, agent_task_assignments)
CREATE TABLE IF NOT EXISTS unified_tasks (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES unified_projects(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),
    task_type VARCHAR(50), -- 'implementation', 'review', 'testing', 'documentation', 'research', 'bugfix'
    estimated_effort VARCHAR(20), -- 'tiny', 'small', 'medium', 'large', 'epic'
    actual_effort_hours FLOAT,
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    parent_task_id INTEGER REFERENCES unified_tasks(id) ON DELETE SET NULL,
    dependencies JSONB DEFAULT '[]', -- Array of task IDs this depends on
    blockers TEXT, -- Description of blockers if any
    metadata JSONB DEFAULT '{}',
    tags VARCHAR(100)[] DEFAULT '{}',
    due_date TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_by_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL
);

-- Project documentation (structured, versioned)
CREATE TABLE IF NOT EXISTS project_documents (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES unified_projects(id) ON DELETE CASCADE,
    doc_type VARCHAR(50) NOT NULL, -- 'readme', 'architecture', 'api', 'changelog', 'decision', 'guide', 'spec'
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_format VARCHAR(20) DEFAULT 'markdown', -- 'markdown', 'html', 'plaintext'
    version INTEGER DEFAULT 1,
    is_current BOOLEAN DEFAULT TRUE,
    file_path VARCHAR(500), -- Original file path if migrated from /docs/
    metadata JSONB DEFAULT '{}',
    tags VARCHAR(100)[] DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_by_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL
);

-- Decision log (ADR - Architecture Decision Records)
CREATE TABLE IF NOT EXISTS project_decisions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES unified_projects(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES unified_tasks(id) ON DELETE SET NULL,
    decision_number INTEGER, -- ADR number like ADR-001
    title VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'proposed', -- 'proposed', 'accepted', 'deprecated', 'superseded'
    context TEXT, -- Why was this decision needed?
    decision TEXT NOT NULL, -- What was decided?
    alternatives TEXT, -- What alternatives were considered?
    consequences TEXT, -- What are the implications?
    superseded_by INTEGER REFERENCES project_decisions(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    tags VARCHAR(100)[] DEFAULT '{}',
    decided_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decided_by_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    decided_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- TEAM COLLABORATION TABLES
-- ============================================================================

-- Unified team members view (combines users + agents)
CREATE OR REPLACE VIEW team_members AS
SELECT
    'user' as member_type,
    u.id,
    u.username as name,
    u.email,
    u.role,
    NULL::JSONB as capabilities,
    u.is_active as active,
    NULL as department,
    u.created_at
FROM users u
UNION ALL
SELECT
    'agent' as member_type,
    a.id,
    a.name,
    a.email,
    COALESCE(at.name, 'unknown') as role,
    a.capabilities,
    a.status = 'active' as active,
    a.department,
    a.created_at
FROM agents a
LEFT JOIN agent_types at ON a.type_id = at.id;

-- Project team assignments
CREATE TABLE IF NOT EXISTS project_team (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES unified_projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'contributor', -- 'owner', 'lead', 'contributor', 'reviewer', 'observer'
    permissions JSONB DEFAULT '{"read": true, "write": false, "admin": false}',
    responsibilities TEXT, -- What this member is responsible for
    assigned_at TIMESTAMP DEFAULT NOW(),
    assigned_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT team_member_check CHECK (
        (user_id IS NOT NULL AND agent_id IS NULL) OR
        (user_id IS NULL AND agent_id IS NOT NULL)
    ),
    CONSTRAINT unique_project_user UNIQUE (project_id, user_id),
    CONSTRAINT unique_project_agent UNIQUE (project_id, agent_id)
);

-- Activity stream (audit trail of who did what)
CREATE TABLE IF NOT EXISTS project_activity (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES unified_projects(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES unified_tasks(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES project_documents(id) ON DELETE CASCADE,
    decision_id INTEGER REFERENCES project_decisions(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL, -- 'created', 'updated', 'completed', 'commented', 'assigned', 'status_changed'
    entity_type VARCHAR(50) NOT NULL, -- 'project', 'task', 'document', 'decision', 'team'
    description TEXT,
    changes JSONB DEFAULT '{}', -- What fields changed
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    session_id VARCHAR(100), -- Claude Code session ID
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- CONSCIOUSNESS INTEGRATION TABLES
-- ============================================================================

-- A.R.C.H.I.E.'s self-awareness of projects
CREATE TABLE IF NOT EXISTS archie_project_awareness (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES unified_projects(id) ON DELETE CASCADE UNIQUE,
    understanding_level INTEGER DEFAULT 0 CHECK (understanding_level >= 0 AND understanding_level <= 100),
    familiarity_score FLOAT DEFAULT 0.0, -- 0.0 to 1.0
    last_interaction TIMESTAMP,
    interaction_count INTEGER DEFAULT 0,
    notes TEXT, -- ARCHIE's internal notes about the project
    key_insights TEXT[], -- Array of key insights ARCHIE has about this project
    emotional_association VARCHAR(50), -- 'excited', 'concerned', 'neutral', 'focused', 'curious'
    complexity_assessment VARCHAR(20), -- 'simple', 'moderate', 'complex', 'very_complex'
    risk_assessment VARCHAR(20), -- 'low', 'medium', 'high', 'critical'
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Configuration change tracking (ARCHIE knows her own changes)
CREATE TABLE IF NOT EXISTS archie_config_history (
    id SERIAL PRIMARY KEY,
    config_type VARCHAR(100) NOT NULL, -- 'module', 'setting', 'integration', 'database', 'mcp', 'hook', 'env'
    config_path VARCHAR(500), -- File path or DB table affected
    config_key VARCHAR(255), -- Specific key/setting changed
    change_type VARCHAR(50) NOT NULL, -- 'created', 'modified', 'deleted', 'enabled', 'disabled'
    previous_value JSONB,
    new_value JSONB,
    change_reason TEXT,
    impact_assessment TEXT, -- What impact does this change have?
    rollback_possible BOOLEAN DEFAULT TRUE,
    changed_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    changed_by_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    changed_by_session VARCHAR(100), -- Claude Code session ID
    related_project_id INTEGER REFERENCES unified_projects(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Link projects to consciousness/memory system
CREATE TABLE IF NOT EXISTS project_memory_links (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES unified_projects(id) ON DELETE CASCADE,
    memory_id INTEGER NOT NULL REFERENCES long_term_memory(id) ON DELETE CASCADE,
    link_type VARCHAR(50) DEFAULT 'related', -- 'related', 'derived_from', 'influences', 'documents'
    relevance_score FLOAT DEFAULT 0.5 CHECK (relevance_score >= 0.0 AND relevance_score <= 1.0),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_project_memory UNIQUE (project_id, memory_id)
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Project indexes
CREATE INDEX IF NOT EXISTS idx_unified_projects_status ON unified_projects(status);
CREATE INDEX IF NOT EXISTS idx_unified_projects_type ON unified_projects(project_type);
CREATE INDEX IF NOT EXISTS idx_unified_projects_priority ON unified_projects(priority);
CREATE INDEX IF NOT EXISTS idx_unified_projects_parent ON unified_projects(parent_project_id);
CREATE INDEX IF NOT EXISTS idx_unified_projects_created_by_user ON unified_projects(created_by_user_id);
CREATE INDEX IF NOT EXISTS idx_unified_projects_created_by_agent ON unified_projects(created_by_agent_id);
CREATE INDEX IF NOT EXISTS idx_unified_projects_tags ON unified_projects USING GIN(tags);

-- Task indexes
CREATE INDEX IF NOT EXISTS idx_unified_tasks_project ON unified_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_status ON unified_tasks(status);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_priority ON unified_tasks(priority);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_assigned_user ON unified_tasks(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_assigned_agent ON unified_tasks(assigned_agent_id);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_parent ON unified_tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_due_date ON unified_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_unified_tasks_tags ON unified_tasks USING GIN(tags);

-- Document indexes
CREATE INDEX IF NOT EXISTS idx_project_documents_project ON project_documents(project_id);
CREATE INDEX IF NOT EXISTS idx_project_documents_type ON project_documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_project_documents_current ON project_documents(is_current) WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_project_documents_tags ON project_documents USING GIN(tags);

-- Decision indexes
CREATE INDEX IF NOT EXISTS idx_project_decisions_project ON project_decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_project_decisions_status ON project_decisions(status);
CREATE INDEX IF NOT EXISTS idx_project_decisions_number ON project_decisions(decision_number);

-- Team indexes
CREATE INDEX IF NOT EXISTS idx_project_team_project ON project_team(project_id);
CREATE INDEX IF NOT EXISTS idx_project_team_user ON project_team(user_id);
CREATE INDEX IF NOT EXISTS idx_project_team_agent ON project_team(agent_id);

-- Activity indexes
CREATE INDEX IF NOT EXISTS idx_project_activity_project ON project_activity(project_id);
CREATE INDEX IF NOT EXISTS idx_project_activity_task ON project_activity(task_id);
CREATE INDEX IF NOT EXISTS idx_project_activity_type ON project_activity(activity_type);
CREATE INDEX IF NOT EXISTS idx_project_activity_created ON project_activity(created_at DESC);

-- Consciousness indexes
CREATE INDEX IF NOT EXISTS idx_archie_awareness_project ON archie_project_awareness(project_id);
CREATE INDEX IF NOT EXISTS idx_archie_awareness_level ON archie_project_awareness(understanding_level);
CREATE INDEX IF NOT EXISTS idx_archie_config_type ON archie_config_history(config_type);
CREATE INDEX IF NOT EXISTS idx_archie_config_path ON archie_config_history(config_path);
CREATE INDEX IF NOT EXISTS idx_archie_config_created ON archie_config_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_memory_project ON project_memory_links(project_id);
CREATE INDEX IF NOT EXISTS idx_project_memory_memory ON project_memory_links(memory_id);

-- ============================================================================
-- TRIGGERS FOR AUTOMATIC UPDATES
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at trigger to all tables
DROP TRIGGER IF EXISTS update_unified_projects_updated_at ON unified_projects;
CREATE TRIGGER update_unified_projects_updated_at
    BEFORE UPDATE ON unified_projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_unified_tasks_updated_at ON unified_tasks;
CREATE TRIGGER update_unified_tasks_updated_at
    BEFORE UPDATE ON unified_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_project_documents_updated_at ON project_documents;
CREATE TRIGGER update_project_documents_updated_at
    BEFORE UPDATE ON project_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_project_decisions_updated_at ON project_decisions;
CREATE TRIGGER update_project_decisions_updated_at
    BEFORE UPDATE ON project_decisions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_archie_project_awareness_updated_at ON archie_project_awareness;
CREATE TRIGGER update_archie_project_awareness_updated_at
    BEFORE UPDATE ON archie_project_awareness
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to log project activity on changes
CREATE OR REPLACE FUNCTION log_project_activity()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO project_activity (project_id, entity_type, activity_type, description, changes)
        VALUES (NEW.id, 'project', 'created', 'Project created: ' || NEW.name, to_jsonb(NEW));
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status != NEW.status THEN
            INSERT INTO project_activity (project_id, entity_type, activity_type, description, changes)
            VALUES (NEW.id, 'project', 'status_changed',
                    'Status changed from ' || OLD.status || ' to ' || NEW.status,
                    jsonb_build_object('old_status', OLD.status, 'new_status', NEW.status));
        END IF;
    END IF;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS log_project_changes ON unified_projects;
CREATE TRIGGER log_project_changes
    AFTER INSERT OR UPDATE ON unified_projects
    FOR EACH ROW EXECUTE FUNCTION log_project_activity();

-- Function to log task activity on changes
CREATE OR REPLACE FUNCTION log_task_activity()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO project_activity (project_id, task_id, entity_type, activity_type, description)
        VALUES (NEW.project_id, NEW.id, 'task', 'created', 'Task created: ' || NEW.title);
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status != NEW.status THEN
            INSERT INTO project_activity (project_id, task_id, entity_type, activity_type, description, changes)
            VALUES (NEW.project_id, NEW.id, 'task', 'status_changed',
                    'Task status changed from ' || OLD.status || ' to ' || NEW.status,
                    jsonb_build_object('old_status', OLD.status, 'new_status', NEW.status));

            -- If task completed, update completed_at
            IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
                NEW.completed_at = NOW();
            END IF;
        END IF;

        IF OLD.assigned_user_id IS DISTINCT FROM NEW.assigned_user_id OR
           OLD.assigned_agent_id IS DISTINCT FROM NEW.assigned_agent_id THEN
            INSERT INTO project_activity (project_id, task_id, entity_type, activity_type, description)
            VALUES (NEW.project_id, NEW.id, 'task', 'assigned', 'Task assignment changed');
        END IF;
    END IF;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS log_task_changes ON unified_tasks;
CREATE TRIGGER log_task_changes
    AFTER INSERT OR UPDATE ON unified_tasks
    FOR EACH ROW EXECUTE FUNCTION log_task_activity();

-- Function to update ARCHIE's awareness when interacting with projects
CREATE OR REPLACE FUNCTION update_archie_awareness()
RETURNS TRIGGER AS $$
BEGIN
    -- Ensure awareness record exists
    INSERT INTO archie_project_awareness (project_id)
    VALUES (NEW.project_id)
    ON CONFLICT (project_id) DO UPDATE SET
        last_interaction = NOW(),
        interaction_count = archie_project_awareness.interaction_count + 1;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS track_archie_project_interaction ON project_activity;
CREATE TRIGGER track_archie_project_interaction
    AFTER INSERT ON project_activity
    FOR EACH ROW
    WHEN (NEW.agent_id IS NOT NULL OR NEW.session_id IS NOT NULL)
    EXECUTE FUNCTION update_archie_awareness();

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Get project progress (percentage of completed tasks)
CREATE OR REPLACE FUNCTION get_project_progress(p_project_id INTEGER)
RETURNS FLOAT AS $$
DECLARE
    total_tasks INTEGER;
    completed_tasks INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'completed')
    INTO total_tasks, completed_tasks
    FROM unified_tasks
    WHERE project_id = p_project_id;

    IF total_tasks = 0 THEN
        RETURN 0.0;
    END IF;

    RETURN (completed_tasks::FLOAT / total_tasks::FLOAT) * 100;
END;
$$ LANGUAGE plpgsql;

-- Get next ADR number for a project
CREATE OR REPLACE FUNCTION get_next_adr_number(p_project_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    max_number INTEGER;
BEGIN
    SELECT COALESCE(MAX(decision_number), 0)
    INTO max_number
    FROM project_decisions
    WHERE project_id = p_project_id;

    RETURN max_number + 1;
END;
$$ LANGUAGE plpgsql;

-- Generate slug from name
CREATE OR REPLACE FUNCTION generate_slug(p_name VARCHAR)
RETURNS VARCHAR AS $$
BEGIN
    RETURN LOWER(REGEXP_REPLACE(REGEXP_REPLACE(p_name, '[^a-zA-Z0-9\s-]', '', 'g'), '\s+', '-', 'g'));
END;
$$ LANGUAGE plpgsql;

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Run these after migration to verify success:

-- SELECT 'unified_projects' as table_name, COUNT(*) as row_count FROM unified_projects
-- UNION ALL SELECT 'unified_tasks', COUNT(*) FROM unified_tasks
-- UNION ALL SELECT 'project_documents', COUNT(*) FROM project_documents
-- UNION ALL SELECT 'project_decisions', COUNT(*) FROM project_decisions
-- UNION ALL SELECT 'project_team', COUNT(*) FROM project_team
-- UNION ALL SELECT 'project_activity', COUNT(*) FROM project_activity
-- UNION ALL SELECT 'archie_project_awareness', COUNT(*) FROM archie_project_awareness
-- UNION ALL SELECT 'archie_config_history', COUNT(*) FROM archie_config_history
-- UNION ALL SELECT 'project_memory_links', COUNT(*) FROM project_memory_links;
