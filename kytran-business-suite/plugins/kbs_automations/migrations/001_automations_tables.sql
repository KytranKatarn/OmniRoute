-- Automations plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

CREATE TABLE IF NOT EXISTS workflow_templates (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    trigger_event   VARCHAR(100) NOT NULL,
    conditions      JSONB DEFAULT '{}',
    actions         JSONB DEFAULT '[]',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_executions (
    id              SERIAL PRIMARY KEY,
    template_id     INTEGER REFERENCES workflow_templates(id) ON DELETE CASCADE,
    trigger_event   VARCHAR(100),
    event_data      JSONB DEFAULT '{}',
    status          VARCHAR(20) DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    result          JSONB DEFAULT '{}',
    started_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP,
    error_message   TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_workflow_templates_trigger_event ON workflow_templates(trigger_event);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_is_active ON workflow_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_template_id ON workflow_executions(template_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status);
