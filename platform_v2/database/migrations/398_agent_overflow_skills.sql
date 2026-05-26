-- T3165: Cross-capability bidding — secondary skill registration for overflow dispatch.
--
-- Agents can register overflow bids on capabilities outside their primary agent_skills.
-- The cluster_orchestration_worker (pass 5) UNIONs primary skills + overflow bids when
-- building the candidate pool; bid_priority (1-10) scales the computed overflow score
-- via bid_factor = bid_priority / 10.0, so primary-skill agents still win at equal load.
--
-- Example: F.O.R.G.E. has code_review as a primary skill (agent_skills).
--          An overflow bid for 'documentation' at bid_priority=3 allows F.O.R.G.E. to
--          pick up documentation queue items during idle periods, but at 30% weight vs
--          a primary-skill documentation agent.

CREATE TABLE IF NOT EXISTS agent_overflow_skills (
    id           BIGSERIAL    PRIMARY KEY,
    agent_id     INTEGER      NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability   VARCHAR(100) NOT NULL,
    bid_priority SMALLINT     NOT NULL DEFAULT 5
                     CHECK (bid_priority BETWEEN 1 AND 10),
    enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, capability)
);

-- Fast lookup: which agents bid on a capability? (used by pass 5 UNION query)
CREATE INDEX IF NOT EXISTS idx_aos_capability
    ON agent_overflow_skills (capability)
    WHERE enabled = TRUE;

-- Fast lookup: all overflow bids for a given agent (used by admin UI)
CREATE INDEX IF NOT EXISTS idx_aos_agent_id
    ON agent_overflow_skills (agent_id)
    WHERE enabled = TRUE;
