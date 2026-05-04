-- Migration: P.R.O.B.E. performance baselines + deploy gate
-- Spec: docs/superpowers/specs/2026-05-03-perf-baselines-design.md
-- Task: #1755 (Project #239)

BEGIN;

CREATE TABLE IF NOT EXISTS qa_perf_baselines (
    id              SERIAL PRIMARY KEY,
    suite_id        INTEGER NOT NULL REFERENCES qa_test_suites(id) ON DELETE CASCADE,
    test_name       TEXT NOT NULL,
    baseline_p95_ms INTEGER NOT NULL,
    sample_count    INTEGER NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(suite_id, test_name)
);

CREATE TABLE IF NOT EXISTS qa_perf_regressions (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES qa_test_runs(id) ON DELETE CASCADE,
    suite_id        INTEGER NOT NULL,
    test_name       TEXT NOT NULL,
    baseline_ms     INTEGER NOT NULL,
    observed_ms     INTEGER NOT NULL,
    pct_over        INTEGER NOT NULL,
    is_critical     BOOLEAN NOT NULL DEFAULT FALSE,
    action_taken    TEXT,
    proposal_id     INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'cleared', 'accepted')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cleared_at      TIMESTAMPTZ,
    cleared_by      TEXT,
    UNIQUE(run_id, test_name)
);

CREATE INDEX IF NOT EXISTS qa_perf_regressions_pending
    ON qa_perf_regressions(status) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS qa_perf_acceptances (
    id          SERIAL PRIMARY KEY,
    suite_id    INTEGER NOT NULL,
    test_name   TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_by TEXT,
    UNIQUE(suite_id, test_name)
);

-- Extend improvement_proposals.status to include paused_for_perf_review.
-- No existing CHECK constraint on this column (verified 2026-05-03 — only
-- valid_complexity and valid_escalation_status constraints exist).
-- Adding a new CHECK constraint that covers all current values plus the new one.
ALTER TABLE improvement_proposals
    DROP CONSTRAINT IF EXISTS improvement_proposals_status_check;
ALTER TABLE improvement_proposals
    ADD CONSTRAINT improvement_proposals_status_check
    CHECK (status IN ('proposed', 'approved', 'sandboxed', 'deployed',
                      'regression', 'paused_for_perf_review', 'rejected',
                      'archived', 'fix_requested', 'pending',
                      'pending_approval', 'ready_for_review'));

COMMIT;
