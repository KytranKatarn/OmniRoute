-- Node-local schema for agent configs and job tracking
-- Runs automatically on first Postgres start via docker-entrypoint-initdb.d

CREATE TABLE IF NOT EXISTS node_agent_configs (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    model VARCHAR(200) NOT NULL,
    system_prompt TEXT,
    station_codes TEXT[] DEFAULT '{}',
    capabilities TEXT[] DEFAULT '{}',
    sync_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS node_jobs (
    id SERIAL PRIMARY KEY,
    hub_job_id BIGINT,
    sync_id BIGINT,
    agent_name VARCHAR(100) NOT NULL,
    job_type VARCHAR(50),
    description TEXT,
    prompt TEXT,
    timeout_seconds INT DEFAULT 300,
    status VARCHAR(20) DEFAULT 'pending',
    output TEXT,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_node_jobs_status ON node_jobs(status);
CREATE INDEX IF NOT EXISTS idx_node_jobs_agent ON node_jobs(agent_name);
