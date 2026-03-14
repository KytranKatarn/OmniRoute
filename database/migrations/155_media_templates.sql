-- Migration 155: Workflow templates + pipeline execution tracking
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS media_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL,
    visibility VARCHAR(20) DEFAULT 'private',
    version INTEGER DEFAULT 1,
    parent_id INTEGER REFERENCES media_templates(id),
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS media_template_steps (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES media_templates(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_type VARCHAR(30) NOT NULL,
    step_name VARCHAR(100) DEFAULT '',
    params JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS media_pipeline_executions (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES media_templates(id),
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER NOT NULL,
    result_ids JSONB DEFAULT '[]',
    error_message TEXT,
    failed_at_step INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS media_template_collection_items (
    id SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES media_collections(id) ON DELETE CASCADE,
    template_id INTEGER NOT NULL REFERENCES media_templates(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, template_id)
);

CREATE INDEX IF NOT EXISTS idx_media_templates_owner ON media_templates(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_templates_visibility ON media_templates(visibility);
CREATE INDEX IF NOT EXISTS idx_media_templates_parent ON media_templates(parent_id);
CREATE INDEX IF NOT EXISTS idx_media_template_steps_template ON media_template_steps(template_id, step_order);
CREATE INDEX IF NOT EXISTS idx_media_pipeline_exec_owner ON media_pipeline_executions(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_pipeline_exec_status ON media_pipeline_executions(status);
CREATE INDEX IF NOT EXISTS idx_media_tpl_coll_items_coll ON media_template_collection_items(collection_id);
