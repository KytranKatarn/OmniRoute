-- Node skill push tracking — one row per skill per node
-- Separate from skill_installations to avoid write contention
CREATE TABLE IF NOT EXISTS node_skill_pushes (
    id SERIAL PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES remote_nodes(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL,
    pushed_at TIMESTAMP DEFAULT NOW(),
    fail_count INTEGER DEFAULT 0,
    last_error TEXT,
    CONSTRAINT uq_node_skill UNIQUE(node_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_node_skill_pushes_node
    ON node_skill_pushes(node_id);
CREATE INDEX IF NOT EXISTS idx_node_skill_pushes_failed
    ON node_skill_pushes(fail_count) WHERE fail_count > 0;
