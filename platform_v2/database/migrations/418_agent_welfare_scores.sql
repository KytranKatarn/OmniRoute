-- 418_agent_welfare_scores.sql
-- Project #379 Phase 4 — E.T.H.O.S./C.R.E.E.D. welfare governance.
-- One row per welfare-governance run: a 0-100 score grading the ORGANISATION on
-- how it treats its AI workforce, plus the violations + improvement recommendations
-- that produced it. Read by /creed + CREED Command (Phase 5). Idempotent.

CREATE TABLE IF NOT EXISTS agent_welfare_scores (
    id                 SERIAL PRIMARY KEY,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    score              INTEGER     NOT NULL,
    grade              VARCHAR(4)  NOT NULL,
    healthy_pct        NUMERIC(5, 2),
    break_honored_pct  NUMERIC(5, 2),
    active_agents      INTEGER,
    needed_break       INTEGER,
    violations         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    recommendations    JSONB       NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_welfare_scores_computed_at
    ON agent_welfare_scores (computed_at DESC);
