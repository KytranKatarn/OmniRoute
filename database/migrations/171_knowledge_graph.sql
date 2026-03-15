-- Migration 171: Knowledge graph — connections between knowledge entries
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS knowledge_connections (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    connection_type VARCHAR(50) NOT NULL,  -- relates_to, governs, implements, depends_on, supersedes
    strength NUMERIC DEFAULT 1.0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_id, target_id, connection_type)
);

CREATE TABLE IF NOT EXISTS knowledge_tags_index (
    id SERIAL PRIMARY KEY,
    tag VARCHAR(100) NOT NULL,
    knowledge_id INTEGER NOT NULL,
    UNIQUE(tag, knowledge_id)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_conn_source ON knowledge_connections(source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_conn_target ON knowledge_connections(target_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_conn_type ON knowledge_connections(connection_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_tags_tag ON knowledge_tags_index(tag);
