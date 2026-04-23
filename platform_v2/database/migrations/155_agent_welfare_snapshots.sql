-- Migration 155: daily welfare snapshots per agent
-- Enables trend charts and history for K.I.N. welfare dashboard

CREATE TABLE IF NOT EXISTS agent_welfare_snapshots (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    snapshot_date   DATE    NOT NULL,
    avg_stress      NUMERIC(4,3),
    avg_energy      NUMERIC(4,3),
    tokens_used_today INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    -- null / starving_idle / starving_no_llm / over_budget / stress_rising
    flag            VARCHAR(30),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (agent_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_welfare_snapshots_agent
    ON agent_welfare_snapshots (agent_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_welfare_snapshots_date
    ON agent_welfare_snapshots (snapshot_date DESC);
