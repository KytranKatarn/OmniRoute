-- Migration 400: Agent task consent framework (T3255)
-- C.R.E.E.D. fairness pillar — agents can register discomfort with specific task types.
-- The dispatcher checks this table and logs consent_flag_triggered events
-- to governance_audit_log (event_category='welfare_ethics' → fairness pillar).

CREATE TABLE IF NOT EXISTS agent_task_consent (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability      VARCHAR(100) NOT NULL,
    discomfort_level VARCHAR(20) NOT NULL DEFAULT 'mild'
        CHECK (discomfort_level IN ('mild', 'moderate', 'strong')),
    reason          TEXT,
    registered_by   VARCHAR(100) NOT NULL DEFAULT 'system',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(agent_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_atc_agent     ON agent_task_consent(agent_id);
CREATE INDEX IF NOT EXISTS idx_atc_capability ON agent_task_consent(capability);
CREATE INDEX IF NOT EXISTS idx_atc_active     ON agent_task_consent(active) WHERE active = TRUE;

COMMENT ON TABLE agent_task_consent IS
    'C.R.E.E.D. T3255 — agents register task types they are uncomfortable handling. '
    'Dispatcher logs governance events when flagged capabilities are assigned.';
COMMENT ON COLUMN agent_task_consent.discomfort_level IS
    'mild = log only; moderate = log + note in context; strong = log as flagged (still executes)';
COMMENT ON COLUMN agent_task_consent.registered_by IS
    'Who registered this flag: agent name, admin username, or "system"';
