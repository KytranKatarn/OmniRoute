-- Migration 110: Agent activity events for SSE streaming
-- Part of Phase 6: Multi-Agent Orchestration UI

CREATE TABLE IF NOT EXISTS agent_activity_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    agent_id INTEGER REFERENCES agents(id),
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_agent_activity_events_created ON agent_activity_events(created_at DESC);
CREATE INDEX idx_agent_activity_events_agent ON agent_activity_events(agent_id);

COMMENT ON TABLE agent_activity_events IS 'Lightweight event store for SSE streaming. Auto-pruned to 24h.';
