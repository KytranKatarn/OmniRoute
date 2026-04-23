-- Migration 006: DB-driven triage policy rules
CREATE TABLE IF NOT EXISTS triage_policies (
    id                      SERIAL PRIMARY KEY,
    severity                VARCHAR(20),
    category_prefix         VARCHAR(100),
    director_agent_pattern  VARCHAR(100),
    action                  VARCHAR(20) NOT NULL,
    reason                  TEXT        NOT NULL,
    priority                INTEGER     DEFAULT 50,
    active                  BOOLEAN     DEFAULT TRUE,
    created_at              TIMESTAMP   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triage_policies_active
  ON triage_policies(active, priority);
