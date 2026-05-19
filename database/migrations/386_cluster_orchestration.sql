-- 386_cluster_orchestration.sql
-- Cluster Orchestration & Elastic Agent Dispatch (Project #352)

CREATE TABLE IF NOT EXISTS cluster_orchestration_config (
    id                        SERIAL PRIMARY KEY,
    scope                     VARCHAR(20) NOT NULL DEFAULT 'global'
                              CHECK (scope IN ('global','agent','capability','node')),
    agent_id                  INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    capability                VARCHAR(100),
    node_id                   INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    idle_threshold_minutes    INTEGER     NOT NULL DEFAULT 5,
    utilization_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 60.00,
    queue_pressure_threshold  INTEGER     NOT NULL DEFAULT 10,
    idle_weight               NUMERIC(4,3) NOT NULL DEFAULT 0.300,
    utilization_weight        NUMERIC(4,3) NOT NULL DEFAULT 0.300,
    queue_pressure_weight     NUMERIC(4,3) NOT NULL DEFAULT 0.400,
    overflow_enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    overflow_paused           BOOLEAN     NOT NULL DEFAULT FALSE,
    priority_boost            INTEGER     NOT NULL DEFAULT 0,
    max_overflow_concurrent   INTEGER     NOT NULL DEFAULT 3,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_capability_scope CHECK (scope != 'capability' OR capability IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS agent_overflow_state (
    agent_id         INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability       VARCHAR(100) NOT NULL,
    overflow_score   NUMERIC(5,4) NOT NULL DEFAULT 0.0000,
    is_active        BOOLEAN NOT NULL DEFAULT FALSE,
    activated_at     TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '90 seconds',
    dispatches_sent  INTEGER NOT NULL DEFAULT 0,
    node_id          INTEGER REFERENCES remote_nodes(id),
    reason           JSONB   NOT NULL DEFAULT '{}',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, capability)
);

-- Global default config row
INSERT INTO cluster_orchestration_config (scope)
VALUES ('global')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_overflow_state_active
    ON agent_overflow_state (is_active, capability) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_overflow_state_expires
    ON agent_overflow_state (expires_at);
