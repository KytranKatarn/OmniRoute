-- Node-specific agents: each Starship node gets its own crew with unique identities
-- Same roles/models as Bridge agents but different first/last names per node

CREATE TABLE IF NOT EXISTS node_agents (
    id SERIAL PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES remote_nodes(id) ON DELETE CASCADE,
    source_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    name VARCHAR(100) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    display_name VARCHAR(200),
    title VARCHAR(200),
    model VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    system_prompt TEXT,
    capabilities JSONB,
    station_codes TEXT[] DEFAULT '{}',
    is_allowed BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(node_id, name)
);

CREATE INDEX IF NOT EXISTS idx_node_agents_node ON node_agents(node_id);
CREATE INDEX IF NOT EXISTS idx_node_agents_status ON node_agents(status);
CREATE INDEX IF NOT EXISTS idx_node_agents_source ON node_agents(source_agent_id);
