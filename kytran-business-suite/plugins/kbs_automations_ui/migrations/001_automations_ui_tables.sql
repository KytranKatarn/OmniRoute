-- Automations UI plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

CREATE TABLE IF NOT EXISTS workflow_categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    color       VARCHAR(7) DEFAULT '#00e5ff',
    sort_order  INT DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_logs (
    id             SERIAL PRIMARY KEY,
    execution_id   INT,
    workflow_name  VARCHAR(255),
    event_type     VARCHAR(100),
    message        TEXT,
    level          VARCHAR(20) DEFAULT 'info'
                       CHECK (level IN ('info', 'warning', 'error')),
    created_at     TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_workflow_logs_execution_id ON workflow_logs(execution_id);
CREATE INDEX IF NOT EXISTS idx_workflow_logs_level        ON workflow_logs(level);
CREATE INDEX IF NOT EXISTS idx_workflow_logs_created_at   ON workflow_logs(created_at);
