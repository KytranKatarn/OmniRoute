-- Migration 147: Fleet Management — rotation log + performance rankings
-- Idempotent: safe to re-run

-- 1. Agent rotation log — tracks shift lifecycle transitions
CREATE TABLE IF NOT EXISTS agent_rotation_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE SET NULL,
    shift_state VARCHAR(20) NOT NULL DEFAULT 'active',
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP,
    tasks_completed INTEGER DEFAULT 0,
    tasks_failed INTEGER DEFAULT 0,
    replaced_by INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    reason VARCHAR(50),
    metadata JSONB DEFAULT '{}',
    CONSTRAINT valid_shift_state CHECK (shift_state IN ('active', 'winding_down', 'cooldown', 'off_duty'))
);

CREATE INDEX IF NOT EXISTS idx_rotation_log_agent ON agent_rotation_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_rotation_log_active ON agent_rotation_log(agent_id, shift_state) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rotation_log_station ON agent_rotation_log(station_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rotation_log_recent ON agent_rotation_log(started_at DESC);

-- 2. Agent performance rankings — comparative scoring per capability
CREATE TABLE IF NOT EXISTS agent_performance_rankings (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability VARCHAR(50) NOT NULL,
    tasks_completed INTEGER DEFAULT 0,
    success_rate NUMERIC(5,4) DEFAULT 0.0,
    avg_duration_ms NUMERIC(12,2) DEFAULT 0.0,
    avg_tokens_used NUMERIC(12,2) DEFAULT 0.0,
    rank_score NUMERIC(5,4) DEFAULT 0.0,
    rank_position INTEGER DEFAULT 0,
    sample_size INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_agent_capability UNIQUE (agent_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_perf_rank_capability ON agent_performance_rankings(capability, rank_score DESC);
CREATE INDEX IF NOT EXISTS idx_perf_rank_agent ON agent_performance_rankings(agent_id);

-- 3. Add shift_state column to agents table for quick lookups
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agents' AND column_name = 'shift_state') THEN
        ALTER TABLE agents ADD COLUMN shift_state VARCHAR(20) DEFAULT 'active';
        ALTER TABLE agents ADD CONSTRAINT valid_agent_shift_state CHECK (shift_state IN ('active', 'winding_down', 'cooldown', 'off_duty'));
    END IF;
END $$;
