-- Migration 403: creed_coordination_chains
-- Tracks multi-agent coordination chains for the C.R.E.E.D. agentic safety
-- framework (T3275). Each row represents one dispatch hop within a chain;
-- multiple rows may share the same chain_id (UUID) for a single coordination
-- sequence.
--
-- Risk assessment (populated by log_coordination_event() in creed_routes.py):
--   risk_score  0.00–1.00  (composite)
--   risk_flags  JSONB array — loop_detected, depth_elevated, depth_exceeded,
--               cost_elevated, cost_exceeded
--   outcome     allowed | flagged | blocked

CREATE TABLE IF NOT EXISTS creed_coordination_chains (
    id                  SERIAL PRIMARY KEY,
    chain_id            UUID           NOT NULL DEFAULT gen_random_uuid(),
    root_capability     VARCHAR(100),
    parent_dispatch_id  INTEGER,       -- bridge_jobs.id when available
    depth               INTEGER        NOT NULL DEFAULT 1,
    agent_sequence      JSONB          NOT NULL DEFAULT '[]',
    estimated_cost_usd  NUMERIC(10, 6),
    risk_score          NUMERIC(3, 2)  NOT NULL DEFAULT 0.00
                            CHECK (risk_score >= 0.00 AND risk_score <= 1.00),
    risk_flags          JSONB          NOT NULL DEFAULT '[]',
    outcome             VARCHAR(20)    NOT NULL DEFAULT 'allowed'
                            CHECK (outcome IN ('allowed', 'blocked', 'flagged')),
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_creed_coord_chain_id
    ON creed_coordination_chains (chain_id);
CREATE INDEX IF NOT EXISTS idx_creed_coord_outcome
    ON creed_coordination_chains (outcome);
CREATE INDEX IF NOT EXISTS idx_creed_coord_created_at
    ON creed_coordination_chains (created_at DESC);

COMMENT ON TABLE creed_coordination_chains IS
    'C.R.E.E.D. agentic safety — multi-agent coordination chain log (T3275)';
