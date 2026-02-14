-- 089: Agent Hierarchy & Sub-Agent Governance
-- Supports Phase 2: ARCHIE creating/managing agents via Chat

-- 1. Agent hierarchy columns
ALTER TABLE agents ADD COLUMN IF NOT EXISTS parent_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS agent_generation INTEGER DEFAULT 0;
-- 0 = human-created (seed data), 1+ = created by another agent

COMMENT ON COLUMN agents.parent_agent_id IS 'Supervising agent (NULL = top-level)';
COMMENT ON COLUMN agents.created_by_agent_id IS 'Which agent requested creation';
COMMENT ON COLUMN agents.created_by_user_id IS 'Which user approved creation';
COMMENT ON COLUMN agents.agent_generation IS '0=seed, 1+=sub-agent depth';

CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id) WHERE parent_agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agents_generation ON agents(agent_generation);

-- 2. Agent creation events (immutable audit trail)
CREATE TABLE IF NOT EXISTS agent_creation_events (
    id SERIAL PRIMARY KEY,
    parent_agent_id INTEGER REFERENCES agents(id),
    child_agent_id INTEGER NOT NULL REFERENCES agents(id),
    created_by_user_id INTEGER REFERENCES users(id),
    creation_reason TEXT,
    creation_source VARCHAR(50) DEFAULT 'chat',  -- 'chat', 'api', 'migration', 'admin_ui'
    capabilities_requested JSONB,
    station_requested VARCHAR(50),
    is_approved BOOLEAN DEFAULT FALSE,
    approved_at TIMESTAMP,
    terminated_at TIMESTAMP,
    termination_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_creation_events_parent ON agent_creation_events(parent_agent_id);
CREATE INDEX IF NOT EXISTS idx_creation_events_child ON agent_creation_events(child_agent_id);

-- 3. Agent budgets (token/task limits per agent)
CREATE TABLE IF NOT EXISTS agent_budgets (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) UNIQUE,
    token_limit_per_day INTEGER DEFAULT 100000,
    tokens_used_today INTEGER DEFAULT 0,
    token_reset_at TIMESTAMP DEFAULT (NOW() + INTERVAL '1 day'),
    task_queue_limit INTEGER DEFAULT 10,
    current_task_count INTEGER DEFAULT 0,
    can_create_sub_agents BOOLEAN DEFAULT FALSE,
    max_sub_agents INTEGER DEFAULT 0,
    max_lifespan_hours INTEGER,  -- NULL = unlimited
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 4. Set ARCHIE (id=2) as top-level with sub-agent creation rights
INSERT INTO agent_budgets (agent_id, can_create_sub_agents, max_sub_agents, token_limit_per_day)
VALUES (2, TRUE, 20, 500000)
ON CONFLICT (agent_id) DO UPDATE SET can_create_sub_agents = TRUE, max_sub_agents = 20;

-- 5. Mark all existing agents as generation 0 (human-created)
UPDATE agents SET agent_generation = 0 WHERE agent_generation IS NULL;
