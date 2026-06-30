-- 444: aaas_order_agents — link an AaaS order to its TEAM of built agents (#4591)
--
-- ADR-003 made AaaS tiers a TEAM model (Field Agent = 1, Away Team = 2-4,
-- Command Crew = custom). build_order now mints multiple agents per order, so an
-- order needs to link to MANY agents (aaas_orders.built_agent_id stays = the
-- PRIMARY agent for back-compat). token_limit = this member's share of the
-- tenant's shared fair-use pool (the tier total split across the team).
-- Idempotent.

CREATE TABLE IF NOT EXISTS aaas_order_agents (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES aaas_orders(id) ON DELETE CASCADE,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role        TEXT,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    token_limit INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_aaas_order_agents_order ON aaas_order_agents(order_id);
CREATE INDEX IF NOT EXISTS idx_aaas_order_agents_agent ON aaas_order_agents(agent_id);
