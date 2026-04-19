-- database/migrations/330_hiring_candidates.sql
-- Task #2102 — DHQ Hiring Queue backing store.

BEGIN;

CREATE TABLE IF NOT EXISTS hiring_candidates (
    id                   SERIAL PRIMARY KEY,

    capability           VARCHAR(100) NOT NULL,
    gap_reason           TEXT NOT NULL,
    gap_alert_id         INTEGER,
    narrative            TEXT,

    shortlist            JSONB NOT NULL DEFAULT '[]'::jsonb,

    proposed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    proposed_by_agent_id INTEGER,

    status               VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','approved','rejected','expired')),
    chosen_agent_id      INTEGER,
    decided_by_user_id   INTEGER,
    decided_at           TIMESTAMPTZ,
    decision_notes       TEXT,

    precheck_status      VARCHAR(20),
    precheck_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_hiring_candidates_status
    ON hiring_candidates(status);

CREATE INDEX IF NOT EXISTS idx_hiring_candidates_cap_pending
    ON hiring_candidates(capability) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_hiring_candidates_proposed_at
    ON hiring_candidates(proposed_at DESC);

COMMIT;
